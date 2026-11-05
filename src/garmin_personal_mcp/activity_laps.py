from .activity_records import counts_steps, duration, pace

INTENSITY = {
    0: "active",
    1: "rest",
    2: "warmup",
    3: "cooldown",
    4: "recovery",
    5: "interval",
    6: "other",
}
TRIGGER = {
    0: "manual",
    1: "time",
    2: "distance",
    3: "position",
    4: "position",
    5: "position",
    6: "position",
    7: "session_end",
    8: "fitness_equipment",
}
WORK = {"active", "interval"}
RECOVERY = {"rest", "recovery"}
MIN_LAP_SECONDS = 20


def _cadence(lap: dict, double: bool) -> int | None:
    if "avg_cadence" not in lap:
        return None
    cadence = lap["avg_cadence"] + lap.get("avg_fractional_cadence", 0)
    if double:
        cadence *= 2
    return round(cadence)


def laps(fit: dict) -> list[dict]:
    double = counts_steps(fit)
    raw = fit.get("laps", [])
    if not raw:
        return []
    start = raw[0].get("start_time")
    result = []
    for number, lap in enumerate(raw, start=1):
        offset = None
        if start is not None and "start_time" in lap:
            offset = lap["start_time"] - start
        result.append(
            {
                "lap": number,
                "starts_at": duration(offset),
                "distance_km": round(lap.get("total_distance", 0) / 1000, 3),
                "time": duration(lap.get("total_timer_time")),
                "seconds": round(lap.get("total_timer_time", 0)),
                "pace_per_km": pace(lap.get("avg_speed")),
                "avg_hr": lap.get("avg_heart_rate"),
                "max_hr": lap.get("max_heart_rate"),
                "avg_power": lap.get("avg_power"),
                "max_power": lap.get("max_power"),
                "avg_cadence": _cadence(lap, double),
                "elevation_gain_m": lap.get("total_ascent"),
                "elevation_loss_m": lap.get("total_descent"),
                "intensity": INTENSITY.get(lap.get("intensity")),
                "trigger": TRIGGER.get(lap.get("lap_trigger")),
                "workout_step": lap.get("wkt_step_index"),
            }
        )
    return result


def _speed(lap: dict) -> float:
    if not lap["seconds"]:
        return 0.0
    return lap["distance_km"] * 1000 / lap["seconds"]


def classify(rows: list[dict]) -> tuple[list[dict], list[dict], str]:
    """A structured workout labels each lap's intensity. A free run doesn't,
    so the faster laps are taken as the work."""
    structured = any(
        row["intensity"] not in WORK and row["intensity"] is not None for row in rows
    )
    if structured:
        work = [row for row in rows if row["intensity"] in WORK]
        rest = [row for row in rows if row["intensity"] in RECOVERY]
        return work, rest, "workout steps"
    long_laps = [row for row in rows if row["seconds"] >= MIN_LAP_SECONDS]
    if len(long_laps) < 2:
        return long_laps, [], "single effort"
    speeds = [_speed(row) for row in long_laps]
    threshold = (max(speeds) + min(speeds)) / 2
    work = [row for row in long_laps if _speed(row) >= threshold]
    rest = [row for row in long_laps if _speed(row) < threshold]
    return work, rest, "pace"


def _average(rows: list[dict], field: str) -> float | None:
    values = [row[field] for row in rows if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values))


def intervals(fit: dict) -> dict:
    rows = laps(fit)
    work, rest, method = classify(rows)
    if not work:
        return {"method": method, "repetitions": [], "summary": None}
    by_speed = sorted(work, key=_speed, reverse=True)
    total_m = sum(row["distance_km"] for row in work) * 1000
    total_s = sum(row["seconds"] for row in work)
    first, last = work[0], work[-1]
    fade = None
    if _speed(first) and _speed(last):
        fade = round(1000 / _speed(last) - 1000 / _speed(first))
    summary = {
        "count": len(work),
        "work_distance_km": round(total_m / 1000, 2),
        "work_time": duration(total_s),
        "avg_pace_per_km": None,
        "avg_hr": _average(work, "avg_hr"),
        "avg_power": _average(work, "avg_power"),
        "fastest": {"lap": by_speed[0]["lap"], "pace": by_speed[0]["pace_per_km"]},
        "slowest": {"lap": by_speed[-1]["lap"], "pace": by_speed[-1]["pace_per_km"]},
        "first_to_last_pace_change_s_per_km": fade,
        "first_to_last_hr_change": None,
        "recovery_avg_hr": _average(rest, "avg_hr"),
    }
    if total_s:
        summary["avg_pace_per_km"] = pace(total_m / total_s)
    if first["avg_hr"] and last["avg_hr"]:
        summary["first_to_last_hr_change"] = last["avg_hr"] - first["avg_hr"]
    return {"method": method, "repetitions": work, "summary": summary}
