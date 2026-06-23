"""Render the Scout's output into a Markdown brief."""

import os
from datetime import date


def write_brief(brief: dict, diff_result: dict, longest: list[dict],
                calendar: list[dict], report_dir: str) -> str:
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"scout-{date.today().isoformat()}.md")

    def lines(items, fmt):
        return "\n".join(fmt(x) for x in items) or "- (لا يوجد)"

    season = lines(
        calendar,
        lambda e: f"- **{e['event']}** بعد {e['days_away']} يوم — انحياز: {e['angle_bias']}",
    )
    rising = lines(
        diff_result.get("rising_or_new", []),
        lambda c: f"- {c['theme']} ({c['status']}, {c['competitor_count']} منافس)",
    )
    saturated = lines(
        diff_result.get("saturated", []) + diff_result.get("declining", []),
        lambda c: f"- {c['theme']} ({c['status']})",
    )
    winners = lines(
        longest,
        lambda a: f"- **{a['page_name']}** — {a['days']} يوم — {a['snapshot_url']}",
    )

    if brief.get("emit"):
        hooks = lines(brief.get("hooks", []), lambda h: f"- {h}")
        directions = lines(brief.get("creative_directions", []), lambda d: f"- {d}")
        avoid = lines(brief.get("avoid", []), lambda a: f"- {a}")
        opportunity = f"""## \U0001F3AF الفرصة (ثقة: {brief.get('confidence')})

**الثيم:** {brief.get('theme')}

**ليه دلوقتي:** {brief.get('reasoning')}

**الزاوية المقترحة:** {brief.get('target_angle')}

### Hooks جاهزة
{hooks}

### اتجاهات الكرييتف
{directions}

### تجنّب (متشبّع)
{avoid}

**نافذة التنفيذ:** {brief.get('window_days', 14)} يوم
"""
    else:
        opportunity = (
            f"## \u23F8\uFE0F مفيش فرصة عالية الثقة الـ cycle ده\n\n"
            f"أعلى ثقة: {brief.get('confidence', 0)}. "
            f"{brief.get('error', 'الإشارات لسه مش كفاية — كمّل تجميع داتا.')}"
        )

    md = f"""# تقرير الـ Scout — {date.today().isoformat()}

{opportunity}

---

## \U0001F4C5 المواسم القادمة
{season}

## \U0001F4C8 ثيمات صاعدة / جديدة (فرص)
{rising}

## \U0001F6D1 ثيمات متشبّعة / هابطة (تجنّب)
{saturated}

## \u23F3 أطول إعلانات عمرًا (مرشّحة كرابحة)
{winners}
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path
