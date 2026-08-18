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

    def test_user_visible_strings_are_real_unicode_not_mojibake(self):
        for corrupt in ("Ã¢", "Ã£", "Ã¨", "Ã¦", "Ã‚", "â†", "ã€", "ï¼"):
            self.assertNotIn(corrupt, self.source)
        for expected in ("英文 → 中文", "EN→ZH", "ZH→EN", "。"):
            self.assertIn(expected, self.source)

    def test_worker_ends_duplicate_suppression_on_idle(self):
        self.assertIn("KT07DuplicateSuppressor", self.source)
        self.assertIn("duplicates.observe", self.worker_source)

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

        # There are two legitimate global relocation paths:
        # 1. the bounded periodic Windowed-mode fallback;
        # 2. immediate relocation after a previously validated lock is lost.
        #
        # Both only discover an anchor. Neither path may establish geometry
        # without complete tracker validation.
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

        # There are two legitimate global relocation paths:
        # 1. the bounded periodic Windowed-mode fallback;
        # 2. immediate relocation after a previously validated lock is lost.
        #
        # Both only discover an anchor. Neither path may establish geometry
        # without complete tracker validation.
        self.assertEqual(2, len(calls))

    def test_windowed_anchor_still_requires_tracker_validation(self):
        self.assertIn("candidate_rois=locate_kt07_anchor_anywhere(im)", self.worker_source)

        # Discovery is only an anchor hint. The resulting box/pitch must
        # still flow through tracker.decode(), which performs complete
        # KT07 frame validation before geometry can become locked.
        self.assertIn("relocated=_validate_relocation", self.worker_source)

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


    def test_dynamic_kt07_protection_is_derived_from_validated_geometry(self):
        self.assertIn(
            "def _protected_rect_for_geometry",
            self.source,
        )

        helper = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_protected_rect_for_geometry"
        )

        calls = [
            node
            for node in ast.walk(helper)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "capture_box_for_geometry"
        ]

        # There are two legitimate global relocation paths:
        # 1. the bounded periodic Windowed-mode fallback;
        # 2. immediate relocation after a previously validated lock is lost.
        #
        # Both only discover an anchor. Neither path may establish geometry
        # without complete tracker validation.
        self.assertEqual(1, len(calls))

        call = calls[0]

        self.assertTrue(
            any(
                keyword.arg == "margin"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "KT07_PROTECTED_PADDING"
                for keyword in call.keywords
            )
        )

    def test_ui_handles_dynamic_kt07_geometry_event(self):
        poll_ui = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "poll_ui"
        )

        poll_source = ast.get_source_segment(
            self.source,
            poll_ui,
        )

        self.assertIn(
            'kind=="kt07_geometry"',
            poll_source,
        )

        self.assertIn(
            "_apply_kt07_protected_rect(data)",
            poll_source,
        )

    def test_worker_publishes_validated_geometry_to_overlay(self):
        self.assertIn(
            "def _publish_validated_geometry",
            self.worker_source,
        )
        self.assertGreaterEqual(
            self.worker_source.count("_publish_validated_geometry("),
            5,
        )

    def test_local_recalibration_updates_overlay_protection(self):
        state_pos = self.worker_source.find(
            'result.state=="local-recalibrated"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 500
        ]

        self.assertIn(
            "_publish_validated_geometry(result.geometry)",
            block,
        )

    def test_initial_calibration_updates_overlay_protection(self):
        state_pos = self.worker_source.find(
            '"exhaustive-calibrated"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 600
        ]

        self.assertIn(
            "_publish_validated_geometry(result.geometry)",
            block,
        )

    def test_protected_rect_change_revalidates_current_overlay(self):
        helper = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_apply_kt07_protected_rect"
        )

        helper_source = ast.get_source_segment(
            self.source,
            helper,
        )

        self.assertIn(
            "_overlay_rect()",
            helper_source,
        )

        self.assertIn(
            "_safe_geometry(",
            helper_source,
        )

        self.assertIn(
            "_apply_overlay_geometry(*safe)",
            helper_source,
        )

    def test_dynamic_protection_can_override_manual_overlay_position(self):
        helper = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_apply_kt07_protected_rect"
        )

        helper_source = ast.get_source_segment(
            self.source,
            helper,
        )

        # Safety correction must not be conditional on
        # _user_has_positioned_overlay. Resolution/window changes can move
        # KT07 underneath an overlay that the user positioned previously.
        self.assertNotIn(
            "if not _user_has_positioned_overlay",
            helper_source,
        )

        self.assertIn(
            "desired_geometry=None",
            helper_source,
        )



    def test_lost_lock_triggers_immediate_global_relocation(self):
        state_pos = self.worker_source.find(
            'result.state=="unlocked"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 2600
        ]

        self.assertIn(
            "locate_kt07_anchor_anywhere",
            block,
        )

        self.assertIn("relocation_backoff.next_probe=0.0", block)


    def test_relocated_anchor_requires_complete_tracker_validation(self):
        state_pos = self.worker_source.find(
            'result.state=="unlocked"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 3000
        ]

        self.assertIn("_validate_relocation", self.worker_source)
        self.assertIn("validate_candidate_rois", self.source)
        tracker_source = (
            BRIDGE.parent / "kt07_tracker.py"
        ).read_text(encoding="utf-8")
        self.assertIn("accept_validated_relocation", tracker_source)

    def test_locked_idle_relocation_is_throttled(self):
        self.assertIn('result.state=="idle"', self.worker_source)
        self.assertIn("relocation_backoff.due", self.worker_source)
        self.assertIn("relocation_backoff.attempted", self.worker_source)

    def test_window_change_enters_bounded_relocation_pending_mode(self):
        self.assertIn("WoWWindowChangeMonitor", self.worker_source)
        self.assertIn("RelocationPendingState", self.worker_source)
        self.assertIn("window_monitor.poll", self.worker_source)
        self.assertIn("relocation_pending.enter", self.worker_source)
        self.assertIn("client_anchor_presence_box", self.worker_source)
        self.assertIn("client_anchor_probe_box", self.worker_source)
        self.assertIn("pending_plausible=fast_locate_kt07_anchor", self.worker_source)
        self.assertIn("inspect_client_anchor_probe", self.worker_source)

    def test_native_window_observer_suppresses_global_discovery(self):
        self.assertIn("window_monitor.snapshot is None", self.worker_source)

    def test_normal_idle_uses_tiny_client_presence_observer(self):
        self.assertIn("relocation_pending.observation_due", self.worker_source)
        self.assertIn("ImageGrab.grab(bbox=presence_box)", self.worker_source)

    def test_native_relocation_requests_overlay_suppression(self):
        marker = "if window_monitor.poll(_now):"
        block = self.worker_source[self.worker_source.index(marker):][:500]
        self.assertIn("_enter_native_relocation", block)
        self.assertIn('"kt07_overlay_suppress"', self.worker_source)

    def test_pending_capture_is_gated_by_matching_ui_acknowledgement(self):
        marker = 'and result.state=="idle"'
        block = self.worker_source[self.worker_source.index(marker):][:650]
        gate = block.index("overlay_relocation_suppression.capture_allowed")
        capture = self.worker_source.index(
            "ImageGrab.grab(bbox=presence_box)",
            self.worker_source.index(marker),
        )
        self.assertGreater(capture, self.worker_source.index(marker) + gate)

    def test_ordinary_presence_observer_does_not_request_suppression(self):
        marker = "relocation_pending.observation_due"
        block = self.worker_source[self.worker_source.index(marker):][:1000]
        self.assertNotIn("request_suppression", block)
        self.assertNotIn('"kt07_overlay_suppress"', block)

    def test_tk_visibility_operations_are_confined_to_ui_helpers(self):
        worker_tree = ast.parse(self.worker_source)
        worker_attributes = {
            node.attr
            for node in ast.walk(worker_tree)
            if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("withdraw", worker_attributes)
        self.assertNotIn("deiconify", worker_attributes)
        suppress = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_suppress_overlay_for_relocation"
        )
        restore = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_restore_overlay_after_relocation"
        )
        self.assertIn("rootui.withdraw()", ast.get_source_segment(self.source, suppress))
        self.assertIn("rootui.deiconify()", ast.get_source_segment(self.source, restore))

    def test_relocation_restore_positions_while_hidden_then_shows(self):
        helper = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_restore_overlay_after_relocation"
        )
        source = ast.get_source_segment(self.source, helper)
        self.assertLess(
            source.index("_apply_kt07_protected_rect"),
            source.index("rootui.deiconify()"),
        )

    def test_shutdown_cleans_overlay_suppression_state(self):
        helper = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "close_overlay"
        )
        source = ast.get_source_segment(self.source, helper)
        self.assertIn("overlay_relocation_suppression.cleanup()", source)
        self.assertIn("rootui.deiconify()", source)

    def test_pending_relocation_emits_same_validated_frame(self):
        marker = "pending_decoded,pending_diagnostic=inspect_client_anchor_probe"
        position = self.worker_source.find(marker)
        self.assertNotEqual(-1, position)
        block = self.worker_source[position:position + 10000]
        self.assertIn("raw=pending_result.text", block)
        self.assertIn("_publish_validated_geometry(", block)

    def test_pending_validation_is_snapshot_bound_and_commits_after_refresh(self):
        marker = "pending_attempt=relocation_pending.attempt()"
        block = self.worker_source[self.worker_source.index(marker):]
        self.assertIn("pending_snapshot=pending_attempt[1]", block)
        self.assertIn("window_monitor.poll(time.monotonic(),force=True)", block)
        self.assertIn("relocation_pending.is_current(pending_attempt)", block)
        commit = block.index("tracker.accept_validated_relocation")
        refresh = block.index("window_monitor.poll(time.monotonic(),force=True)")
        self.assertLess(refresh, commit)

    def test_initial_native_snapshot_is_bound_before_client_probe(self):
        marker = "pending_attempt=relocation_pending.attempt()"
        prefix = self.worker_source[max(0, self.worker_source.index(marker) - 180):self.worker_source.index(marker)]
        self.assertIn(
            "relocation_pending.bind_snapshot(window_monitor.snapshot)",
            prefix,
        )

    def test_stationary_startup_binding_does_not_enter_pending(self):
        marker = "relocation_pending.bind_snapshot(window_monitor.snapshot)"
        position = self.worker_source.index(marker)
        self.assertNotIn(
            "relocation_pending.enter",
            self.worker_source[position:position + len(marker)],
        )

    def test_pending_diagnostic_is_initialized_before_presence_branch(self):
        initialized = self.worker_source.index(
            "pending_diagnostic=empty_client_probe_diagnostic()"
        )
        branch = self.worker_source.index("if pending_plausible:", initialized)
        self.assertLess(initialized, branch)

    def test_initial_and_relocation_anchor_locators_are_separate(self):
        self.assertIn("result=tracker.decode", self.worker_source)
        pending_marker = "pending_decoded,pending_diagnostic=inspect_client_anchor_probe"
        pending_block = self.worker_source[self.worker_source.index(pending_marker):]
        self.assertIn("locate_client_anchor", pending_block[:400])

    def test_successful_payloads_do_not_write_obsolete_runtime_diagnostics(self):
        for obsolete in (
            "_save_locked_payload_transition",
            "kt07_locked_payload_change.png",
            "kt07_locked_payload_change.txt",
            "_save_idle_visible_capture",
            "kt07_idle_visible_transition.txt",
        ):
            self.assertNotIn(obsolete, self.source)
        self.assertIn("emit_raw=duplicates.observe", self.worker_source)

    def test_shared_runtime_logs_use_transport_terminology(self):
        for obsolete in (
            "[OVERLAY] KT07 protected area updated",
            "[OVERLAY] KT07 moved under overlay",
            "[OVERLAY] KT07 area protected",
            "[KT07] WoW window/display geometry changed",
        ):
            self.assertNotIn(obsolete, self.source)
        self.assertIn("[TRANSPORT] WoW window/display geometry changed", self.source)
        self.assertIn("[OVERLAY] Transport protected area updated", self.source)

    def test_transient_presence_absence_is_status_not_validation_failure(self):
        marker = "if not pending_plausible:"
        block = self.worker_source[self.worker_source.index(marker):][:500]
        absence_branch = block[:block.index("else:")]
        self.assertIn("Relocation transport not visible yet", absence_branch)
        self.assertNotIn("_save_relocation_diagnostic", absence_branch)
        self.assertNotIn("request_restore", absence_branch)

    def test_genuine_kt07_failure_diagnostics_retain_protocol_label(self):
        self.assertIn("[KT07] Relocation diagnostic updated", self.source)
        self.assertIn("[KT07] Initial calibration consensus diagnostic", self.source)
        self.assertIn("[KT07] Preserved first strict relocation failure", self.source)

    def test_temporary_overlay_contamination_diagnostic_is_removed(self):
        self.assertNotIn("kt07_overlay_capture_test", self.source)

    def test_first_strict_relocation_failure_preserves_raw_roi_and_overlay_metadata(self):
        self.assertIn("preserve_validation_failure", self.worker_source)
        self.assertIn('pending_diagnostic["stage"]=="strict_frame_validation_failed"', self.worker_source)
        self.assertIn('"kt07_relocation_overlay_diagnostic"', self.worker_source)
        self.assertIn("_append_relocation_overlay_metadata", self.source)
        self.assertIn('"overlay_intersects_validation_roi"', self.source)
        self.assertIn('"overlay_intersects_anchor_estimate"', self.source)
        self.assertIn('"include_layered_windows_effective_default":False', self.source)

    def test_global_locator_has_no_desktop_pixel_loops(self):
        helper = next(
            node for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "locate_kt07_anchor_anywhere"
        )
        self.assertFalse(any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(helper)))


    def test_relocation_updates_dynamic_overlay_protection(self):
        state_pos = self.worker_source.find(
            'result.state=="unlocked"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 3200
        ]

        self.assertIn(
            "_publish_validated_geometry(result.geometry)",
            block,
        )


    def test_relocation_does_not_directly_assign_discovered_geometry(self):
        state_pos = self.worker_source.find(
            'result.state=="unlocked"'
        )

        self.assertNotEqual(-1, state_pos)

        block = self.worker_source[
            state_pos:state_pos + 3000
        ]

        self.assertNotIn(
            "tracker.geometry=geometry",
            block,
        )

        self.assertNotIn(
            "tracker.geometry=recovery_found",
            block,
        )
if __name__ == "__main__":
    unittest.main()
