import unittest

from Bridge.kt08_protocol import (
    HEADER_SIZE,
    MAGIC,
    MAX_PAYLOAD,
    KT08ProtocolError,
    decode_frame,
    encode_frame,
    crc32,
)


class KT08ProtocolTests(unittest.TestCase):
    def test_crc32_ieee_known_vector(self):
        self.assertEqual(0xCBF43926, crc32(b"123456789"))

    def test_ascii_chinese_arbitrary_unicode_and_empty(self):
        for sequence, text in enumerate(("hello", "第一个翻译", "🙂 café Καλημέρα", "")):
            with self.subTest(text=text):
                frame = decode_frame(encode_frame(text, sequence))
                self.assertEqual(text, frame.text)
                self.assertEqual(sequence, frame.sequence)

    def test_maximum_payload(self):
        payload = b"x" * MAX_PAYLOAD
        self.assertEqual(payload, decode_frame(encode_frame(payload, 42)).payload)

    def test_sequence_wraparound_values(self):
        self.assertEqual(65535, decode_frame(encode_frame("last", 65535)).sequence)
        self.assertEqual(0, decode_frame(encode_frame("next", 0)).sequence)

    def test_invalid_magic_version_flags_and_length(self):
        cases = []
        raw = bytearray(encode_frame("x", 1)); raw[0] ^= 1; cases.append((raw, "magic"))
        raw = bytearray(encode_frame("x", 1)); raw[4] = 2; cases.append((raw, "version"))
        raw = bytearray(encode_frame("x", 1)); raw[5] = 1; cases.append((raw, "flags"))
        raw = bytearray(encode_frame("x", 1)); raw[8:10] = (181).to_bytes(2, "big"); cases.append((raw, "length"))
        for raw, stage in cases:
            with self.subTest(stage=stage), self.assertRaises(KT08ProtocolError) as raised:
                decode_frame(raw)
            self.assertEqual(stage, raised.exception.stage)

    def test_crc_rejects_one_bit_payload_corruption(self):
        raw = bytearray(encode_frame("payload", 8))
        raw[HEADER_SIZE] ^= 1
        with self.assertRaises(KT08ProtocolError) as raised:
            decode_frame(raw)
        self.assertEqual("crc", raised.exception.stage)

    def test_crc_rejects_balanced_corruption_legacy_sum_would_miss(self):
        raw = bytearray(encode_frame("balanced", 9))
        original_sum = sum(raw[HEADER_SIZE:HEADER_SIZE + 8]) & 0xFF
        raw[HEADER_SIZE] += 1
        raw[HEADER_SIZE + 1] -= 1
        self.assertEqual(original_sum, sum(raw[HEADER_SIZE:HEADER_SIZE + 8]) & 0xFF)
        with self.assertRaises(KT08ProtocolError) as raised:
            decode_frame(raw)
        self.assertEqual("crc", raised.exception.stage)

    def test_sequence_mismatch(self):
        raw = bytearray(encode_frame("sequence", 12))
        payload_end = HEADER_SIZE + len("sequence")
        raw[payload_end:payload_end + 2] = (13).to_bytes(2, "big")
        with self.assertRaises(KT08ProtocolError) as raised:
            decode_frame(raw)
        self.assertEqual("sequence", raised.exception.stage)

    def test_invalid_utf8_with_valid_crc(self):
        frame = encode_frame(b"\xff", 4)
        with self.assertRaises(KT08ProtocolError) as raised:
            decode_frame(frame)
        self.assertEqual("utf8", raised.exception.stage)


if __name__ == "__main__":
    unittest.main()
