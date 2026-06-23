"""
MENA commercial / cultural calendar.

The Scout must never recommend generic angles during a major season. We inject
the next upcoming events as structured data on every run (don't rely on the LLM
to "know" where Ramadan is this year).

NOTE: Islamic dates depend on moon sighting and vary slightly by country.
The dates below are approximate — verify/refresh once a year.
"""

from datetime import date

# (name, gregorian_date, suggested_angle_bias)
EVENTS = [
    ("رمضان", date(2026, 2, 18), "هدايا، لمّة العيلة، سحور/فطار، روتين رمضان"),
    ("عيد الفطر", date(2026, 3, 20), "هدايا العيد، عروض، تجديد"),
    ("عيد الأضحى", date(2026, 5, 27), "هدايا، تجمّعات، عروض"),
    ("العودة للمدارس", date(2026, 9, 1), "تجهيز، تنظيم، عروض الطلبة"),
    ("اليوم الوطني السعودي", date(2026, 9, 23), "فخر وطني، عروض خاصة KSA"),
    ("الجمعة البيضاء", date(2026, 11, 27), "أكبر موسم خصومات، عجلة/ندرة"),
    ("اليوم الوطني الإماراتي", date(2026, 12, 2), "فخر وطني، عروض خاصة UAE"),
    ("رمضان", date(2027, 2, 8), "هدايا، لمّة العيلة، سحور/فطار"),
    ("عيد الفطر", date(2027, 3, 10), "هدايا العيد، عروض، تجديد"),
]


def upcoming_events(window_days: int, today: date | None = None) -> list[dict]:
    """Events starting within `window_days` from today (the seasonal bias window)."""
    today = today or date.today()
    out = []
    for name, when, bias in EVENTS:
        days = (when - today).days
        if 0 <= days <= window_days:
            out.append({"event": name, "date": when.isoformat(),
                        "days_away": days, "angle_bias": bias})
    return sorted(out, key=lambda e: e["days_away"])


def next_event(today: date | None = None) -> dict | None:
    """The single next event regardless of window (for context)."""
    today = today or date.today()
    future = [(when, name, bias) for name, when, bias in EVENTS if (when - today).days >= 0]
    if not future:
        return None
    when, name, bias = min(future, key=lambda x: x[0])
    return {"event": name, "date": when.isoformat(),
            "days_away": (when - today).days, "angle_bias": bias}
