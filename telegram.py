"""
Telegram reporter — sends the Scout brief as a formatted message.

Setup (one time):
  1. Open Telegram → search @BotFather → /newbot → follow steps → copy token.
  2. Send any message to your new bot.
  3. Open: https://api.telegram.org/bot<TOKEN>/getUpdates
     Find "chat":{"id": XXXXXXX} — that's your CHAT_ID.
  4. Add to Railway Variables:
       TELEGRAM_BOT_TOKEN = ...
       TELEGRAM_CHAT_ID   = ...
"""

import os
import requests

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

MAX_MSG = 4000   # Telegram limit is 4096 chars per message


def _chunk(text: str, size: int = MAX_MSG) -> list[str]:
    """Split long text into Telegram-safe chunks."""
    return [text[i:i+size] for i in range(0, len(text), size)]


def send(text: str) -> bool:
    """Send one or more messages. Returns True if all succeeded."""
    if not BOT_TOKEN or not CHAT_ID:
        print("[telegram] BOT_TOKEN or CHAT_ID not set — skipping.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    ok  = True

    for chunk in _chunk(text):
        # نحاول Markdown الأول، ولو فشل نبعت plain text
        resp = requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       chunk,
            "parse_mode": "Markdown",
        }, timeout=15)
        if not resp.ok:
            data = resp.json()
            if "parse" in data.get("description", "").lower() or data.get("error_code") == 400:
                # Markdown فشل بسبب characters خاصة — نبعت plain text
                resp = requests.post(url, json={
                    "chat_id": CHAT_ID,
                    "text":    chunk,
                }, timeout=15)
            if not resp.ok:
                print(f"[telegram] send failed: {resp.text[:150]}")
                ok = False

    return ok


def send_brief(brief: dict, diff_result: dict,
               longest: list[dict], calendar: list[dict]) -> None:
    """Format and send the Scout brief to Telegram."""

    # Header
    from datetime import date
    today = date.today().isoformat()

    if brief.get("emit"):
        conf   = brief.get("confidence", 0)
        stars  = "🟢" if conf >= 0.80 else "🟡"
        header = f"*🎯 Scout Brief — {today}*\n{stars} ثقة: {conf}\n"

        opp = (
            f"\n*الفرصة:* {brief.get('theme')}\n"
            f"*ليه دلوقتي:* {brief.get('reasoning')}\n"
            f"*الزاوية:* {brief.get('target_angle')}\n"
            f"*نافذة التنفيذ:* {brief.get('window_days', 14)} يوم\n"
        )

        hooks_list = brief.get("hooks", [])
        hooks = "\n*Hooks جاهزة:*\n" + "\n".join(f"• {h}" for h in hooks_list)

        dirs_list = brief.get("creative_directions", [])
        dirs = "\n*اتجاهات الكرييتف:*\n" + "\n".join(f"• {d}" for d in dirs_list)

        avoid_list = brief.get("avoid", [])
        avoid = "\n*تجنّب (متشبّع):*\n" + "\n".join(f"• {a}" for a in avoid_list)

        body = header + opp + hooks + dirs + avoid

    else:
        body = (
            f"*⏸ Scout — {today}*\n"
            f"مفيش فرصة عالية الثقة الـ run ده.\n"
            f"أعلى ثقة: {brief.get('confidence', 0)}"
        )

    # Themes section
    rising   = diff_result.get("rising_or_new", [])
    saturated = diff_result.get("saturated", []) + diff_result.get("declining", [])

    themes = "\n\n*📈 ثيمات صاعدة/جديدة:*\n"
    themes += "\n".join(f"• {c['theme']} ({c['status']})" for c in rising) or "• لا يوجد"

    themes += "\n\n*🛑 ثيمات متشبّعة/هابطة:*\n"
    themes += "\n".join(f"• {c['theme']}" for c in saturated) or "• لا يوجد"

    # Winners section
    if longest:
        winners = "\n\n*⏳ أطول إعلانات عمرًا:*\n"
        winners += "\n".join(
            f"• {a['page_name']} — {a['days']} يوم" for a in longest[:5]
        )
    else:
        winners = ""

    # Calendar section
    if calendar:
        cal = "\n\n*📅 مواسم قادمة:*\n"
        cal += "\n".join(
            f"• {e['event']} بعد {e['days_away']} يوم" for e in calendar
        )
    else:
        cal = ""

    full_msg = body + themes + winners + cal
    send(full_msg)


def send_weekly_competitive_report(conn) -> bool:
    """رسالة أسبوعية شاملة بالمشهد التنافسي — تُرسَل كل جمعة."""
    from datetime import datetime, timezone, timedelta, date

    cutoff_week = datetime.now(timezone.utc) - timedelta(days=7)
    cutoff_2w   = datetime.now(timezone.utc) - timedelta(days=14)

    try:
        total_advertisers = conn.execute(
            "SELECT COUNT(DISTINCT page_name) FROM competitor_snapshots"
        ).fetchone()[0]

        active = conn.execute(
            """SELECT page_name,
                 COUNT(*) FILTER (WHERE first_seen >= %s) AS new_this_week,
                 COUNT(*) FILTER (WHERE first_seen >= %s AND first_seen < %s) AS new_last_week,
                 COUNT(*) AS total
               FROM competitor_snapshots
               GROUP BY page_name
               HAVING COUNT(*) FILTER (WHERE first_seen >= %s) > 0
               ORDER BY new_this_week DESC LIMIT 10""",
            (cutoff_week, cutoff_2w, cutoff_week, cutoff_week),
        ).fetchall()

        by_country = conn.execute(
            """SELECT country, COUNT(*) AS ads
               FROM competitor_snapshots
               WHERE first_seen >= %s
               GROUP BY country ORDER BY ads DESC LIMIT 5""",
            (cutoff_week,),
        ).fetchall()

        winners = conn.execute(
            """SELECT page_name,
                      EXTRACT(DAY FROM (now() - start_time))::int AS days
               FROM competitor_snapshots
               WHERE start_time IS NOT NULL
                 AND (stop_time IS NULL OR stop_time > now())
               ORDER BY start_time ASC LIMIT 5"""
        ).fetchall()

        total_new = sum(r[1] or 0 for r in active)

    except Exception as e:
        print("[telegram] weekly report query failed: " + str(e))
        return False

    week_num = date.today().isocalendar()[1]
    parts = []

    # Header
    parts.append("*📊 المشهد التنافسي — الأسبوع " + str(week_num) + "*")

    # Active competitors
    parts.append("\n*🏢 أكثر المنافسين نشاطاً (" + str(total_new) + " إعلان جديد):*")
    for name, new_w, new_lw, total in active[:8]:
        delta = (new_w or 0) - (new_lw or 0)
        if delta > 0:
            arrow = " ↑" + str(delta)
        elif delta < 0:
            arrow = " ↓" + str(abs(delta))
        else:
            arrow = ""
        badge = " 🆕" if (new_lw or 0) == 0 else ""
        parts.append("• *" + str(name) + "* — " + str(new_w) + " جديد" + arrow + badge
                     + " (إجمالي: " + str(total) + ")")

    # By country
    if by_country:
        parts.append("\n*🌍 توزيع الإعلانات الجديدة:*")
        parts.append(" | ".join(str(r[0]) + ": " + str(r[1]) for r in by_country))

    # Total
    parts.append("\n*👥 إجمالي المعلنين المرصودين: " + str(total_advertisers) + "*")

    # Winners
    if winners:
        parts.append("\n*⏳ أطول إعلانات عمراً (Winners):*")
        for name, days in winners:
            parts.append("• " + str(name) + " — " + str(days or 0) + " يوم")

    return send("\n".join(parts))
