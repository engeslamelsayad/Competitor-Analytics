"""
Postgres + pgvector data layer.

Replaces the old SQLite store. Handles de-dup + longevity tracking, embedding
storage, cluster persistence, and the agent_events spine.
"""

import os
import json
from datetime import datetime, timezone, timedelta

import psycopg
from pgvector.psycopg import register_vector

from sources.base import NormalizedAd


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class DB:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL is empty. Set your Railway pgvector URL.")
        self.conn = psycopg.connect(database_url, autocommit=True)
        register_vector(self.conn)

    def ensure_schema(self, schema_path: str = "schema.sql") -> None:
        if os.path.exists(schema_path):
            with open(schema_path, encoding="utf-8") as f:
                self.conn.execute(f.read())

    # --- snapshots ------------------------------------------------------------
    def upsert(self, ad: NormalizedAd) -> bool:
        """Insert new ad or refresh last_seen/stop_time. Returns True if new."""
        d = ad.as_dict()
        row = self.conn.execute(
            "SELECT 1 FROM competitor_snapshots WHERE ad_id = %s", (ad.ad_id,)
        ).fetchone()
        now = datetime.now(timezone.utc)
        if row:
            self.conn.execute(
                "UPDATE competitor_snapshots SET last_seen=%s, stop_time=%s WHERE ad_id=%s",
                (now, _parse_ts(d["stop_time"]), ad.ad_id),
            )
            return False
        self.conn.execute(
            """INSERT INTO competitor_snapshots
               (ad_id,page_id,page_name,country,source,body,title,description,
                link_caption,platforms,snapshot_url,start_time,stop_time,
                first_seen,last_seen)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (d["ad_id"], d["page_id"], d["page_name"], d["country"], d["source"],
             d["body"], d["title"], d["description"], d["link_caption"],
             d["platforms"], d["snapshot_url"], _parse_ts(d["start_time"]),
             _parse_ts(d["stop_time"]), now, now),
        )
        return True

    def needs_embedding(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT ad_id, page_name, body, title, description "
            "FROM competitor_snapshots WHERE embedding IS NULL"
        ).fetchall()
        cols = ["ad_id", "page_name", "body", "title", "description"]
        return [dict(zip(cols, r)) for r in rows]

    def save_embedding(self, ad_id: str, vector) -> None:
        self.conn.execute(
            "UPDATE competitor_snapshots SET embedding=%s WHERE ad_id=%s",
            (vector, ad_id),
        )

    def active_with_embeddings(self, since_days: int = 7) -> list[dict]:
        """Ads seen recently that already have an embedding (today's working set)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        rows = self.conn.execute(
            """SELECT ad_id,page_name,country,body,title,description,snapshot_url,
                      start_time,stop_time,embedding
               FROM competitor_snapshots
               WHERE embedding IS NOT NULL AND last_seen >= %s""",
            (cutoff,),
        ).fetchall()
        cols = ["ad_id", "page_name", "country", "body", "title", "description",
                "snapshot_url", "start_time", "stop_time", "embedding"]
        return [dict(zip(cols, r)) for r in rows]

    def longest_running(self, threshold_days: int, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            """SELECT page_name, body, snapshot_url, start_time,
                      EXTRACT(DAY FROM (now() - start_time))::int AS days
               FROM competitor_snapshots
               WHERE start_time IS NOT NULL AND stop_time IS NULL
               ORDER BY start_time ASC LIMIT %s""",
            (limit,),
        ).fetchall()
        cols = ["page_name", "body", "snapshot_url", "start_time", "days"]
        out = [dict(zip(cols, r)) for r in rows]
        return [a for a in out if (a["days"] or 0) >= threshold_days]

    # --- clusters -------------------------------------------------------------
    def save_cluster(self, run_date, theme, size, competitor_count,
                     sample_ad_ids, centroid) -> None:
        self.conn.execute(
            """INSERT INTO clusters
               (run_date,theme,size,competitor_count,sample_ad_ids,centroid)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (run_date, theme, size, competitor_count,
             json.dumps(sample_ad_ids), centroid),
        )

    def clusters_on_or_before(self, target_date) -> list[dict]:
        """Most recent cluster snapshot at/just before target_date (for diffing)."""
        row = self.conn.execute(
            "SELECT max(run_date) FROM clusters WHERE run_date <= %s", (target_date,)
        ).fetchone()
        if not row or not row[0]:
            return []
        run_date = row[0]
        rows = self.conn.execute(
            """SELECT theme,size,competitor_count,centroid
               FROM clusters WHERE run_date = %s""",
            (run_date,),
        ).fetchall()
        cols = ["theme", "size", "competitor_count", "centroid"]
        return [dict(zip(cols, r)) for r in rows]

    # --- events ---------------------------------------------------------------
    def emit_event(self, type_: str, confidence: float, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO agent_events (type,confidence,payload) VALUES (%s,%s,%s)",
            (type_, confidence, json.dumps(payload, ensure_ascii=False)),
        )

    def close(self):
        self.conn.close()

    # --- alerts helpers -------------------------------------------------------

    def new_competitors_since(self, hours: int = 26) -> list[dict]:
        """Page names that appeared for the first time within the last N hours.
        'hours' is slightly over 24 so we never miss a run that fires late."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = self.conn.execute(
            """SELECT page_name, country, source,
                      COUNT(*)          AS ad_count,
                      MIN(first_seen)   AS first_seen,
                      MAX(snapshot_url) AS sample_url
               FROM competitor_snapshots
               WHERE first_seen >= %s
               GROUP BY page_name, country, source
               HAVING COUNT(*) >= 2
               ORDER BY ad_count DESC""",
            (cutoff,),
        ).fetchall()
        cols = ["page_name", "country", "source", "ad_count", "first_seen", "sample_url"]
        # Filter to truly new: page must not exist before cutoff
        truly_new = []
        for r in rows:
            d = dict(zip(cols, r))
            old = self.conn.execute(
                """SELECT 1 FROM competitor_snapshots
                   WHERE page_name = %s AND first_seen < %s LIMIT 1""",
                (d["page_name"], cutoff),
            ).fetchone()
            if not old:
                truly_new.append(d)
        return truly_new

    def winning_creatives_unsent(self, min_days: int = 14, limit: int = 15) -> list[dict]:
        """Ads running >= min_days that have NOT been sent in a previous digest."""
        # Get already-sent ad_ids from agent_events
        sent_rows = self.conn.execute(
            """SELECT payload->'ad_ids' AS ids
               FROM agent_events
               WHERE type = 'creative_digest_sent'
               ORDER BY ts DESC LIMIT 30"""
        ).fetchall()
        sent_ids: set[str] = set()
        for row in sent_rows:
            ids = row[0]
            if isinstance(ids, list):
                sent_ids.update(str(i) for i in ids)
            elif isinstance(ids, str):
                import json as _j
                try:
                    sent_ids.update(str(i) for i in _j.loads(ids))
                except Exception:
                    pass

        rows = self.conn.execute(
            """SELECT ad_id, page_name, country, body, snapshot_url,
                      start_time,
                      EXTRACT(DAY FROM (now() - start_time))::int AS days
               FROM competitor_snapshots
               WHERE start_time IS NOT NULL
                 AND (stop_time IS NULL OR stop_time > now())
               ORDER BY start_time ASC
               LIMIT 200"""
        ).fetchall()
        cols = ["ad_id", "page_name", "country", "body", "snapshot_url", "start_time", "days"]
        result = []
        for r in rows:
            d = dict(zip(cols, r))
            if (d["days"] or 0) >= min_days and d["ad_id"] not in sent_ids:
                result.append(d)
        return result[:limit]

    def mark_digest_sent(self, ad_ids: list[str]) -> None:
        """Record which ad_ids were sent so they won't repeat tomorrow."""
        import json as _j
        self.emit_event("creative_digest_sent", 1.0, {"ad_ids": ad_ids})