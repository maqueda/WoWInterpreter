import unittest
from unittest.mock import patch
from PIL import Image

from Bridge.kt07_decoder import Geometry
from Bridge.kt07_tracker import KT07DuplicateSuppressor, KT07GeometryTracker


G1 = Geometry(7.0, 10.0, 3.0, 3.0)
G2 = Geometry(7.25, 10.0, 3.0, 3.0)


class KT07GeometryTrackerTests(unittest.TestCase):
    def test_consensus_selection_overrides_corrupt_first_candidate_and_emits_once(self):
        tracker = KT07GeometryTracker()
        gate = KT07DuplicateSuppressor()
        correct_geometry = Geometry(7.5, 16.75, 5.875, 5.75)
        diagnostic = {
            "ambiguous": False,
            "selected_text": "OUT\tYou\tTesting the first translation",
            "selected_geometry": correct_geometry,
            "unique_payload_count": 2,
        }
        with patch(
            "Bridge.kt07_tracker.decode_near_anchor",
            return_value=("OUT\tYou\tTUU\x14Ynf corrupt", G1),
        ), patch(
            "Bridge.kt07_tracker.audit_initial_candidate", return_value=diagnostic
        ):
            result = tracker.decode(
                Image.new("RGB", (200, 200)), (6, 1, 78, 13), 6.0
            )
        self.assertEqual("calibrated", result.state)
        self.assertEqual(correct_geometry, tracker.geometry)
        self.assertEqual(diagnostic["selected_text"], gate.observe(result.text, result.state, True))
        self.assertIsNone(gate.observe(result.text, "fast", True))
    def test_initial_lock_rejects_ambiguous_structurally_valid_payloads(self):
        tracker = KT07GeometryTracker()
        diagnostic = {
            "ambiguous": True,
            "candidates": [
                {"geometry": G1, "text": "wrong"},
                {"geometry": G2, "text": "arbitrary 二进制 UTF-8"},
            ],
        }
        with patch(
            "Bridge.kt07_tracker.decode_near_anchor", return_value=("wrong", G1)
        ), patch(
            "Bridge.kt07_tracker.audit_initial_candidate", return_value=diagnostic
        ):
            result = tracker.decode(
                Image.new("RGB", (100, 100)), (7, 1, 43, 7), 3.0
            )

        self.assertEqual("calibration-ambiguous", result.state)
        self.assertFalse(tracker.locked)
        self.assertIs(tracker.initial_calibration_diagnostic, diagnostic)

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

    def test_transient_signal_failure_does_not_drop_lock(self):
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
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
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

    def test_local_recalibration_requires_confirmation(self):
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
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(("moved", G2), 1),
        ) as calibrate:

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual(
            "local-candidate",
            result.state,
        )
        self.assertIsNone(result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)
        self.assertEqual(G2, tracker.candidate_geometry)
        self.assertEqual(1, tracker.candidate_hits)

        calibrate.assert_called_once()

    def test_repeated_screenshots_of_one_frame_do_not_replace_geometry(self):
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
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(("moved", G2), 1),
        ):
            first = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

            second = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("local-candidate", first.state)
        self.assertEqual("local-candidate", second.state)
        self.assertIsNone(second.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertEqual(G2, tracker.candidate_geometry)
        self.assertEqual(1, tracker.candidate_hits)

    def test_local_candidate_recalibrates_across_distinct_transport_frames(self):
        tracker = KT07GeometryTracker(local_after=2, unlock_after=5, exhaustive_after=9)
        tracker.geometry = G1
        tracker.failures = 1

        with patch("Bridge.kt07_tracker.decode_at", return_value=None), patch(
            "Bridge.kt07_tracker.has_signal_at",
            side_effect=[True, False] + [True] * 11,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate", return_value=(("moved", G2), 1)
        ):
            first = tracker.decode(object(), (7, 1, 43, 7), 3.0)
            idle = tracker.decode(object(), (7, 1, 43, 7), 3.0)
            settling = [
                tracker.decode(object(), (7, 1, 43, 7), 3.0)
                for _ in range(10)
            ]
            second = tracker.decode(object(), (7, 1, 43, 7), 3.0)

        self.assertEqual("local-candidate", first.state)
        self.assertEqual("idle", idle.state)
        self.assertEqual({"settling"}, {result.state for result in settling})
        self.assertEqual("local-recalibrated", second.state)
        self.assertEqual("moved", second.text)
        self.assertEqual(G2, tracker.geometry)

    def test_different_local_candidate_restarts_confirmation(self):
        tracker = KT07GeometryTracker(
            local_after=2,
            unlock_after=5,
            exhaustive_after=9,
        )

        g3 = Geometry(7.5, 10.0, 3.0, 3.0)

        tracker.geometry = G1
        tracker.failures = 1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            side_effect=[
                (("first", G2), 1),
                (("second", g3), 1),
            ],
        ):
            tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("local-candidate", result.state)
        self.assertEqual(G1, tracker.geometry)
        self.assertEqual(g3, tracker.candidate_geometry)
        self.assertEqual(1, tracker.candidate_hits)

    def test_fast_decode_clears_pending_candidate(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1
        tracker.candidate_geometry = G2
        tracker.candidate_hits = 1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value="stable",
        ):
            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("fast", result.state)
        self.assertEqual("stable", result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertIsNone(tracker.candidate_geometry)
        self.assertEqual(0, tracker.candidate_hits)

    def test_repeated_signal_failures_unlock_geometry(self):
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
            "Bridge.kt07_tracker.has_signal_at",
            return_value=True,
        ), patch(
            "Bridge.kt07_tracker.decode_local_candidate",
            return_value=(None, 625),
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

    def test_idle_frame_preserves_validated_geometry(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=False,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            result = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("idle", result.state)
        self.assertIsNone(result.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)
        self.assertEqual(0, tracker.failures)
        self.assertEqual(0, tracker.misses_since_lock)
        calibrate.assert_not_called()

    def test_one_hundred_idle_frames_keep_geometry_locked(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            return_value=None,
        ), patch(
            "Bridge.kt07_tracker.has_signal_at",
            return_value=False,
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            for _ in range(100):
                result = tracker.decode(
                    object(),
                    (7, 1, 43, 7),
                    3.0,
                )

        self.assertEqual("idle", result.state)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)
        self.assertEqual(0, tracker.failures)
        self.assertEqual(0, tracker.misses_since_lock)
        calibrate.assert_not_called()

    def test_payload_after_idle_uses_existing_geometry_immediately(self):
        tracker = KT07GeometryTracker()
        tracker.geometry = G1

        with patch(
            "Bridge.kt07_tracker.decode_at",
            side_effect=[None, None, "new message"],
        ) as fast, patch(
            "Bridge.kt07_tracker.has_signal_at",
            side_effect=[False, False],
        ), patch(
            "Bridge.kt07_tracker.decode_near_anchor",
        ) as calibrate:

            first = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )
            second = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )
            third = tracker.decode(
                object(),
                (7, 1, 43, 7),
                3.0,
            )

        self.assertEqual("idle", first.state)
        self.assertEqual("idle", second.state)
        self.assertEqual("fast", third.state)
        self.assertEqual("new message", third.text)
        self.assertEqual(G1, tracker.geometry)
        self.assertTrue(tracker.locked)

        self.assertEqual(3, fast.call_count)
        calibrate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
