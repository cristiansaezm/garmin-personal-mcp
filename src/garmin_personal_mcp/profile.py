import datetime

from .garmin_api import in_windows, query

# Not documented in the Swagger reference; kept at the month other ranges use.
VO2MAX_MAX_DAYS = 31


def get_settings(client) -> dict | None:
    return client.get("/userprofile-service/userprofile/settings")


def get_heart_rate_zones(client, *, generate_defaults: bool = True) -> list | None:
    return client.get(
        "/biometric-service/heartRateZones/v2",
        params=query(generateDefaults=generate_defaults),
    )


def get_fitness_age(
    client, day: datetime.date, *, full_history_scan: bool = True
) -> list | None:
    return client.get(
        f"/fitnessage-service/fitnessage/v2/{day}",
        params=query(fullHistoryScan=full_history_scan),
    )


def get_vo2max(client, start: datetime.date, end: datetime.date) -> list:
    return in_windows(
        start,
        end,
        VO2MAX_MAX_DAYS,
        lambda first, last: client.get(
            f"/metrics-service/metrics/maxmet/daily/{first}/{last}"
        ),
    )
