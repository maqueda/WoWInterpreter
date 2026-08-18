import unittest
from pathlib import Path
from PIL import Image

from Bridge.kt07_tracker import KT07DuplicateSuppressor
from Bridge.kt08_tracker import KT08GeometryTracker
from tests.kt08_helpers import render_kt08


class KT08TrackerTests(unittest.TestCase):
    def test_real_initial_fixtures_lock_and_emit_each_sequence_once(self):
        fixtures = Path(__file__).parent / "fixtures"
        first_image = Image.open(fixtures / "kt08_initial_failure_1.png").convert("RGB")
        second_image = Image.open(fixtures / "kt08_initial_failure_2.png").convert("RGB")
        tracker = KT08GeometryTracker()
        duplicates = KT07DuplicateSuppressor()

        first = tracker.acquire(first_image)
        self.assertEqual("calibrated", first.state)
        self.assertIsNotNone(duplicates.observe(
            first.text, first.state, True, (first.sequence, first.text)
        ))
        repeated = tracker.decode(first_image)
        self.assertIsNone(duplicates.observe(
            repeated.text, repeated.state, True, (repeated.sequence, repeated.text)
        ))
        second = tracker.decode(second_image)
        self.assertEqual("OUT\tYou\tThis is the first translation", second.text)
        self.assertIsNotNone(duplicates.observe(
            second.text, second.state, True, (second.sequence, second.text)
        ))
        self.assertEqual((18.0, 36.0, 6.0, 6.0), (
            tracker.geometry.x, tracker.geometry.y,
            tracker.geometry.pitch_x, tracker.geometry.pitch_y,
        ))

    def test_first_payload_idle_next_payload_and_changed_sequence(self):
        tracker = KT08GeometryTracker()
        duplicates = KT07DuplicateSuppressor()
        first = tracker.acquire(render_kt08("same", 1))
        self.assertEqual("calibrated", first.state)
        self.assertEqual("same", duplicates.observe(first.text, first.state, True, (first.sequence, first.text)))
        repeated = tracker.decode(render_kt08("same", 1))
        self.assertIsNone(duplicates.observe(repeated.text, repeated.state, True, (repeated.sequence, repeated.text)))

        idle = tracker.decode(Image.new("RGB", (420, 350), (10, 12, 14)))
        self.assertEqual("idle", idle.state)
        duplicates.observe(None, idle.state, True)

        second = tracker.decode(render_kt08("same", 2))
        self.assertEqual("same", duplicates.observe(second.text, second.state, True, (second.sequence, second.text)))
        third = tracker.decode(render_kt08("changed", 3))
        self.assertEqual("changed", third.text)

    def test_invalid_visible_frame_never_emits(self):
        tracker = KT08GeometryTracker()
        tracker.acquire(render_kt08("good", 1))
        damaged = render_kt08("bad", 2, mutate=lambda raw: raw.__setitem__(10, raw[10] ^ 1))
        result = tracker.decode(damaged)
        self.assertEqual("settling", result.state)
        self.assertIsNone(result.text)

    def test_relocation_offsets_geometry_once(self):
        tracker = KT08GeometryTracker()
        local = __import__("Bridge.kt08_decoder", fromlist=["locate_and_decode"]).locate_and_decode(
            render_kt08("moved", 4, 10, 18, 4, 4)
        )
        result = tracker.accept_validated_relocation(local, (320, 167))
        self.assertAlmostEqual(330, result.geometry.x)
        self.assertAlmostEqual(185, result.geometry.y)
        self.assertEqual("moved", result.text)


if __name__ == "__main__":
    unittest.main()
