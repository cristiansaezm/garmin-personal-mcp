from . import activities
from .activity_effort import effort_summary
from .activity_laps import intervals


def _identity(activity_id: int, detail: dict | None) -> dict:
    summary = (detail or {}).get("summaryDTO") or {}
    return {
        "activity_id": activity_id,
        "name": (detail or {}).get("activityName"),
        "start_local": summary.get("startTimeLocal"),
    }


def compare(client, activity_ids: list[int]) -> list[dict]:
    rows = []
    for activity_id in activity_ids:
        detail = activities.get_activity(client, activity_id)
        data = activities.load_fit(client, activity_id)
        row = {**_identity(activity_id, detail), **effort_summary(data)}
        work = intervals(data)
        row["intervals"] = None
        if work["method"] == "workout steps":
            row["intervals"] = work["summary"]
        rows.append(row)
    return rows


def matching_ids(client, filters: activities.ActivitySearch, limit: int) -> list[int]:
    found = activities.search_activities(client, filters, limit=limit, offset=0)
    return [row["activityId"] for row in found or [] if "activityId" in row]
