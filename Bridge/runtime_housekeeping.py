"""Bounded, conservative retention for runtime logs and diagnostics."""

from __future__ import annotations

import os
import re
import sys
import threading
from pathlib import Path


LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3
DIAGNOSTIC_SET_LIMIT = 10


def report_stream_error(error, output=None, fallback=None):
    """Best-effort error reporting that never propagates a stream failure."""
    output = sys.stdout if output is None else output
    fallback = sys.stderr if fallback is None else fallback
    message = "ERROR: " + repr(error) + "\n"
    try:
        print(message,end="",file=output,flush=True)
        return True
    except Exception:
        try:
            buffer = getattr(fallback,"buffer",None)
            if buffer is not None:
                buffer.write(message.encode("utf-8",errors="backslashreplace"))
                buffer.flush()
                return True
        except Exception:
            pass
    return False


class RuntimeLogWriter:
    """Single-process log owner with Windows-safe close-before-rename rotation."""

    def __init__(self, path, max_bytes=LOG_MAX_BYTES, backup_count=LOG_BACKUP_COUNT):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.backup_count = int(backup_count)
        self._lock = threading.Lock()
        try:
            self._size = self.path.stat().st_size
        except OSError:
            self._size = 0

    def write(self, text):
        data = str(text).encode("utf-8")
        with self._lock:
            if self.max_bytes > 0 and self._size + len(data) > self.max_bytes:
                self._rotate_safely()
            try:
                with self.path.open("ab") as stream:
                    stream.write(data)
                    stream.flush()
                self._size += len(data)
            except OSError:
                # Logging maintenance must never terminate the application.
                pass

    def _rotate_safely(self):
        try:
            if self.backup_count <= 0:
                self.path.unlink(missing_ok=True)
            else:
                oldest = Path(f"{self.path}.{self.backup_count}")
                oldest.unlink(missing_ok=True)
                for number in range(self.backup_count - 1, 0, -1):
                    source = Path(f"{self.path}.{number}")
                    if source.exists():
                        os.replace(source, Path(f"{self.path}.{number + 1}"))
                if self.path.exists():
                    os.replace(self.path, Path(f"{self.path}.1"))
            self._size = 0
        except OSError:
            # Keep appending to the current file if Windows temporarily denies
            # rename/delete (for example while a support tool has it open).
            try:
                self._size = self.path.stat().st_size
            except OSError:
                self._size = 0


_NUMBERED_PATTERNS = (
    re.compile(r"^(kt08_initial_failure)_(\d+)\.(png|txt)$"),
    re.compile(r"^(kt08_relocation_failure)_(\d+)(_validation\.png|\.txt)$"),
    re.compile(r"^(kt07_relocation_failure)_(\d+)(_validation\.png|\.txt)$"),
)
_FIXED_SETS = {
    "debug_capture.png": "debug_capture",
    "kt07_initial_ambiguity.png": "kt07_initial_ambiguity",
    "kt07_initial_ambiguity.txt": "kt07_initial_ambiguity",
    "kt07_visible_capture.png": "kt07_visible",
    "kt07_visible_crop.png": "kt07_visible",
    "kt07_geometry.txt": "kt07_visible",
    "kt07_relocation_failure.png": "kt07_relocation_discovery",
    "kt07_relocation_reduced.png": "kt07_relocation_discovery",
    "kt07_relocation_closest.png": "kt07_relocation_discovery",
    "kt07_relocation_failure.txt": "kt07_relocation_discovery",
}


def _diagnostic_set_key(name):
    fixed = _FIXED_SETS.get(name)
    if fixed is not None:
        return fixed
    for pattern in _NUMBERED_PATTERNS:
        match = pattern.fullmatch(name)
        if match:
            return f"{match.group(1)}_{match.group(2)}"
    return None


def cleanup_runtime_diagnostics(directory, retain_sets=DIAGNOSTIC_SET_LIMIT):
    """Retain recent known diagnostic sets only inside the runtime Bridge dir."""
    directory = Path(directory)
    try:
        resolved = directory.resolve(strict=True)
    except OSError:
        return False
    # Both source and frozen layouts use a directory literally named Bridge.
    # This deliberately rejects tests/fixtures and arbitrary caller paths.
    if not resolved.is_dir() or resolved.name.casefold() != "bridge":
        return False

    groups = {}
    try:
        entries = list(resolved.iterdir())
    except OSError:
        return False
    for path in entries:
        key = _diagnostic_set_key(path.name)
        if key is None:
            continue
        try:
            if path.is_symlink() or not path.is_file() or path.parent.resolve() != resolved:
                continue
            modified = path.stat().st_mtime_ns
        except OSError:
            continue
        item = groups.setdefault(key, {"modified": modified, "paths": []})
        item["modified"] = max(item["modified"], modified)
        item["paths"].append(path)

    keep = max(0, int(retain_sets))
    stale = sorted(groups.values(), key=lambda item: item["modified"], reverse=True)[keep:]
    for item in stale:
        for path in item["paths"]:
            try:
                if path.parent.resolve() == resolved and _diagnostic_set_key(path.name) is not None:
                    path.unlink()
            except OSError:
                pass
    return True
