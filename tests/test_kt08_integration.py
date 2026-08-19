import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class KT08IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = (ROOT / "Bridge" / "bridge.py").read_text(encoding="utf-8")
        cls.lua = (ROOT / "Addon" / "WoWInterpreter" / "WoWInterpreter.lua").read_text(encoding="utf-8")
        cls.toc = (ROOT / "Addon" / "WoWInterpreter" / "WoWInterpreter.toc").read_text(encoding="utf-8")
        cls.tray = (ROOT / "WoWInterpreterTray.py").read_text(encoding="utf-8")
        cls.installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
        cls.release_build = (ROOT / "build_release.bat").read_text(encoding="utf-8")
        ast.parse(cls.bridge)

    def test_runtime_component_versions_are_consistent(self):
        self.assertIn("WoWInterpreter Bridge 2.2.0", self.bridge)
        self.assertIn("WoWInterpreter v2.2.0 starting", self.tray)
        self.assertIn("## Version: 2.2.0", self.toc)
        self.assertIn("WoWInterpreter v2.2.0", self.lua)
        self.assertIn('#define MyAppVersion "2.2.0"', self.installer)
        self.assertIn("WoWInterpreter-2.2.0-Setup.exe", self.release_build)
        self.assertIn("runtime_housekeeping.py", self.release_build)
        for language in ("English", "Chinese-Simplified"):
            self.assertTrue((
                ROOT / "Documentation" /
                f"WoWInterpreter-2.2.0-User-Guide-{language}.docx"
            ).is_file())

    def test_bridge_dispatches_kt08_before_kt07_initial_calibration(self):
        kt08 = self.bridge.index("kt08_tracker.acquire(im)")
        kt07 = self.bridge.index("found=locate_kt07_anchor(im)", kt08)
        self.assertLess(kt08, kt07)

    def test_displaced_windowed_initial_acquisition_is_client_relative(self):
        marker = "# KT08 initial acquisition is client-relative."
        block = self.bridge[self.bridge.index(marker):self.bridge.index(marker) + 4200]
        self.assertIn("client_anchor_presence_box(window_monitor.snapshot)", block)
        self.assertIn("client_anchor_probe_box(window_monitor.snapshot)", block)
        self.assertIn("ImageGrab.grab(bbox=_initial_probe_box)", block)
        self.assertIn("(_initial_probe_box[0],_initial_probe_box[1])", block)
        self.assertNotIn("ImageGrab.grab()", block)

    def test_initial_capture_is_impossible_before_matching_suppression_ack(self):
        marker = "# KT08 initial acquisition is client-relative."
        block = self.bridge[self.bridge.index(marker):self.bridge.index(marker) + 4200]
        gate = block.index(
            "overlay_relocation_suppression.capture_allowed(_initial_generation)"
        )
        presence = block.index("ImageGrab.grab(bbox=_initial_presence_box)")
        probe = block.index("ImageGrab.grab(bbox=_initial_probe_box)")
        self.assertLess(gate, presence)
        self.assertLess(gate, probe)
        self.assertIn("continue", block[gate:presence])

    def test_initial_decode_is_side_effect_free_until_native_generation_recheck(self):
        marker = "_initial_decoded=locate_and_decode_kt08(_initial_probe)"
        block = self.bridge[self.bridge.index(marker):self.bridge.index(marker) + 1800]
        decoded = block.index(marker)
        refreshed = block.index("window_monitor.poll(time.monotonic(),force=True)")
        current = block.index("relocation_pending.is_current(_initial_attempt)")
        commit = block.index("kt08_tracker.accept_validated_relocation")
        self.assertLess(decoded, refreshed)
        self.assertLess(refreshed, current)
        self.assertLess(current, commit)
        self.assertNotIn("kt08_tracker.acquire", block[:commit])

    def test_initial_wait_keeps_one_generation_suppressed_until_valid_frame(self):
        marker = "if not tracker.locked and window_monitor.snapshot is not None:"
        block = self.bridge[self.bridge.index(marker):self.bridge.index(marker) + 5000]
        self.assertIn("if not relocation_pending.pending:", block)
        self.assertIn('"initial KT08 acquisition"', block)
        self.assertIn("initial_waiting_logged_generation", block)
        self.assertNotIn("request_restore", block[:block.index("accept_validated_relocation")])

    def test_initial_and_relocation_share_one_suppression_coordinator(self):
        self.assertEqual(1, self.bridge.count("OverlayRelocationSuppression()"))
        self.assertIn(
            'events.append(("kt07_overlay_suppress",(generation,purpose)))',
            self.bridge,
        )

    def test_stale_initial_restore_is_checked_on_ui_thread(self):
        marker = "def _restore_overlay_after_relocation(data):"
        block = self.bridge[self.bridge.index(marker):self.bridge.index(marker) + 800]
        self.assertIn("generation != current_generation", block)
        self.assertIn('state != "restore_requested"', block)
        self.assertLess(block.index("generation != current_generation"), block.index("deiconify"))

    def test_damaged_detected_kt08_does_not_fall_back_to_kt07(self):
        self.assertIn(
            'if kt08_acquired.state!="calibrated" and kt08_acquired.geometry is None:',
            self.bridge,
        )
        self.assertIn('pending_kt08.geometry is None and active_protocol!="KT08"', self.bridge)

    def test_kt08_relocation_reuses_generation_and_overlay_gate(self):
        marker = "pending_kt08=locate_and_decode_kt08(pending_im)"
        block = self.bridge[self.bridge.index(marker) - 2500:self.bridge.index(marker) + 12000]
        self.assertIn("overlay_relocation_suppression.capture_allowed", block)
        self.assertIn("relocation_pending.is_current(pending_attempt)", block)
        self.assertIn("_publish_validated_geometry", block)

    def test_long_idle_relocation_without_pilots_does_not_enter_kt07_timing(self):
        marker = 'elif active_protocol=="KT08":\n       print(\n        "[KT08] Pending relocation waiting for pilots:'
        self.assertIn(marker, self.bridge)

    def test_lua_emits_kt08_crc_sequences_and_double_buffers(self):
        for required in (
            'local MAGIC="KT08"', "local VERSION=1", "local function crc32",
            "0xEDB88320", "sequence=(sequence+1)%65536",
            "buffers[1]=makeBuffer(1)", "buffers[2]=makeBuffer(2)",
            "if activeBuffer then activeBuffer:Hide() end", "activeBuffer:Show()",
        ):
            self.assertIn(required, self.lua)

    def test_lua_crc_covers_matching_end_sequence(self):
        self.assertIn('..text..u16(sequence)', self.lua)
        self.assertIn('frameBytes=body..u32(crc32(body))', self.lua)

    def test_lua_python_physical_contract_constants_match(self):
        for required in (
            "local COLS=32", "local CELL=4", "local GRID_COLS=36",
            "local GRID_ROWS=29", "local pilotPositions={{0,0},{34,0},{0,27},{34,27}}",
            '(col+2)*CELL', '(row+2)*CELL',
            '2,-(2+ANCHOR_H+CELL)',
        ):
            self.assertIn(required, self.lua)
        geometry = (ROOT / "Bridge" / "kt08_geometry.py").read_text(encoding="utf-8")
        decoder = (ROOT / "Bridge" / "kt08_decoder.py").read_text(encoding="utf-8")
        self.assertIn("PILOT_DX = 34.0", geometry)
        self.assertIn("PILOT_DY = 27.0", geometry)
        self.assertIn("COLS = 32", decoder)

    def test_tk_calls_remain_outside_worker(self):
        worker = self.bridge[self.bridge.index("def worker():"):]
        self.assertNotIn("rootui.withdraw()", worker)
        self.assertNotIn("rootui.deiconify()", worker)


if __name__ == "__main__":
    unittest.main()
