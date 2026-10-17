import unittest

from src.integrity_sync import extract_step_timing


def _field(field_number, payload):
    return bytes([(field_number << 3) | 2]) + _varint(len(payload)) + payload


def _timestamp(seconds, nanos=0):
    payload = bytes([1 << 3]) + _varint(seconds)
    if nanos:
        payload += bytes([2 << 3]) + _varint(nanos)
    return payload


def _varint(value):
    encoded = bytearray()
    while True:
        current = value & 0x7F
        value >>= 7
        encoded.append(current | (0x80 if value else 0))
        if not value:
            return bytes(encoded)


class IntegrityStepTimingTests(unittest.TestCase):
    def test_extracts_completed_step_duration(self):
        metadata = _field(6, _timestamp(100, 250_000_000)) + _field(
            8,
            _timestamp(136, 750_000_000),
        )

        self.assertEqual(
            extract_step_timing(metadata, 3),
            {
                "started_at": 100.25,
                "finished_at": 136.75,
                "duration_ms": 36_500,
            },
        )

    def test_running_step_does_not_publish_a_finished_duration(self):
        metadata = _field(6, _timestamp(100)) + _field(8, _timestamp(136))

        self.assertEqual(extract_step_timing(metadata, 2), {"started_at": 100.0})


if __name__ == "__main__":
    unittest.main()
