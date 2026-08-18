"""Small geometry lifecycle for pilot-synchronized KT08."""
from dataclasses import dataclass

from Bridge.kt08_decoder import decode_at, locate_and_decode
from Bridge.kt08_geometry import offset_geometry, validate_pilots_at


@dataclass(frozen=True)
class KT08TrackResult:
    text: str | None
    geometry: object | None
    state: str
    sequence: int | None = None
    diagnostic: dict | None = None


class KT08GeometryTracker:
    def __init__(self):
        self.geometry = None
        self.transition_capture_index = None
        self.initial_calibration_diagnostic = None

    @property
    def locked(self):
        return self.geometry is not None

    def reset(self):
        self.geometry = None

    def acquire(self, image, screen_offset=(0, 0)):
        decoded = locate_and_decode(image)
        if decoded.frame is None:
            state = "absent" if decoded.geometry is None else "invalid"
            return KT08TrackResult(None, decoded.geometry, state, diagnostic=decoded.diagnostic)
        geometry = offset_geometry(decoded.geometry, *screen_offset)
        self.geometry = geometry
        return KT08TrackResult(
            decoded.frame.text, geometry, "calibrated", decoded.frame.sequence, decoded.diagnostic
        )

    def decode(self, image, _anchor_box=None, _anchor_pitch=None):
        if self.geometry is None:
            return self.acquire(image)
        if not validate_pilots_at(image, self.geometry):
            return KT08TrackResult(None, self.geometry, "idle")
        decoded = decode_at(image, self.geometry)
        if decoded.frame is None:
            return KT08TrackResult(
                None, self.geometry, "settling", diagnostic=decoded.diagnostic
            )
        return KT08TrackResult(
            decoded.frame.text, self.geometry, "fast", decoded.frame.sequence, decoded.diagnostic
        )

    def accept_validated_relocation(self, decoded, screen_offset):
        if decoded.frame is None or decoded.geometry is None:
            raise ValueError("cannot accept an invalid KT08 relocation")
        geometry = offset_geometry(decoded.geometry, *screen_offset)
        self.geometry = geometry
        return KT08TrackResult(
            decoded.frame.text, geometry, "relocated", decoded.frame.sequence, decoded.diagnostic
        )
