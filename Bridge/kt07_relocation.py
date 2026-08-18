"""Cheap, untrusted candidate discovery for displaced KT07 frames."""
from dataclasses import dataclass, replace
import ctypes
import ctypes.wintypes
import math
import threading
import time
from pathlib import Path
import pprint

from PIL import Image, ImageChops, ImageDraw

from Bridge.kt07_decoder import decode_near_anchor, decode_relocation_candidate


ANCHOR_COLORS = (
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255),
)

DISCOVERY_SCALE = 4
DISCOVERY_TOLERANCE = 75
MAX_CANDIDATES = 8
PENDING_PROBE_INTERVAL = 0.5
WINDOW_STATE_INTERVAL = 1.0


def locate_client_anchor(image, tolerance=80):
    """Locate the KT07 anchor in its bounded client-top-left region.

    Search every raster phase. Window moves can change fractional-DPI
    rounding, so a two-pixel stride is not safe across relocations.
    """
    max_w = min(image.width, 120)
    max_h = min(image.height, 45)
    for width in range(4, 17):
        half = max(1, int(round(width * .25)))
        for cy in range(half, max_h - half):
            for cx in range(half, max_w - 6 * width - half):
                valid = True
                for index, target in enumerate(ANCHOR_COLORS):
                    px = cx + index * width
                    points = [
                        image.getpixel((px + sx, cy + sy))
                        for sx in (-half, 0, half)
                        for sy in (-half, 0, half)
                        if 0 <= px + sx < image.width and 0 <= cy + sy < image.height
                    ]
                    close = sum(
                        all(abs(point[channel] - target[channel]) <= tolerance
                            for channel in range(3))
                        for point in points
                    )
                    if close < max(3, len(points) // 2):
                        valid = False
                        break
                if valid:
                    scale = width / 8.0
                    pitch = width / 2.0
                    left = cx - width / 2.0
                    top = cy - width / 2.0
                    return (
                        left + 2 * scale,
                        top + 10 * scale,
                        pitch,
                        (round(left), round(top), round(left + 6 * width), round(top + width)),
                    )
    return None


@dataclass(frozen=True)
class WoWWindowSnapshot:
    client_rect: tuple
    virtual_rect: tuple
    style: int
    ex_style: int
    dpi: int


def get_wow_window_snapshot():
    """Return cheap Win32 state that changes when WoW's geometry changes."""
    if not hasattr(ctypes, "windll"):
        return None
    user32 = ctypes.windll.user32
    candidates = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    @callback_type
    def visit(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, len(title))
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        title_text = title.value.lower()
        class_text = class_name.value.lower()
        if "world of warcraft" not in title_text and "gxwindowclass" not in class_text:
            return True
        rect = ctypes.wintypes.RECT()
        if user32.GetClientRect(hwnd, ctypes.byref(rect)):
            area = max(0, rect.right - rect.left) * max(0, rect.bottom - rect.top)
            if area:
                candidates.append((area, hwnd, rect))
        return True

    try:
        user32.EnumWindows(visit, 0)
        if not candidates:
            return None
        _area, hwnd, rect = max(candidates, key=lambda item: item[0])
        origin = ctypes.wintypes.POINT(0, 0)
        extent = ctypes.wintypes.POINT(rect.right, rect.bottom)
        if (
            not user32.ClientToScreen(hwnd, ctypes.byref(origin))
            or not user32.ClientToScreen(hwnd, ctypes.byref(extent))
        ):
            return None
        to_physical = getattr(user32, "LogicalToPhysicalPointForPerMonitorDPI", None)
        if to_physical:
            to_physical(hwnd, ctypes.byref(origin))
            to_physical(hwnd, ctypes.byref(extent))
        client_rect = (
            origin.x,
            origin.y,
            extent.x,
            extent.y,
        )
        virtual_rect = (
            user32.GetSystemMetrics(76),
            user32.GetSystemMetrics(77),
            user32.GetSystemMetrics(76) + user32.GetSystemMetrics(78),
            user32.GetSystemMetrics(77) + user32.GetSystemMetrics(79),
        )
        get_dpi = getattr(user32, "GetDpiForWindow", None)
        dpi = int(get_dpi(hwnd)) if get_dpi else 96
        return WoWWindowSnapshot(
            client_rect,
            virtual_rect,
            int(user32.GetWindowLongW(hwnd, -16)),
            int(user32.GetWindowLongW(hwnd, -20)),
            dpi,
        )
    except Exception:
        return None


class WoWWindowChangeMonitor:
    """Poll inexpensive external evidence without invalidating geometry."""

    def __init__(self, provider=get_wow_window_snapshot, interval=WINDOW_STATE_INTERVAL):
        self.provider = provider
        self.interval = float(interval)
        self.snapshot = None
        self.next_check = 0.0

    def poll(self, now, force=False):
        if not force and now < self.next_check:
            return False
        self.next_check = now + self.interval
        current = self.provider()
        if current is None:
            return False
        changed = self.snapshot is not None and current != self.snapshot
        self.snapshot = current
        return changed


class RelocationPendingState:
    """Observe a small WoW-client ROI until the first KT07 frame appears."""

    def __init__(self, interval=PENDING_PROBE_INTERVAL):
        self.interval = float(interval)
        self.pending = False
        self.next_probe = 0.0
        self.snapshot = None
        self.generation = 0

    def enter(self, now, snapshot=None):
        self.pending = True
        self.next_probe = now
        self.snapshot = snapshot
        self.generation += 1
        return self.generation

    def bind_snapshot(self, snapshot):
        """Synchronize observer coordinates without declaring relocation."""
        if snapshot != self.snapshot:
            self.snapshot = snapshot
            self.generation += 1

    def attempt(self):
        """Return the immutable window state identifying the next probe."""
        return self.generation, self.snapshot

    def is_current(self, attempt):
        return self.pending and attempt == (self.generation, self.snapshot)

    def due(self, now):
        return self.pending and now >= self.next_probe

    def observation_due(self, now, window_available):
        return window_available and now >= self.next_probe

    def attempted(self, now):
        self.next_probe = now + self.interval

    def clear(self):
        self.pending = False


class OverlayRelocationSuppression:
    """Coordinate transport-capture overlay suppression across two threads.

    Initial acquisition and native relocation share the same generation and
    state.  The capture worker may probe only after the Tk thread has withdrawn
    the overlay and acknowledged that exact generation.  Stale acknowledgements
    and restores are deliberately ignored.
    """

    VISIBLE = "visible"
    SUPPRESSION_REQUESTED = "suppression_requested"
    SUPPRESSED = "suppressed"
    RESTORE_REQUESTED = "restore_requested"

    def __init__(self):
        self._lock = threading.Lock()
        self._state = self.VISIBLE
        self._generation = None

    def request_suppression(self, generation):
        with self._lock:
            if self._generation is not None and generation < self._generation:
                return False
            if generation == self._generation and self._state in (
                self.SUPPRESSION_REQUESTED, self.SUPPRESSED
            ):
                return False
            self._generation = generation
            self._state = self.SUPPRESSION_REQUESTED
            return True

    def acknowledge_suppressed(self, generation):
        with self._lock:
            if (
                generation != self._generation
                or self._state != self.SUPPRESSION_REQUESTED
            ):
                return False
            self._state = self.SUPPRESSED
            return True

    def capture_allowed(self, generation):
        with self._lock:
            return generation == self._generation and self._state == self.SUPPRESSED

    def request_restore(self, generation):
        with self._lock:
            if generation != self._generation or self._state not in (
                self.SUPPRESSION_REQUESTED, self.SUPPRESSED
            ):
                return False
            self._state = self.RESTORE_REQUESTED
            return True

    def acknowledge_restored(self, generation):
        with self._lock:
            if (
                generation != self._generation
                or self._state != self.RESTORE_REQUESTED
            ):
                return False
            self._state = self.VISIBLE
            self._generation = None
            return True

    def snapshot(self):
        with self._lock:
            return self._state, self._generation

    def cleanup(self):
        with self._lock:
            was_suppressed = self._state != self.VISIBLE
            self._state = self.VISIBLE
            self._generation = None
            return was_suppressed


def empty_client_probe_diagnostic(stage="presence_prefilter_failed"):
    return {
        "stage": stage,
        "candidate_anchor_roi": None,
        "candidate_anchor_absolute": None,
        "candidate_anchor_pitch": None,
        "decoded_geometry": None,
        "anchor_refinement_seconds": 0.0,
        "geometry_generation_seconds": 0.0,
        "decode_seconds": 0.0,
        "total_seconds": 0.0,
        "decode_attempts": 0,
        "geometry_candidates": 0,
    }


def inspect_client_anchor_probe(image, screen_offset, anchor_locator):
    """Decode a bounded probe without publishing its untrusted geometry."""
    diagnostic = empty_client_probe_diagnostic("anchor_not_found")
    total_started = time.perf_counter()
    anchor_started = time.perf_counter()
    found = anchor_locator(image)
    diagnostic["anchor_refinement_seconds"] = time.perf_counter() - anchor_started
    if found is None:
        diagnostic["total_seconds"] = time.perf_counter() - total_started
        return None, diagnostic
    _ox, _oy, pitch, local_anchor_box = found
    diagnostic["candidate_anchor_pitch"] = pitch
    diagnostic["candidate_anchor_roi"] = local_anchor_box
    diagnostic["candidate_anchor_absolute"] = offset_box(
        local_anchor_box, *screen_offset
    )
    diagnostic["stage"] = "strict_frame_validation_failed"
    validated, decode_diagnostic = decode_relocation_candidate(
        image, local_anchor_box, pitch
    )
    diagnostic.update(decode_diagnostic)
    diagnostic["total_seconds"] = time.perf_counter() - total_started
    if validated is None:
        return None, diagnostic
    text, local_geometry = validated
    geometry = offset_geometry(local_geometry, *screen_offset)
    diagnostic["decoded_geometry"] = geometry
    diagnostic["stage"] = "validated"
    return (text, geometry, diagnostic["candidate_anchor_absolute"], pitch), diagnostic


def client_anchor_probe_box(snapshot, width=420, height=350):
    if snapshot is None:
        return None
    left, top, right, bottom = snapshot.client_rect
    return left, top, min(right, left + width), min(bottom, top + height)


def client_anchor_presence_box(snapshot, width=120, height=45):
    return client_anchor_probe_box(snapshot, width, height)


def reduced_discovery_image(image):
    width = max(1, math.ceil(image.width / DISCOVERY_SCALE))
    height = max(1, math.ceil(image.height / DISCOVERY_SCALE))
    return image.convert("RGB").resize(
        (width, height),
        Image.Resampling.NEAREST,
    )


def _discovery_patterns():
    """Reduced-pixel offsets produced by 4..16 px blocks at every phase."""
    patterns = set()
    sample_offset = DISCOVERY_SCALE // 2
    for block in range(4, 17):
        for phase in range(DISCOVERY_SCALE):
            positions = []
            for index in range(len(ANCHOR_COLORS)):
                left = phase + index * block
                right = left + block
                first = math.ceil((left - sample_offset) / DISCOVERY_SCALE)
                while first * DISCOVERY_SCALE + sample_offset < left:
                    first += 1
                if first * DISCOVERY_SCALE + sample_offset >= right:
                    break
                positions.append(first)
            if len(positions) == len(ANCHOR_COLORS):
                origin = positions[0]
                patterns.add(tuple(value - origin for value in positions))
    return tuple(sorted(patterns, key=lambda row: (row[-1], row)))


DISCOVERY_PATTERNS = _discovery_patterns()


class RelocationProbeBackoff:
    """Gate full-screen relocation probes while preserving an idle lock."""

    def __init__(self, initial=5.0, maximum=60.0, multiplier=2.0):
        self.initial = float(initial)
        self.maximum = float(maximum)
        self.multiplier = float(multiplier)
        self.interval = self.initial
        self.next_probe = 0.0

    def due(self, now):
        return now >= self.next_probe

    def attempted(self, now, candidate_found=False):
        if candidate_found:
            self.interval = self.initial
        else:
            self.interval = min(
                self.maximum,
                self.interval * self.multiplier,
            )
        self.next_probe = now + self.interval

    def reset(self, now):
        self.interval = self.initial
        self.next_probe = now + self.initial


def _range_mask(channel, target, tolerance):
    low = max(0, target - tolerance)
    high = min(255, target + tolerance)
    return channel.point(
        [255 if low <= value <= high else 0 for value in range(256)]
    )


def _color_mask(channels, color, tolerance):
    mask = _range_mask(channels[0], color[0], tolerance)
    mask = ImageChops.multiply(mask, _range_mask(channels[1], color[1], tolerance))
    return ImageChops.multiply(mask, _range_mask(channels[2], color[2], tolerance))


def _shift_left(image, pixels):
    """Align source x+pixels with destination x without wraparound."""
    shifted = ImageChops.offset(image, -pixels, 0)
    if pixels:
        ImageDraw.Draw(shifted).rectangle(
            (shifted.width - pixels, 0, shifted.width, shifted.height),
            fill=0,
        )
    return shifted


def discover_candidate_rois(image, max_candidates=MAX_CANDIDATES):
    """Return bounded screen-space ROIs using native/downsampled operations.

    Results are hints only. This function deliberately does not decode or
    establish geometry.
    """
    reduced = reduced_discovery_image(image)
    channels = reduced.split()
    masks = [
        _color_mask(channels, color, DISCOVERY_TOLERANCE)
        for color in ANCHOR_COLORS
    ]
    points = []

    # Non-integral reduced block widths do not have constant spacing. Match
    # the small set of layouts produced by every supported width and sampling
    # phase. PIL still performs all image-sized work in native code.
    for pattern in DISCOVERY_PATTERNS:
        matches = masks[0]
        for index in range(1, len(masks)):
            matches = ImageChops.multiply(
                matches,
                _shift_left(masks[index], pattern[index]),
            )

        while len(points) < max_candidates:
            bbox = matches.getbbox()
            if bbox is None:
                break
            x, y = bbox[0], bbox[1]
            point = (x * DISCOVERY_SCALE, y * DISCOVERY_SCALE)
            if all(
                abs(point[0] - old[0]) > 96
                or abs(point[1] - old[1]) > 96
                for old in points
            ):
                points.append(point)
            ImageDraw.Draw(matches).rectangle(
                (max(0, x - 5), max(0, y - 5), x + 10, y + 10),
                fill=0,
            )

        if len(points) >= max_candidates:
            break

    rois = []
    for x, y in points:
        roi = (
            # Keep the first anchor block inside the existing top-left
            # locater's tiny fast-prefilter bounds, including 16 px blocks.
            max(0, x - 8),
            max(0, y - 4),
            min(image.width, x + 400),
            min(image.height, y + 330),
        )
        if roi[2] > roi[0] and roi[3] > roi[1] and roi not in rois:
            rois.append(roi)
    return rois


def save_discovery_diagnostic(
    image,
    directory,
    candidate_count,
    screen_offset=(0, 0),
):
    """Overwrite one bounded diagnostic set; the caller controls throttling."""
    directory = Path(directory)
    full_path = directory / "kt07_relocation_failure.png"
    reduced_path = directory / "kt07_relocation_reduced.png"
    closest_path = directory / "kt07_relocation_closest.png"
    meta_path = directory / "kt07_relocation_failure.txt"
    image.save(full_path)
    reduced = reduced_discovery_image(image)
    reduced.save(reduced_path)
    evidence = analyze_discovery_failure(reduced)
    crop_box = evidence.pop("full_resolution_crop")
    image.crop(crop_box).save(closest_path)
    meta_path.write_text(
        f"screen={image.width}x{image.height}\n"
        f"screen_offset={screen_offset}\n"
        f"discovery_scale={DISCOVERY_SCALE}\n"
        f"candidate_count={candidate_count}\n"
        + "".join(f"{key}={value}\n" for key, value in evidence.items()),
        encoding="utf-8",
    )
    return full_path, reduced_path, closest_path, meta_path


def preserve_validation_failure(
    image, directory, generation, metadata, retain_generations=3
):
    """Preserve the first raw strict-failure ROI for one relocation generation."""
    directory = Path(directory)
    image_path = directory / f"kt07_relocation_failure_{generation}_validation.png"
    report_path = directory / f"kt07_relocation_failure_{generation}.txt"
    if image_path.exists() or report_path.exists():
        return None
    image.save(image_path)
    report_path.write_text(
        pprint.pformat(metadata, sort_dicts=False, width=140) + "\n",
        encoding="utf-8",
    )
    generations = []
    for path in directory.glob("kt07_relocation_failure_*_validation.png"):
        value = path.name.removeprefix("kt07_relocation_failure_").removesuffix("_validation.png")
        if value.isdigit():
            generations.append(int(value))
    for old_generation in sorted(set(generations))[:-retain_generations]:
        for suffix in ("_validation.png", ".txt"):
            old_path = directory / f"kt07_relocation_failure_{old_generation}{suffix}"
            if old_path.exists():
                old_path.unlink()
    return image_path, report_path


def analyze_discovery_failure(reduced):
    """Diagnostic-only native scoring of the closest six-color layout."""
    channels = reduced.split()
    masks = [
        _color_mask(channels, color, DISCOVERY_TOLERANCE)
        for color in ANCHOR_COLORS
    ]
    counts = tuple(mask.histogram()[255] for mask in masks)
    unit_masks = [mask.point([0] * 255 + [1]) for mask in masks]
    best_score = -1
    best_pattern = DISCOVERY_PATTERNS[0]
    best_origin = (0, 0)

    for pattern in DISCOVERY_PATTERNS:
        score = unit_masks[0]
        for index in range(1, len(unit_masks)):
            score = ImageChops.add(
                score,
                _shift_left(unit_masks[index], pattern[index]),
            )
        maximum = score.getextrema()[1]
        if maximum > best_score:
            best_score = maximum
            best_pattern = pattern
            peak = score.point(
                [255 if value == maximum else 0 for value in range(256)]
            ).getbbox()
            best_origin = (peak[0], peak[1]) if peak else (0, 0)

    samples = []
    passes = []
    for index, offset in enumerate(best_pattern):
        x = min(reduced.width - 1, best_origin[0] + offset)
        y = min(reduced.height - 1, best_origin[1])
        sample = reduced.getpixel((x, y))[:3]
        samples.append(sample)
        passes.append(all(
            abs(sample[channel] - ANCHOR_COLORS[index][channel])
            <= DISCOVERY_TOLERANCE
            for channel in range(3)
        ))

    full_x = best_origin[0] * DISCOVERY_SCALE
    full_y = best_origin[1] * DISCOVERY_SCALE
    return {
        "color_mask_counts": counts,
        "closest_match_count": best_score,
        "closest_pattern": best_pattern,
        "closest_reduced_origin": best_origin,
        "closest_sample_rgb": tuple(samples),
        "closest_color_passes": tuple(passes),
        "sequence_present_in_reduced": best_score == len(ANCHOR_COLORS),
        "full_resolution_crop": (
            max(0, full_x - 24),
            max(0, full_y - 24),
            min(reduced.width * DISCOVERY_SCALE, full_x + 160),
            min(reduced.height * DISCOVERY_SCALE, full_y + 80),
        ),
    }


def offset_box(box, offset_x, offset_y):
    return (
        box[0] + offset_x,
        box[1] + offset_y,
        box[2] + offset_x,
        box[3] + offset_y,
    )


def offset_geometry(geometry, offset_x, offset_y):
    return replace(
        geometry,
        x=geometry.x + offset_x,
        y=geometry.y + offset_y,
    )


def validate_candidate_rois(full_image, candidate_rois, tracker, anchor_locator):
    """Promote only a fully decoded candidate, translated to screen space."""
    for roi_box in candidate_rois:
        roi = full_image.crop(roi_box)
        found = anchor_locator(roi)
        if found is None:
            continue
        _ox, _oy, pitch, local_anchor_box = found
        validated = decode_near_anchor(roi, local_anchor_box, pitch, exhaustive=False)
        if validated is None:
            continue
        text, local_geometry = validated
        geometry = offset_geometry(local_geometry, roi_box[0], roi_box[1])
        anchor_box = offset_box(local_anchor_box, roi_box[0], roi_box[1])
        result = tracker.accept_validated_relocation(text, geometry)
        return result, anchor_box, pitch
    return None


def validate_client_anchor_probe(image, screen_offset, tracker, anchor_locator):
    """Validate one bounded client-top-left image and publish absolute geometry."""
    decoded, _diagnostic = inspect_client_anchor_probe(
        image, screen_offset, anchor_locator
    )
    if decoded is None:
        return None
    text, geometry, anchor_box, pitch = decoded
    result = tracker.accept_validated_relocation(text, geometry)
    return result, anchor_box, pitch
