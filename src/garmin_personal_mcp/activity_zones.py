from . import activities, profile
from .activity_records import by_distance, samples, stats


def zone_index(value: float, floors: list[float]) -> int:
    """0 is below zone 1; zone n starts at floors[n-1]."""
    zone = 0
    for floor in floors:
        if value >= floor:
            zone += 1
    return zone


def _seconds_in_zones(segment: list[dict], field: str, floors: list[float]):
    if not floors:
        return None
    seconds = [0.0] * (len(floors) + 1)
    for row in segment:
        value = row.get(field)
        if value is None or not row["dt"]:
            continue
        seconds[zone_index(value, floors)] += row["dt"]
    if not any(seconds):
        return None
    return {f"zone_{zone}": round(total) for zone, total in enumerate(seconds)}


def zones_by_segment(
    fit: dict,
    segment_km: float,
    *,
    hr_floors: list[float],
    power_floors: list[float],
) -> list[dict]:
    result = []
    for segment in by_distance(samples(fit), segment_km * 1000):
        summary = stats(segment)
        result.append(
            {
                "from_km": round(segment[0]["km"] - segment[0]["dd"] / 1000, 2),
                "to_km": round(segment[-1]["km"], 2),
                "pace_per_km": summary["pace_per_km"],
                "avg_hr": summary["avg_hr"],
                "avg_power": summary["avg_power"],
                "hr_zone_seconds": _seconds_in_zones(segment, "heart_rate", hr_floors),
                "power_zone_seconds": _seconds_in_zones(segment, "power", power_floors),
            }
        )
    return result


def floors_from_fit(fit: dict, boundary_field: str) -> list[float]:
    """The device records each zone's upper bound; zone n+1 starts just above
    zone n's. The session's entry reflects the zones in force that day."""
    entries = fit.get("time_in_zone", [])
    session_entries = [e for e in entries if e.get("reference_mesg") == 18]
    for entry in session_entries + entries:
        bounds = entry.get(boundary_field)
        if isinstance(bounds, list) and len(bounds) > 1:
            return [bound + 1 for bound in bounds[:-1]]
    return []


def floors_from_garmin(zones: list | dict | None) -> list[float]:
    """Garmin's heart rate zones endpoint returns one entry per sport, each
    with zone1Floor..zone5Floor; running zones win over the default ones."""
    if isinstance(zones, dict):
        zones = zones.get("results") or [zones]
    entries = [entry for entry in zones or [] if isinstance(entry, dict)]
    entries.sort(key=lambda entry: entry.get("sport") != "RUNNING")
    for entry in entries:
        floors = [entry.get(f"zone{n}Floor") for n in range(1, 6)]
        if all(isinstance(floor, int | float) for floor in floors):
            return floors
    return []


def zones_report(
    client,
    activity_id: int,
    segment_km: float,
    *,
    hr_floors: list[float] | None = None,
    power_floors: list[float] | None = None,
) -> dict:
    data = activities.load_fit(client, activity_id)
    hr_source = "given"
    if not hr_floors:
        hr_floors = floors_from_fit(data, "hr_zone_high_boundary")
        hr_source = "activity file"
    if not hr_floors:
        hr_floors = floors_from_garmin(profile.get_heart_rate_zones(client))
        hr_source = "current Garmin settings"
    if not hr_floors:
        hr_source = None
    power_source = "given"
    if not power_floors:
        power_floors = floors_from_fit(data, "power_zone_high_boundary")
        power_source = "activity file"
    if not power_floors:
        power_source = None
    return {
        "hr_zone_floors": hr_floors or None,
        "hr_zones_from": hr_source,
        "power_zone_floors": power_floors or None,
        "power_zones_from": power_source,
        "segments": zones_by_segment(
            data, segment_km, hr_floors=hr_floors, power_floors=power_floors
        ),
    }
