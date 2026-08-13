"""Resolution-independent KT07 symbol-grid decoder.

The decoder deliberately validates an entire KT07 frame before returning a
geometry.  Seeing the MAGIC bytes is only a candidate signal; checksum and
UTF-8 validation are required before a geometry can be locked by the caller.
"""
from dataclasses import dataclass
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


def _sample_axis(center, pitch):
    """Return interior sample coordinates, including multipoint sampling at 3px."""
    half = max(0.25, min(1.25, pitch * 0.24))
    return (center - half, center, center + half)


def _symbol_value(im, geometry, index):
    col, row = index % COLS, index // COLS
    cx = geometry.x + (col + 0.5) * geometry.pitch_x
    cy = geometry.y + (row + 0.5) * geometry.pitch_y
    values = []
    seen = set()
    for sy in _sample_axis(cy, geometry.pitch_y):
        for sx in _sample_axis(cx, geometry.pitch_x):
            px, py = int(round(sx)), int(round(sy))
            if (px, py) in seen:
                continue
            seen.add((px, py))
            if 0 <= px < im.width and 0 <= py < im.height:
                r, g, b = im.getpixel((px, py))[:3]
                if max(r, g, b) - min(r, g, b) < 35:
                    values.append((r + g + b) // 3)
    return int(statistics.median(values)) if values else None


def read_byte(im, geometry, byte_index):
    digits = [_classify(_symbol_value(im, geometry, byte_index * 4 + i)) for i in range(4)]
    if any(digit is None for digit in digits):
        return None
    return digits[0] * 64 + digits[1] * 16 + digits[2] * 4 + digits[3]


def decode_at(im, geometry):
    """Decode only a completely valid KT07 frame at an exact geometry."""
    if tuple(read_byte(im, geometry, i) for i in range(4)) != MAGIC:
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


def _candidate_origins(anchor_box):
    left, top, right, bottom = anchor_box
    # Anchor determines locality only; it does not dictate grid scale.
    for y in range(max(0, int(top) - 2), max(1, int(bottom) + 42)):
        for x in range(max(0, int(left) - 20), max(1, int(right) + 20)):
            yield float(x), float(y)


def _refine(im, coarse_geometry, coarse_step=0.25):
    """Sub-pixel refinement around a MAGIC candidate; checksum chooses winner."""
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


def decode_near_anchor(im, anchor_box, anchor_symbol_pitch=None):
    """Find and fully validate KT07 without assuming resolution or equal X/Y pitch.

    ``anchor_symbol_pitch`` is intentionally only a search-order hint.  The
    absolute search remains broad enough to recover when the anchor and payload
    are rasterized at different effective scales.
    """
    pitch_min, pitch_max, step = 1.75, 10.0, 0.25
    pitches = list(_frange(pitch_min, pitch_max, step))
    if anchor_symbol_pitch:
        hint = float(anchor_symbol_pitch)
        pitches.sort(key=lambda value: abs(value - hint))

    origins = tuple(_candidate_origins(anchor_box))
    for pitch_y in pitches:
        for pitch_x in pitches:
            # A strongly anisotropic candidate is unlikely to be a UI-scaled
            # square grid; keeping a generous ratio bound controls CPU without
            # assuming pitch_x == pitch_y.
            ratio = pitch_x / pitch_y
            if not 0.70 <= ratio <= 1.30:
                continue
            for x, y in origins:
                geometry = Geometry(x, y, pitch_x, pitch_y)
                if tuple(read_byte(im, geometry, i) for i in range(4)) != MAGIC:
                    continue
                # MAGIC only earns refinement.  It never locks geometry.
                refined = _refine(im, geometry, step)
                if refined is not None:
                    return refined
    return None
