"""Binary KT08 wire format and integrity validation."""
from dataclasses import dataclass
import struct
import zlib


MAGIC = b"KT08"
VERSION = 1
SUPPORTED_FLAGS = 0
MAX_PAYLOAD = 180
HEADER_SIZE = 10
TRAILER_SIZE = 6
MAX_FRAME_SIZE = HEADER_SIZE + MAX_PAYLOAD + TRAILER_SIZE


class KT08ProtocolError(ValueError):
    def __init__(self, stage, message, **details):
        super().__init__(message)
        self.stage = stage
        self.details = details


@dataclass(frozen=True)
class KT08Frame:
    sequence: int
    payload: bytes
    text: str
    flags: int = 0
    version: int = VERSION


def crc32(data):
    """CRC-32/IEEE: reflected 0xEDB88320, init/final XOR FFFFFFFF."""
    return zlib.crc32(data) & 0xFFFFFFFF


def encode_frame(payload, sequence, flags=0):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    payload = bytes(payload)
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("KT08 payload exceeds 180 bytes")
    if not 0 <= sequence <= 0xFFFF:
        raise ValueError("KT08 sequence must be an unsigned 16-bit integer")
    if flags != SUPPORTED_FLAGS:
        raise ValueError("unsupported KT08 flags")
    body = (
        MAGIC
        + bytes((VERSION, flags))
        + struct.pack(">HH", sequence, len(payload))
        + payload
        + struct.pack(">H", sequence)
    )
    return body + struct.pack(">I", crc32(body))


def decode_frame(data):
    data = bytes(data)
    if len(data) < HEADER_SIZE + TRAILER_SIZE:
        raise KT08ProtocolError("truncated", "KT08 frame is shorter than its fixed fields")
    if data[:4] != MAGIC:
        raise KT08ProtocolError("magic", "invalid KT08 magic", actual=data[:4])
    version, flags = data[4], data[5]
    if version != VERSION:
        raise KT08ProtocolError("version", "unsupported KT08 version", actual=version)
    if flags != SUPPORTED_FLAGS:
        raise KT08ProtocolError("flags", "unsupported KT08 flags", actual=flags)
    sequence_start, length = struct.unpack(">HH", data[6:10])
    if length > MAX_PAYLOAD:
        raise KT08ProtocolError("length", "illegal KT08 payload length", actual=length)
    expected_size = HEADER_SIZE + length + TRAILER_SIZE
    if len(data) < expected_size:
        raise KT08ProtocolError(
            "truncated", "KT08 payload is incomplete", expected=expected_size, actual=len(data)
        )
    if len(data) > expected_size:
        raise KT08ProtocolError(
            "length", "KT08 frame contains trailing bytes",
            expected=expected_size, actual=len(data),
        )
    frame = data[:expected_size]
    payload_end = HEADER_SIZE + length
    sequence_end = struct.unpack(">H", frame[payload_end:payload_end + 2])[0]
    expected_crc = struct.unpack(">I", frame[payload_end + 2:payload_end + 6])[0]
    actual_crc = crc32(frame[:payload_end + 2])
    if sequence_start != sequence_end:
        raise KT08ProtocolError(
            "sequence", "KT08 start/end sequence mismatch",
            sequence_start=sequence_start, sequence_end=sequence_end,
        )
    if expected_crc != actual_crc:
        raise KT08ProtocolError(
            "crc", "KT08 CRC mismatch", expected_crc=expected_crc, actual_crc=actual_crc,
        )
    payload = frame[HEADER_SIZE:payload_end]
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KT08ProtocolError("utf8", "KT08 payload is not valid UTF-8") from exc
    return KT08Frame(sequence_start, payload, text, flags, version)
