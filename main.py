"""
Scout orchestrator — one run.

  collect (Apify Meta + TikTok)  ->  upsert (dedup + longevity)
  -> embed new ads (Voyage)      ->  cluster today (HDBSCAN) + label
  -> persist clusters            ->  diff vs ~14d ago
  -> reason (Claude)             ->  emit event + write brief

Run on Railway via cron (e.g. every 4h or daily). Locally: python main.py
"""

from datetime import date, timedelta

import config
from db import DB
from sources import MetaAdLibrarySource, ApifyMetaSource, TikTokCCSource
from embeddings import Embedder, creative_text
from cluster import cluster_ads, label_clusters
from diff import diff_clusters
from scout import reason
from calendar_mena import upcoming_events
from report import write_brief
from telegram import send_brief
from alerts import new_competitor_alert, winning_creatives_digest


# Max ads to embed per run — keeps us within Voyage free-tier rate limits.
# Remaining unemedded ads are picked up automatically in the next run.
EMBED_PER_RUN = 150


def build_sources() -> list:
    srcs = []
    if config.META_SOURCE == "apify":
        srcs.append(ApifyMetaSource(config.APIFY_TOKEN, config.APIFY_META_ACTOR))
    else:
        srcs.append(MetaAdLibrarySource(
            config.META_ACCESS_TOKEN, config.META_API_VERSION))
    if config.USE_TIKTOK and config.APIFY_TOKEN:
        srcs.append(TikTokCCSource(config.APIFY_TOKEN, config.APIFY_TIKTOK_ACTOR))
    return srcs


def collect(sources, db: DB) -> int:
    new = 0
    for src in sources:
        for country in config.COUNTRIES:
            try:
                for ad in src.fetch_ads(
                    country=country,
                    page_ids=config.COMPETITOR_PAGE_IDS or None,
                    search_terms=config.SEARCH_TERMS or None,
                    limit=config.MAX_ADS_PER_QUERY,
                ):
                    if db.upsert(ad):
                        new += 1
            except Exception as e:
                print(f"[collect] {src.name}/{country} failed: {e}")
    print(f"[collect] {new} new ad(s)")
    return new


def embed_new(db: DB) -> None:
    """Embed up to EMBED_PER_RUN ads per run — respects Voyage free-tier limits.
    Remaining ads are picked up automatically in the next cron run."""
    pending = db.needs_embedding()
    if not pending:
        return
    batch = pending[:EMBED_PER_RUN]
    if len(pending) > EMBED_PER_RUN:
        print(f"[embed] {len(pending)} pending — doing {EMBED_PER_RUN} this run, rest next run")
    embedder = Embedder(config.VOYAGE_API_KEY, config.EMBED_MODEL)
    texts = [creative_text(a) for a in batch]
    print(f"[embed] {len(texts)} ad(s)")
    vectors = embedder.embed(texts)
    for ad, vec in zip(batch, vectors):
        db.save_embedding(ad["ad_id"], vec)


def main() -> None:
    db = DB(config.DATABASE_URL)
    db.ensure_schema()

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
    brief = reason(
        config.STORE, diff_result, previous, calendar,
        config.ANTHROPIC_API_KEY, config.SCOUT_MODEL, config.CONFIDENCE_FLOOR)

    event_type = "opportunity_brief" if brief.get("emit") else "noop"
    db.emit_event(event_type, float(brief.get("confidence", 0)), brief)

    longest = db.longest_running(config.WINNER_DAYS_THRESHOLD)
    path = write_brief(brief, diff_result, longest, calendar, config.REPORT_DIR)

    send_brief(brief, diff_result, longest, calendar)
    new_competitor_alert(db)
    winning_creatives_digest(db, min_days=14)
    db.close()
    print(f"✅ done — {event_type} — brief at {path}")


if __name__ == "__main__":
    main()