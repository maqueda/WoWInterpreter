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

        self.assertGreaterEqual(len(attributes), 3)

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


if __name__ == "__main__":
    unittest.main()
