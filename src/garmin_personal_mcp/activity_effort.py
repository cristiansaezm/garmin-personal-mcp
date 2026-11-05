from .activity_records import between_km, samples, stats


def _halves(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    middle = (rows[0]["elapsed"] + rows[-1]["elapsed"]) / 2
    first = [row for row in rows if row["elapsed"] <= middle]
    second = [row for row in rows if row["elapsed"] > middle]
    return first, second


def _speed(summary: dict) -> float | None:
    if not summary["moving_seconds"]:
        return None
    return summary["distance_km"] * 1000 / summary["moving_seconds"]


def _decoupling(first: float | None, second: float | None) -> float | None:
    """Percent drop in output per heartbeat from the first half to the
    second; under about 5% reads as aerobically steady."""
    if not first or not second:
        return None
    return round((first - second) / first * 100, 1)


def _efficiency(output: float | None, heart_rate: float | None) -> float | None:
    if output is None or not heart_rate:
        return None
    return output / heart_rate


def drift(
    fit: dict,
    *,
    from_km: float | None = None,
    to_km: float | None = None,
    skip_minutes: float = 0,
) -> dict | None:
    rows = between_km(samples(fit), from_km, to_km)
    if rows:
        start = rows[0]["elapsed"] + skip_minutes * 60
        rows = [row for row in rows if row["elapsed"] >= start]
    if len(rows) < 2:
        return None
    halves = [stats(half) for half in _halves(rows)]
    speeds = [_speed(half) for half in halves]
    pace_ef = [_efficiency(s, h["avg_hr"]) for s, h in zip(speeds, halves, strict=True)]
    power_ef = [_efficiency(h["avg_power"], h["avg_hr"]) for h in halves]
    hr_change = None
    if halves[0]["avg_hr"] and halves[1]["avg_hr"]:
        hr_change = halves[1]["avg_hr"] - halves[0]["avg_hr"]
    quarters = []
    span = rows[-1]["elapsed"] - rows[0]["elapsed"]
    for n in range(4):
        low = rows[0]["elapsed"] + span * n / 4
        high = rows[0]["elapsed"] + span * (n + 1) / 4
        part = [row for row in rows if low <= row["elapsed"] <= high]
        summary = stats(part)
        quarters.append(
            {
                "quarter": n + 1,
                "pace_per_km": summary["pace_per_km"],
                "avg_hr": summary["avg_hr"],
                "avg_power": summary["avg_power"],
            }
        )
    return {
        "analyzed": stats(rows),
        "first_half": halves[0],
        "second_half": halves[1],
        "hr_change_bpm": hr_change,
        "pace_hr_decoupling_pct": _decoupling(*pace_ef),
        "power_hr_decoupling_pct": _decoupling(*power_ef),
        "by_quarter": quarters,
    }


def effort_summary(fit: dict) -> dict:
    rows = samples(fit)
    summary = stats(rows)
    efficiency = _efficiency(_speed(summary), summary["avg_hr"])
    result = dict(summary)
    result["meters_per_heartbeat"] = None
    if efficiency:
        result["meters_per_heartbeat"] = round(efficiency * 60, 2)
    analysis = drift(fit)
    if analysis:
        result["pace_hr_decoupling_pct"] = analysis["pace_hr_decoupling_pct"]
        result["power_hr_decoupling_pct"] = analysis["power_hr_decoupling_pct"]
    return result
