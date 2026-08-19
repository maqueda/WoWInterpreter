import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw

from Bridge.kt07_decoder import Geometry, decode_at, relocation_candidate_pitches
from Bridge.kt07_relocation import (
    ANCHOR_COLORS,
    OverlayRelocationSuppression,
    RelocationProbeBackoff,
    RelocationPendingState,
    WoWWindowChangeMonitor,
    WoWWindowSnapshot,
    analyze_discovery_failure,
    client_anchor_presence_box,
    client_anchor_probe_box,
    discover_candidate_rois,
    inspect_client_anchor_probe,
    locate_client_anchor,
    offset_box,
    offset_geometry,
    preserve_validation_failure,
    save_discovery_diagnostic,
    validate_client_anchor_probe,
    validate_candidate_rois,
)
from Bridge.kt07_tracker import KT07GeometryTracker


class KT07RelocationTests(unittest.TestCase):

    def test_real_generation_6_fixture_uses_fractional_data_pitch(self):
        fixture = Path(__file__).parent / "fixtures" / "kt07_relocation_failure_6_validation.png"
        image = Image.open(fixture).convert("RGB")
        found = locate_client_anchor(image)
        self.assertEqual((5.25, 9.25, 3.5, (4, 0, 46, 8)), found)
        self.assertNotIn(3.875, tuple(x / 4 for x in range(11, 18)))
        self.assertIn(3.875, relocation_candidate_pitches(found[2]))
        self.assertIsNone(decode_at(image, Geometry(3.75, 12.0, 4.5, 4.5)))
        self.assertEqual(
            "OUT\tYou\tI have one sister",
            decode_at(image, Geometry(3.75, 12.0, 3.875, 3.875)),
        )

        started = time.perf_counter()
        decoded, diagnostic = inspect_client_anchor_probe(
            image, (90, 437), locate_client_anchor
        )
        elapsed = time.perf_counter() - started

        self.assertIsNotNone(decoded)
        self.assertEqual("OUT\tYou\tI have one sister", decoded[0])
        self.assertEqual(Geometry(92.75, 447.5, 3.875, 3.875), decoded[1])
        self.assertEqual(3.875, decoded[1].pitch_x)
        self.assertEqual(3.875, decoded[1].pitch_y)
        self.assertEqual("validated", diagnostic["stage"])
        self.assertEqual(24_375, diagnostic["geometry_candidates"])
        self.assertLess(diagnostic["decode_attempts"], 24_375)
        self.assertLess(elapsed, 0.5)

    def test_overlay_suppression_requires_matching_ui_ack_before_capture(self):
        suppression = OverlayRelocationSuppression()
        self.assertTrue(suppression.request_suppression(1))
        self.assertFalse(suppression.capture_allowed(1))
        self.assertFalse(suppression.acknowledge_suppressed(0))
        self.assertTrue(suppression.acknowledge_suppressed(1))
        self.assertTrue(suppression.capture_allowed(1))

    def test_new_native_generation_invalidates_old_ack_and_restore(self):
        suppression = OverlayRelocationSuppression()
        suppression.request_suppression(1)
        suppression.acknowledge_suppressed(1)
        self.assertTrue(suppression.request_suppression(2))
        self.assertFalse(suppression.capture_allowed(1))
        self.assertFalse(suppression.capture_allowed(2))
        self.assertFalse(suppression.request_restore(1))
        self.assertFalse(suppression.acknowledge_suppressed(1))
        self.assertTrue(suppression.acknowledge_suppressed(2))
        self.assertTrue(suppression.capture_allowed(2))

    def test_failed_and_idle_relocation_remain_suppressed(self):
        suppression = OverlayRelocationSuppression()
        suppression.request_suppression(4)
        suppression.acknowledge_suppressed(4)
        for _observer_cycle in range(100):
            self.assertTrue(suppression.capture_allowed(4))
            self.assertEqual(("suppressed", 4), suppression.snapshot())

    def test_strict_validation_failure_does_not_restore_overlay(self):
        suppression = OverlayRelocationSuppression()
        suppression.request_suppression(5)
        suppression.acknowledge_suppressed(5)
        # A failed decoder produces no state transition.
        self.assertEqual(("suppressed", 5), suppression.snapshot())
        self.assertTrue(suppression.capture_allowed(5))

    def test_stationary_fullscreen_never_requests_suppression(self):
        snapshot = self._snapshot((0, 0, 2560, 1440), style=1)
        monitor = WoWWindowChangeMonitor(lambda: snapshot, interval=0)
        suppression = OverlayRelocationSuppression()
        self.assertFalse(monitor.poll(0))
        self.assertFalse(monitor.poll(1))
        self.assertEqual(("visible", None), suppression.snapshot())

    def test_stationary_windowed_never_requests_suppression(self):
        snapshot = self._snapshot((320, 167, 2240, 1247), style=2)
        monitor = WoWWindowChangeMonitor(lambda: snapshot, interval=0)
        suppression = OverlayRelocationSuppression()
        self.assertFalse(monitor.poll(0))
        self.assertFalse(monitor.poll(1))
        self.assertEqual(("visible", None), suppression.snapshot())

    def test_normal_presence_observation_does_not_suppress_overlay(self):
        pending = RelocationPendingState(interval=0.5)
        pending.bind_snapshot(self._snapshot())
        suppression = OverlayRelocationSuppression()
        self.assertTrue(pending.observation_due(0, True))
        self.assertFalse(pending.pending)
        self.assertEqual(("visible", None), suppression.snapshot())

    def test_success_restores_only_current_generation(self):
        suppression = OverlayRelocationSuppression()
        suppression.request_suppression(7)
        suppression.acknowledge_suppressed(7)
        self.assertTrue(suppression.request_restore(7))
        self.assertFalse(suppression.capture_allowed(7))
        self.assertFalse(suppression.acknowledge_restored(6))
        self.assertEqual(("restore_requested", 7), suppression.snapshot())
        self.assertTrue(suppression.acknowledge_restored(7))
        self.assertEqual(("visible", None), suppression.snapshot())

    def test_repeated_suppression_request_is_idempotent(self):
        suppression = OverlayRelocationSuppression()
        self.assertTrue(suppression.request_suppression(3))
        self.assertFalse(suppression.request_suppression(3))
        suppression.acknowledge_suppressed(3)
        self.assertFalse(suppression.request_suppression(3))

    def test_cleanup_returns_state_to_visible(self):
        suppression = OverlayRelocationSuppression()
        suppression.request_suppression(9)
        suppression.acknowledge_suppressed(9)
        self.assertTrue(suppression.cleanup())
        self.assertEqual(("visible", None), suppression.snapshot())

    @staticmethod
    def _snapshot(rect=(0, 0, 1920, 1080), style=1, dpi=96):
        return WoWWindowSnapshot(rect, (0, 0, 2560, 1440), style, 0, dpi)

    def test_unchanged_window_does_not_enter_relocation(self):
        snapshot = self._snapshot()
        monitor = WoWWindowChangeMonitor(lambda: snapshot, interval=1)
        pending = RelocationPendingState()
        self.assertFalse(monitor.poll(0))
        self.assertFalse(monitor.poll(1))
        self.assertFalse(pending.pending)

    def test_startup_snapshot_binding_does_not_enter_relocation(self):
        snapshot = self._snapshot()
        monitor = WoWWindowChangeMonitor(lambda: snapshot, interval=0)
        pending = RelocationPendingState()

        self.assertFalse(monitor.poll(0))
        pending.bind_snapshot(monitor.snapshot)

        self.assertEqual(snapshot, pending.snapshot)
        self.assertFalse(pending.pending)
        self.assertFalse(monitor.poll(1))
        pending.bind_snapshot(monitor.snapshot)
        self.assertFalse(pending.pending)

    def test_move_resize_mode_dpi_and_display_changes_are_detected(self):
        changes = (
            self._snapshot((300, 170, 1300, 870)),
            self._snapshot((300, 170, 1500, 970)),
            self._snapshot((300, 170, 1500, 970), style=2),
            self._snapshot((300, 170, 1500, 970), style=2, dpi=120),
            WoWWindowSnapshot((300, 170, 1500, 970), (-1920, 0, 2560, 1440), 2, 0, 120),
        )
        values = iter((self._snapshot(),) + changes)
        monitor = WoWWindowChangeMonitor(lambda: next(values), interval=0)
        self.assertFalse(monitor.poll(0))
        self.assertTrue(all(monitor.poll(index) for index in range(1, 6)))

    def test_pending_state_is_bounded_and_independent_of_idle_duration(self):
        pending = RelocationPendingState(interval=0.5)
        pending.enter(100)
        self.assertTrue(pending.due(100))
        pending.attempted(100)
        self.assertFalse(pending.due(100.49))
        self.assertTrue(pending.due(100.5))
        pending.attempted(1_000_000)
        self.assertFalse(pending.due(1_000_000.49))
        self.assertTrue(pending.due(1_000_000.5))

    def test_client_probe_is_bounded_to_wow_top_left(self):
        snapshot = self._snapshot((300, 170, 1600, 1000))
        self.assertEqual((300, 170, 720, 520), client_anchor_probe_box(snapshot))
        self.assertEqual((300, 170, 420, 215), client_anchor_presence_box(snapshot))

    def test_tiny_observer_remains_due_after_hours_without_pending_change(self):
        observer = RelocationPendingState(interval=0.5)
        self.assertTrue(observer.observation_due(1_000_000, window_available=True))
        observer.attempted(1_000_000)
        self.assertFalse(observer.observation_due(1_000_000.49, True))
        self.assertTrue(observer.observation_due(1_000_000.5, True))
        self.assertFalse(observer.observation_due(2_000_000, False))

    def test_pending_state_keeps_latest_window_geometry(self):
        pending = RelocationPendingState(interval=0.5)
        geometry_a = self._snapshot((300, 170, 1600, 1000))
        intermediate = self._snapshot((420, 240, 1500, 900))
        geometry_b = self._snapshot((640, 360, 1840, 1060))

        pending.enter(1.0, geometry_a)
        stale_a = pending.attempt()
        pending.enter(1.1, intermediate)
        stale_intermediate = pending.attempt()
        pending.enter(1.2, geometry_b)

        self.assertFalse(pending.is_current(stale_a))
        self.assertFalse(pending.is_current(stale_intermediate))
        self.assertEqual(geometry_b, pending.attempt()[1])
        self.assertEqual((640, 360, 1060, 710), client_anchor_probe_box(pending.snapshot))

    def test_forced_monitor_refresh_detects_change_during_validation(self):
        geometry_a = self._snapshot((300, 170, 1600, 1000))
        geometry_b = self._snapshot((640, 360, 1840, 1060))
        values = iter((geometry_a, geometry_b))
        monitor = WoWWindowChangeMonitor(lambda: next(values), interval=60)
        self.assertFalse(monitor.poll(0))
        self.assertTrue(monitor.poll(0.1, force=True))
        self.assertEqual(geometry_b, monitor.snapshot)

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

    def test_client_anchor_locator_accepts_every_raster_phase_after_move(self):
        for x in range(3, 7):
            for y in range(3, 7):
                with self.subTest(x=x, y=y):
                    image = self._anchor_image(9, x, y, size=(120, 45))
                    self.assertIsNotNone(locate_client_anchor(image))

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

    def test_real_windowed_geometry_anchor_at_pitch_4_5(self):
        scale = 4
        for x_phase in (0.0, 0.25, 0.5, 0.75):
            for y_phase in (0.0, 0.25, 0.5, 0.75):
                with self.subTest(x_phase=x_phase, y_phase=y_phase):
                    large = Image.new("RGB", (1000 * scale, 700 * scale), (20, 20, 20))
                    draw = ImageDraw.Draw(large)
                    anchor_x = 323.75 + x_phase
                    anchor_y = 179.0 - 2 * 4.5 + y_phase
                    block = 2 * 4.5
                    perturbed = (
                        (220, 20, 25), (25, 225, 20), (20, 25, 220),
                        (225, 220, 20), (20, 220, 225), (220, 20, 225),
                    )
                    for index, color in enumerate(perturbed):
                        left = round((anchor_x + index * block) * scale)
                        top = round(anchor_y * scale)
                        right = round((anchor_x + (index + 1) * block) * scale) - 1
                        bottom = round((anchor_y + block) * scale) - 1
                        draw.rectangle((left, top, right, bottom), fill=color)
                    image = large.resize((1000, 700), Image.Resampling.LANCZOS)
                    rois = discover_candidate_rois(image)
                    self.assertTrue(rois)
                    self.assertTrue(any(
                        roi[0] <= 323.75 < roi[2]
                        and roi[1] <= 170.0 < roi[3]
                        for roi in rois
                    ))

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
            self.assertEqual(4, len(paths))
            self.assertTrue(all(path.exists() for path in paths))
            metadata = paths[3].read_text(encoding="utf-8")
            self.assertIn("screen=320x180", metadata)
            self.assertIn("candidate_count=0", metadata)
            self.assertIn("closest_match_count=", metadata)
            self.assertIn("closest_sample_rgb=", metadata)

    def test_first_strict_failure_per_generation_is_preserved_raw(self):
        first = Image.new("RGB", (420, 350), (11, 22, 33))
        later = Image.new("RGB", (420, 350), (200, 100, 50))
        with tempfile.TemporaryDirectory() as directory:
            saved = preserve_validation_failure(
                first, directory, 7, {"failure_stage": "strict_frame_validation_failed"}
            )
            self.assertIsNotNone(saved)
            self.assertIsNone(preserve_validation_failure(
                later, directory, 7, {"failure_stage": "presence_prefilter_failed"}
            ))
            preserved = Image.open(saved[0])
            self.assertEqual((420, 350), preserved.size)
            self.assertEqual((11, 22, 33), preserved.getpixel((200, 200)))

    def test_validation_failure_retention_is_centralized_by_runtime_directory(self):
        image = Image.new("RGB", (20, 20), (1, 2, 3))
        with tempfile.TemporaryDirectory() as directory:
            for generation in range(1, 6):
                preserve_validation_failure(image, directory, generation, {})
            names = {path.name for path in Path(directory).iterdir()}
            self.assertTrue(any("_1" in name and "validation" in name for name in names))
            for generation in (3, 4, 5):
                self.assertIn(
                    f"kt07_relocation_failure_{generation}_validation.png", names
                )
                self.assertIn(f"kt07_relocation_failure_{generation}.txt", names)

    def test_diagnostic_reports_closest_layout_and_color_results(self):
        image = self._anchor_image(9, 323, 170).resize((225, 150))
        evidence = analyze_discovery_failure(image)
        self.assertEqual(6, evidence["closest_match_count"])
        self.assertEqual(6, len(evidence["closest_sample_rgb"]))
        self.assertEqual((True,) * 6, evidence["closest_color_passes"])
        self.assertTrue(evidence["sequence_present_in_reduced"])

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

    def test_first_pending_frame_validates_relocates_and_returns_same_payload(self):
        tracker = KT07GeometryTracker()
        trusted = Geometry(8.0, 16.0, 3.0, 3.0)
        tracker.geometry = trusted
        image = Image.new("RGB", (420, 350), (20, 20, 20))
        anchor = (8.0, 4.0, 4.5, (7, 1, 61, 10))
        local = Geometry(23.75, 9.0, 4.5, 4.5)
        with patch(
            "Bridge.kt07_relocation.decode_relocation_candidate",
            return_value=(("first relocated payload", local), {}),
        ):
            result, anchor_box, pitch = validate_client_anchor_probe(
                image, (300, 170), tracker, lambda _image: anchor
            )
        self.assertEqual("first relocated payload", result.text)
        self.assertEqual(Geometry(323.75, 179.0, 4.5, 4.5), result.geometry)
        self.assertEqual(result.geometry, tracker.geometry)
        self.assertEqual((307, 171, 361, 180), anchor_box)
        self.assertEqual(4.5, pitch)

    def test_probe_can_decode_without_committing_stale_geometry(self):
        tracker = KT07GeometryTracker()
        trusted = Geometry(323.75, 179.0, 4.5, 4.5)
        tracker.geometry = trusted
        anchor = (8.0, 4.0, 4.5, (7, 1, 61, 10))
        local = Geometry(23.75, 9.0, 4.5, 4.25)
        with patch(
            "Bridge.kt07_relocation.decode_relocation_candidate",
            return_value=(("first payload at B", local), {}),
        ):
            decoded, diagnostic = inspect_client_anchor_probe(
                Image.new("RGB", (420, 350)),
                (640, 360),
                lambda _image: anchor,
            )
        self.assertEqual(trusted, tracker.geometry)
        self.assertEqual("validated", diagnostic["stage"])
        self.assertEqual(Geometry(663.75, 369.0, 4.5, 4.25), decoded[1])
        result = tracker.accept_validated_relocation(decoded[0], decoded[1])
        self.assertEqual("first payload at B", result.text)
        self.assertEqual(decoded[1], tracker.geometry)

    def test_invalid_pending_candidate_preserves_trusted_geometry(self):
        tracker = KT07GeometryTracker()
        trusted = Geometry(8.0, 16.0, 3.0, 3.0)
        tracker.geometry = trusted
        anchor = (8.0, 4.0, 4.5, (7, 1, 61, 10))
        with patch(
            "Bridge.kt07_relocation.decode_relocation_candidate",
            return_value=(None, {}),
        ):
            result = validate_client_anchor_probe(
                Image.new("RGB", (420, 350)),
                (300, 170),
                tracker,
                lambda _image: anchor,
            )
        self.assertIsNone(result)
        self.assertEqual(trusted, tracker.geometry)

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

    def test_global_fallback_remains_rare_outside_pending_mode(self):
        backoff = RelocationProbeBackoff()
        backoff.reset(0)
        backoff.attempted(5, candidate_found=False)
        self.assertEqual(10.0, backoff.interval)
        backoff.attempted(15, candidate_found=False)
        self.assertEqual(20.0, backoff.interval)


if __name__ == "__main__":
    unittest.main()
