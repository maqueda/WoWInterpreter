"""Pilot-derived KT08 physical geometry."""
from dataclasses import dataclass
import math
import time


PILOT_COLORS = {
    "tl": (255, 0, 0),
    "tr": (0, 255, 0),
    "bl": (0, 0, 255),
    "br": (255, 255, 0),
}
PILOT_DX = 34.0
PILOT_DY = 27.0


@dataclass(frozen=True)
class KT08Geometry:
    x: float
    y: float
    pitch_x: float
    pitch_y: float
    pilots: tuple


def _near(pixel, target, tolerance=55):
    return all(abs(pixel[index] - target[index]) <= tolerance for index in range(3))


def _extract_components(matching):
    matching = set(matching)
    result = []
    while matching:
        seed = matching.pop()
        stack = [seed]
        points = [seed]
        while stack:
            x, y = stack.pop()
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in matching:
                    matching.remove(neighbor)
                    stack.append(neighbor)
                    points.append(neighbor)
        left = min(x for x, _y in points)
        right = max(x for x, _y in points) + 1
        top = min(y for _x, y in points)
        bottom = max(y for _x, y in points) + 1
        if right - left >= 3 and bottom - top >= 3:
            result.append((left, top, right, bottom))
    return sorted(result)


def _pilot_components(image, max_width=420, max_height=350, tolerance=55):
    width = min(image.width, max_width)
    height = min(image.height, max_height)
    points = {name: set() for name in PILOT_COLORS}
    for y in range(height):
        for x in range(width):
            red, green, blue = image.getpixel((x, y))[:3]
            if red >= 255 - tolerance and green <= tolerance and blue <= tolerance:
                points["tl"].add((x, y))
            elif green >= 255 - tolerance and red <= tolerance and blue <= tolerance:
                points["tr"].add((x, y))
            elif blue >= 255 - tolerance and red <= tolerance and green <= tolerance:
                points["bl"].add((x, y))
            elif red >= 255 - tolerance and green >= 255 - tolerance and blue <= tolerance:
                points["br"].add((x, y))
    return {name: _extract_components(matching) for name, matching in points.items()}


def _center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _component_evidence(image, boxes):
    evidence = []
    for box in boxes:
        left, top, right, bottom = box
        pixels = [image.getpixel((x, y))[:3] for y in range(top, bottom) for x in range(left, right)]
        representative = tuple(
            round(sum(pixel[channel] for pixel in pixels) / len(pixels), 1)
            for channel in range(3)
        )
        evidence.append({
            "bbox": box,
            "center": _center(box),
            "width": right - left,
            "height": bottom - top,
            "representative_rgb": representative,
        })
    return evidence


def inspect_pilot_geometry(image):
    """Return geometry plus complete component/constraint evidence."""
    started = time.perf_counter()
    components = _pilot_components(image)
    diagnostic = {
        "stage": "pilots_not_found",
        "expected_colors": dict(PILOT_COLORS),
        "pilot_detection": {
            name: {
                "detected": bool(boxes),
                "candidate_count": len(boxes),
                "expected_rgb": PILOT_COLORS[name],
            }
            for name, boxes in components.items()
        },
        "components": {
            name: [
                {
                    **item,
                    "expected_rgb": PILOT_COLORS[name],
                    "tolerance_passed": True,
                }
                for item in _component_evidence(image, boxes)
            ]
            for name, boxes in components.items()
        },
        "selected_pilots": None,
        "derived_pitch_x": None,
        "derived_pitch_y": None,
        "derived_origin": None,
        "predicted_br_center": None,
        "measured_br_center": None,
        "br_residual": None,
        "tuple_combinations": 0,
        "topology_rejections": 0,
        "br_geometry_rejections": 0,
        "geometrically_valid_tuple_count": 0,
        "geometry_candidates": [],
        "tuple_diagnostics": [],
        "strict_decode_attempts": 0,
        "deepest_strict_validation_stage": None,
    }
    for name in ("tl", "tr", "bl", "br"):
        if not components[name]:
            diagnostic["stage"] = f"{name}_missing"
            diagnostic["pilot_selection_seconds"] = time.perf_counter() - started
            return None, diagnostic
    candidates = []
    for tl_box in components["tl"]:
        tl = _center(tl_box)
        for tr_box in components["tr"]:
            diagnostic["tuple_combinations"] += len(components["bl"]) * len(components["br"])
            tr = _center(tr_box)
            if tr[0] - tl[0] < 50 or abs(tr[1] - tl[1]) > 4:
                diagnostic["topology_rejections"] += len(components["bl"]) * len(components["br"])
                diagnostic["tuple_diagnostics"].append({
                    "tl": tl_box, "tr": tr_box, "reason": "top_edge_topology",
                    "rejected_combinations": len(components["bl"]) * len(components["br"]),
                })
                continue
            for bl_box in components["bl"]:
                bl = _center(bl_box)
                if bl[1] - tl[1] < 40 or abs(bl[0] - tl[0]) > 4:
                    diagnostic["topology_rejections"] += len(components["br"])
                    diagnostic["tuple_diagnostics"].append({
                        "tl": tl_box, "tr": tr_box, "bl": bl_box,
                        "reason": "left_edge_topology",
                        "rejected_combinations": len(components["br"]),
                    })
                    continue
                pitch_x = (tr[0] - tl[0]) / PILOT_DX
                pitch_y = (bl[1] - tl[1]) / PILOT_DY
                if not (1.5 <= pitch_x <= 10.0 and 1.5 <= pitch_y <= 10.0):
                    diagnostic["topology_rejections"] += len(components["br"])
                    diagnostic["tuple_diagnostics"].append({
                        "tl": tl_box, "tr": tr_box, "bl": bl_box,
                        "reason": "pitch_range",
                        "pitch_x": pitch_x, "pitch_y": pitch_y,
                        "rejected_combinations": len(components["br"]),
                    })
                    continue
                expected_br = (tl[0] + PILOT_DX * pitch_x, tl[1] + PILOT_DY * pitch_y)
                tolerance = max(1.5, 0.5 * max(pitch_x, pitch_y))
                for br_box in components["br"]:
                    br = _center(br_box)
                    error = math.hypot(br[0] - expected_br[0], br[1] - expected_br[1])
                    if error <= tolerance:
                        geometry = KT08Geometry(
                            tl[0] + pitch_x,
                            tl[1] + pitch_y,
                            pitch_x,
                            pitch_y,
                            (tl, tr, bl, br),
                        )
                        candidates.append((error, geometry, (tl_box, tr_box, bl_box, br_box), expected_br))
                        diagnostic["tuple_diagnostics"].append({
                            "tl": tl_box, "tr": tr_box, "bl": bl_box, "br": br_box,
                            "reason": "geometrically_valid", "pitch_x": pitch_x,
                            "pitch_y": pitch_y, "br_residual": error,
                        })
                    else:
                        diagnostic["br_geometry_rejections"] += 1
                        diagnostic["tuple_diagnostics"].append({
                            "tl": tl_box, "tr": tr_box, "bl": bl_box, "br": br_box,
                            "reason": "br_residual", "pitch_x": pitch_x,
                            "pitch_y": pitch_y, "br_residual": error,
                            "br_tolerance": tolerance,
                        })
    if not candidates:
        diagnostic["stage"] = "pilot_geometry_inconsistent"
        diagnostic["pilot_selection_seconds"] = time.perf_counter() - started
        return None, diagnostic
    candidates.sort(key=lambda item: item[0])
    diagnostic["geometrically_valid_tuple_count"] = len(candidates)
    diagnostic["geometry_candidates"] = [
        {
            "geometry": item[1],
            "boxes": item[2],
            "predicted_br_center": item[3],
            "measured_br_center": item[1].pilots[3],
            "br_residual": item[0],
        }
        for item in candidates
    ]
    error, geometry, boxes, expected_br = candidates[0]
    diagnostic.update({
        "stage": "pilots_validated",
        "selected_pilots": {
            name: {
                **_component_evidence(image, [box])[0],
                "detected": True,
                "expected_rgb": PILOT_COLORS[name],
                "tolerance_passed": True,
            }
            for name, box in zip(("tl", "tr", "bl", "br"), boxes)
        },
        "derived_pitch_x": geometry.pitch_x,
        "derived_pitch_y": geometry.pitch_y,
        "derived_origin": (geometry.x, geometry.y),
        "predicted_br_center": expected_br,
        "measured_br_center": geometry.pilots[3],
        "br_residual": error,
        "pilot_selection_seconds": time.perf_counter() - started,
    })
    return geometry, diagnostic


def locate_pilot_geometry(image):
    """Find four colored corner pilots and solve origin/pitch analytically."""
    return inspect_pilot_geometry(image)[0]


def validate_pilots_at(image, geometry, tolerance=70):
    for center, target in zip(geometry.pilots, PILOT_COLORS.values()):
        cx, cy = center
        matches = 0
        samples = 0
        radius = max(1, int(min(geometry.pitch_x, geometry.pitch_y) * 0.35))
        for y in range(round(cy) - radius, round(cy) + radius + 1):
            for x in range(round(cx) - radius, round(cx) + radius + 1):
                if 0 <= x < image.width and 0 <= y < image.height:
                    samples += 1
                    matches += _near(image.getpixel((x, y)), target, tolerance)
        if not samples or matches < max(3, int(samples * 0.7)):
            return False
    return True


def offset_geometry(geometry, dx, dy):
    return KT08Geometry(
        geometry.x + dx,
        geometry.y + dy,
        geometry.pitch_x,
        geometry.pitch_y,
        tuple((x + dx, y + dy) for x, y in geometry.pilots),
    )


def capture_box_for_geometry(geometry, margin=12):
    right = geometry.x + 35.0 * geometry.pitch_x + margin
    bottom = geometry.y + 28.0 * geometry.pitch_y + margin
    return 0, 0, max(1, int(math.ceil(right))), max(1, int(math.ceil(bottom)))
