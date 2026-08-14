import time
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image, ImageDraw

from Bridge.kt07_decoder import Geometry
from Bridge.kt07_relocation import (
    ANCHOR_COLORS,
    RelocationProbeBackoff,
    discover_candidate_rois,
    offset_box,
    offset_geometry,
    save_discovery_diagnostic,
    validate_candidate_rois,
)
from Bridge.kt07_tracker import KT07GeometryTracker


class KT07RelocationTests(unittest.TestCase):

    @staticmethod
    def _anchor_image(width, x, y, size=(900, 600)):
        image = Image.new("RGB", size, (20, 20, 20))
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(ANCHOR_COLORS):
            draw.rectangle(
                (x + index * width, y, x + (index + 1) * width - 1, y + width - 1),
                fill=color,
            )
        return image

    def test_all_supported_widths_and_modulo_four_phases_are_discovered(self):
        for width in range(4, 17):
            for x_phase in range(4):
                for y_phase in range(4):
                    with self.subTest(width=width, x=x_phase, y=y_phase):
                        image = self._anchor_image(
                            width,
                            301 + x_phase,
                            201 + y_phase,
                        )
                        self.assertTrue(discover_candidate_rois(image))

    def test_displaced_anchor_produces_small_candidate_roi(self):
        image = Image.new("RGB", (1000, 700), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        x, y, block = 620, 310, 8
        for index, color in enumerate(ANCHOR_COLORS):
            draw.rectangle(
                (x + index * block, y, x + (index + 1) * block - 1, y + block - 1),
                fill=color,
            )

        rois = discover_candidate_rois(image)

        self.assertTrue(rois)
        left, top, right, bottom = rois[0]
        self.assertLessEqual(left, x)
        self.assertLessEqual(top, y)
        self.assertGreater(right, x + 6 * block)
        self.assertGreater(bottom, y + block)
        self.assertLess((right - left) * (bottom - top), image.width * image.height)

    def test_blank_full_hd_discovery_is_fast_and_has_no_candidates(self):
        image = Image.new("RGB", (2560, 1440), (20, 20, 20))
        started = time.perf_counter()
        rois = discover_candidate_rois(image)
        elapsed = time.perf_counter() - started
        self.assertEqual([], rois)
        self.assertLess(elapsed, 1.0)

    def test_wrong_color_order_is_not_a_candidate(self):
        image = Image.new("RGB", (900, 600), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(reversed(ANCHOR_COLORS)):
            draw.rectangle((300 + index * 8, 200, 307 + index * 8, 207), fill=color)
        self.assertEqual([], discover_candidate_rois(image))

    def test_fractional_scale_rasterization_and_odd_desktop_size(self):
        # A fractional UI/DPI scale commonly rasterizes an 8-unit Lua block
        # to alternating 5/6 px widths. Use those exact full-resolution runs
        # on a desktop whose dimensions are not divisible by four.
        image = Image.new("RGB", (903, 607), (20, 20, 20))
        draw = ImageDraw.Draw(image)
        x, y = 731, 417
        widths = (5, 6, 5, 6, 5, 6)
        cursor = x
        for width, color in zip(widths, ANCHOR_COLORS):
            draw.rectangle((cursor, y, cursor + width - 1, y + 4), fill=color)
            cursor += width
        self.assertTrue(discover_candidate_rois(image))

    def test_multiple_displaced_anchors_produce_multiple_rois(self):
        image = self._anchor_image(5, 101, 83, size=(1200, 800))
        draw = ImageDraw.Draw(image)
        for index, color in enumerate(ANCHOR_COLORS):
            draw.rectangle((801 + index * 10, 503, 810 + index * 10, 512), fill=color)
        rois = discover_candidate_rois(image)
        self.assertGreaterEqual(len(rois), 2)
        self.assertTrue(any(roi[0] < 150 for roi in rois))
        self.assertTrue(any(roi[0] > 700 for roi in rois))

    def test_failure_diagnostic_is_bounded_and_overwritten(self):
        image = Image.new("RGB", (320, 180), (20, 20, 20))
        with tempfile.TemporaryDirectory() as directory:
            paths = save_discovery_diagnostic(image, directory, 0)
            self.assertEqual(3, len(paths))
            self.assertTrue(all(path.exists() for path in paths))
            metadata = paths[2].read_text(encoding="utf-8")
            self.assertIn("screen=320x180", metadata)
            self.assertIn("candidate_count=0", metadata)

    def test_roi_coordinates_translate_to_absolute_screen_coordinates(self):
        local = Geometry(8.0, 16.0, 3.0, 3.25)
        self.assertEqual(
            Geometry(608.0, 316.0, 3.0, 3.25),
            offset_geometry(local, 600, 300),
        )
        self.assertEqual((607, 301, 643, 307), offset_box((7, 1, 43, 7), 600, 300))

    def test_candidate_discovery_does_not_replace_trusted_geometry(self):
        tracker = KT07GeometryTracker()
        trusted = Geometry(8.0, 16.0, 3.0, 3.0)
        tracker.geometry = trusted
        image = Image.new("RGB", (1000, 700), (20, 20, 20))
        discover_candidate_rois(image)
        self.assertEqual(trusted, tracker.geometry)

    def test_only_explicit_validated_relocation_replaces_geometry(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = Geometry(8.0, 16.0, 3.0, 3.0)
        moved = Geometry(608.0, 316.0, 3.25, 3.0)
        result = tracker.accept_validated_relocation("message", moved)
        self.assertEqual("relocated", result.state)
        self.assertEqual(moved, tracker.geometry)

    def test_invalid_candidate_cannot_replace_trusted_geometry(self):
        tracker = KT07GeometryTracker()
        trusted = Geometry(8.0, 16.0, 3.0, 3.0)
        tracker.geometry = trusted
        image = Image.new("RGB", (1000, 700), (20, 20, 20))
        anchor = (8.0, 4.0, 3.0, (7, 1, 43, 7))
        with patch("Bridge.kt07_relocation.decode_near_anchor", return_value=None):
            result = validate_candidate_rois(
                image, [(600, 300, 950, 650)], tracker, lambda _image: anchor
            )
        self.assertIsNone(result)
        self.assertEqual(trusted, tracker.geometry)

    def test_validated_candidate_replaces_with_absolute_geometry(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = Geometry(8.0, 16.0, 3.0, 3.0)
        image = Image.new("RGB", (1000, 700), (20, 20, 20))
        anchor = (8.0, 4.0, 3.0, (7, 1, 43, 7))
        local = Geometry(8.0, 16.0, 3.25, 3.0)
        with patch(
            "Bridge.kt07_relocation.decode_near_anchor",
            return_value=("moved", local),
        ):
            result, anchor_box, pitch = validate_candidate_rois(
                image, [(600, 300, 950, 650)], tracker, lambda _image: anchor
            )
        self.assertEqual(Geometry(608.0, 316.0, 3.25, 3.0), result.geometry)
        self.assertEqual(result.geometry, tracker.geometry)
        self.assertEqual((607, 301, 643, 307), anchor_box)
        self.assertEqual(3.0, pitch)

    def test_backoff_prevents_probe_on_each_idle_iteration(self):
        backoff = RelocationProbeBackoff(initial=5, maximum=20)
        backoff.reset(100)
        self.assertFalse(backoff.due(104.99))
        self.assertTrue(backoff.due(105))
        backoff.attempted(105, candidate_found=False)
        self.assertFalse(backoff.due(114.99))
        self.assertTrue(backoff.due(115))
        backoff.attempted(115, candidate_found=False)
        self.assertFalse(backoff.due(134.99))
        self.assertTrue(backoff.due(135))


if __name__ == "__main__":
    unittest.main()
