import datetime

import pytest
from conftest import FakeClient
from fitfile import FitWriter, lap, record, session, steady_run, zipped
from garmin_personal_api import GarminPersonalApiError

from garmin_personal_mcp import (
    activities,
    activity_compare,
    activity_effort,
    activity_laps,
    activity_splits,
    activity_timeseries,
    activity_zones,
    fit,
    training_weeks,
)


def decoded(writer):
    return fit.decode(writer.bytes())


def interval_session():
    """Warmup, then 3 x (60 s at 4 m/s, 30 s easy at 2 m/s), then cooldown."""
    writer = FitWriter()
    session(writer)
    lap(writer, start=0, seconds=300, distance_m=750, heart_rate=130, intensity=2)
    clock = 300
    for rep in range(3):
        lap(writer, start=clock, seconds=60, distance_m=240, heart_rate=165 + rep)
        lap(
            writer,
            start=clock + 60,
            seconds=30,
            distance_m=60,
            heart_rate=140,
            intensity=4,
        )
        clock += 90
    lap(writer, start=clock, seconds=300, distance_m=750, heart_rate=135, intensity=3)
    return writer


def test_splits_cover_the_run_in_even_kilometers_plus_the_remainder():
    rows = activity_splits.splits(decoded(steady_run(km=2.5)))
    assert [row["split"] for row in rows] == [1, 2, 3]
    assert rows[0]["pace_per_km"] == "5:33"
    assert rows[0]["distance_km"] == pytest.approx(1.0, abs=0.01)
    assert rows[-1]["distance_km"] == pytest.approx(0.5, abs=0.01)
    assert rows[0]["avg_cadence"] == 180


def test_splits_can_cover_only_a_stretch():
    rows = activity_splits.splits(decoded(steady_run(km=5)), from_km=2, to_km=4)
    assert rows[0]["from_km"] == pytest.approx(2.0, abs=0.01)
    assert rows[-1]["to_km"] == pytest.approx(4.0, abs=0.01)


def test_auto_pause_gaps_are_not_moving_time():
    writer = FitWriter()
    session(writer)
    record(writer, second=0, distance_m=0, heart_rate=140)
    record(writer, second=1, distance_m=3, heart_rate=140)
    record(writer, second=120, distance_m=3, heart_rate=120)
    record(writer, second=121, distance_m=6, heart_rate=140)
    rows = activity_splits.splits(decoded(writer))
    assert rows[0]["moving_seconds"] == 2


def test_timeseries_is_reduced_to_the_requested_points():
    rows = activity_timeseries.timeseries(decoded(steady_run(km=5)), 50)
    assert 45 <= len(rows) <= 50
    assert rows[-1]["km"] == pytest.approx(5.0, abs=0.01)
    assert rows[0]["pace_per_km"] == "5:33"


def test_drift_reports_hr_rise_and_decoupling():
    result = activity_effort.drift(decoded(steady_run(start_hr=140, end_hr=160)))
    assert result["hr_change_bpm"] == 10
    assert result["pace_hr_decoupling_pct"] > 5
    assert len(result["by_quarter"]) == 4


def test_steady_hr_shows_no_decoupling():
    result = activity_effort.drift(decoded(steady_run(start_hr=150, end_hr=150)))
    assert result["pace_hr_decoupling_pct"] == 0


def test_laps_read_intensity_pace_and_step_cadence():
    rows = activity_laps.laps(decoded(interval_session()))
    assert rows[0]["intensity"] == "warmup"
    assert rows[1]["pace_per_km"] == "4:10"
    assert rows[1]["avg_cadence"] == 180
    assert rows[1]["starts_at"] == "5:00"


def test_intervals_use_workout_steps_when_present():
    result = activity_laps.intervals(decoded(interval_session()))
    assert result["method"] == "workout steps"
    assert result["summary"]["count"] == 3
    assert result["summary"]["first_to_last_hr_change"] == 2
    assert result["summary"]["recovery_avg_hr"] == 140


def test_intervals_fall_back_to_pace_without_workout_steps():
    writer = FitWriter()
    session(writer)
    for n, speed in enumerate([4, 2, 4, 2]):
        lap(writer, start=n * 60, seconds=60, distance_m=speed * 60, heart_rate=150)
    result = activity_laps.intervals(decoded(writer))
    assert result["method"] == "pace"
    assert result["summary"]["count"] == 2


def test_zone_floors_come_from_the_activity_file():
    writer = steady_run(km=1)
    writer.message(216, [(0, 0x84, 18), (6, 0x02, [119, 139, 154, 167, 177, 190])])
    floors = activity_zones.floors_from_fit(decoded(writer), "hr_zone_high_boundary")
    assert floors == [120, 140, 155, 168, 178]


def test_zone_floors_prefer_running_zones_from_garmin():
    zones = [
        {"sport": "DEFAULT", **{f"zone{n}Floor": n for n in range(1, 6)}},
        {"sport": "RUNNING", **{f"zone{n}Floor": n * 10 for n in range(1, 6)}},
    ]
    assert activity_zones.floors_from_garmin(zones) == [10, 20, 30, 40, 50]


def test_zones_by_segment_counts_seconds_per_zone():
    rows = activity_zones.zones_by_segment(
        decoded(steady_run(km=2, start_hr=140, end_hr=160)),
        1,
        hr_floors=[150],
        power_floors=[],
    )
    first, second = rows[0]["hr_zone_seconds"], rows[1]["hr_zone_seconds"]
    assert first["zone_0"] > 300 > first["zone_1"]
    assert second["zone_1"] > 300 > second["zone_0"]
    assert rows[0]["power_zone_seconds"] is None


def test_zones_report_falls_back_to_garmin_settings():
    client = FakeClient(
        {
            "heartRateZones": [
                {
                    "sport": "RUNNING",
                    "zone1Floor": 120,
                    "zone2Floor": 140,
                    "zone3Floor": 155,
                    "zone4Floor": 168,
                    "zone5Floor": 178,
                }
            ]
        }
    )
    client.downloads[7] = zipped(steady_run(km=1).bytes())
    report = activity_zones.zones_report(client, 7, 5)
    assert report["hr_zones_from"] == "current Garmin settings"
    assert report["power_zones_from"] is None


def test_load_fit_explains_a_file_without_fit_inside(client):
    client.downloads[7] = zipped(b"<gpx/>", name="1.gpx")
    with pytest.raises(GarminPersonalApiError, match="no .fit inside"):
        activities.load_fit(client, 7)


def test_compare_summarizes_each_activity():
    client = FakeClient(
        {
            "/activity-service/activity/": {
                "activityName": "Tempo",
                "summaryDTO": {"startTimeLocal": "x"},
            }
        }
    )
    client.downloads[1] = zipped(interval_session().bytes())
    client.downloads[2] = zipped(steady_run(km=1).bytes())
    rows = activity_compare.compare(client, [1, 2])
    assert rows[0]["name"] == "Tempo"
    assert rows[0]["intervals"]["count"] == 3
    assert rows[1]["intervals"] is None
    assert rows[1]["meters_per_heartbeat"] > 0


def test_training_weeks_totals_by_monday_including_empty_weeks():
    activities_list = [
        {
            "startTimeLocal": "2026-11-02 19:16:55",
            "distance": 8000.0,
            "duration": 2900.0,
            "activityTrainingLoad": 70.0,
            "elevationGain": 120.0,
        },
        {
            "startTimeLocal": "2026-11-05 12:30:16",
            "distance": 18000.0,
            "duration": 6000.0,
            "activityTrainingLoad": 170.0,
        },
    ]
    weeks = training_weeks.training_weeks(
        activities_list, datetime.date(2026, 10, 26), datetime.date(2026, 11, 8)
    )
    assert [w["week_start"] for w in weeks] == ["2026-10-26", "2026-11-02"]
    assert weeks[0]["activities"] == 0
    assert weeks[1]["distance_km"] == 26.0
    assert weeks[1]["longest_km"] == 18.0
    assert weeks[1]["training_load"] == 240


def test_search_all_pages_until_a_short_page():
    pages = {0: [{"activityId": n} for n in range(100)], 100: [{"activityId": 1}]}
    client = FakeClient(
        {"search/activities": lambda path, params: pages[params["start"]]}
    )
    rows = activities.search_all(client, activities.ActivitySearch())
    assert len(rows) == 101
