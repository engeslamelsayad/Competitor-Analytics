-- Scout database schema (Postgres + pgvector).
-- Run once on your Railway pgvector instance. EMBED_DIM = 1024 (voyage-3).
-- If you change the embedding model/dim, change vector(1024) below too.

CREATE EXTENSION IF NOT EXISTS vector;

-- Every ad we ever saw, with de-dup + longevity + its embedding.
CREATE TABLE IF NOT EXISTS competitor_snapshots (
    ad_id         TEXT PRIMARY KEY,
    page_id       TEXT,
    page_name     TEXT,
    country       TEXT,
    source        TEXT,
    body          TEXT,
    title         TEXT,
    description   TEXT,
    link_caption  TEXT,
    platforms     TEXT,
    snapshot_url  TEXT,
    start_time    TIMESTAMPTZ,
    stop_time     TIMESTAMPTZ,
    first_seen    TIMESTAMPTZ DEFAULT now(),
    last_seen     TIMESTAMPTZ DEFAULT now(),
    embedding     vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_snap_last_seen ON competitor_snapshots (last_seen);
CREATE INDEX IF NOT EXISTS idx_snap_embedding
    ON competitor_snapshots USING hnsw (embedding vector_l2_ops);

-- One row per theme cluster per run (so we can diff across time).
CREATE TABLE IF NOT EXISTS clusters (
    id               BIGSERIAL PRIMARY KEY,
    run_date         DATE NOT NULL,
    theme            TEXT,
    size             INT,
    competitor_count INT,
    sample_ad_ids    JSONB,
    centroid         vector(1024)
);

CREATE INDEX IF NOT EXISTS idx_clusters_run_date ON clusters (run_date);

-- The "spine": events the Scout emits (other agents can subscribe later).
CREATE TABLE IF NOT EXISTS agent_events (
    id          BIGSERIAL PRIMARY KEY,
    ts          TIMESTAMPTZ DEFAULT now(),
    agent       TEXT DEFAULT 'scout',
    type        TEXT,                      -- opportunity_brief | pattern_shift | noop
    confidence  REAL,
    payload     JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON agent_events (ts);

-- Dashboard config table (single row, updated via dashboard UI)
CREATE TABLE IF NOT EXISTS scout_config (
    id          INT PRIMARY KEY DEFAULT 1,
    data        JSONB NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT now(),
    updated_by  TEXT DEFAULT 'dashboard'
);

-- Seed with defaults (only if empty)
INSERT INTO scout_config (id, data) VALUES (1, '{
    "countries": ["SA", "AE", "EG"],
    "competitor_page_ids": [],
    "search_terms_config": [],
    "store": {
        "name": "",
        "category": "",
        "country": "SA",
        "platform": "Shopify",
        "brand_voice": "",
        "current_campaigns": "",
        "past_winners": ""
    },
    "use_tiktok": true,
    "confidence_floor": 0.60,
    "winner_days_threshold": 30
}'::jsonb)
ON CONFLICT (id) DO NOTHING;

-- Swipe file: ads saved manually by user with notes
CREATE TABLE IF NOT EXISTS swipe_file (
    id           BIGSERIAL PRIMARY KEY,
    ad_id        TEXT,
    page_name    TEXT,
    country      TEXT,
    body         TEXT,
    snapshot_url TEXT,
    notes        TEXT DEFAULT '',
    tags         TEXT DEFAULT '',
    saved_at     TIMESTAMPTZ DEFAULT now()
);

-- Manual run triggers (from Dashboard "Run Now" button)
CREATE TABLE IF NOT EXISTS run_triggers (
    id           BIGSERIAL PRIMARY KEY,
    requested_at TIMESTAMPTZ DEFAULT now(),
    status       TEXT DEFAULT 'pending',  -- pending | running | done | failed
    source       TEXT DEFAULT 'dashboard'
);
