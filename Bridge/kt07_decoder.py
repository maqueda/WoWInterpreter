"""Resolution-independent KT07 symbol-grid decoder.

A geometry is valid only when the complete KT07 frame validates: MAGIC,
length, checksum and UTF-8. MAGIC alone is never enough to lock geometry.
"""
from dataclasses import dataclass
import math
import statistics

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
    """Probe for KT07-like cells at an already validated geometry.

    This is only a presence probe. It never establishes or validates
    geometry; a geometry lock still requires full decode_at() validation.
    """
    matches = 0

    for index in (0, 1, 2, 3):
        col, row = index % COLS, index // COLS
        cx = geometry.x + (col + 0.5) * geometry.pitch_x
        cy = geometry.y + (row + 0.5) * geometry.pitch_y
        px, py = int(math.floor(cx)), int(math.floor(cy))

        if not (0 <= px < im.width and 0 <= py < im.height):
            continue

        r, g, b = im.getpixel((px, py))[:3]

        # KT07 transport cells are grayscale.
        if max(r, g, b) - min(r, g, b) >= 35:
            continue

        level = (r + g + b) // 3

        # Unlike _classify(), presence detection must reject pixels that
        # merely happen to be closest to a KT07 level. This prevents an
        # empty/dark background from looking like active transport.
        if min(abs(level - ideal) for ideal in IDEAL) <= 18:
            matches += 1

    return matches >= 2


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
