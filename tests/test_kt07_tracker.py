import unittest
from unittest.mock import patch

from Bridge.kt07_decoder import Geometry
from Bridge.kt07_tracker import KT07GeometryTracker


G1 = Geometry(7.0, 10.0, 3.0, 3.0)
G2 = Geometry(7.25, 10.0, 3.0, 3.0)


class KT07GeometryTrackerTests(unittest.TestCase):

    def test_initial_lock_requires_validated_calibration(self):
        tracker = KT07GeometryTracker()

        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("hello", G1),
        ):
            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("calibrated", result.state)
        self.assertEqual("hello", result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)

    def test_locked_geometry_uses_fast_path(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="hello",
        ) as fast, patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("fast", result.state)
        self.assertEqual("hello", result.text)

        fast.assert_called_once()
        calibrate.assert_not_called()

    def test_transient_failure_does_not_drop_lock(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=5,
            exhaustive_after=9,
        )
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("transient", result.state)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)

        calibrate.assert_not_called()

    def test_local_recalibration_replaces_geometry(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=5,
            exhaustive_after=9,
        )

        tracker.geometry = G1
        tracker.failures = 1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("moved", G2),
        ) as calibrate:

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual(
            "local-recalibrated",
            result.state,
        )
        self.assertEqual("moved", result.text)
        self.assertEqual(G2, tracker.geometry)
        self.assertEqual(0, tracker.failures)

        self.assertFalse(
            calibrate.call_args.kwargs["exhaustive"]
        )

    def test_repeated_failures_unlock_geometry(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=3,
            exhaustive_after=5,
        )

        tracker.geometry = G1
        tracker.failures = 2

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=None,
        ):

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("unlocked", result.state)
        self.assertIsNone(tracker.geometry)
        self.assertFalse(tracker.locked)

    def test_exhaustive_search_is_rare_and_explicit(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=3,
            exhaustive_after=4,
        )

        tracker.misses_since_lock = 3
        calls = []

        def fake_search(
            image,
            anchor_box,
            anchor_pitch,
            exhaustive=False,
        ):
            calls.append(exhaustive)

            if exhaustive:
                return ("recovered", G2)

            return None

        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            side_effect=fake_search,
        ):
            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual([False, True], calls)

        self.assertEqual(
            "exhaustive-calibrated",
            result.state,
        )
        self.assertEqual("recovered", result.text)
        self.assertEqual(G2, tracker.geometry)

    def test_failed_exhaustive_search_resets_counter(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=3,
            exhaustive_after=4,
        )

        tracker.misses_since_lock = 3

        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=None,
        ):
            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual(
            "exhaustive-miss",
            result.state,
        )
        self.assertEqual(
            0,
            tracker.misses_since_lock,
        )
        self.assertIsNone(tracker.geometry)

    def test_reset_clears_all_tracking_state(self):
        tracker = KT07GeometryTracker()

        tracker.geometry = G1
        tracker.failures = 4
        tracker.misses_since_lock = 8

        tracker.reset()

        self.assertIsNone(tracker.geometry)
        self.assertEqual(0, tracker.failures)
        self.assertEqual(
            0,
            tracker.misses_since_lock,
        )
        self.assertFalse(tracker.locked)


if __name__ == "__main__":
    unittest.main()
