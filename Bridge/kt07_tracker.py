"""Stateful KT07 calibration policy for the live Bridge capture loop.

Owns only geometry lifecycle: validated lock, cheap fast path, bounded local
recovery, and rare exhaustive recalibration. Screen capture stays in bridge.py.
"""
from dataclasses import dataclass

from Bridge.kt07_decoder import decode_at, decode_near_anchor, has_signal_at


@dataclass
class DecodeResult:
    text: str | None
    geometry: object | None
    state: str


class KT07GeometryTracker:
    """Manage KT07 geometry without ever locking on anchor evidence alone."""

    def __init__(self, local_after=2, unlock_after=5, exhaustive_after=9):
        if not (0 < local_after < unlock_after <= exhaustive_after):
            raise ValueError("invalid KT07 recovery thresholds")

        self.local_after = local_after
        self.unlock_after = unlock_after
        self.exhaustive_after = exhaustive_after

        self.geometry = None
        self.failures = 0
        self.misses_since_lock = 0

    @property
    def locked(self):
        return self.geometry is not None

    def reset(self):
        self.geometry = None
        self.failures = 0
        self.misses_since_lock = 0

    def _accept(self, text, geometry, state):
        self.geometry = geometry
        self.failures = 0
        self.misses_since_lock = 0
        return DecodeResult(text, geometry, state)

    def decode(self, image, anchor_box, anchor_pitch):
        # Fast path: a previously checksum-validated geometry.
        if self.geometry is not None:
            text = decode_at(image, self.geometry)

            if text is not None:
                return self._accept(text, self.geometry, "fast")

            # A validated geometry remains useful while KT07 is idle.
            # No visible transport signal is not evidence of a geometry
            # change, so keep the lock and reset recovery counters.
            if not has_signal_at(image, self.geometry):
                self.failures = 0
                self.misses_since_lock = 0
                return DecodeResult(None, self.geometry, "idle")

            self.failures += 1
            self.misses_since_lock += 1

            # One isolated bad capture must not destroy a good lock.
            if self.failures < self.local_after:
                return DecodeResult(
                    None,
                    self.geometry,
                    "transient",
                )

            # Try bounded recalibration around the current anchor.
            found = decode_near_anchor(
                image,
                anchor_box,
                anchor_pitch,
                exhaustive=False,
            )

            if found is not None:
                text, geometry = found
                return self._accept(
                    text,
                    geometry,
                    "local-recalibrated",
                )

            # Keep the previous geometry for a few failures in case the
            # transport is temporarily incomplete.
            if self.failures < self.unlock_after:
                return DecodeResult(
                    None,
                    self.geometry,
                    "local-miss",
                )

            # Too many validated failures: the old geometry is no longer
            # trustworthy.
            self.geometry = None
            return DecodeResult(
                None,
                None,
                "unlocked",
            )

        # No lock: bounded calibration is always attempted first.
        self.misses_since_lock += 1

        found = decode_near_anchor(
            image,
            anchor_box,
            anchor_pitch,
            exhaustive=False,
        )

        if found is not None:
            text, geometry = found
            return self._accept(
                text,
                geometry,
                "calibrated",
            )

        # Broad recovery is deliberately rare because it is substantially
        # more expensive. It can never lock unless the complete frame passes
        # MAGIC + length + checksum + UTF-8 validation.
        if self.misses_since_lock >= self.exhaustive_after:
            found = decode_near_anchor(
                image,
                anchor_box,
                anchor_pitch,
                exhaustive=True,
            )

            if found is not None:
                text, geometry = found
                return self._accept(
                    text,
                    geometry,
                    "exhaustive-calibrated",
                )

            self.misses_since_lock = 0

            return DecodeResult(
                None,
                None,
                "exhaustive-miss",
            )

        return DecodeResult(
            None,
            None,
            "calibration-miss",
        )
