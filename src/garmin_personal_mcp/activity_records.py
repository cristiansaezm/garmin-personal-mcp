"""Second-by-second samples from a FIT file, and the statistics every
activity-analysis tool computes over a stretch of them."""

PAUSE_GAP_SECONDS = 10
PAUSE_SPEED = 0.5
ELEVATION_HYSTERESIS = 1.0
STEP_SPORTS = {1, 11, 17}  # running, walking, hiking: FIT stores strides/min


def pace(speed: float | None) -> str | None:
    if not speed:
        return None
    seconds = round(1000 / speed)
    return f"{seconds // 60}:{seconds % 60:02d}"


def duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    whole = round(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def counts_steps(fit: dict) -> bool:
    sessions = fit.get("sessions") or [{}]
    return sessions[0].get("sport", 1) in STEP_SPORTS


def samples(fit: dict) -> list[dict]:
    """Each record gains dt (moving seconds since the previous one), dd
    (meters since the previous one), elapsed (moving seconds since the start),
    and km. Auto-pause leaves a gap with no distance, which isn't moving time."""
    double = counts_steps(fit)
    result = []
    previous = None
    elapsed = 0.0
    for record in fit.get("records", []):
        if "timestamp" not in record:
            continue
        sample = dict(record)
        if "cadence" in sample:
            cadence = sample["cadence"] + sample.pop("fractional_cadence", 0)
            if double:
                cadence *= 2
            sample["cadence"] = cadence
        distance = sample.get("distance")
        if distance is None and previous is not None:
            distance = previous["distance"]
        sample["distance"] = distance or 0.0
        dt = 0.0
        dd = 0.0
        if previous is not None:
            gap = sample["timestamp"] - previous["timestamp"]
            dd = max(sample["distance"] - previous["distance"], 0.0)
            dt = gap
            if gap > PAUSE_GAP_SECONDS and dd / gap < PAUSE_SPEED:
                dt = 0.0
        elapsed += dt
        sample.update(dt=dt, dd=dd, elapsed=elapsed, km=sample["distance"] / 1000)
        result.append(sample)
        previous = sample
    return result


def between_km(rows: list[dict], from_km: float | None, to_km: float | None):
    return [
        row
        for row in rows
        if (from_km is None or row["km"] >= from_km)
        and (to_km is None or row["km"] <= to_km)
    ]


def by_distance(rows: list[dict], every_m: float) -> list[list[dict]]:
    """Splits samples into consecutive stretches of every_m meters; the last
    stretch holds whatever distance remains."""
    segments = []
    current = []
    boundary = every_m
    for row in rows:
        current.append(row)
        if row["distance"] >= boundary:
            segments.append(current)
            current = []
            while row["distance"] >= boundary:
                boundary += every_m
    if current and sum(row["dd"] for row in current) > 0:
        segments.append(current)
    return segments


def _weighted(rows: list[dict], field: str) -> float | None:
    total = 0.0
    weight = 0.0
    for row in rows:
        value = row.get(field)
        if value is None or not row["dt"]:
            continue
        total += value * row["dt"]
        weight += row["dt"]
    if not weight:
        return None
    return total / weight


def _elevation(rows: list[dict]) -> tuple[float, float]:
    gain = 0.0
    loss = 0.0
    reference = None
    for row in rows:
        altitude = row.get("altitude")
        if altitude is None:
            continue
        if reference is None:
            reference = altitude
            continue
        change = altitude - reference
        if change >= ELEVATION_HYSTERESIS:
            gain += change
            reference = altitude
        elif change <= -ELEVATION_HYSTERESIS:
            loss -= change
            reference = altitude
    return gain, loss


def _rounded(value: float | None, digits: int = 0):
    if value is None:
        return None
    if digits == 0:
        return round(value)
    return round(value, digits)


def stats(rows: list[dict]) -> dict:
    """Distance, moving time, pace, and time-weighted HR, power, and cadence
    for a stretch of samples."""
    distance = sum(row["dd"] for row in rows)
    seconds = sum(row["dt"] for row in rows)
    speed = None
    if seconds:
        speed = distance / seconds
    gain, loss = _elevation(rows)
    heart_rates = [row["heart_rate"] for row in rows if row.get("heart_rate")]
    return {
        "distance_km": round(distance / 1000, 3),
        "moving_time": duration(seconds),
        "moving_seconds": round(seconds),
        "pace_per_km": pace(speed),
        "avg_hr": _rounded(_weighted(rows, "heart_rate")),
        "max_hr": max(heart_rates, default=None),
        "avg_power": _rounded(_weighted(rows, "power")),
        "avg_cadence": _rounded(_weighted(rows, "cadence")),
        "elevation_gain_m": round(gain),
        "elevation_loss_m": round(loss),
    }
