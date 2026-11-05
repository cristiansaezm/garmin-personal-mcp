from .activity_records import between_km, pace, samples


def _average(bucket: list[dict], field: str) -> float | None:
    values = [row[field] for row in bucket if row.get(field) is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def timeseries(
    fit: dict,
    points: int = 300,
    *,
    from_km: float | None = None,
    to_km: float | None = None,
) -> list[dict]:
    """Averages the samples into at most `points` equal stretches of moving
    time so a long activity fits in a model's context."""
    rows = [row for row in between_km(samples(fit), from_km, to_km) if row["dt"]]
    if not rows:
        return []
    start = rows[0]["elapsed"] - rows[0]["dt"]
    span = rows[-1]["elapsed"] - start
    width = max(span / max(points, 1), 1.0)
    buckets: dict[int, list[dict]] = {}
    for row in rows:
        index = min(int((row["elapsed"] - start) / width), points - 1)
        buckets.setdefault(index, []).append(row)
    result = []
    for bucket in buckets.values():
        seconds = sum(row["dt"] for row in bucket)
        meters = sum(row["dd"] for row in bucket)
        speed = None
        if seconds:
            speed = meters / seconds
        result.append(
            {
                "moving_seconds": round(bucket[-1]["elapsed"]),
                "km": round(bucket[-1]["km"], 2),
                "pace_per_km": pace(speed),
                "heart_rate": _average(bucket, "heart_rate"),
                "power": _average(bucket, "power"),
                "cadence": _average(bucket, "cadence"),
                "altitude_m": _average(bucket, "altitude"),
            }
        )
    return result
