"""
Central configuration for the Scout — competitive-intelligence agent.
Secrets come from environment variables (Railway variables / .env).
Edit the non-secret lists (competitors, countries, store context) here.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --- Secrets ------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")          # Railway Postgres+pgvector
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
VOYAGE_API_KEY = os.environ.get("VOYAGE_API_KEY", "")
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")  # only for official-API fallback

# --- Which data sources to use ------------------------------------------------
# "apify"   -> scrape public Ad Library via Apify (real MENA commercial coverage)
# "meta_api"-> official API (free, but commercial = EU/UK only)
META_SOURCE = os.environ.get("META_SOURCE", "apify")
USE_TIKTOK = os.environ.get("USE_TIKTOK", "true").lower() == "true"

# Apify actors (pick from Apify Store; field mapping may need light tweaks).
APIFY_META_ACTOR = os.environ.get("APIFY_META_ACTOR", "curious_coder/facebook-ads-library-scraper")
APIFY_TIKTOK_ACTOR = os.environ.get("APIFY_TIKTOK_ACTOR", "doliz/tiktok-creative-center-scraper")

# Official Meta API (fallback)
META_API_VERSION = os.environ.get("META_API_VERSION", "v22.0")

# --- WHO + WHERE --------------------------------------------------------------
COMPETITOR_PAGE_IDS: list[str] = ["786079437911484"]
SEARCH_TERMS: list[str] = ["Yularay", "cosmetics"]
COUNTRIES = ["SA", "AE", "EG"]   # GCC + Egypt; edit freely

# --- Store context (fed into the Scout's reasoning) ---------------------------
STORE = {
    "name": "Junara",
    "category": "cosmetics",          # فئة منتجك
    "country": "EG",                  # سوقك الأساسي
    "platform": "Shopify",
    "brand_voice": "حنونه و عطوفه",
    "current_campaigns": "منتجات لعلاج الاسنان",
    "past_winners": "",
}

# --- Models -------------------------------------------------------------------
EMBED_MODEL = "voyage-3"             # أحسن للعربي من ada-002
EMBED_DIM = 1024                     # لازم يطابق عمود vector() في schema.sql
LABEL_MODEL = "claude-haiku-4-5-20251001"   # تسمية رخيصة للـ clusters
SCOUT_MODEL = "claude-sonnet-4-6"           # التفكير الأساسي

# --- Brain params -------------------------------------------------------------
MIN_CLUSTER_SIZE = 4                 # أقل من 4 إعلانات = إشارة ضعيفة
DIFF_WINDOW_DAYS = 14                # نقارن النهاردة بكام يوم فاتوا
CLUSTER_MATCH_THRESHOLD = 0.72       # cosine لمطابقة theme عبر اللقطات
CONFIDENCE_FLOOR = 0.60              # تحت كده الـ Scout ميطلّعش brief
SEASONAL_WINDOW_DAYS = 21            # نبدأ نحقن الموسم قبله بكام يوم

WINNER_DAYS_THRESHOLD = 30           # إشارة longevity إضافية
MAX_ADS_PER_QUERY = 200

REPORT_DIR = os.environ.get("REPORT_DIR", "reports")
