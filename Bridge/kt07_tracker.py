"""Stateful KT07 calibration policy for the live Bridge capture loop.

Owns only geometry lifecycle: validated lock, cheap fast path, bounded local
recovery, and rare exhaustive recalibration. Screen capture stays in bridge.py.
"""
from dataclasses import dataclass

from Bridge.kt07_decoder import audit_initial_candidate, decode_at, decode_local_candidate, decode_near_anchor, has_signal_at


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

        # A locally discovered replacement geometry must validate repeatedly
        # before it is allowed to replace an already trusted geometry.
        self.candidate_geometry = None
        self.candidate_hits = 0
        self.candidate_seen_this_transport = False
        self.initial_calibration_diagnostic = None
        self.awaiting_visible_after_idle = False
        self.transition_capture_index = None
        self.transition_capture_limit = 10
        self._last_transition_capture_index = self.transition_capture_limit

    @property
    def locked(self):
        return self.geometry is not None

    def reset(self):
        self.geometry = None
        self.failures = 0
        self.misses_since_lock = 0
        self.candidate_geometry = None
        self.candidate_hits = 0
        self.candidate_seen_this_transport = False
        self.initial_calibration_diagnostic = None
        self.awaiting_visible_after_idle = False
        self.transition_capture_index = None
        self._last_transition_capture_index = self.transition_capture_limit

    def _accept(self, text, geometry, state):
        self.geometry = geometry
        self.failures = 0
        self.misses_since_lock = 0
        self.candidate_geometry = None
        self.candidate_hits = 0
        self.candidate_seen_this_transport = False
        return DecodeResult(text, geometry, state)

    def accept_validated_relocation(self, text, geometry):
        """Install geometry only after a complete decoder validation."""
        return self._accept(text, geometry, "relocated")

    def decode(self, image, anchor_box, anchor_pitch):
        self.transition_capture_index = None
        # Fast path: a previously checksum-validated geometry.
        if self.geometry is not None:
            text = decode_at(image, self.geometry)

            if text is not None:
                self._note_visible_capture()
                return self._accept(
                    text,
                    self.geometry,
                    "fast",
                )

            # A validated geometry remains useful while KT07 is idle.
            # No visible transport signal is not evidence of a geometry
            # change. Keep the trusted lock. A local candidate may survive
            # idle so it can be confirmed by a later transport frame, but
            # repeated screenshots of one visible frame count only once.
            if not has_signal_at(image, self.geometry):
                self.failures = 0
                self.misses_since_lock = 0
                self.candidate_seen_this_transport = False
                self.awaiting_visible_after_idle = True
                self._last_transition_capture_index = 0
                return DecodeResult(
                    None,
                    self.geometry,
                    "idle",
                )

            self._note_visible_capture()
            if (
                self.transition_capture_index is not None
                and self.transition_capture_index <= self.transition_capture_limit
            ):
                return DecodeResult(None, self.geometry, "settling")

            self.failures += 1
            self.misses_since_lock += 1

            # One isolated bad capture must not destroy a good lock.
            if (
                self.failures < self.local_after
                and self.candidate_geometry is None
            ):
                return DecodeResult(
                    None,
                    self.geometry,
                    "transient",
                )

            # Try bounded recalibration around the current anchor.
            found, _local_attempts = decode_local_candidate(
                image, self.geometry
            )

            if found is not None:
                text, geometry = found

                if (
                    geometry == self.candidate_geometry
                    and not self.candidate_seen_this_transport
                ):
                    self.candidate_hits += 1
                elif geometry != self.candidate_geometry:
                    self.candidate_geometry = geometry
                    self.candidate_hits = 1
                self.candidate_seen_this_transport = True

                # While a fully validated replacement candidate is being
                # confirmed, do not let ordinary failure escalation destroy
                # the trusted geometry. Keep us eligible to check the
                # candidate again on the next frame.
                self.failures = self.local_after - 1

                if self.candidate_hits >= 2:
                    return self._accept(
                        text,
                        geometry,
                        "local-recalibrated",
                    )

                return DecodeResult(
                    None,
                    self.geometry,
                    "local-candidate",
                )

            # Confirmation must be consecutive.
            self.candidate_geometry = None
            self.candidate_hits = 0
            self.candidate_seen_this_transport = False

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
            self.candidate_geometry = None
            self.candidate_hits = 0
            self.candidate_seen_this_transport = False

            return DecodeResult(
                None,
                None,
                "unlocked",
            )

        # No lock: bounded calibration is always attempted first.
        self.misses_since_lock += 1

        found = decode_near_anchor(
            image, anchor_box, anchor_pitch, exhaustive=False
        )
        self.initial_calibration_diagnostic = None
        if found is not None and hasattr(image, "width"):
            self.initial_calibration_diagnostic = audit_initial_candidate(
                image, anchor_box, anchor_pitch, found
            )
            if self.initial_calibration_diagnostic["ambiguous"]:
                found = None
            else:
                found = (
                    self.initial_calibration_diagnostic["selected_text"],
                    self.initial_calibration_diagnostic["selected_geometry"],
                )

        if (
            self.initial_calibration_diagnostic is not None
            and self.initial_calibration_diagnostic["ambiguous"]
        ):
            return DecodeResult(None, None, "calibration-ambiguous")

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

    def _note_visible_capture(self):
        if self.awaiting_visible_after_idle:
            self.awaiting_visible_after_idle = False
            self.transition_capture_index = 1
            self._last_transition_capture_index = 1
            return
        if (
            self.transition_capture_index is None
            and hasattr(self, "_last_transition_capture_index")
            and self._last_transition_capture_index < self.transition_capture_limit
        ):
            self.transition_capture_index = self._last_transition_capture_index + 1
        if self.transition_capture_index is not None:
            self._last_transition_capture_index = self.transition_capture_index


class KT07DuplicateSuppressor:
    """Suppress a frame while visible, but end suppression at real idle."""

    def __init__(self):
        self.last = None

    def observe(self, raw, state, locked, identity=None):
        if raw:
            key = raw if identity is None else identity
            if key == self.last:
                return None
            self.last = key
            return raw
        if state == "idle" or not locked:
            self.last = None
        return None
