import datetime

from .activity_records import duration, pace


def _week_start(day: datetime.date) -> datetime.date:
    return day - datetime.timedelta(days=day.weekday())


def _empty_week(monday: datetime.date) -> dict:
    return {
        "week_start": monday.isoformat(),
        "activities": 0,
        "distance_m": 0.0,
        "seconds": 0.0,
        "training_load": 0.0,
        "elevation_gain_m": 0.0,
        "longest_m": 0.0,
    }


def _finish(week: dict) -> dict:
    speed = None
    if week["seconds"]:
        speed = week["distance_m"] / week["seconds"]
    return {
        "week_start": week["week_start"],
        "activities": week["activities"],
        "distance_km": round(week["distance_m"] / 1000, 1),
        "time": duration(week["seconds"]),
        "avg_pace_per_km": pace(speed),
        "training_load": round(week["training_load"]),
        "elevation_gain_m": round(week["elevation_gain_m"]),
        "longest_km": round(week["longest_m"] / 1000, 1),
    }


def training_weeks(
    activities: list[dict], start: datetime.date, end: datetime.date
) -> list[dict]:
    """Monday-to-Sunday totals for every week the range touches, including
    weeks with nothing recorded."""
    weeks = {}
    monday = _week_start(start)
    while monday <= end:
        weeks[monday] = _empty_week(monday)
        monday += datetime.timedelta(days=7)
    for activity in activities:
        local = activity.get("startTimeLocal")
        if not local:
            continue
        day = datetime.date.fromisoformat(local[:10])
        week = weeks.get(_week_start(day))
        if week is None:
            continue
        distance = activity.get("distance") or 0.0
        week["activities"] += 1
        week["distance_m"] += distance
        week["seconds"] += activity.get("duration") or 0.0
        week["training_load"] += activity.get("activityTrainingLoad") or 0.0
        week["elevation_gain_m"] += activity.get("elevationGain") or 0.0
        week["longest_m"] = max(week["longest_m"], distance)
    return [_finish(week) for week in weeks.values()]
