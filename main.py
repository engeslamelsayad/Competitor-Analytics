"""
Scout orchestrator — one run.

  check trigger / scheduled hour  ->  collect  ->  embed  ->  cluster  ->  diff
  ->  reason  ->  emit event  ->  alerts  ->  report

Run on Railway via cron (*/5 * * * *). Locally: python main.py

التصحيحات في هذه النسخة:
  1. منع التكرار في الـ daily run: بدل ما نعتمد بس على hour==6 (اللي بيتكرر
     12 مرة لأن الـ cron كل 5 دقائق)، بنتحقق كمان من جدول daily_runs في DB
     إن كان فيه run اليوم خلص بالفعل.
  2. حماية الـ embeddings من "poison pill": قص النص لأي إعلان لـ 2000 حرف
     قبل إرساله لـ Voyage، عشان نص طويل جداً ميفشّلش الـ batch كله.
"""

from datetime import date, timedelta, datetime, timezone

import config
from db import DB
from sources import MetaAdLibrarySource, ApifyMetaSource, TikTokCCSource
from embeddings import Embedder, creative_text
from cluster import cluster_ads, label_clusters
from diff import diff_clusters
from scout import reason
from calendar_mena import upcoming_events
from report import write_brief
from telegram import send_brief, send_weekly_competitive_report
from alerts import new_competitor_alert, winning_creatives_digest

# أقصى عدد إعلانات نعمله embed في الـ run الواحد — يحافظ على Voyage free-tier.
# الباقي بيتلقط تلقائياً في الـ run الجاي.
EMBED_PER_RUN = 150

# أقصى طول نص نبعته لـ Voyage — حماية من poison pill (نص طويل جداً يفشّل الـ batch).
MAX_EMBED_TEXT_CHARS = 2000


def build_sources() -> list:
    srcs = []
    if config.META_SOURCE == "apify":
        srcs.append(ApifyMetaSource(config.APIFY_TOKEN, config.APIFY_META_ACTOR))
    else:
        srcs.append(MetaAdLibrarySource(config.META_ACCESS_TOKEN, config.META_API_VERSION))
    if config.USE_TIKTOK and config.APIFY_TOKEN:
        srcs.append(TikTokCCSource(config.APIFY_TOKEN, config.APIFY_TIKTOK_ACTOR))
    return srcs


def load_runtime_config(db: DB) -> None:
    """DB config (من الداشبورد) بيـ override إعدادات config.py لو موجود."""
    live = db.load_config()
    if not live:
        return
    if live.get("countries"):
        config.COUNTRIES = live["countries"]
    if live.get("competitor_page_ids") is not None:
        config.COMPETITOR_PAGE_IDS = live["competitor_page_ids"]
    if live.get("search_terms_config"):
        config.SEARCH_TERMS_CONFIG = live["search_terms_config"]
        config.SEARCH_TERMS = [c["term"] for c in config.SEARCH_TERMS_CONFIG]
    if live.get("store"):
        config.STORE = live["store"]
    if "use_tiktok" in live:
        config.USE_TIKTOK = live["use_tiktok"]
    if "confidence_floor" in live:
        config.CONFIDENCE_FLOOR = live["confidence_floor"]
    if "winner_days_threshold" in live:
        config.WINNER_DAYS_THRESHOLD = live["winner_days_threshold"]
    print("[config] loaded live settings from DB (dashboard override active)")


def collect(sources, db: DB) -> int:
    """Collect ads using per-term count from SEARCH_TERMS_CONFIG for cost control."""
    new = 0
    for src in sources:
        for country in config.COUNTRIES:
            if config.COMPETITOR_PAGE_IDS:
                try:
                    for ad in src.fetch_ads(country=country,
                                             page_ids=config.COMPETITOR_PAGE_IDS,
                                             limit=config.MAX_ADS_PER_QUERY):
                        if db.upsert(ad):
                            new += 1
                except Exception as e:
                    print(f"[collect] {src.name}/pages/{country}: {e}")
            for term_cfg in config.SEARCH_TERMS_CONFIG:
                term = term_cfg["term"]
                count = term_cfg.get("count", 50)
                try:
                    for ad in src.fetch_ads(country=country,
                                             search_terms=[term], limit=count):
                        if db.upsert(ad):
                            new += 1
                except Exception as e:
                    print(f"[collect] {src.name}/{country}/{term}: {e}")
    print(f"[collect] {new} new ad(s)")
    return new


def embed_new(db: DB) -> None:
    """Embed up to EMBED_PER_RUN ads per run — respects Voyage free-tier limits.
    Remaining ads are picked up automatically in the next cron run.

    كل نص بيتقص لـ MAX_EMBED_TEXT_CHARS قبل الإرسال عشان إعلان واحد بنص
    طويل جداً (أو tokens زيادة عن حد Voyage) ميفشّلش الـ batch كله ويدخلنا
    في loop مفرغ من نفس الإعلانات الفاشلة كل run."""
    pending = db.needs_embedding()
    if not pending:
        return
    batch = pending[:EMBED_PER_RUN]
    if len(pending) > EMBED_PER_RUN:
        print(f"[embed] {len(pending)} pending — doing {EMBED_PER_RUN} this run, rest next run")

    embedder = Embedder(config.VOYAGE_API_KEY, config.EMBED_MODEL)
    texts = [creative_text(a)[:MAX_EMBED_TEXT_CHARS] for a in batch]
    ad_ids = [a["ad_id"] for a in batch]
    print(f"[embed] {len(texts)} ad(s)")

    try:
        results = embedder.embed(texts, ad_ids)
        saved = 0
        for ad_id, vec in results.items():
            db.save_embedding(ad_id, vec)
            saved += 1
        print(f"[embed] saved {saved}/{len(batch)} embeddings")
        if saved < len(batch):
            print(f"[embed] ⚠️ {len(batch) - saved} skipped — will retry next run")
    except Exception as e:
        print(f"[embed] ⚠️ embedding failed even after truncation: {e} — continuing pipeline")


def run_pipeline(db: DB) -> None:
    """Core Scout pipeline — يتنفذ مرة واحدة فقط (سواء trigger يدوي أو scheduled)."""
    collect(build_sources(), db)
    embed_new(db)

    ads = db.active_with_embeddings(since_days=7)
    print(f"[cluster] {len(ads)} active ad(s) with embeddings")
    today_clusters = cluster_ads(ads, config.MIN_CLUSTER_SIZE)
    label_clusters(today_clusters, config.ANTHROPIC_API_KEY, config.LABEL_MODEL)

    run_date = date.today()
    for c in today_clusters:
        sample_ids = [ads[i]["ad_id"] for i in c["ad_indices"]][:10]
        db.save_cluster(run_date, c.get("theme"), c["size"],
                         c["competitor_count"], sample_ids, c["centroid"])

    previous = db.clusters_on_or_before(
        run_date - timedelta(days=config.DIFF_WINDOW_DAYS))
    diff_result = diff_clusters(
        today_clusters, previous, config.CLUSTER_MATCH_THRESHOLD)

    calendar = upcoming_events(config.SEASONAL_WINDOW_DAYS)
    brief = reason(config.STORE, diff_result, previous, calendar,
                    config.ANTHROPIC_API_KEY, config.SCOUT_MODEL, config.CONFIDENCE_FLOOR)

    event_type = "opportunity_brief" if brief.get("emit") else "noop"
    db.emit_event(event_type, float(brief.get("confidence", 0)), brief)

    longest = db.longest_running(config.WINNER_DAYS_THRESHOLD)
    path = write_brief(brief, diff_result, longest, calendar, config.REPORT_DIR)

    send_brief(brief, diff_result, longest, calendar)
    new_competitor_alert(db)
    winning_creatives_digest(db, min_days=14)

    # رسالة أسبوعية كل جمعة (weekday 4 = Friday) — مرة واحدة بس بفضل
    # إن run_pipeline نفسه بقى مضمون يتنفذ مرة واحدة في اليوم للـ scheduled runs.
    if datetime.now(timezone.utc).weekday() == 4:
        send_weekly_competitive_report(db.conn)

    print(f"✅ done — {event_type} — brief at {path}")


def main() -> None:
    db = DB(config.DATABASE_URL)
    db.ensure_schema()
    load_runtime_config(db)

    # ── تحقق: trigger يدوي، أو وقت الـ cron اليومي ولسه ما اتنفذش النهاردة ──
    trigger_id = db.pending_trigger()
    is_daily_hour = datetime.now(timezone.utc).hour == 6
    daily_already_done = db.daily_run_done_today()
    is_daily_due = is_daily_hour and not daily_already_done

    if not trigger_id and not is_daily_due:
        if is_daily_hour and daily_already_done:
            print("[main] daily run already completed today — skipping duplicate fire")
        else:
            print("[main] no pending trigger and not 06:00 UTC — skipping")
        db.close()
        return

    if trigger_id:
        print(f"[main] 🟡 manual trigger #{trigger_id} — running pipeline")
        db.mark_trigger_running(trigger_id)
    else:
        print("[main] 🕕 scheduled daily run (06:00 UTC)")

    try:
        run_pipeline(db)
        if trigger_id:
            db.mark_trigger_done(trigger_id, "done")
        else:
            db.mark_daily_run_done()
    except Exception as e:
        print(f"[main] ❌ pipeline failed: {e}")
        if trigger_id:
            try:
                db.mark_trigger_done(trigger_id, "failed")
            except Exception:
                pass
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
