import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw

from Bridge.kt07_decoder import (COLS, Geometry, MAGIC, audit_initial_candidate, capture_box_for_geometry, decode_at, decode_local_candidate, decode_near_anchor, decode_relocation_candidate, has_signal_at, summarize_initial_consensus)

IDEAL = (31, 92, 163, 224)


def _frame_bytes(text):
    payload = list(text.encode("utf-8"))
    checksum = (sum(MAGIC) + len(payload) + sum(payload)) % 256
    return list(MAGIC) + [len(payload)] + payload + [checksum]


def _symbols(text):
    result = []
    for value in _frame_bytes(text):
        result.extend(((value >> 6) & 3, (value >> 4) & 3, (value >> 2) & 3, value & 3))
    return result


def render(text, geometry, size=(900, 260)):
    image = Image.new("RGB", size, (8, 8, 8))
    draw = ImageDraw.Draw(image)
    for index, symbol in enumerate(_symbols(text)):
        col, row = index % COLS, index // COLS
        x0 = geometry.x + col * geometry.pitch_x
        y0 = geometry.y + row * geometry.pitch_y
        x1 = geometry.x + (col + 1) * geometry.pitch_x
        y1 = geometry.y + (row + 1) * geometry.pitch_y
        level = IDEAL[symbol]
        draw.rectangle((int(round(x0)), int(round(y0)), int(round(x1)) - 1,
                        int(round(y1)) - 1), fill=(level, level, level))
    return image


class KT07DecoderTests(unittest.TestCase):

    def test_real_fullscreen_ambiguity_fixture_remains_rejected(self):
        fixture = Path(__file__).parent / "fixtures" / "kt07_initial_ambiguity.png"
        image = Image.open(fixture).convert("RGB")
        anchor_box = (11, 1, 71, 11)
        found = decode_near_anchor(image, anchor_box, 5.0, exhaustive=False)
        diagnostic = audit_initial_candidate(image, anchor_box, 5.0, found)
        self.assertTrue(diagnostic["ambiguous"])
        self.assertEqual(21, diagnostic["total_valid_candidates"])
        self.assertEqual(2, diagnostic["unique_payload_count"])
        supports = sorted(
            group["support_count"] for group in diagnostic["payload_groups"]
        )
        self.assertEqual([9, 12], supports)
    @staticmethod
    def _consensus_candidates(populations):
        candidates = []
        order = 0
        for text, count in populations:
            for index in range(count):
                order += 1
                geometry = Geometry(
                    7.25 + (index % 4) * .25,
                    16.0 + ((index // 4) % 4) * .25,
                    5.75 + (index % 3) * .125,
                    5.625 + ((index // 3) % 3) * .125,
                )
                candidates.append({
                    "order": order,
                    "geometry": geometry,
                    "text": text,
                    "payload_hex": text.encode("utf-8").hex(),
                    "anchor_pitch_error": abs(5.875 - geometry.pitch_x) + abs(5.75 - geometry.pitch_y),
                    "anchor_origin_error": abs(7.5 - geometry.x) + abs(16.5 - geometry.y),
                })
        return candidates

    def test_real_118_to_1_consensus_ignores_first_corrupt_candidate(self):
        corrupt = "OUT\tYou\tTUU\x14Ynf\x14dieting t(e first ira"
        correct = "OUT\tYou\tTesting the first translation"
        candidates = self._consensus_candidates(((corrupt, 1), (correct, 118)))
        result = summarize_initial_consensus(candidates)
        self.assertTrue(result["consensus_accepted"])
        self.assertEqual(118, result["winning_support"])
        self.assertEqual(1, result["runner_up_support"])
        self.assertEqual(correct, result["selected_text"])
        winning_geometries = {
            item["geometry"] for item in candidates if item["text"] == correct
        }
        self.assertIn(result["selected_geometry"], winning_geometries)

    def test_conservative_consensus_rejects_competitive_populations(self):
        for winner, runner in ((1, 1), (2, 1), (3, 2), (6, 4), (60, 40)):
            with self.subTest(winner=winner, runner=runner):
                result = summarize_initial_consensus(
                    self._consensus_candidates((("任意一", winner), ("arbitrary two", runner)))
                )
                self.assertFalse(result["consensus_accepted"])

    def test_consensus_accepts_99_to_1_and_unanimous_or_single(self):
        overwhelming = summarize_initial_consensus(
            self._consensus_candidates((("任意 UTF-8", 99), ("other", 1)))
        )
        unanimous = summarize_initial_consensus(
            self._consensus_candidates((("binary-safe ✓", 12),))
        )
        single = summarize_initial_consensus(
            self._consensus_candidates((("single", 1),))
        )
        self.assertTrue(overwhelming["consensus_accepted"])
        self.assertTrue(unanimous["consensus_accepted"])
        self.assertTrue(single["consensus_accepted"])

    def test_representative_geometry_uses_anchor_errors_not_order(self):
        candidates = self._consensus_candidates((("same bytes", 12),))
        candidates[0]["anchor_pitch_error"] = 99
        candidates[0]["anchor_origin_error"] = 99
        result = summarize_initial_consensus(candidates)
        self.assertNotEqual(candidates[0]["geometry"], result["selected_geometry"])
    def test_initial_audit_reports_and_rejects_competing_valid_payloads(self):
        first = Geometry(7.5, 16.5, 5.875, 5.625)
        correct = Geometry(7.75, 16.5, 5.875, 5.75)

        def details(_image, geometry):
            text = None
            if geometry == first:
                text = "this is thi!!ir!t(e first ira"
            elif geometry == correct:
                text = "任意 UTF-8 payload"
            if text is None:
                return None
            payload = text.encode("utf-8")
            checksum = (sum(MAGIC) + len(payload) + sum(payload)) % 256
            return {
                "geometry": geometry,
                "magic": MAGIC,
                "length": len(payload),
                "checksum_expected": checksum,
                "checksum_actual": checksum,
                "text": text,
            }

        with patch(
            "Bridge.kt07_decoder._quick_magic_prefix", return_value=True
        ), patch(
            "Bridge.kt07_decoder.decode_details", side_effect=details
        ):
            diagnostic = audit_initial_candidate(
                object(), (6, 1, 78, 13), 6.0, ("wrong", first)
            )

        self.assertTrue(diagnostic["ambiguous"])
        self.assertEqual(2, len(diagnostic["candidates"]))
        self.assertEqual(
            {"this is thi!!ir!t(e first ira", "任意 UTF-8 payload"},
            {candidate["text"] for candidate in diagnostic["candidates"]},
        )
    def test_capture_box_scales_with_geometry(self):
        small = Geometry(7.5, 16.5, 3.0, 3.0)
        large = Geometry(7.5, 16.5, 8.0, 7.75)

        small_box = capture_box_for_geometry(small)
        large_box = capture_box_for_geometry(large)

        self.assertGreater(
            large_box[2] - large_box[0],
            small_box[2] - small_box[0],
        )
        self.assertGreater(
            large_box[3] - large_box[1],
            small_box[3] - small_box[1],
        )

    def test_capture_box_contains_maximum_frame(self):
        cases = (
            Geometry(7.5, 16.5, 2.5, 2.5),
            Geometry(12.25, 16.5, 3.25, 3.5),
            Geometry(21.0, 24.0, 6.0, 6.0),
            Geometry(300.5, 180.25, 8.0, 7.75),
        )

        total_symbols = (
            (len(MAGIC) + 1 + 180 + 1) * 4
        )
        rows = (total_symbols + COLS - 1) // COLS

        for geometry in cases:
            with self.subTest(geometry=geometry):
                left, top, right, bottom = (
                    capture_box_for_geometry(geometry)
                )

                self.assertLessEqual(left, geometry.x)
                self.assertLessEqual(top, geometry.y)

                self.assertGreaterEqual(
                    right,
                    geometry.x
                    + COLS * geometry.pitch_x,
                )
                self.assertGreaterEqual(
                    bottom,
                    geometry.y
                    + rows * geometry.pitch_y,
                )

    def test_origin_preserving_crop_decodes_without_translation(self):
        geometry = Geometry(
            120.25,
            90.5,
            4.25,
            4.0,
        )
        image = render(
            "cropped transport",
            geometry,
            size=(900, 500),
        )

        box = capture_box_for_geometry(geometry)
        cropped = image.crop(box)

        self.assertEqual((0, 0), box[:2])
        self.assertEqual(
            "cropped transport",
            decode_at(cropped, geometry),
        )

    def test_capture_box_never_uses_negative_origin(self):
        geometry = Geometry(
            2.0,
            3.0,
            3.0,
            3.0,
        )

        box = capture_box_for_geometry(geometry)

        self.assertEqual(0, box[0])
        self.assertEqual(0, box[1])

    def test_exact_geometries(self):
        cases = (
            Geometry(7.0, 12.0, 2.5, 2.5),
            Geometry(11.25, 17.5, 2.75, 3.0),
            Geometry(7.0, 12.0, 3.0, 3.0),
            Geometry(12.25, 16.5, 3.25, 3.5),
            Geometry(13.5, 19.25, 4.5, 4.25),
            Geometry(21.0, 24.0, 6.0, 6.0),
            Geometry(30.25, 31.5, 8.0, 7.75),
        )
        for geometry in cases:
            with self.subTest(geometry=geometry):
                image = render("hello 世界", geometry)
                self.assertEqual("hello 世界", decode_at(image, geometry))

    def test_fractional_origin_drift_matrix(self):
        pitches = (2.5, 2.75, 3.0, 3.25, 3.5, 4.25)
        origins = ((7.0, 10.0), (7.25, 10.5), (11.5, 17.25))
        for pitch in pitches:
            for x, y in origins:
                geometry = Geometry(x, y, pitch, pitch)
                with self.subTest(geometry=geometry):
                    image = render("KT07 scale test", geometry)
                    self.assertEqual("KT07 scale test", decode_at(image, geometry))

    def test_adaptive_search_recovers_three_pixel_case(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("can you invite me?", geometry)
        result = decode_near_anchor(image, (7, 1, 43, 7), 3.0)
        self.assertIsNotNone(result)
        self.assertEqual("can you invite me?", result[0])

    def test_adaptive_search_handles_anisotropic_fractional_pitch(self):
        geometry = Geometry(12.25, 16.5, 3.25, 3.5)
        image = render("我们需要一个治疗。", geometry)
        result = decode_near_anchor(image, (8, 2, 45, 8), 3.25)
        self.assertIsNotNone(result)
        self.assertEqual("我们需要一个治疗。", result[0])

    def test_windowed_relocation_candidate_is_strict_and_bounded(self):
        geometry = Geometry(3.75, 12.0, 4.5, 4.5)
        image = render("first Windowed payload", geometry, size=(420, 350))
        started = time.perf_counter()
        result, diagnostic = decode_relocation_candidate(
            image, (6, 0, 54, 8), 4.0
        )
        elapsed = time.perf_counter() - started
        self.assertIsNotNone(result)
        self.assertEqual("first Windowed payload", result[0])
        self.assertAlmostEqual(3.75, result[1].x, delta=1.0)
        self.assertAlmostEqual(12.0, result[1].y, delta=2.0)
        self.assertEqual(4.5, result[1].pitch_x)
        self.assertEqual(4.5, result[1].pitch_y)
        self.assertLess(elapsed, 0.5)
        self.assertLessEqual(diagnostic["decode_attempts"], diagnostic["geometry_candidates"])
        self.assertLess(diagnostic["geometry_candidates"], 25_000)

    def test_additive_checksum_can_accept_balanced_ascii_corruption(self):
        original = b"first trailer deflation eul"
        corrupted = bytearray(original)
        corrupted[1] += 1
        corrupted[2] -= 1
        self.assertNotEqual(original, bytes(corrupted))
        self.assertEqual(sum(original) % 256, sum(corrupted) % 256)
        bytes(corrupted).decode("utf-8")

    def test_failed_windowed_relocation_search_has_hard_candidate_bound(self):
        image = Image.new("RGB", (420, 350), (92, 92, 92))
        started = time.perf_counter()
        result, diagnostic = decode_relocation_candidate(
            image, (6, 0, 54, 8), 4.0
        )
        elapsed = time.perf_counter() - started
        self.assertIsNone(result)
        self.assertEqual(24_375, diagnostic["decode_attempts"])
        self.assertEqual(24_375, diagnostic["geometry_candidates"])
        self.assertLess(elapsed, 0.5)

    def test_failed_locked_local_search_is_bounded(self):
        image = Image.new("RGB", (420, 350), (92, 92, 92))
        trusted = Geometry(7.5, 16.5, 5.875, 5.75)
        started = time.perf_counter()
        result, attempts = decode_local_candidate(image, trusted)
        elapsed = time.perf_counter() - started
        self.assertIsNone(result)
        self.assertEqual(625, attempts)
        self.assertLess(elapsed, 0.5)

    def test_checksum_corruption_is_rejected(self):
        geometry = Geometry(10.0, 15.0, 4.0, 4.0)
        image = render("checksum", geometry)
        data = _frame_bytes("checksum")
        checksum_byte = len(data) - 1
        first_symbol = checksum_byte * 4
        col, row = first_symbol % COLS, first_symbol // COLS
        x0 = int(round(geometry.x + col * geometry.pitch_x))
        y0 = int(round(geometry.y + row * geometry.pitch_y))
        draw = ImageDraw.Draw(image)
        draw.rectangle((x0, y0, x0 + 3, y0 + 3), fill=(224, 224, 224))
        self.assertIsNone(decode_at(image, geometry))

    def test_magic_without_valid_frame_never_passes(self):
        geometry = Geometry(8.0, 12.0, 3.0, 3.0)
        image = render("valid", geometry)
        payload_symbol = 5 * 4
        col, row = payload_symbol % COLS, payload_symbol // COLS
        x0 = int(round(geometry.x + col * geometry.pitch_x))
        y0 = int(round(geometry.y + row * geometry.pitch_y))
        ImageDraw.Draw(image).rectangle((x0, y0, x0 + 2, y0 + 2),
                                        fill=(224, 224, 224))
        self.assertIsNone(decode_at(image, geometry))

    def test_signal_probe_detects_real_rendered_frame(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("signal probe", geometry)

        self.assertTrue(
            has_signal_at(image, geometry)
        )

    def test_signal_probe_rejects_empty_transport_area(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = Image.new(
            "RGB",
            (900, 260),
            (8, 8, 8),
        )

        self.assertFalse(
            has_signal_at(image, geometry)
        )

    def test_signal_probe_tolerates_reasonable_level_drift(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("level drift", geometry)

        # Simulate modest capture/interpolation luminance drift while
        # preserving grayscale KT07 cells.
        pixels = image.load()

        for y in range(image.height):
            for x in range(image.width):
                r, g, b = pixels[x, y]

                if r == g == b and r in IDEAL:
                    shifted = min(255, r + 12)
                    pixels[x, y] = (
                        shifted,
                        shifted,
                        shifted,
                    )

        self.assertTrue(
            has_signal_at(image, geometry)
        )
        self.assertEqual(
            "level drift",
            decode_at(image, geometry),
        )

    def test_signal_probe_does_not_validate_geometry(self):
        real_geometry = Geometry(
            12.25,
            16.5,
            3.25,
            3.5,
        )
        wrong_geometry = Geometry(
            200.0,
            120.0,
            3.25,
            3.5,
        )

        image = render(
            "geometry probe",
            real_geometry,
        )

        self.assertTrue(
            has_signal_at(image, real_geometry)
        )
        self.assertFalse(
            has_signal_at(image, wrong_geometry)
        )
        self.assertIsNone(
            decode_at(image, wrong_geometry)
        )

    def test_locked_fast_path_is_cheap(self):
        geometry = Geometry(7.0, 10.0, 3.0, 3.0)
        image = render("fast path", geometry)
        start = time.perf_counter()
        for _ in range(100):
            self.assertEqual("fast path", decode_at(image, geometry))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0, f"100 locked decodes took {elapsed:.3f}s")

    def test_bounded_negative_calibration_does_not_run_away(self):
        image = Image.new("RGB", (360, 260), (8, 8, 8))
        start = time.perf_counter()
        self.assertIsNone(decode_near_anchor(image, (7, 1, 43, 7), 3.0))
        elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 2.0, f"negative calibration took {elapsed:.3f}s")


    def test_signal_probe_rejects_idle_background_near_kt07_levels(self):
        geometry = Geometry(
            7.5,
            16.5,
            5.875,
            5.75,
        )

        # Simulate the transport area after the payload disappears.
        # Background may be grayscale and numerically close to a KT07
        # symbol level, but that alone must not count as active transport.
        image = Image.new(
            "RGB",
            (360, 260),
            (32, 32, 32),
        )

        self.assertFalse(
            has_signal_at(image, geometry)
        )

    def test_signal_probe_detects_corrupted_real_transport(self):
        geometry = Geometry(
            7.5,
            16.5,
            5.875,
            5.75,
        )

        image = render(
            "active transport",
            geometry,
            size=(360, 260),
        )

        # Break validation later in the frame while leaving the transport
        # header physically present.
        draw = ImageDraw.Draw(image)
        index = 5 * 4
        col, row = index % COLS, index // COLS

        x0 = int(round(
            geometry.x + col * geometry.pitch_x
        ))
        y0 = int(round(
            geometry.y + row * geometry.pitch_y
        ))

        draw.rectangle(
            (x0, y0, x0 + 4, y0 + 4),
            fill=(255, 0, 0),
        )

        self.assertIsNone(
            decode_at(image, geometry)
        )
        self.assertTrue(
            has_signal_at(image, geometry)
        )


if __name__ == "__main__":
    unittest.main()
