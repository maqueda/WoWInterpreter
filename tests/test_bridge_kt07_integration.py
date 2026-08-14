import ast
import unittest
from pathlib import Path


BRIDGE = (
    Path(__file__).resolve().parents[1]
    / "Bridge"
    / "bridge.py"
)


class BridgeKT07IntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(
            encoding="utf-8-sig"
        )
        cls.tree = ast.parse(cls.source)

        cls.worker = next(
            node
            for node in cls.tree.body
            if isinstance(
                node,
                (ast.FunctionDef, ast.AsyncFunctionDef),
            )
            and node.name == "worker"
        )

        cls.worker_source = ast.get_source_segment(
            cls.source,
            cls.worker,
        )

    def test_bridge_imports_geometry_tracker(self):
        imports = [
            node
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "Bridge.kt07_tracker"
        ]

        self.assertTrue(imports)

        imported_names = {
            alias.name
            for node in imports
            for alias in node.names
        }

        self.assertIn(
            "KT07GeometryTracker",
            imported_names,
        )

    def test_bridge_imports_adaptive_capture_box(self):
        imports = [
            node
            for node in self.tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "Bridge.kt07_decoder"
        ]

        imported_names = {
            alias.name
            for node in imports
            for alias in node.names
        }

        self.assertIn(
            "capture_box_for_geometry",
            imported_names,
        )

    def test_locked_capture_uses_adaptive_bbox(self):
        box_calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "capture_box_for_geometry"
        ]

        self.assertEqual(1, len(box_calls))

        box_call = box_calls[0]

        self.assertEqual(1, len(box_call.args))
        self.assertIsInstance(
            box_call.args[0],
            ast.Attribute,
        )
        self.assertIsInstance(
            box_call.args[0].value,
            ast.Name,
        )
        self.assertEqual(
            "tracker",
            box_call.args[0].value.id,
        )
        self.assertEqual(
            "geometry",
            box_call.args[0].attr,
        )

        grab_calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "grab"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ImageGrab"
        ]

        bbox_grabs = [
            call
            for call in grab_calls
            if any(
                keyword.arg == "bbox"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "locked_box"
                for keyword in call.keywords
            )
        ]

        self.assertEqual(1, len(bbox_grabs))

    def test_locked_path_no_longer_uses_capture_full_metric(self):
        self.assertNotIn(
            '"capture_full"',
            self.worker_source,
        )

        self.assertIn(
            '"capture_locked_roi"',
            self.worker_source,
        )

    def test_worker_constructs_geometry_tracker(self):
        calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "KT07GeometryTracker"
        ]

        self.assertEqual(1, len(calls))

    def test_worker_uses_tracker_decode(self):
        calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "decode"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tracker"
        ]

        self.assertGreaterEqual(len(calls), 2)

    def test_old_time_based_geometry_lock_is_removed(self):
        self.assertNotIn(
            "lock_deadline",
            self.worker_source,
        )

        self.assertNotIn(
            "locked_geo",
            self.worker_source,
        )

    def test_worker_does_not_call_legacy_kt07_payload(self):
        legacy_calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "kt07_payload"
        ]

        self.assertEqual([], legacy_calls)

    def test_anchor_result_is_not_assigned_as_geometry_lock(self):
        assignments = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Assign)
        ]

        forbidden_targets = {
            "locked_geo",
            "geometry",
        }

        for assignment in assignments:
            if not (
                isinstance(assignment.value, ast.Name)
                and assignment.value.id == "found"
            ):
                continue

            targets = {
                target.id
                for target in assignment.targets
                if isinstance(target, ast.Name)
            }

            self.assertTrue(
                targets.isdisjoint(forbidden_targets),
                "anchor result must never become "
                "validated geometry directly",
            )

    def test_capture_mode_depends_on_tracker_lock(self):
        attributes = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Attribute)
            and node.attr == "locked"
            and isinstance(node.value, ast.Name)
            and node.value.id == "tracker"
        ]

        # Geometry lock controls capture/calibration lifecycle only.
        # Polling cadence is deliberately controlled separately by
        # transport_active.
        self.assertGreaterEqual(len(attributes), 2)

    def test_validated_lock_states_are_handled(self):
        self.assertIn(
            '"calibrated"',
            self.worker_source,
        )

        self.assertIn(
            '"exhaustive-calibrated"',
            self.worker_source,
        )

        self.assertIn(
            '"local-recalibrated"',
            self.worker_source,
        )

        self.assertIn(
            '"unlocked"',
            self.worker_source,
        )


    def test_polling_speed_depends_on_transport_activity(self):
        self.assertIn(
            "if transport_active",
            self.worker_source,
        )

        self.assertNotIn(
            "KT07_ACTIVE_INTERVAL\n    if tracker.locked",
            self.worker_source,
        )

    def test_idle_tracker_state_stops_fast_polling(self):
        self.assertIn(
            'result.state=="idle"',
            self.worker_source,
        )

        idle_pos = self.worker_source.find(
            'result.state=="idle"'
        )

        self.assertNotEqual(-1, idle_pos)

        idle_block = self.worker_source[
            idle_pos:idle_pos + 120
        ]

        self.assertIn(
            "transport_active=False",
            idle_block,
        )

    def test_valid_frame_starts_fast_polling(self):
        fast_pos = self.worker_source.find(
            'result.state=="fast"'
        )

        self.assertNotEqual(-1, fast_pos)

        fast_block = self.worker_source[
            fast_pos:fast_pos + 120
        ]

        self.assertIn(
            "transport_active=True",
            fast_block,
        )

    def test_geometry_lock_remains_independent_from_polling_state(self):
        self.assertIn(
            "if tracker.locked:",
            self.worker_source,
        )

        self.assertIn(
            "if transport_active",
            self.worker_source,
        )


    def test_windowed_fallback_locator_exists(self):
        functions = {
            node.name
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
        }

        self.assertIn(
            "locate_kt07_anchor_anywhere",
            functions,
        )

    def test_normal_idle_path_keeps_tiny_roi(self):
        self.assertIn(
            "ImageGrab.grab(bbox=KT07_IDLE_ROI)",
            self.worker_source,
        )

        self.assertIn(
            "fast_locate_kt07_anchor(idle_im)",
            self.worker_source,
        )

    def test_windowed_fallback_is_bounded_by_miss_counter(self):
        self.assertIn(
            "generic_fallback_misses",
            self.worker_source,
        )

        self.assertIn(
            "KT07_GENERIC_FALLBACK_EVERY",
            self.worker_source,
        )

        comparisons = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Name)
            and node.left.id == "generic_fallback_misses"
        ]

        self.assertTrue(
            comparisons,
            "Windowed fallback must be gated by the miss counter",
        )

    def test_windowed_fallback_performs_occasional_full_capture(self):
        self.assertIn(
            '"capture_windowed_full"',
            self.worker_source,
        )

        calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "locate_kt07_anchor_anywhere"
        ]

        self.assertEqual(1, len(calls))

    def test_windowed_anchor_still_requires_tracker_validation(self):
        self.assertIn(
            "found=locate_kt07_anchor_anywhere(im)",
            self.worker_source,
        )

        # Discovery is only an anchor hint. The resulting box/pitch must
        # still flow through tracker.decode(), which performs complete
        # KT07 frame validation before geometry can become locked.
        self.assertIn(
            "anchor_box=box",
            self.worker_source,
        )

        self.assertIn(
            "anchor_pitch=cell",
            self.worker_source,
        )

        tracker_calls = [
            node
            for node in ast.walk(self.worker)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "decode"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "tracker"
        ]

        self.assertGreaterEqual(len(tracker_calls), 2)


if __name__ == "__main__":
    unittest.main()
