"""Resolution-independent KT07 symbol-grid decoder.

A geometry is valid only when the complete KT07 frame validates: MAGIC,
length, checksum and UTF-8. MAGIC alone is never enough to lock geometry.
"""
from dataclasses import dataclass
import math
import statistics
import time

MAX_BYTES = 180
COLS = 32
MAGIC = (75, 84, 48, 55)
IDEAL = (31, 92, 163, 224)


@dataclass(frozen=True)
class Geometry:
    x: float
    y: float
    pitch_x: float
    pitch_y: float


def capture_box_for_geometry(geometry, margin=8):
    """Return a screen-space bbox covering the largest valid KT07 frame.

    The box is derived only from validated geometry and protocol limits, so
    it scales with DPI/UI scale rather than monitor resolution.
    """
    total_bytes = len(MAGIC) + 1 + MAX_BYTES + 1
    total_symbols = total_bytes * 4
    rows = math.ceil(total_symbols / COLS)

    # Keep the crop in screen coordinates with origin (0, 0).
    # This lets the validated Geometry remain unchanged when decoding the
    # cropped image, while right/bottom still adapt to position and UI scale.
    left = 0
    top = 0
    right = math.ceil(
        geometry.x + COLS * geometry.pitch_x + margin
    )
    bottom = math.ceil(
        geometry.y + rows * geometry.pitch_y + margin
    )

    return (left, top, right, bottom)


def _classify(value):
    if value is None:
        return None
    return min(range(4), key=lambda i: abs(value - IDEAL[i]))


def _safe_pixel_centers(start, end):
    width = end - start
    if width <= 0:
        return ()
    margin = min(width * 0.20, max(0.0, (width - 1.0) / 2.0))
    inner_start, inner_end = start + margin, end - margin
    pixels = []
    first, last = max(0, int(math.floor(start)) - 1), int(math.ceil(end)) + 1
    for pixel in range(first, last + 1):
        center = pixel + 0.5
        if inner_start <= center < inner_end:
            pixels.append(pixel)
    return tuple(pixels) if pixels else (max(0, int(math.floor((start + end) / 2.0))),)


def _symbol_value(im, geometry, index):
    col, row = index % COLS, index // COLS
    x0 = geometry.x + col * geometry.pitch_x
    x1 = geometry.x + (col + 1) * geometry.pitch_x
    y0 = geometry.y + row * geometry.pitch_y
    y1 = geometry.y + (row + 1) * geometry.pitch_y
    values = []
    for py in _safe_pixel_centers(y0, y1):
        if not 0 <= py < im.height:
            continue
        for px in _safe_pixel_centers(x0, x1):
            if not 0 <= px < im.width:
                continue
            r, g, b = im.getpixel((px, py))[:3]
            if max(r, g, b) - min(r, g, b) < 35:
                values.append((r + g + b) // 3)
    return int(statistics.median(values)) if values else None


def _quick_symbol(im, geometry, index):
    """One-pixel interior probe used only to reject impossible candidates.

    A hit is never trusted: every surviving candidate is re-read by the robust
    multipoint sampler and must pass the complete KT07 frame validation.
    """
    col, row = index % COLS, index // COLS
    cx = geometry.x + (col + 0.5) * geometry.pitch_x
    cy = geometry.y + (row + 0.5) * geometry.pitch_y
    px, py = int(math.floor(cx)), int(math.floor(cy))
    if not (0 <= px < im.width and 0 <= py < im.height):
        return None
    r, g, b = im.getpixel((px, py))[:3]
    if max(r, g, b) - min(r, g, b) >= 35:
        return None
    return _classify((r + g + b) // 3)


def _quick_magic_prefix(im, geometry):
    # First byte 75 == base4 digits 1,0,2,3. Two well-separated digits are a
    # cheap discriminator. False positives are harmless because robust MAGIC,
    # checksum and UTF-8 validation still follow.
    return _quick_symbol(im, geometry, 0) == 1 and _quick_symbol(im, geometry, 3) == 3


def has_signal_at(im, geometry):
    """Detect physical KT07 transport at validated geometry.

    This deliberately does not validate a complete frame. Its only job is
    distinguishing an idle background from transport that is still visibly
    present but whose frame failed full validation.

    Require the characteristic MAGIC symbol pattern rather than merely
    accepting pixels close to any KT07 grayscale level. A uniform dark
    background can be close to IDEAL[0], but cannot reproduce this pattern.
    """
    expected_symbols = []

    for value in MAGIC:
        expected_symbols.extend((
            (value >> 6) & 3,
            (value >> 4) & 3,
            (value >> 2) & 3,
            value & 3,
        ))

    matches = 0
    observed = 0

    for index, expected in enumerate(expected_symbols):
        col, row = index % COLS, index // COLS

        cx = geometry.x + (
            col + 0.5
        ) * geometry.pitch_x
        cy = geometry.y + (
            row + 0.5
        ) * geometry.pitch_y

        px = int(math.floor(cx))
        py = int(math.floor(cy))

        if not (
            0 <= px < im.width
            and 0 <= py < im.height
        ):
            continue

        r, g, b = im.getpixel((px, py))[:3]

        if max(r, g, b) - min(r, g, b) >= 35:
            continue

        level = (r + g + b) // 3
        observed += 1

        if abs(level - IDEAL[expected]) <= 18:
            matches += 1

    # MAGIC contributes 16 symbols. Requiring a strong majority keeps this
    # probe tolerant of a few noisy pixels while making uniform backgrounds
    # and incidental grayscale UI extremely unlikely to count as transport.
    return (
        observed >= 12
        and matches >= 12
    )


def read_byte(im, geometry, byte_index):
    digits = [_classify(_symbol_value(im, geometry, byte_index * 4 + i)) for i in range(4)]
    if any(digit is None for digit in digits):
        return None
    return digits[0] * 64 + digits[1] * 16 + digits[2] * 4 + digits[3]


def _has_magic(im, geometry):
    for index, expected in enumerate(MAGIC):
        if read_byte(im, geometry, index) != expected:
            return False
    return True


def decode_at(im, geometry):
    if not _has_magic(im, geometry):
        return None
    length = read_byte(im, geometry, 4)
    if length is None or not 0 < length <= MAX_BYTES:
        return None
    payload = [read_byte(im, geometry, 5 + i) for i in range(length)]
    if any(value is None for value in payload):
        return None
    expected = (sum(MAGIC) + length + sum(payload)) % 256
    if read_byte(im, geometry, 5 + length) != expected:
        return None
    try:
        return bytes(payload).decode("utf-8")
    except UnicodeDecodeError:
        return None


def decode_details(im, geometry):
    """Return strict frame evidence for diagnostics, or None when invalid."""
    magic = tuple(read_byte(im, geometry, index) for index in range(len(MAGIC)))
    if magic != MAGIC:
        return None
    length = read_byte(im, geometry, len(MAGIC))
    if length is None or not 0 < length <= MAX_BYTES:
        return None
    payload = [read_byte(im, geometry, 5 + index) for index in range(length)]
    if any(value is None for value in payload):
        return None
    expected = (sum(MAGIC) + length + sum(payload)) % 256
    actual = read_byte(im, geometry, 5 + length)
    if actual != expected:
        return None
    try:
        text = bytes(payload).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return {
        "geometry": geometry,
        "magic": magic,
        "length": length,
        "checksum_expected": expected,
        "checksum_actual": actual,
        "payload_hex": bytes(payload).hex(),
        "text": text,
    }


def inspect_decode_at(im, geometry):
    """Describe the exact strict-validation stage without accepting failures."""
    magic = tuple(read_byte(im, geometry, index) for index in range(len(MAGIC)))
    evidence = {
        "stage": "magic_failed",
        "magic": magic,
        "length": None,
        "checksum_expected": None,
        "checksum_actual": None,
        "payload_hex": None,
        "decoded_utf8": None,
    }
    if magic != MAGIC:
        return evidence
    length = read_byte(im, geometry, len(MAGIC))
    evidence["length"] = length
    evidence["stage"] = "length_failed"
    if length is None or not 0 < length <= MAX_BYTES:
        return evidence
    payload = [read_byte(im, geometry, 5 + index) for index in range(length)]
    evidence["stage"] = "payload_read_failed"
    if any(value is None for value in payload):
        return evidence
    payload_bytes = bytes(payload)
    evidence["payload_hex"] = payload_bytes.hex()
    expected = (sum(MAGIC) + length + sum(payload)) % 256
    actual = read_byte(im, geometry, 5 + length)
    evidence["checksum_expected"] = expected
    evidence["checksum_actual"] = actual
    evidence["stage"] = "checksum_failed"
    if actual != expected:
        return evidence
    evidence["stage"] = "utf8_failed"
    try:
        evidence["decoded_utf8"] = payload_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return evidence
    evidence["stage"] = "validated"
    return evidence


def _frange(start, stop, step):
    value = start
    while value <= stop + 1e-9:
        yield round(value, 4)
        value += step


def _ordered_pitches(anchor_symbol_pitch, exhaustive):
    step = 0.25
    if anchor_symbol_pitch:
        hint = float(anchor_symbol_pitch)
        local = list(_frange(max(1.75, hint - 1.5), min(10.0, hint + 1.5), step))
        local.sort(key=lambda value: abs(value - hint))
    else:
        local = list(_frange(1.75, 6.0, step))
    if not exhaustive:
        return local
    broad = list(_frange(1.75, 10.0, step))
    broad.sort(key=lambda value: (0 if value in local else 1, abs(value - float(anchor_symbol_pitch or 4.0))))
    return broad


def _candidate_origins(anchor_box, exhaustive):
    left, top, right, bottom = anchor_box
    if exhaustive:
        x0, x1 = max(0, int(left) - 20), max(1, int(right) + 20)
        y0, y1 = max(0, int(top) - 2), max(1, int(bottom) + 42)
    else:
        x0, x1 = max(0, int(left) - 14), max(1, int(right) + 8)
        y0, y1 = max(0, int(bottom) - 1), max(1, int(bottom) + 22)
    for y in range(y0, y1):
        for x in range(x0, x1):
            yield float(x), float(y)


def _refine(im, coarse_geometry, coarse_step=0.25):
    offsets = (-0.5, -0.25, 0.0, 0.25, 0.5)
    pitch_offsets = (-coarse_step, -coarse_step / 2, 0.0, coarse_step / 2, coarse_step)
    for dpy in pitch_offsets:
        py = coarse_geometry.pitch_y + dpy
        if py < 1.5:
            continue
        for dpx in pitch_offsets:
            px = coarse_geometry.pitch_x + dpx
            if px < 1.5:
                continue
            for dy in offsets:
                for dx in offsets:
                    geometry = Geometry(coarse_geometry.x + dx, coarse_geometry.y + dy, px, py)
                    decoded = decode_at(im, geometry)
                    if decoded is not None:
                        return decoded, geometry
    return None


def _pitch_pairs(pitches, anchor_symbol_pitch):
    pitch_set = set(pitches)
    deltas = (0.0, -0.25, 0.25, -0.5, 0.5, -0.75, 0.75)
    pairs = []
    for pitch_y in pitches:
        for delta in deltas:
            pitch_x = round(pitch_y + delta, 4)
            if pitch_x in pitch_set and (pitch_x, pitch_y) not in pairs:
                pairs.append((pitch_x, pitch_y))
    hint = float(anchor_symbol_pitch or 4.0)
    pairs.sort(key=lambda pair: (abs(pair[0] - pair[1]), abs(pair[0] - hint) + abs(pair[1] - hint)))
    return pairs


def decode_near_anchor(im, anchor_box, anchor_symbol_pitch=None, exhaustive=False):
    """Calibrate KT07 near an anchor without assuming monitor resolution."""
    pitches = _ordered_pitches(anchor_symbol_pitch, exhaustive)
    origins = tuple(_candidate_origins(anchor_box, exhaustive))
    for pitch_x, pitch_y in _pitch_pairs(pitches, anchor_symbol_pitch):
        for x, y in origins:
            geometry = Geometry(x, y, pitch_x, pitch_y)
            if not _quick_magic_prefix(im, geometry):
                continue
            if not _has_magic(im, geometry):
                continue
            refined = _refine(im, geometry, 0.25)
            if refined is not None:
                return refined
    return None


def audit_initial_candidate(im, anchor_box, anchor_symbol_pitch, found):
    """Enumerate a bounded neighborhood around an initially valid geometry."""
    text, geometry = found
    left, _top, right, bottom = anchor_box
    expected_pitch_x = (right - left) / 12.0
    expected_pitch_y = (bottom - _top) / 2.0
    expected_x = float(left)
    expected_y = float(bottom)
    candidates = []
    order = 0
    for pitch_y in _frange(geometry.pitch_y - .25, geometry.pitch_y + .25, .125):
        for pitch_x in _frange(geometry.pitch_x - .25, geometry.pitch_x + .25, .125):
            for y in _frange(geometry.y - .5, geometry.y + .5, .25):
                for x in _frange(geometry.x - .5, geometry.x + .5, .25):
                    candidate = Geometry(x, y, pitch_x, pitch_y)
                    if not _quick_magic_prefix(im, candidate):
                        continue
                    details = decode_details(im, candidate)
                    if details is None:
                        continue
                    order += 1
                    details["order"] = order
                    details["anchor_pitch_error"] = (
                        abs(pitch_x - expected_pitch_x)
                        + abs(pitch_y - expected_pitch_y)
                    )
                    details["anchor_origin_error"] = (
                        abs(x - expected_x) + abs(y - expected_y)
                    )
                    candidates.append(details)
    consensus = summarize_initial_consensus(candidates)
    return {
        "first_geometry": geometry,
        "first_text": text,
        "anchor_pitch": anchor_symbol_pitch,
        "anchor_box": anchor_box,
        "candidates": candidates,
        **consensus,
        "ambiguous": not consensus["consensus_accepted"],
    }


def _candidate_payload_bytes(candidate):
    payload_hex = candidate.get("payload_hex")
    if payload_hex is not None:
        return bytes.fromhex(payload_hex)
    return candidate["text"].encode("utf-8")


def _representative_candidate(candidates):
    return min(
        candidates,
        key=lambda candidate: (
            candidate["anchor_pitch_error"] + candidate["anchor_origin_error"],
            candidate["anchor_pitch_error"],
            candidate["anchor_origin_error"],
            candidate["geometry"].pitch_x,
            candidate["geometry"].pitch_y,
            candidate["geometry"].x,
            candidate["geometry"].y,
            candidate["order"],
        ),
    )


def summarize_initial_consensus(candidates):
    """Choose only unanimous or overwhelmingly supported byte-exact payloads."""
    groups = {}
    for candidate in candidates:
        groups.setdefault(_candidate_payload_bytes(candidate), []).append(candidate)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    total = len(candidates)
    summaries = []
    for payload, members in ordered:
        representative = _representative_candidate(members)
        pitch_pairs = {
            (item["geometry"].pitch_x, item["geometry"].pitch_y)
            for item in members
        }
        origins = {(item["geometry"].x, item["geometry"].y) for item in members}
        summaries.append({
            "support_count": len(members),
            "support_ratio": len(members) / total if total else 0.0,
            "unique_pitch_pair_count": len(pitch_pairs),
            "unique_origin_count": len(origins),
            "representative_geometry": representative["geometry"],
            "best_anchor_pitch_error": representative["anchor_pitch_error"],
            "best_anchor_origin_error": representative["anchor_origin_error"],
            "payload_hex": payload.hex(),
            "decoded_utf8": representative["text"],
            "_representative": representative,
        })

    winner = summaries[0] if summaries else None
    runner_up = summaries[1]["support_count"] if len(summaries) > 1 else 0
    accepted = False
    reason = "no_valid_candidates"
    if winner is not None and len(summaries) == 1:
        accepted = True
        reason = "unanimous"
    elif winner is not None:
        enough_support = winner["support_count"] >= 10
        dominant_share = winner["support_ratio"] >= 0.95
        dominant_margin = winner["support_count"] >= 10 * runner_up
        diverse_geometry = (
            winner["unique_pitch_pair_count"] >= 2
            and winner["unique_origin_count"] >= 4
        )
        accepted = (
            enough_support and dominant_share and dominant_margin and diverse_geometry
        )
        reason = (
            "overwhelming_byte_exact_geometric_consensus"
            if accepted else
            "competitive_or_insufficient_geometric_consensus"
        )

    selected = winner["_representative"] if accepted and winner else None
    public_groups = []
    for summary in summaries:
        public_groups.append({
            key: value for key, value in summary.items() if key != "_representative"
        })
    return {
        "total_valid_candidates": total,
        "unique_payload_count": len(summaries),
        "payload_groups": public_groups,
        "consensus_accepted": accepted,
        "consensus_reason": reason,
        "winning_support": winner["support_count"] if winner else 0,
        "runner_up_support": runner_up,
        "selected_text": selected["text"] if selected else None,
        "selected_geometry": selected["geometry"] if selected else None,
    }


def decode_relocation_candidate(im, anchor_box, anchor_symbol_pitch):
    """Strictly decode a localized relocation anchor in a bounded neighborhood."""
    started = time.perf_counter()
    left, _top, _right, bottom = anchor_box
    hint = float(anchor_symbol_pitch)
    # WoW rasterizes the logical 8-unit anchor blocks and 4-unit data cells
    # independently. Their rounded pixel edges need not preserve an exact
    # 2:1 integer ratio: a 7 px locator match can accompany a 3.875 px data
    # grid. Use the half-pixel logical relationship with subpixel resolution,
    # while narrowing the radius so relocation remains strictly bounded.
    pitches = relocation_candidate_pitches(hint)
    pitch_pairs = _pitch_pairs(pitches, hint)
    origins_started = time.perf_counter()
    x_origins = tuple(_frange(max(0.0, left - 3.0), left + 3.0, .25))
    # Lua places the payload one rendered anchor height below the anchor.
    # Fractional UI scaling can move the rasterized box edge by a few pixels.
    y_origins = tuple(_frange(max(0.0, bottom + hint - 3.0), bottom + hint + 3.0, .25))
    origins = tuple((x, y) for y in y_origins for x in x_origins)
    generation_seconds = time.perf_counter() - origins_started
    decode_started = time.perf_counter()
    attempts = 0
    strict_attempts = 0
    for pitch_x, pitch_y in pitch_pairs:
        for x, y in origins:
            attempts += 1
            geometry = Geometry(x, y, pitch_x, pitch_y)
            if not _quick_magic_prefix(im, geometry):
                continue
            strict_attempts += 1
            decoded = decode_at(im, geometry)
            if decoded is not None:
                elapsed = time.perf_counter() - decode_started
                return (decoded, geometry), {
                    "geometry_generation_seconds": generation_seconds,
                    "decode_seconds": elapsed,
                    "total_seconds": time.perf_counter() - started,
                    "decode_attempts": attempts,
                    "strict_decode_attempts": strict_attempts,
                    "quick_rejects": attempts - strict_attempts,
                    "geometry_candidates": len(pitch_pairs) * len(origins),
                }
    elapsed = time.perf_counter() - decode_started
    return None, {
        "geometry_generation_seconds": generation_seconds,
        "decode_seconds": elapsed,
        "total_seconds": time.perf_counter() - started,
        "decode_attempts": attempts,
        "strict_decode_attempts": strict_attempts,
        "quick_rejects": attempts - strict_attempts,
        "geometry_candidates": len(pitch_pairs) * len(origins),
    }


RELOCATION_PITCH_RADIUS = 0.5
RELOCATION_PITCH_STEP = 0.125


def relocation_candidate_pitches(anchor_symbol_pitch):
    hint = float(anchor_symbol_pitch)
    lower = max(1.75, hint - RELOCATION_PITCH_RADIUS)
    upper = min(10.0, hint + RELOCATION_PITCH_RADIUS)
    # Align the bounded interval to the decoder's global subpixel grid.
    lower = math.ceil(lower / RELOCATION_PITCH_STEP) * RELOCATION_PITCH_STEP
    upper = math.floor(upper / RELOCATION_PITCH_STEP) * RELOCATION_PITCH_STEP
    return tuple(_frange(lower, upper, RELOCATION_PITCH_STEP))


def decode_local_candidate(im, trusted_geometry):
    """Strictly search only a tiny neighborhood of trusted locked geometry."""
    attempts = 0
    for pitch_y in _frange(
        max(1.5, trusted_geometry.pitch_y - .25),
        trusted_geometry.pitch_y + .25,
        .125,
    ):
        for pitch_x in _frange(
            max(1.5, trusted_geometry.pitch_x - .25),
            trusted_geometry.pitch_x + .25,
            .125,
        ):
            for y in _frange(
                max(0.0, trusted_geometry.y - .5),
                trusted_geometry.y + .5,
                .25,
            ):
                for x in _frange(
                    max(0.0, trusted_geometry.x - .5),
                    trusted_geometry.x + .5,
                    .25,
                ):
                    attempts += 1
                    geometry = Geometry(x, y, pitch_x, pitch_y)
                    if not _quick_magic_prefix(im, geometry):
                        continue
                    text = decode_at(im, geometry)
                    if text is not None:
                        return (text, geometry), attempts
    return None, attempts
