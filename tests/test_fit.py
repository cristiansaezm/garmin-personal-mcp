import pytest
from fitfile import START, FitWriter, fit_time, record, session, steady_run

from garmin_personal_mcp import fit


def test_records_are_scaled_and_timestamped_in_unix_seconds():
    decoded = fit.decode(steady_run(km=0.003).bytes())
    first = decoded["records"][0]
    assert first["timestamp"] == START
    assert first["speed"] == 3.0
    assert first["altitude"] == 10.0
    assert first["heart_rate"] == 140
    assert decoded["sessions"] == [{"start_time": START, "sport": 1}]


def test_invalid_values_are_dropped():
    writer = FitWriter()
    record(writer, second=0, distance_m=0, heart_rate=0xFF, power=0xFFFF)
    decoded = fit.decode(writer.bytes())
    assert "heart_rate" not in decoded["records"][0]
    assert "power" not in decoded["records"][0]


def test_compressed_timestamps_continue_from_the_last_full_one():
    writer = FitWriter()
    session(writer)
    record(writer, second=0, distance_m=0, heart_rate=150)
    fields = [(5, 0x86, 900), (3, 0x02, 151)]
    local = writer.define(20, fields)
    offset = (fit_time(START) + 3) & 0x1F
    writer.compressed(local, offset, [(0x86, 900), (0x02, 151)])
    decoded = fit.decode(writer.bytes())
    assert decoded["records"][1]["timestamp"] == START + 3
    assert decoded["records"][1]["distance"] == 9.0
    assert decoded["records"][1]["heart_rate"] == 151


def test_array_fields_decode_as_lists():
    writer = FitWriter()
    writer.message(
        216,
        [(0, 0x84, 18), (6, 0x02, [119, 139, 154, 167, 177, 190])],
    )
    zone = fit.decode(writer.bytes())["time_in_zone"][0]
    assert zone["hr_zone_high_boundary"] == [119, 139, 154, 167, 177, 190]


def test_rejects_a_file_that_is_not_fit():
    with pytest.raises(fit.FitError, match="isn't a FIT file"):
        fit.decode(b"<gpx>not a fit file at all</gpx>")
