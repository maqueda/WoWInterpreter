"""Cheap, untrusted candidate discovery for displaced KT07 frames."""
from dataclasses import replace
import math

from PIL import Image, ImageChops, ImageDraw

from Bridge.kt07_decoder import decode_near_anchor


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
    width = max(1, math.ceil(image.width / DISCOVERY_SCALE))
    height = max(1, math.ceil(image.height / DISCOVERY_SCALE))
    reduced = image.convert("RGB").resize((width, height), Image.Resampling.NEAREST)
    channels = reduced.split()
    masks = [
        _color_mask(channels, color, DISCOVERY_TOLERANCE)
        for color in ANCHOR_COLORS
    ]
    points = []

    # Physical anchor blocks are 4..16 px wide, or approximately 1..4 px
    # after reduction. PIL performs all desktop-sized work in native code.
    for spacing in range(1, 5):
        matches = masks[0]
        for index in range(1, len(masks)):
            matches = ImageChops.multiply(
                matches,
                _shift_left(masks[index], index * spacing),
            )

        while len(points) < max_candidates:
            bbox = matches.getbbox()
            if bbox is None:
                break
            x, y = bbox[0], bbox[1]
            points.append((x * DISCOVERY_SCALE, y * DISCOVERY_SCALE))
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
