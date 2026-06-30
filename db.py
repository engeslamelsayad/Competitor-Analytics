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
                link_caption,platforms,snapshot_url,image_url,start_time,stop_time,
                first_seen,last_seen)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (d["ad_id"], d["page_id"], d["page_name"], d["country"], d["source"],
             d["body"], d["title"], d["description"], d["link_caption"],
             d["platforms"], d["snapshot_url"], d.get("image_url",""),
             _parse_ts(d["start_time"]), _parse_ts(d["stop_time"]), now, now),
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
            """SELECT ad_id,page_name,country,body,title,description,
                      snapshot_url,image_url,start_time,stop_time,embedding
               FROM competitor_snapshots
               WHERE embedding IS NOT NULL AND last_seen >= %s""",
            (cutoff,),
        ).fetchall()
        cols = ["ad_id", "page_name", "country", "body", "title", "description",
                "snapshot_url", "image_url", "start_time", "stop_time", "embedding"]
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

    # --- scout_config (dashboard settings) ----------------------------------

    def load_config(self) -> dict:
        """Load live config from DB. Falls back to empty dict if not seeded."""
        row = self.conn.execute(
            "SELECT data FROM scout_config WHERE id = 1"
        ).fetchone()
        if row:
            import json as _j
            d = row[0]
            return d if isinstance(d, dict) else _j.loads(d)
        return {}

    def save_config(self, data: dict, updated_by: str = "dashboard") -> None:
        import json as _j
        self.conn.execute(
            """INSERT INTO scout_config (id, data, updated_at, updated_by)
               VALUES (1, %s, now(), %s)
               ON CONFLICT (id) DO UPDATE
               SET data = EXCLUDED.data,
                   updated_at = now(),
                   updated_by = EXCLUDED.updated_by""",
            (_j.dumps(data, ensure_ascii=False), updated_by),
        )

    def get_stats(self) -> dict:
        """Quick stats for the dashboard overview."""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM competitor_snapshots"
        ).fetchone()[0]

        by_country = self.conn.execute(
            """SELECT country, COUNT(*) FROM competitor_snapshots
               GROUP BY country ORDER BY COUNT(*) DESC"""
        ).fetchall()

        by_source = self.conn.execute(
            """SELECT source, COUNT(*) FROM competitor_snapshots
               GROUP BY source ORDER BY COUNT(*) DESC"""
        ).fetchall()

        last_event = self.conn.execute(
            """SELECT type, confidence, ts, payload
               FROM agent_events ORDER BY ts DESC LIMIT 1"""
        ).fetchone()

        last_cluster = self.conn.execute(
            "SELECT MAX(run_date) FROM clusters"
        ).fetchone()[0]

        import json as _j
        return {
            "total_ads":   total,
            "by_country":  [{"country": r[0], "count": r[1]} for r in by_country],
            "by_source":   [{"source": r[0], "count": r[1]} for r in by_source],
            "last_event":  {
                "type":       last_event[0] if last_event else None,
                "confidence": last_event[1] if last_event else None,
                "ts":         last_event[2].isoformat() if last_event and last_event[2] else None,
                "brief":      (_j.loads(last_event[3]) if isinstance(last_event[3], str)
                               else last_event[3]) if last_event and last_event[3] else {},
            } if last_event else {},
            "last_cluster_date": last_cluster.isoformat() if last_cluster else None,
        }


    # --- dashboard extra queries -------------------------------------------

    def get_runs_history(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """SELECT id, type, confidence, ts, payload
               FROM agent_events
               ORDER BY ts DESC LIMIT %s""", (limit,)
        ).fetchall()
        import json as _j
        out = []
        for r in rows:
            payload = r[4]
            if isinstance(payload, str):
                try: payload = _j.loads(payload)
                except: payload = {}
            new_ads = payload.get("new_ads", 0) if payload else 0
            out.append({
                "id": r[0], "type": r[1],
                "confidence": round(float(r[2] or 0), 2),
                "ts": r[3].strftime("%Y-%m-%d %H:%M") if r[3] else "",
                "new_ads": new_ads,
                "theme": payload.get("theme", "") if payload else "",
            })
        return out

    def get_winners(self, min_days: int = 14, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            """SELECT ad_id, page_name, country, body, snapshot_url, start_time,
                      EXTRACT(DAY FROM (now()-start_time))::int AS days
               FROM competitor_snapshots
               WHERE start_time IS NOT NULL
                 AND (stop_time IS NULL OR stop_time > now())
               ORDER BY start_time ASC LIMIT 200"""
        ).fetchall()
        cols = ["ad_id","page_name","country","body","snapshot_url","start_time","days"]
        result = [dict(zip(cols,r)) for r in rows if (r[6] or 0) >= min_days]
        result.sort(key=lambda x: x["days"] or 0, reverse=True)
        return result[:limit]

    def get_competitor_activity(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT page_name, country,
                 COUNT(*) FILTER (WHERE first_seen >= now()-INTERVAL '7 days') AS this_week,
                 COUNT(*) FILTER (WHERE first_seen >= now()-INTERVAL '14 days'
                                    AND first_seen <  now()-INTERVAL '7 days')  AS last_week,
                 COUNT(*) AS total
               FROM competitor_snapshots
               GROUP BY page_name, country
               HAVING COUNT(*) >= 2
               ORDER BY this_week DESC, total DESC
               LIMIT 30"""
        ).fetchall()
        cols = ["page_name","country","this_week","last_week","total"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            d["delta"] = (d["this_week"] or 0) - (d["last_week"] or 0)
            out.append(d)
        return out

    def get_themes_history(self, limit: int = 60) -> list[dict]:
        rows = self.conn.execute(
            """SELECT run_date, theme, size, competitor_count
               FROM clusters
               ORDER BY run_date DESC, size DESC
               LIMIT %s""", (limit,)
        ).fetchall()
        cols = ["run_date","theme","size","competitor_count"]
        return [dict(zip(cols, r)) | {"run_date": r[0].isoformat() if r[0] else ""} for r in rows]

    def get_swipe_file(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id,ad_id,page_name,country,body,snapshot_url,notes,tags,saved_at FROM swipe_file ORDER BY saved_at DESC"
        ).fetchall()
        cols = ["id","ad_id","page_name","country","body","snapshot_url","notes","tags","saved_at"]
        return [dict(zip(cols,r)) | {"saved_at": r[8].strftime("%Y-%m-%d") if r[8] else ""} for r in rows]

    def add_to_swipe(self, ad_id: str, page_name: str, country: str,
                     body: str, snapshot_url: str, notes: str, tags: str) -> int:
        row = self.conn.execute(
            """INSERT INTO swipe_file (ad_id,page_name,country,body,snapshot_url,notes,tags)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (ad_id, page_name, country, body, snapshot_url, notes, tags)
        ).fetchone()
        return row[0]

    def remove_from_swipe(self, item_id: int) -> None:
        self.conn.execute("DELETE FROM swipe_file WHERE id=%s", (item_id,))

    def get_top_competitors(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT page_name, country, COUNT(*) AS ads,
                      MIN(first_seen)::date AS since
               FROM competitor_snapshots
               GROUP BY page_name, country
               ORDER BY ads DESC LIMIT 20"""
        ).fetchall()
        cols = ["page_name","country","ads","since"]
        return [dict(zip(cols,r)) | {"since": str(r[3])} for r in rows]

    # --- run triggers (manual trigger from Dashboard) ----------------------

    def pending_trigger(self) -> int | None:
        """Return ID of oldest pending trigger, or None."""
        row = self.conn.execute(
            "SELECT id FROM run_triggers WHERE status='pending' ORDER BY requested_at ASC LIMIT 1"
        ).fetchone()
        return row[0] if row else None

    def mark_trigger_running(self, trigger_id: int) -> None:
        self.conn.execute(
            "UPDATE run_triggers SET status='running' WHERE id=%s", (trigger_id,)
        )

    def mark_trigger_done(self, trigger_id: int, status: str = "done") -> None:
        self.conn.execute(
            "UPDATE run_triggers SET status=%s WHERE id=%s", (status, trigger_id)
        )

    def insert_trigger(self, source: str = "dashboard") -> int:
        """Insert a new pending trigger. Returns the new trigger ID."""
        row = self.conn.execute(
            "INSERT INTO run_triggers (source) VALUES (%s) RETURNING id", (source,)
        ).fetchone()
        return row[0]

    # --- daily run dedup --------------------------------------------------

    def daily_run_done_today(self) -> bool:
        """هل الـ daily scheduled run (06:00 UTC) اتنفذ النهاردة بالفعل؟
        يمنع الـ cron (اللي بيشتغل كل 5 دقائق) من تكرار نفس الـ run
        12 مرة خلال ساعة الـ 6 صباحاً."""
        row = self.conn.execute(
            "SELECT 1 FROM daily_runs WHERE run_date = CURRENT_DATE"
        ).fetchone()
        return row is not None

    def mark_daily_run_done(self) -> None:
        """سجّل إن الـ daily run اتنفذ النهاردة."""
        self.conn.execute(
            "INSERT INTO daily_runs (run_date) VALUES (CURRENT_DATE) "
            "ON CONFLICT (run_date) DO NOTHING"
        )

    def close(self):
        self.conn.close()

    # --- alerts helpers -------------------------------------------------------

    def new_competitors_since(self, hours: int = 26) -> list[dict]:
        """Page names that appeared for the first time within the last N hours.
        Returns empty list on first 48h (no baseline yet — every brand is "new")."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=hours)

        # Guard: if oldest record is less than 48h old, we have no baseline yet.
        oldest = self.conn.execute(
            "SELECT MIN(first_seen) FROM competitor_snapshots"
        ).fetchone()
        if not oldest or not oldest[0]:
            return []
        db_age_hours = (now - oldest[0]).total_seconds() / 3600
        if db_age_hours < 48:
            print(f"[alerts] skipping new-competitor check — DB is only {db_age_hours:.0f}h old (need 48h baseline)")
            return []

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
        truly_new = []
        for r in rows:
            d = dict(zip(cols, r))
            existing = self.conn.execute(
                """SELECT 1 FROM competitor_snapshots
                   WHERE page_name = %s AND first_seen < %s LIMIT 1""",
                (d["page_name"], cutoff),
            ).fetchone()
            if not existing:
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
