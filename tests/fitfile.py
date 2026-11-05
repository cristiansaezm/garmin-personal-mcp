"""Builds small synthetic FIT files for the analysis tests."""

import io
import struct
import zipfile

FIT_EPOCH_OFFSET = 631065600
CODES = {0x00: "B", 0x02: "B", 0x84: "H", 0x85: "i", 0x86: "I"}


class FitWriter:
    def __init__(self):
        self.body = bytearray()
        self.local = {}

    def message(self, global_num: int, fields: list[tuple[int, int, object]]):
        """fields: (field number, base type, raw value); a list value is an
        array field."""
        local = self.define(global_num, fields)
        self.body += bytes([local])
        for _, base, value in fields:
            values = value if isinstance(value, list) else [value]
            self.body += struct.pack(f"<{len(values)}{CODES[base]}", *values)

    def define(self, global_num: int, fields: list[tuple[int, int, object]]) -> int:
        key = (global_num, tuple((num, base, _count(v)) for num, base, v in fields))
        if key not in self.local:
            local = len(self.local) % 16
            self.local[key] = local
            self.body += bytes([0x40 | local, 0, 0])
            self.body += struct.pack("<HB", global_num, len(fields))
            for num, base, value in fields:
                size = struct.calcsize(CODES[base]) * _count(value)
                self.body += bytes([num, size, base])
        return self.local[key]

    def compressed(self, local: int, offset: int, values: list[tuple[int, object]]):
        self.body += bytes([0x80 | (local << 5) | offset])
        for base, value in values:
            self.body += struct.pack(f"<{CODES[base]}", value)

    def bytes(self) -> bytes:
        header = struct.pack("<BBHI4sH", 14, 0x20, 2132, len(self.body), b".FIT", 0)
        return header + bytes(self.body) + b"\x00\x00"


def _count(value) -> int:
    if isinstance(value, list):
        return len(value)
    return 1


def fit_time(unix: int) -> int:
    return unix - FIT_EPOCH_OFFSET


START = 1791112273  # 2026-10-04 11:11:13 UTC


def record(writer, *, second, distance_m, heart_rate, power=300, cadence=90):
    writer.message(
        20,
        [
            (253, 0x86, fit_time(START + second)),
            (5, 0x86, round(distance_m * 100)),
            (73, 0x86, 3000),
            (78, 0x86, round((10 + 500) * 5)),
            (3, 0x02, heart_rate),
            (4, 0x02, cadence),
            (7, 0x84, power),
        ],
    )


def lap(writer, *, start, seconds, distance_m, heart_rate, intensity=0, power=300):
    writer.message(
        19,
        [
            (2, 0x86, fit_time(START + start)),
            (8, 0x86, seconds * 1000),
            (7, 0x86, seconds * 1000),
            (9, 0x86, round(distance_m * 100)),
            (110, 0x86, round(distance_m / seconds * 1000)),
            (15, 0x02, heart_rate),
            (16, 0x02, heart_rate + 5),
            (17, 0x02, 90),
            (19, 0x84, power),
            (23, 0x00, intensity),
            (24, 0x00, 2),
        ],
    )


def session(writer, sport=1):
    writer.message(18, [(2, 0x86, fit_time(START)), (5, 0x00, sport)])


def steady_run(*, km=10, start_hr=140, end_hr=160, speed=3.0):
    """A run at constant speed whose HR climbs linearly, one sample a second."""
    writer = FitWriter()
    session(writer)
    seconds = round(km * 1000 / speed)
    for second in range(seconds + 1):
        heart_rate = round(start_hr + (end_hr - start_hr) * second / seconds)
        record(writer, second=second, distance_m=second * speed, heart_rate=heart_rate)
    return writer


def zipped(data: bytes, name="1_ACTIVITY.fit") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, data)
    return buffer.getvalue()
