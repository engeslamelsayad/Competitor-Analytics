"""
Central configuration for the Scout agent.
Secrets come from environment variables (Railway Variables / .env).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Secrets ------------------------------------------------------------------
DATABASE_URL      = os.environ.get("DATABASE_URL", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY    = os.environ.get("VOYAGE_API_KEY", "")
APIFY_TOKEN       = os.environ.get("APIFY_TOKEN", "")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")

# --- Data sources -------------------------------------------------------------
META_SOURCE        = os.environ.get("META_SOURCE", "apify")
USE_TIKTOK         = os.environ.get("USE_TIKTOK", "true").lower() == "true"
APIFY_META_ACTOR   = os.environ.get("APIFY_META_ACTOR",
                                    "curious_coder~facebook-ads-library-scraper")
APIFY_TIKTOK_ACTOR = os.environ.get("APIFY_TIKTOK_ACTOR",
                                    "doliz~tiktok-creative-center-scraper")
META_API_VERSION   = os.environ.get("META_API_VERSION", "v22.0")

# --- WHO + WHERE to track -----------------------------------------------------
COMPETITOR_PAGE_IDS: list[str] = []

# ── Smart Search Terms ────────────────────────────────────────────────────────
# بدل ما تحط list بسيطة، حدد لكل term حجمها عشان تتحكم في التكلفة.
# "primary"  → أوسع مصطلح يعبّر عن الفئة → count كبير (150-200)
# "secondary" → مصطلحات تانية مترادفة أو أضيق → count صغير (30-50)
#
# مثال: منتج بواسير
# SEARCH_TERMS_CONFIG = [
#     {"term": "بواسير",          "count": 150, "primary": True},
#     {"term": "بخاخ بواسير",    "count": 30},
#     {"term": "علاج بواسير",    "count": 30},
#     {"term": "اعشاب بواسير",   "count": 30},
# ]
#
# لو عندك منتج واحد وكلمة بحث واحدة، سيب القائمة البسيطة:
SEARCH_TERMS_CONFIG: list[dict] = [
    {"term": "Yularay", "count": 150, "primary": True},
    {"term": "Junara", "count": 30},
]

# للتوافق مع الكود القديم — مش تلمسه
SEARCH_TERMS: list[str] = [c["term"] for c in SEARCH_TERMS_CONFIG]

COUNTRIES = ["EG"]

# --- Store context ------------------------------------------------------------
STORE = {
    "name":             "متجرك",
    "category":         "skincare",
    "country":          "SA",
    "platform":         "Shopify",
    "brand_voice":      "اكتب نبرة البراند وجمهورك المستهدف.",
    "current_campaigns":"الحملات الشغّالة دلوقتي.",
    "past_winners":     "الإعلانات اللي اشتغلت قبل كده.",
}

# --- Models -------------------------------------------------------------------
EMBED_MODEL  = "voyage-3"
EMBED_DIM    = 1024
LABEL_MODEL  = "claude-haiku-4-5-20251001"
SCOUT_MODEL  = "claude-sonnet-4-6"

# --- Brain params -------------------------------------------------------------
MIN_CLUSTER_SIZE        = 4
DIFF_WINDOW_DAYS        = 14
CLUSTER_MATCH_THRESHOLD = 0.72
CONFIDENCE_FLOOR        = 0.60
SEASONAL_WINDOW_DAYS    = 21
WINNER_DAYS_THRESHOLD   = 30

MAX_ADS_PER_QUERY = 200   # fallback لو مش بتستخدم SEARCH_TERMS_CONFIG
REPORT_DIR        = os.environ.get("REPORT_DIR", "reports")