"""A small FIT decoder for the messages the activity-analysis tools need.

Garmin's original activity file is a FIT file. This reads its records
(second-by-second samples), laps, sessions, and time-in-zone messages, applies
the FIT profile's scale and offset, and drops invalid values. Everything else
in the file is skipped. It has no dependencies so the server stays light.
"""

import struct

FIT_EPOCH_OFFSET = 631065600  # seconds between 1970-01-01 and 1989-12-31 (UTC)
SEMICIRCLE_TO_DEGREES = 180 / 2**31

# base type number -> (struct code, size, invalid value)
BASE_TYPES = {
    0x00: ("B", 1, 0xFF),  # enum
    0x01: ("b", 1, 0x7F),  # sint8
    0x02: ("B", 1, 0xFF),  # uint8
    0x03: ("h", 2, 0x7FFF),  # sint16
    0x04: ("H", 2, 0xFFFF),  # uint16
    0x05: ("i", 4, 0x7FFFFFFF),  # sint32
    0x06: ("I", 4, 0xFFFFFFFF),  # uint32
    0x07: (None, 1, None),  # string
    0x08: ("f", 4, None),  # float32
    0x09: ("d", 8, None),  # float64
    0x0A: ("B", 1, 0x00),  # uint8z
    0x0B: ("H", 2, 0x0000),  # uint16z
    0x0C: ("I", 4, 0x00000000),  # uint32z
    0x0D: (None, 1, None),  # byte
    0x0E: ("q", 8, 0x7FFFFFFFFFFFFFFF),  # sint64
    0x0F: ("Q", 8, 0xFFFFFFFFFFFFFFFF),  # uint64
    0x10: ("Q", 8, 0),  # uint64z
}

RECORD, LAP, SESSION, TIME_IN_ZONE = 20, 19, 18, 216
TIMESTAMP_FIELD = 253

# global message number -> {field number: (name, scale, offset)}
PROFILE = {
    RECORD: {
        253: ("timestamp", 1, 0),
        0: ("position_lat", 1, 0),
        1: ("position_long", 1, 0),
        2: ("altitude", 5, 500),
        3: ("heart_rate", 1, 0),
        4: ("cadence", 1, 0),
        5: ("distance", 100, 0),
        6: ("speed", 1000, 0),
        7: ("power", 1, 0),
        41: ("stance_time", 10, 0),
        53: ("fractional_cadence", 128, 0),
        73: ("enhanced_speed", 1000, 0),
        78: ("enhanced_altitude", 5, 500),
    },
    LAP: {
        254: ("message_index", 1, 0),
        253: ("timestamp", 1, 0),
        2: ("start_time", 1, 0),
        7: ("total_elapsed_time", 1000, 0),
        8: ("total_timer_time", 1000, 0),
        9: ("total_distance", 100, 0),
        11: ("total_calories", 1, 0),
        13: ("avg_speed", 1000, 0),
        14: ("max_speed", 1000, 0),
        15: ("avg_heart_rate", 1, 0),
        16: ("max_heart_rate", 1, 0),
        17: ("avg_cadence", 1, 0),
        19: ("avg_power", 1, 0),
        20: ("max_power", 1, 0),
        21: ("total_ascent", 1, 0),
        22: ("total_descent", 1, 0),
        23: ("intensity", 1, 0),
        24: ("lap_trigger", 1, 0),
        71: ("wkt_step_index", 1, 0),
        80: ("avg_fractional_cadence", 128, 0),
        110: ("enhanced_avg_speed", 1000, 0),
        111: ("enhanced_max_speed", 1000, 0),
    },
    SESSION: {
        253: ("timestamp", 1, 0),
        2: ("start_time", 1, 0),
        5: ("sport", 1, 0),
        6: ("sub_sport", 1, 0),
        7: ("total_elapsed_time", 1000, 0),
        8: ("total_timer_time", 1000, 0),
        9: ("total_distance", 100, 0),
        16: ("avg_heart_rate", 1, 0),
        17: ("max_heart_rate", 1, 0),
        20: ("avg_power", 1, 0),
        22: ("total_ascent", 1, 0),
        23: ("total_descent", 1, 0),
    },
    TIME_IN_ZONE: {
        0: ("reference_mesg", 1, 0),
        1: ("reference_index", 1, 0),
        2: ("time_in_hr_zone", 1000, 0),
        5: ("time_in_power_zone", 1000, 0),
        6: ("hr_zone_high_boundary", 1, 0),
        9: ("power_zone_high_boundary", 1, 0),
        11: ("max_heart_rate", 1, 0),
        13: ("threshold_heart_rate", 1, 0),
        15: ("functional_threshold_power", 1, 0),
    },
}

COLLECTIONS = {
    RECORD: "records",
    LAP: "laps",
    SESSION: "sessions",
    TIME_IN_ZONE: "time_in_zone",
}


class FitError(ValueError):
    pass


def _endian(little: bool) -> str:
    if little:
        return "<"
    return ">"


def _valid(value, invalid):
    if invalid is None and value != value:  # NaN never equals itself
        return None
    if invalid is not None and value == invalid:
        return None
    return value


def _value(raw: bytes, base_type: int, little: bool):
    code, size, invalid = BASE_TYPES.get(base_type & 0x1F, (None, 1, None))
    if code is None or len(raw) < size:
        return None
    count = len(raw) // size
    raw_values = struct.unpack(f"{_endian(little)}{count}{code}", raw[: count * size])
    values = [_valid(v, invalid) for v in raw_values]
    if count == 1:
        return values[0]
    cleaned = [v for v in values if v is not None]
    return cleaned or None


def _scaled(value, scale, offset):
    if value is None:
        return None
    if isinstance(value, list):
        return [_scaled(v, scale, offset) for v in value]
    if scale == 1 and offset == 0:
        return value
    return value / scale - offset


def _finish_record(fields: dict) -> dict:
    if "enhanced_speed" in fields:
        fields["speed"] = fields.pop("enhanced_speed")
    if "enhanced_altitude" in fields:
        fields["altitude"] = fields.pop("enhanced_altitude")
    for name in ("position_lat", "position_long"):
        if name in fields:
            fields[name] = fields[name] * SEMICIRCLE_TO_DEGREES
    return fields


def _finish_lap(fields: dict) -> dict:
    if "enhanced_avg_speed" in fields:
        fields["avg_speed"] = fields.pop("enhanced_avg_speed")
    if "enhanced_max_speed" in fields:
        fields["max_speed"] = fields.pop("enhanced_max_speed")
    return fields


def decode(data: bytes) -> dict:
    """Returns {"records": [...], "laps": [...], "sessions": [...],
    "time_in_zone": [...]}, each a list of dicts keyed by field name.
    Timestamps are Unix seconds."""
    result = {name: [] for name in COLLECTIONS.values()}
    position = 0
    files = 0
    while len(data) - position >= 12:
        header_size = data[position]
        if header_size < 12 or data[position + 8 : position + 12] != b".FIT":
            if files:
                break
            raise FitError("this isn't a FIT file (no .FIT signature)")
        data_size = struct.unpack("<I", data[position + 4 : position + 8])[0]
        start = position + header_size
        end = start + data_size
        if end > len(data):
            raise FitError("the FIT file is truncated")
        _decode_messages(data, start, end, result)
        files += 1
        position = end + 2  # file CRC
    if not files:
        raise FitError("this isn't a FIT file")
    return result


def _read_definition(data: bytes, position: int, has_developer: bool):
    little = data[position + 1] == 0
    global_num = struct.unpack(
        f"{_endian(little)}H", data[position + 2 : position + 4]
    )[0]
    field_count = data[position + 4]
    position += 5
    fields = []
    for _ in range(field_count):
        num, size, base = data[position : position + 3]
        fields.append((num, size, base))
        position += 3
    developer_size = 0
    if has_developer:
        dev_count = data[position]
        position += 1
        for _ in range(dev_count):
            developer_size += data[position + 1]
            position += 3
    return (global_num, little, fields, developer_size), position


def _read_fields(data: bytes, position: int, definition):
    """Returns the profiled fields, the raw timestamp if present, and the new
    position."""
    global_num, little, fields, developer_size = definition
    profile = PROFILE.get(global_num, {})
    values = {}
    timestamp = None
    for num, size, base in fields:
        raw = data[position : position + size]
        position += size
        if num == TIMESTAMP_FIELD:
            timestamp = _value(raw, base, little)
        if num not in profile:
            continue
        name, scale, offset = profile[num]
        value = _scaled(_value(raw, base, little), scale, offset)
        if value is not None:
            values[name] = value
    return values, timestamp, position + developer_size


def _compressed_timestamp(last_timestamp: int | None, offset: int) -> int | None:
    if last_timestamp is None:
        return None
    timestamp = (last_timestamp & ~0x1F) + offset
    if offset < (last_timestamp & 0x1F):
        timestamp += 0x20
    return timestamp


def _store(global_num: int, values: dict, result: dict) -> None:
    for name in ("timestamp", "start_time"):
        if name in values:
            values[name] = values[name] + FIT_EPOCH_OFFSET
    if global_num == RECORD:
        values = _finish_record(values)
    elif global_num == LAP:
        values = _finish_lap(values)
    result[COLLECTIONS[global_num]].append(values)


def _decode_messages(data: bytes, position: int, end: int, result: dict) -> None:
    definitions = {}
    last_timestamp = None
    while position < end:
        header = data[position]
        position += 1
        compressed = None
        if header & 0x80:
            local = (header >> 5) & 0x03
            compressed = _compressed_timestamp(last_timestamp, header & 0x1F)
        else:
            local = header & 0x0F
            if header & 0x40:
                definitions[local], position = _read_definition(
                    data, position, bool(header & 0x20)
                )
                continue
        if local not in definitions:
            raise FitError("the FIT file uses a message before defining it")
        definition = definitions[local]
        values, timestamp, position = _read_fields(data, position, definition)
        if timestamp is not None:
            last_timestamp = timestamp
        if compressed is not None and "timestamp" not in values:
            values["timestamp"] = compressed
            last_timestamp = compressed
        if definition[0] in COLLECTIONS:
            _store(definition[0], values, result)
