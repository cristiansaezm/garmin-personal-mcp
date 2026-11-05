from .activity_records import between_km, by_distance, samples, stats


def splits(
    fit: dict,
    every_m: float = 1000,
    *,
    from_km: float | None = None,
    to_km: float | None = None,
) -> list[dict]:
    rows = between_km(samples(fit), from_km, to_km)
    result = []
    for number, segment in enumerate(by_distance(rows, every_m), start=1):
        result.append(
            {
                "split": number,
                "from_km": round(segment[0]["km"] - segment[0]["dd"] / 1000, 2),
                "to_km": round(segment[-1]["km"], 2),
                **stats(segment),
            }
        )
    return result
