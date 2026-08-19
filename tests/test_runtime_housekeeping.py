import os
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from Bridge.runtime_housekeeping import (
    RuntimeLogWriter,
    cleanup_runtime_diagnostics,
    report_stream_error,
)


UNICODE_PIPE_LINES = (
    "EN→ZH: '这是新的版本。'",
    "ZH→EN: 'This is the new version.'",
    'español: "traducción"',
    "中文",
    "日本語",
    "한국어",
    "emoji: 😀🚀",
)


class RuntimeLogWriterTests(unittest.TestCase):
    def test_below_limit_does_not_rotate_and_utf8_round_trips(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "WoWInterpreter.log"
            writer = RuntimeLogWriter(log, max_bytes=100, backup_count=3)
            writer.write("中文日志\n")
            self.assertEqual("中文日志\n", log.read_text(encoding="utf-8"))
            self.assertFalse(Path(f"{log}.1").exists())

    def test_rotation_keeps_current_and_exactly_three_recent_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "WoWInterpreter.log"
            writer = RuntimeLogWriter(log, max_bytes=12, backup_count=3)
            for number in range(1, 7):
                writer.write(f"entry-{number}\n")
            self.assertEqual("entry-6\n", log.read_text(encoding="utf-8"))
            self.assertEqual("entry-5\n", Path(f"{log}.1").read_text(encoding="utf-8"))
            self.assertTrue(Path(f"{log}.2").exists())
            self.assertTrue(Path(f"{log}.3").exists())
            self.assertFalse(Path(f"{log}.4").exists())

    def test_new_writer_preserves_history_across_bridge_style_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "WoWInterpreter.log"
            RuntimeLogWriter(log, max_bytes=100, backup_count=3).write("before restart\n")
            RuntimeLogWriter(log, max_bytes=100, backup_count=3).write("after restart\n")
            self.assertEqual(
                "before restart\nafter restart\n", log.read_text(encoding="utf-8")
            )

    def test_rotation_rename_failure_does_not_raise_or_lose_new_line(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "WoWInterpreter.log"
            log.write_text("existing data", encoding="utf-8")
            writer = RuntimeLogWriter(log, max_bytes=5, backup_count=3)
            with patch("Bridge.runtime_housekeeping.os.replace", side_effect=PermissionError):
                writer.write("\nrecent\n")
            self.assertIn("recent", log.read_text(encoding="utf-8"))

    def test_bridge_subprocess_pipe_relay_is_utf8_end_to_end_and_survives(self):
        import WoWInterpreterTray as tray

        child_code = (
            "import sys; "
            "from WoWInterpreterTray import configure_bridge_stdio; "
            "configure_bridge_stdio(); "
            f"lines={UNICODE_PIPE_LINES!r}; "
            "[print(line, flush=True) for line in lines]; "
            "print('stderr Unicode: 中文 日本語 한국어 😀', file=sys.stderr, flush=True); "
            "print('CHILD_STILL_ALIVE', flush=True)"
        )
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "WoWInterpreter.log"
            old_writer = tray.log_writer
            tray.log_writer = RuntimeLogWriter(log)
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "cp1252:strict"
            try:
                proc = tray.spawn_bridge_process(
                    [sys.executable,"-c",child_code],
                    Path(__file__).resolve().parents[1],
                    env=environment,
                )
                tray.relay_bridge_output(proc)
                self.assertEqual(0,proc.wait(timeout=10))
            finally:
                tray.log_writer = old_writer
            content = log.read_text(encoding="utf-8")
            for line in UNICODE_PIPE_LINES:
                self.assertIn(line,content)
            self.assertIn("stderr Unicode: 中文 日本語 한국어 😀",content)
            self.assertIn("CHILD_STILL_ALIVE",content)

    def test_error_report_falls_back_to_utf8_bytes_without_raising(self):
        class BrokenOutput:
            def write(self,_text):
                raise UnicodeEncodeError("cp1252","→",0,1,"unsupported")

            def flush(self):
                raise AssertionError("unreachable")

        class BinaryFallback:
            def __init__(self):
                self.buffer = io.BytesIO()

        fallback = BinaryFallback()
        self.assertTrue(report_stream_error(ValueError("错误 → 😀"),BrokenOutput(),fallback))
        decoded = fallback.buffer.getvalue().decode("utf-8")
        self.assertIn("错误 → 😀",decoded)


class RuntimeDiagnosticRetentionTests(unittest.TestCase):
    BASE_TIME_NS = 1_700_000_000_000_000_000

    @staticmethod
    def _bridge_directory(temp):
        directory = Path(temp) / "Bridge"
        directory.mkdir()
        return directory

    def test_keeps_ten_latest_sets_and_deletes_pairs_together(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self._bridge_directory(temp)
            for number in range(1, 13):
                for suffix in (".png", ".txt"):
                    path = directory / f"kt08_initial_failure_{number}{suffix}"
                    path.write_text(str(number), encoding="utf-8")
                    timestamp = self.BASE_TIME_NS + number * 1_000_000_000
                    os.utime(path, ns=(timestamp, timestamp))
            self.assertTrue(cleanup_runtime_diagnostics(directory))
            for number in (1, 2):
                self.assertFalse((directory / f"kt08_initial_failure_{number}.png").exists())
                self.assertFalse((directory / f"kt08_initial_failure_{number}.txt").exists())
            for number in range(3, 13):
                self.assertTrue((directory / f"kt08_initial_failure_{number}.png").exists())
                self.assertTrue((directory / f"kt08_initial_failure_{number}.txt").exists())

    def test_unknown_files_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self._bridge_directory(temp)
            unknown = directory / "user-important.png"
            unknown.write_bytes(b"keep")
            for number in range(12):
                path = directory / f"kt08_initial_failure_{number}.png"
                path.write_bytes(b"known")
                timestamp = self.BASE_TIME_NS + number * 1_000_000_000
                os.utime(path, ns=(timestamp, timestamp))
            cleanup_runtime_diagnostics(directory)
            self.assertEqual(b"keep", unknown.read_bytes())

    def test_debug_capture_is_one_known_set_and_can_age_out(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self._bridge_directory(temp)
            debug = directory / "debug_capture.png"
            debug.write_bytes(b"old")
            os.utime(debug, ns=(self.BASE_TIME_NS, self.BASE_TIME_NS))
            for number in range(10):
                path = directory / f"kt08_initial_failure_{number}.png"
                path.write_bytes(b"new")
                timestamp = self.BASE_TIME_NS + (number + 1) * 1_000_000_000
                os.utime(path, ns=(timestamp, timestamp))
            cleanup_runtime_diagnostics(directory)
            self.assertFalse(debug.exists())

    def test_fixtures_and_unexpected_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fixtures = Path(temp) / "tests" / "fixtures"
            fixtures.mkdir(parents=True)
            fixture = fixtures / "kt08_initial_failure_1.png"
            fixture.write_bytes(b"fixture")
            self.assertFalse(cleanup_runtime_diagnostics(fixtures, retain_sets=0))
            self.assertEqual(b"fixture", fixture.read_bytes())

    def test_delete_failure_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = self._bridge_directory(temp)
            path = directory / "debug_capture.png"
            path.write_bytes(b"old")
            with patch("pathlib.Path.unlink", side_effect=PermissionError):
                self.assertTrue(cleanup_runtime_diagnostics(directory, retain_sets=0))
            self.assertTrue(path.exists())

    def test_bridge_owns_no_log_file_and_cleanup_is_not_in_capture_loop(self):
        root = Path(__file__).resolve().parents[1]
        tray = (root / "WoWInterpreterTray.py").read_text(encoding="utf-8")
        bridge = (root / "Bridge" / "bridge.py").read_text(encoding="utf-8")
        bridge_mode = tray.split("def run_bridge_mode():", 1)[1]
        self.assertIn("stdout=subprocess.PIPE", tray)
        self.assertIn("stderr=subprocess.STDOUT", tray)
        self.assertNotIn('open(LOG', bridge_mode)
        self.assertNotIn('LOG.open(', bridge_mode)
        live_loop = bridge.split(" while True:", 1)[1]
        self.assertNotIn("cleanup_runtime_diagnostics(", live_loop)


if __name__ == "__main__":
    unittest.main()
