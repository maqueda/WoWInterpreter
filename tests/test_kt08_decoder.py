import time
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw

from Bridge.kt08_decoder import decode_at, locate_and_decode, preserve_initial_failure
from Bridge.kt08_geometry import locate_pilot_geometry
from tests.kt08_helpers import render_kt08


class KT08DecoderTests(unittest.TestCase):
    FIXTURES = Path(__file__).parent / "fixtures"

    def test_real_initial_failure_fixtures_acquire_and_decode_strictly(self):
        expected = {
            1: (1, "META\tCHAT1\t35.0,50.0,300.7,222.0,0.8000", 2352075125),
            2: (2, "OUT\tYou\tThis is the first translation", 1411320932),
        }
        for number, (sequence, payload, checksum) in expected.items():
            with self.subTest(fixture=number):
                image = Image.open(
                    self.FIXTURES / f"kt08_initial_failure_{number}.png"
                ).convert("RGB")
                result = locate_and_decode(image)
                self.assertEqual("success", result.diagnostic["stage"])
                self.assertEqual(sequence, result.frame.sequence)
                self.assertEqual(payload, result.frame.text)
                self.assertEqual(checksum, result.diagnostic["expected_crc"])
                self.assertEqual(checksum, result.diagnostic["actual_crc"])
                self.assertEqual((18.0, 36.0, 6.0, 6.0), (
                    result.geometry.x, result.geometry.y,
                    result.geometry.pitch_x, result.geometry.pitch_y,
                ))
                evidence = result.diagnostic["pilot_evidence"]
                self.assertEqual(24, evidence["tuple_combinations"])
                self.assertEqual(1, evidence["geometrically_valid_tuple_count"])
                self.assertEqual(1, evidence["strict_decode_attempts"])

    @staticmethod
    def _combine(*images):
        background = (10, 12, 14)
        combined = Image.new("RGB", images[0].size, background)
        for source in images:
            for y in range(source.height):
                for x in range(source.width):
                    pixel = source.getpixel((x, y))
                    if pixel != background:
                        combined.putpixel((x, y), pixel)
        return combined

    def test_conflicting_strictly_valid_pilot_rectangles_are_ambiguous(self):
        image = self._combine(
            render_kt08("one", 1, 10, 25, 2, 2),
            render_kt08("two", 2, 210, 25, 2, 2),
        )
        result = locate_and_decode(image)
        self.assertIsNone(result.frame)
        self.assertIsNone(result.geometry)
        self.assertEqual("ambiguous_valid_frames", result.diagnostic["stage"])
        self.assertEqual(2, len(result.diagnostic["valid_frame_identities"]))

    def test_strict_crc_selects_only_valid_of_two_geometric_rectangles(self):
        image = self._combine(
            render_kt08("winner", 7, 10, 25, 2, 2),
            render_kt08(
                "damaged", 8, 210, 25, 2, 2,
                mutate=lambda raw: raw.__setitem__(10, raw[10] ^ 1),
            ),
        )
        result = locate_and_decode(image)
        self.assertEqual("winner", result.frame.text)
        evidence = result.diagnostic["pilot_evidence"]
        self.assertGreaterEqual(evidence["strict_decode_attempts"], 2)
        self.assertEqual(1, evidence["strict_success_count"])

    def test_extra_same_color_components_do_not_preempt_valid_tuple(self):
        image = render_kt08("joint selection", 9)
        draw = ImageDraw.Draw(image)
        for box, color in (
            ((300, 8, 305, 13), (255, 0, 0)),
            ((360, 8, 365, 13), (0, 255, 0)),
            ((300, 100, 305, 105), (0, 0, 255)),
            ((360, 100, 365, 105), (255, 255, 0)),
        ):
            draw.rectangle(box, fill=color)
        result = locate_and_decode(image)
        self.assertEqual("joint selection", result.frame.text)
        self.assertGreater(result.diagnostic["pilot_evidence"]["tuple_combinations"], 1)

    def test_presence_anchor_alone_is_not_a_kt08_rectangle(self):
        image = Image.new("RGB", (420, 350), (10, 12, 14))
        draw = ImageDraw.Draw(image)
        for index, color in enumerate((
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (0, 255, 255), (255, 0, 255),
        )):
            draw.rectangle((6 + index * 12, 6, 17 + index * 12, 17), fill=color)
        result = locate_and_decode(image)
        self.assertIsNone(result.frame)
        self.assertEqual("pilot_geometry_inconsistent", result.diagnostic["stage"])

    def test_overlay_occluding_lower_pilots_remains_a_capture_failure(self):
        image = render_kt08("physically occluded", 12, 18, 36, 6, 6)
        # Model the real failure: the overlay replaces the lower pilot/data
        # pixels in ImageGrab. The decoder must not compensate for missing data.
        ImageDraw.Draw(image).rectangle((0, 80, 419, 349), fill=(16, 16, 16))
        result = locate_and_decode(image)
        self.assertIsNone(result.frame)
        self.assertEqual("pilot_geometry_inconsistent", result.diagnostic["stage"])
        self.assertEqual(0, result.diagnostic["strict_decode_attempts"])

    def test_real_overlay_occluded_initial_fixtures_remain_rejected(self):
        for number in (3, 4):
            with self.subTest(fixture=number):
                image = Image.open(
                    self.FIXTURES / f"kt08_initial_failure_{number}.png"
                ).convert("RGB")
                result = locate_and_decode(image)
                self.assertIsNone(result.frame)
                self.assertEqual(
                    "pilot_geometry_inconsistent", result.diagnostic["stage"]
                )
                self.assertEqual(0, result.diagnostic["strict_decode_attempts"])


    def test_first_initial_failure_raw_image_cannot_be_overwritten(self):
        image = render_kt08("first", 1, anchor_gap=0)
        diagnostic = locate_and_decode(image).diagnostic
        with tempfile.TemporaryDirectory() as directory:
            saved = preserve_initial_failure(image, directory, 1, diagnostic)
            original_png = saved[0].read_bytes()
            original_txt = saved[1].read_text(encoding="utf-8")
            replacement = render_kt08("replacement", 2)
            self.assertIsNone(
                preserve_initial_failure(replacement, directory, 1, {"stage": "other"})
            )
            self.assertEqual(original_png, saved[0].read_bytes())
            self.assertEqual(original_txt, saved[1].read_text(encoding="utf-8"))
            self.assertIn("header_magic_failed", original_txt)

    def test_maximum_visual_payload(self):
        payload = "x" * 180
        result = locate_and_decode(render_kt08(payload, 65535))
        self.assertEqual(payload, result.frame.text)
        self.assertEqual(65535, result.frame.sequence)

    def test_integer_fractional_anisotropic_and_shifted_geometry(self):
        cases = (
            (10.0, 18.0, 4.0, 4.0),
            (10.25, 18.5, 3.875, 3.875),
            (17.375, 22.625, 4.125, 3.875),
            (93.75, 12.25, 3.625, 3.875),
        )
        for x, y, pitch_x, pitch_y in cases:
            with self.subTest(case=(x, y, pitch_x, pitch_y)):
                image = render_kt08("fractional 第八版", 31, x, y, pitch_x, pitch_y)
                result = locate_and_decode(image)
                self.assertEqual("success", result.diagnostic["stage"])
                self.assertEqual("fractional 第八版", result.frame.text)
                self.assertAlmostEqual(pitch_x, result.geometry.pitch_x, delta=0.04)
                self.assertAlmostEqual(pitch_y, result.geometry.pitch_y, delta=0.04)

    def test_full_lua_layout_keeps_anchor_separate_from_tl_pilot(self):
        image = render_kt08("contract", 5, 12, 24, 4, 4)
        result = locate_and_decode(image)
        self.assertEqual("contract", result.frame.text)
        red_components = result.diagnostic["pilot_evidence"]["components"]["tl"]
        self.assertEqual(2, len(red_components))
        self.assertEqual((4, 4, 12, 12), red_components[0]["bbox"])
        self.assertEqual((4, 16, 12, 24), red_components[1]["bbox"])

    def test_old_contiguous_lua_layout_produces_combined_red_component(self):
        image = render_kt08("contract", 5, 12, 20, 4, 4, anchor_gap=0)
        result = locate_and_decode(image)
        red_components = result.diagnostic.get("pilot_evidence", result.diagnostic)["components"]["tl"]
        self.assertEqual((4, 4, 12, 20), red_components[0]["bbox"])
        self.assertIsNone(result.frame)

    def test_pilot_derived_decode_is_bounded_and_fast(self):
        image = render_kt08("bounded", 1, 92.75, 20.5, 3.875, 3.75)
        started = time.perf_counter()
        result = locate_and_decode(image)
        elapsed = time.perf_counter() - started
        self.assertEqual("bounded", result.frame.text)
        self.assertLess(elapsed, 0.2)

    def test_damaged_pilot_and_inconsistent_geometry_are_rejected(self):
        image = render_kt08("pilot", 2)
        draw = ImageDraw.Draw(image)
        draw.rectangle((140, 10, 150, 25), fill=(0, 0, 0))
        self.assertIsNone(locate_and_decode(image).frame)

        image = render_kt08("pilot", 2)
        draw = ImageDraw.Draw(image)
        draw.rectangle((140, 120, 155, 135), fill=(255, 255, 0))
        self.assertIsNone(locate_and_decode(image).frame)

    def test_valid_pilots_with_crc_corruption_are_rejected(self):
        image = render_kt08("crc", 7, mutate=lambda raw: raw.__setitem__(10, raw[10] ^ 1))
        result = locate_and_decode(image)
        self.assertIsNone(result.frame)
        self.assertEqual("crc_failed", result.diagnostic["stage"])

    def test_payload_without_pilots_is_rejected(self):
        self.assertIsNone(locate_and_decode(render_kt08("no pilots", pilots=False)).frame)

    def test_false_colored_ui_pixels_do_not_form_geometry(self):
        image = render_kt08("hidden", pilots=False)
        draw = ImageDraw.Draw(image)
        draw.rectangle((5, 5, 12, 12), fill=(255, 0, 0))
        draw.rectangle((60, 30, 67, 37), fill=(0, 255, 0))
        draw.rectangle((20, 80, 27, 87), fill=(0, 0, 255))
        draw.rectangle((100, 100, 107, 107), fill=(255, 255, 0))
        self.assertIsNone(locate_pilot_geometry(image))


if __name__ == "__main__":
    unittest.main()
