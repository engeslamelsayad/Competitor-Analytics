"""
Two proactive alert types sent separately from the Scout brief:

1. new_competitor_alert  — fires when a brand-new advertiser appears today.
2. winning_creatives_digest — daily links to ads running 14+ days (no repeats).

Both are called from main.py after the Scout brief is sent.
"""

from db import DB
from telegram import send


def new_competitor_alert(db: DB) -> None:
    """Detect new competitors and send a Telegram alert immediately."""
    new = db.new_competitors_since(hours=26)
    if not new:
        return

    lines = [f"*🆕 منافس جديد ظهر النهاردة!*\n"]
    for c in new:
        name    = c["page_name"]
        country = c["country"]
        count   = c["ad_count"]
        url     = c.get("sample_url", "")
        lines.append(f"• *{name}* — {country} — {count} إعلان")
        if url:
            lines.append(f"  [شوف الإعلان]({url})")

    lines.append("\n_تحقق منه — قد يكون منافس جديد يستحق المتابعة._")
    send("\n".join(lines))
    print(f"[alerts] sent new-competitor alert: {[c['page_name'] for c in new]}")


def winning_creatives_digest(db: DB, min_days: int = 14) -> None:
    """Send links to long-running competitor creatives not sent before."""
    creatives = db.winning_creatives_unsent(min_days=min_days)
    if not creatives:
        print("[alerts] no new winning creatives to send")
        return

    lines = [f"*⏳ Creatives رابحة عند المنافسين (+{min_days} يوم)*\n"]
    for ad in creatives:
        name = ad["page_name"]
        days = ad["days"]
        body = (ad.get("body") or "")[:80].strip()
        body = body.replace("\n", " ")
        url  = ad.get("snapshot_url", "")
        line = f"• *{name}* — {days} يوم"
        if body:
            line += f'\n  _"{body}..."_'
        if url:
            line += f"\n  [شوف الإعلان]({url})"
        lines.append(line)

    lines.append(
        f"\n_هذه الإعلانات لن تُرسَل مرة أخرى. "
        f"إعلانات جديدة فوق {min_days} يوم ستظهر غداً._"
    )

    send("\n".join(lines))
    db.mark_digest_sent([ad["ad_id"] for ad in creatives])
    print(f"[alerts] sent {len(creatives)} winning creatives, marked as sent")
