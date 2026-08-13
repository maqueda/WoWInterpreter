import time
import unittest
from unittest.mock import patch

from Bridge.kt07_decoder import Geometry
from Bridge.kt07_tracker import KT07GeometryTracker


G1 = Geometry(7.0, 10.0, 3.0, 3.0)
G2 = Geometry(8.0, 11.0, 3.25, 3.0)

ANCHOR = (7, 1, 43, 7)
PITCH = 3.0
IMAGE = object()


class KT07LiveCycleTests(unittest.TestCase):

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
            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

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

            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

        self.assertEqual("fast", result.state)
        self.assertEqual("second", result.text)
        fast.assert_called_once()
        calibrate.assert_not_called()

        # 4. One bad capture must not destroy lock.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
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

        # 5. Geometry actually moved. Second failure triggers
        # bounded local recovery and obtains G2.
        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("moved", G2),
        ) as calibrate:

            result = tracker.decode(
                IMAGE,
                ANCHOR,
                PITCH,
            )

        self.assertEqual(
            "local-recalibrated",
            result.state,
        )
        self.assertEqual("moved", result.text)
        self.assertEqual(G2, tracker.geometry)
        self.assertTrue(tracker.locked)

        self.assertFalse(
            calibrate.call_args.kwargs["exhaustive"]
        )

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
                "Bridge.kt07_tracker.decode_near_anchor",
                return_value=None,
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


if __name__ == "__main__":
    unittest.main()
