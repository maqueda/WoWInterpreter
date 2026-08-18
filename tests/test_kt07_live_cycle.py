import time
import unittest
from unittest.mock import patch

from Bridge.kt07_decoder import Geometry
from Bridge.kt07_relocation import RelocationPendingState, validate_candidate_rois
from Bridge.kt07_tracker import KT07DuplicateSuppressor, KT07GeometryTracker


G1 = Geometry(7.0, 10.0, 3.0, 3.0)
G2 = Geometry(8.0, 11.0, 3.25, 3.0)

ANCHOR = (7, 1, 43, 7)
PITCH = 3.0
IMAGE = object()


class KT07LiveCycleTests(unittest.TestCase):

    def test_idle_visible_early_misses_recover_at_trusted_geometry(self):
        gate = KT07DuplicateSuppressor()
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch("Bridge.kt07_tracker.decode_at", return_value="payload A"):
            a = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("payload A", gate.observe(a.text, a.state, True))

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=False
        ):
            idle = tracker.decode(IMAGE, ANCHOR, PITCH)
        gate.observe(idle.text, idle.state, True)

        with patch("Bridge.kt07_tracker.decode_at", side_effect=[None, None, "payload B"]), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=True
        ), patch("Bridge.kt07_tracker.decode_local_candidate") as local:
            early_one = tracker.decode(IMAGE, ANCHOR, PITCH)
            early_two = tracker.decode(IMAGE, ANCHOR, PITCH)
            b = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual("settling", early_one.state)
        self.assertEqual("settling", early_two.state)
        self.assertEqual("fast", b.state)
        local.assert_not_called()
        self.assertEqual(G1, tracker.geometry)
        self.assertEqual("payload B", gate.observe(b.text, b.state, True))
        self.assertIsNone(gate.observe(b.text, b.state, True))

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=False
        ):
            idle = tracker.decode(IMAGE, ANCHOR, PITCH)
        gate.observe(idle.text, idle.state, True)
        with patch("Bridge.kt07_tracker.decode_at", return_value="payload C"):
            c = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("payload C", gate.observe(c.text, c.state, True))
        self.assertEqual(G1, tracker.geometry)

    def test_legacy_collision_then_transient_idle_recovers_payload_c(self):
        gate = KT07DuplicateSuppressor()
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch("Bridge.kt07_tracker.decode_at", return_value="payload A"):
            a = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("payload A", gate.observe(a.text, a.state, tracker.locked))

        with patch("Bridge.kt07_tracker.decode_at", return_value="corrupt$ B"):
            b = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("corrupt$ B", gate.observe(b.text, b.state, tracker.locked))

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=True
        ):
            transient = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("transient", transient.state)

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=False
        ):
            idle = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("idle", idle.state)
        self.assertIsNone(gate.observe(idle.text, idle.state, tracker.locked))

        with patch("Bridge.kt07_tracker.decode_at", return_value="payload C"):
            c = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("payload C", gate.observe(c.text, c.state, tracker.locked))
        self.assertEqual(G1, tracker.geometry)

    def test_stationary_fullscreen_startup_payload_idle_cycle(self):
        gate = KT07DuplicateSuppressor()
        tracker = KT07GeometryTracker()
        pending = RelocationPendingState()
        snapshot = object()
        pending.bind_snapshot(snapshot)

        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("one fullscreen payload", G1),
        ):
            locked = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual("calibrated", locked.state)
        self.assertEqual(
            "one fullscreen payload",
            gate.observe(locked.text, locked.state, tracker.locked),
        )
        self.assertIsNone(gate.observe(locked.text, "fast", tracker.locked))

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=False
        ):
            idle = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual("idle", idle.state)
        self.assertIsNone(gate.observe(idle.text, idle.state, tracker.locked))
        self.assertTrue(tracker.locked)
        self.assertEqual(G1, tracker.geometry)
        self.assertFalse(pending.pending)

    def test_stationary_geometry_survives_transient_and_speculative_candidate(self):
        gate = KT07DuplicateSuppressor()
        tracker = KT07GeometryTracker(local_after=2, unlock_after=5, exhaustive_after=9)
        tracker.geometry = G1
        pending = RelocationPendingState()
        pending.bind_snapshot(object())
        wrong = Geometry(6.75, 9.75, 3.25, 2.75)

        self.assertEqual("first", gate.observe("first", "fast", True))
        self.assertIsNone(gate.observe(None, "idle", True))

        with patch("Bridge.kt07_tracker.decode_at", side_effect=[None, None, None, "second translation after 30"]), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=True
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(("second trangm` dfe%slation after 30", wrong), 1),
        ):
            transient = tracker.decode(IMAGE, ANCHOR, PITCH)
            candidate = tracker.decode(IMAGE, ANCHOR, PITCH)
            repeated_capture = tracker.decode(IMAGE, ANCHOR, PITCH)
            recovered = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual("transient", transient.state)
        self.assertEqual("local-candidate", candidate.state)
        self.assertEqual("local-candidate", repeated_capture.state)
        self.assertEqual("fast", recovered.state)
        self.assertEqual(G1, tracker.geometry)
        self.assertEqual(
            "second translation after 30",
            gate.observe(recovered.text, recovered.state, tracker.locked),
        )
        self.assertFalse(pending.pending)

    def test_failed_relocation_probe_does_not_block_same_geometry_message(self):
        from PIL import Image

        gate = KT07DuplicateSuppressor()
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        self.assertEqual("same message", gate.observe("same message", "fast", True))
        self.assertIsNone(gate.observe(None, "idle", True))

        relocation = validate_candidate_rois(
            Image.new("RGB", (800, 600)),
            [],
            tracker,
            lambda _image: self.fail("no candidate ROI should be validated"),
        )
        self.assertIsNone(relocation)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)
        self.assertEqual("same message", gate.observe("same message", "fast", True))

    def test_message_idle_message_cycle_repeats_multiple_times(self):
        gate = KT07DuplicateSuppressor()
        emitted = []
        for message in ("one", "two", "three"):
            emitted.append(gate.observe(message, "fast", True))
            self.assertIsNone(gate.observe(message, "fast", True))
            self.assertIsNone(gate.observe(None, "idle", True))
        self.assertEqual(["one", "two", "three"], emitted)

    def test_complete_live_recovery_cycle(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=4,
            exhaustive_after=6,
        )

        # 1. No valid KT07 frame yet.
        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=None,
        ):
            result = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual(
            "calibration-miss",
            result.state,
        )
        self.assertFalse(tracker.locked)

        # 2. A complete validated frame appears.
        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("first", G1),
        ):
            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

        self.assertEqual("calibrated", result.state)
        self.assertEqual("first", result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)

        # 3. Normal traffic uses only fast path.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="second",
        ) as fast, patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:
            result = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual("fast", result.state)
        self.assertEqual("second", result.text)
        fast.assert_called_once()
        calibrate.assert_not_called()

        # 4. One bad capture must not destroy lock.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

        self.assertEqual("transient", result.state)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)
        calibrate.assert_not_called()

        # 5. Geometry actually moved. The first validated G2 frame becomes
        # only a candidate; the existing validated geometry remains locked.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(("moved", G2), 1),
        ) as calibrate:
            result = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual(
            "local-candidate",
            result.state,
        )
        self.assertIsNone(result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)

        calibrate.assert_called_once()

        # Repeated screenshots of the same displayed transport do not count
        # as independent confirmation. An idle boundary arms the candidate
        # for confirmation by a later transport frame.
        with patch(
            "Bridge.kt07_tracker.decode_at", return_value=None
        ), patch(
            "Bridge.kt07_tracker.has_signal_at", return_value=False
        ):
            idle = tracker.decode(IMAGE, ANCHOR, PITCH)
        self.assertEqual("idle", idle.state)

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(("moved", G2), 1),
        ) as calibrate:
            settling = [tracker.decode(IMAGE, ANCHOR, PITCH) for _ in range(10)]
            result = tracker.decode(IMAGE, ANCHOR, PITCH)

        self.assertEqual(
            "local-recalibrated",
            result.state,
        )
        self.assertEqual({"settling"}, {item.state for item in settling})
        self.assertEqual("moved", result.text)
        self.assertEqual(G2, tracker.geometry)
        self.assertTrue(tracker.locked)

        calibrate.assert_called_once()

        # 6. New geometry immediately returns to fast path.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="third",
        ):
            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

        self.assertEqual("fast", result.state)
        self.assertEqual(G2, tracker.geometry)

        # 7. KT07 genuinely disappears. Repeated failures
        # eventually invalidate the geometry.
        for expected_state in (
            "transient",
            "local-miss",
            "local-miss",
            "unlocked",
        ):
            with patch(
                "Bridge.kt07_tracker.decode_at",
                return_value=None,
            ), patch(
                "Bridge.kt07_tracker.has_signal_at",
                return_value=True,
            ), patch(
                "Bridge.kt07_tracker.decode_local_candidate",
                return_value=(None, 625),
            ):
                result = tracker.decode(
                    IMAGE,
                    ANCHOR,
                    PITCH,
                )

            self.assertEqual(
                expected_state,
                result.state,
            )

        self.assertFalse(tracker.locked)
        self.assertIsNone(tracker.geometry)

    def test_locked_tracker_dispatch_overhead_is_small(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        iterations = 10000

        # Measure tracker/state-machine overhead independently
        # from image sampling. decode_at itself already has its
        # own performance regression test.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="message",
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            start = time.perf_counter()

            for _ in range(iterations):
                result = tracker.decode(
                    IMAGE,
                    ANCHOR,
                    PITCH,
                )

            elapsed = time.perf_counter() - start

        self.assertEqual("fast", result.state)
        calibrate.assert_not_called()

        # 10k state-machine iterations should remain comfortably
        # below one second on GitHub's Windows runner. This is
        # deliberately generous to avoid flaky CI while still
        # catching accidental expensive work in the live path.
        self.assertLess(
            elapsed,
            1.0,
            f"locked tracker dispatch took "
            f"{elapsed:.3f}s for {iterations} iterations",
        )

    def test_fast_path_never_enters_calibration_when_valid(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="stable",
        ) as fast, patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            for _ in range(100):
                result = tracker.decode(
                    IMAGE,
                    ANCHOR,
                    PITCH,
                )

        self.assertEqual("fast", result.state)
        self.assertEqual(100, fast.call_count)
        calibrate.assert_not_called()


    def test_real_frame_idle_frame_then_new_frame_keeps_lock(self):
        from PIL import Image

        from tests.test_kt07_decoder import render

        geometry = Geometry(
            7.5,
            16.5,
            5.875,
            5.75,
        )

        tracker = KT07GeometryTracker()
        tracker.geometry = geometry

        first_image = render(
            "first message",
            geometry,
            size=(360, 260),
        )

        first = tracker.decode(
            first_image,
            ANCHOR,
            PITCH,
        )

        self.assertEqual("fast", first.state)
        self.assertEqual("first message", first.text)
        self.assertEqual(geometry, tracker.geometry)

        # Realistic idle background: numerically very close to IDEAL[0].
        # This used to produce a false transport-positive and eventually
        # destroy a perfectly valid geometry lock.
        idle_image = Image.new(
            "RGB",
            (360, 260),
            (32, 32, 32),
        )

        for _ in range(100):
            idle = tracker.decode(
                idle_image,
                ANCHOR,
                PITCH,
            )

            self.assertEqual("idle", idle.state)
            self.assertTrue(tracker.locked)
            self.assertEqual(
                geometry,
                tracker.geometry,
            )

        self.assertEqual(0, tracker.failures)
        self.assertEqual(
            0,
            tracker.misses_since_lock,
        )

        second_image = render(
            "second message",
            geometry,
            size=(360, 260),
        )

        second = tracker.decode(
            second_image,
            ANCHOR,
            PITCH,
        )

        self.assertEqual("fast", second.state)
        self.assertEqual(
            "second message",
            second.text,
        )
        self.assertEqual(
            geometry,
            tracker.geometry,
        )


if __name__ == "__main__":
    unittest.main()
