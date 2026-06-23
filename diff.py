"""
Diff today's theme clusters against an older snapshot to detect what is NEW or
RISING vs DECLINING or SATURATED. Matching is by centroid cosine similarity.
"""

import numpy as np


def _cos(a, b) -> float:
    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def diff_clusters(today: list[dict], previous: list[dict], threshold: float) -> dict:
    """Return today/previous clusters tagged with a status.
    status in: new | rising | stable | declining | saturated | disappeared."""
    today_out, prev_matched = [], set()

    for t in today:
        best_i, best_sim = -1, 0.0
        for j, p in enumerate(previous):
            sim = _cos(t["centroid"], p["centroid"])
            if sim > best_sim:
                best_sim, best_i = sim, j

        if best_sim < threshold:
            status = "new"
        else:
            prev_matched.add(best_i)
            prev_size = previous[best_i].get("size", 0)
            if t["size"] > prev_size * 1.3:
                status = "rising"
            elif t["size"] < prev_size * 0.7:
                status = "declining"
            else:
                status = "stable"
            # many competitors crowding the same theme => saturated
            if t.get("competitor_count", 0) >= 5 and status in ("stable", "rising"):
                status = "saturated"

        today_out.append({
            "theme": t.get("theme", "?"),
            "size": t["size"],
            "competitor_count": t.get("competitor_count", 0),
            "status": status,
        })

    disappeared = [
        {"theme": p.get("theme", "?"), "size": p.get("size", 0), "status": "disappeared"}
        for j, p in enumerate(previous) if j not in prev_matched
    ]

    return {
        "today": today_out,
        "rising_or_new": [c for c in today_out if c["status"] in ("new", "rising")],
        "saturated": [c for c in today_out if c["status"] == "saturated"],
        "declining": [c for c in today_out if c["status"] == "declining"] + disappeared,
    }
