"""KT08 pilot geometry and strict visual-frame decoder."""
from dataclasses import dataclass
from pathlib import Path
import pprint
import time

from Bridge.kt08_geometry import KT08Geometry, inspect_pilot_geometry, validate_pilots_at
from Bridge.kt08_protocol import (
    HEADER_SIZE,
    MAX_FRAME_SIZE,
    MAX_PAYLOAD,
    KT08ProtocolError,
    crc32,
    decode_frame,
)


LEVELS = (31, 92, 163, 224)
COLS = 32


@dataclass(frozen=True)
class KT08DecodeResult:
    frame: object | None
    geometry: KT08Geometry | None
    diagnostic: dict


def _sample_symbol(image, geometry, symbol_index):
    row, col = divmod(symbol_index, COLS)
    cx = geometry.x + (col + 0.5) * geometry.pitch_x
    cy = geometry.y + (row + 0.5) * geometry.pitch_y
    radius_x = max(0, int(geometry.pitch_x * 0.2))
    radius_y = max(0, int(geometry.pitch_y * 0.2))
    values = []
    for y in range(max(0, round(cy) - radius_y), min(image.height, round(cy) + radius_y + 1)):
        for x in range(max(0, round(cx) - radius_x), min(image.width, round(cx) + radius_x + 1)):
            pixel = image.getpixel((x, y))
            values.append(sum(pixel[:3]) / 3.0)
    if not values:
        return None
    average = sum(values) / len(values)
    return min(range(4), key=lambda index: abs(average - LEVELS[index]))


def _read_byte(image, geometry, byte_index):
    value = 0
    for offset in range(4):
        symbol = _sample_symbol(image, geometry, byte_index * 4 + offset)
        if symbol is None:
            return None
        value = value * 4 + symbol
    return value


def decode_at(image, geometry):
    started = time.perf_counter()
    diagnostic = {
        "protocol": "KT08",
        "stage": "header",
        "geometry": geometry,
        "pilot_locations": geometry.pilots,
        "sequence_start": None,
        "sequence_end": None,
        "length": None,
        "expected_crc": None,
        "actual_crc": None,
        "decoded_bytes": 0,
    }
    if not validate_pilots_at(image, geometry):
        diagnostic["stage"] = "pilots"
        diagnostic["failure_reason"] = "one or more KT08 pilots are missing or damaged"
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    header = bytearray()
    for index in range(HEADER_SIZE):
        value = _read_byte(image, geometry, index)
        if value is None:
            diagnostic["stage"] = "sampling"
            diagnostic["total_seconds"] = time.perf_counter() - started
            return KT08DecodeResult(None, geometry, diagnostic)
        header.append(value)
    diagnostic["decoded_magic_hex"] = bytes(header[:4]).hex()
    diagnostic["decoded_magic_bytes"] = tuple(header[:4])
    diagnostic["version"] = header[4]
    diagnostic["flags"] = header[5]
    diagnostic["sequence_start"] = int.from_bytes(header[6:8], "big")
    length = int.from_bytes(header[8:10], "big")
    diagnostic["length"] = length
    if bytes(header[:4]) != b"KT08":
        diagnostic["stage"] = "header_magic_failed"
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    if header[4] != 1:
        diagnostic["stage"] = "version_failed"
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    if header[5] != 0:
        diagnostic["stage"] = "flags_failed"
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    if length > MAX_PAYLOAD:
        diagnostic["stage"] = "length_failed"
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    size = HEADER_SIZE + length + 6
    raw = bytearray(header)
    for index in range(HEADER_SIZE, size):
        value = _read_byte(image, geometry, index)
        if value is None:
            diagnostic["stage"] = "sampling"
            diagnostic["total_seconds"] = time.perf_counter() - started
            return KT08DecodeResult(None, geometry, diagnostic)
        raw.append(value)
    diagnostic["decoded_bytes"] = len(raw)
    payload_end = HEADER_SIZE + length
    diagnostic["sequence_start"] = int.from_bytes(raw[6:8], "big")
    diagnostic["sequence_end"] = int.from_bytes(raw[payload_end:payload_end + 2], "big")
    diagnostic["expected_crc"] = int.from_bytes(raw[payload_end + 2:payload_end + 6], "big")
    diagnostic["actual_crc"] = crc32(raw[:payload_end + 2])
    diagnostic["payload_hex"] = bytes(raw[HEADER_SIZE:payload_end]).hex()
    try:
        frame = decode_frame(raw)
    except KT08ProtocolError as exc:
        diagnostic.update(exc.details)
        diagnostic["stage"] = {
            "magic": "header_magic_failed",
            "version": "version_failed",
            "flags": "flags_failed",
            "length": "length_failed",
            "truncated": "frame_truncated",
            "sequence": "sequence_failed",
            "crc": "crc_failed",
            "utf8": "utf8_failed",
        }.get(exc.stage, exc.stage)
        diagnostic["failure_reason"] = str(exc)
        diagnostic["total_seconds"] = time.perf_counter() - started
        return KT08DecodeResult(None, geometry, diagnostic)
    diagnostic.update({
        "stage": "success",
        "sequence_start": frame.sequence,
        "sequence_end": frame.sequence,
        "total_seconds": time.perf_counter() - started,
        "decoded_utf8": frame.text,
    })
    return KT08DecodeResult(frame, geometry, diagnostic)


def locate_and_decode(image):
    started = time.perf_counter()
    geometry, pilot_diagnostic = inspect_pilot_geometry(image)
    if geometry is None:
        pilot_diagnostic.update({
            "protocol": "KT08", "total_seconds": time.perf_counter() - started
        })
        return KT08DecodeResult(None, None, pilot_diagnostic)
    strict_results = []
    attempted = []
    successes = []
    for candidate in pilot_diagnostic["geometry_candidates"]:
        candidate_result = decode_at(image, candidate["geometry"])
        attempted.append((candidate, candidate_result))
        strict_results.append({
            "geometry": candidate["geometry"],
            "br_residual": candidate["br_residual"],
            "stage": candidate_result.diagnostic["stage"],
            "decoded_bytes": candidate_result.diagnostic.get("decoded_bytes", 0),
        })
        if candidate_result.frame is not None:
            successes.append((candidate, candidate_result))
    pilot_diagnostic["strict_decode_attempts"] = len(strict_results)
    pilot_diagnostic["strict_decode_results"] = strict_results
    pilot_diagnostic["strict_success_count"] = len(successes)
    pilot_diagnostic["deepest_strict_validation_stage"] = max(
        strict_results, key=lambda item: item["decoded_bytes"]
    )["stage"]
    if not successes:
        result = attempted[0][1]
        result.diagnostic["pilot_evidence"] = pilot_diagnostic
        result.diagnostic["geometry_seconds"] = pilot_diagnostic["pilot_selection_seconds"]
        result.diagnostic["total_seconds"] = time.perf_counter() - started
        return result
    identities = {
        (item[1].frame.sequence, item[1].frame.payload)
        for item in successes
    }
    if len(identities) > 1:
        return KT08DecodeResult(None, None, {
            "protocol": "KT08",
            "stage": "ambiguous_valid_frames",
            "failure_reason": "multiple pilot geometries produced conflicting valid KT08 frames",
            "valid_frame_identities": [
                {"sequence": sequence, "payload_hex": payload.hex()}
                for sequence, payload in sorted(identities)
            ],
            "pilot_evidence": pilot_diagnostic,
            "total_seconds": time.perf_counter() - started,
        })
    selected_candidate, result = successes[0]
    pilot_diagnostic["selected_geometry"] = selected_candidate["geometry"]
    pilot_diagnostic["selected_tuple"] = selected_candidate["boxes"]
    pilot_diagnostic["selected_br_residual"] = selected_candidate["br_residual"]
    result.diagnostic["pilot_evidence"] = pilot_diagnostic
    result.diagnostic["geometry_seconds"] = pilot_diagnostic["pilot_selection_seconds"]
    result.diagnostic["total_seconds"] = time.perf_counter() - started
    return result


def preserve_failure(image, directory, generation, diagnostic, retain_generations=3):
    """Keep the first raw KT08 pilot/protocol failure for a native generation."""
    directory = Path(directory)
    image_path = directory / f"kt08_relocation_failure_{generation}_validation.png"
    report_path = directory / f"kt08_relocation_failure_{generation}.txt"
    if image_path.exists() or report_path.exists():
        return None
    image.save(image_path)
    report_path.write_text(
        pprint.pformat(diagnostic, sort_dicts=False, width=140) + "\n",
        encoding="utf-8",
    )
    generations = []
    for path in directory.glob("kt08_relocation_failure_*_validation.png"):
        value = path.stem.removeprefix("kt08_relocation_failure_").removesuffix("_validation")
        if value.isdigit():
            generations.append(int(value))
    for old in sorted(set(generations))[:-retain_generations]:
        for suffix in ("_validation.png", ".txt"):
            stale = directory / f"kt08_relocation_failure_{old}{suffix}"
            if stale.exists():
                stale.unlink()
    return image_path, report_path


def preserve_initial_failure(image, directory, counter, diagnostic):
    """Preserve one immutable raw source image for an initial visible interval."""
    directory = Path(directory)
    image_path = directory / f"kt08_initial_failure_{counter}.png"
    report_path = directory / f"kt08_initial_failure_{counter}.txt"
    if image_path.exists() or report_path.exists():
        return None
    image.save(image_path)
    report_path.write_text(
        pprint.pformat(diagnostic, sort_dicts=False, width=140) + "\n",
        encoding="utf-8",
    )
    return image_path, report_path
