# The Scout — وكيل استخبارات تنافسية لإعلانات MENA

وكيل بيكشط إعلانات منافسينك (Meta Ad Library + TikTok Creative Center عبر Apify)،
يخزّنها في Postgres+pgvector، يحوّلها لـ embeddings، يجمّعها في "ثيمات" بالـ
clustering، يقارن النهاردة بآخر ١٤ يوم عشان يكتشف الصاعد والمتشبّع، وبعدين Claude
بيطلّع **opportunity brief** واحد عالي الثقة (مع hooks جاهزة) — وبيحقن التقويم
الثقافي (رمضان/العيد/المواسم) في كل قرار.

> مبني تطويرًا على فكرة "GCC Playbook – The Scout"، بموديلات Claude الحالية.

## المخ (الخطوات)
`scrape → embed (voyage-3) → cluster (HDBSCAN) → diff (آخر 14 يوم) → reason (Claude) → emit event + brief`

أقوى إشارة لغياب بيانات الـ spend في MENA: **عمر الإعلان** (longevity) — اللي يفضل
شغّال أكتر من ٣٠ يوم بيتعلّم كمرشّح رابح، جنب اكتشاف الفراغ في السوق (whitespace).

## النشر على Railway (الموصى به)

1. **قاعدة البيانات:** أضف template **"Postgres + pgvector"** كـ service في مشروعك،
   وشغّل مرة واحدة `CREATE EXTENSION IF NOT EXISTS vector;` ثم محتوى `schema.sql`
   (من query editor في Railway).
2. **الـ service بتاع الوكيل:** اربط ريبو فيه الكود ده. Railway هيبني بـ Nixpacks.
3. **المتغيرات (Variables):**
   - `DATABASE_URL = ${{ pgvector.DATABASE_URL }}`  (شبكة خاصة، آمنة)
   - `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `APIFY_TOKEN`
   - `META_SOURCE=apify` و `USE_TIKTOK=true`
   - `APIFY_META_ACTOR` / `APIFY_TIKTOK_ACTOR` (اختر actor من Apify Store)
4. **الجدولة:** `railway.toml` فيه cron يومي 06:00 UTC. غيّره لـ `0 */4 * * *` للـ
   cadence كل ٤ ساعات (زي الـ Playbook)، أو اضبطه من الـ dashboard.

التكلفة التقريبية: Postgres+pgvector ~$5–15/شهر على Railway + استهلاك Apify
وVoyage وClaude حسب حجمك.

## الإعداد (config.py)
- `COMPETITOR_PAGE_IDS` / `SEARCH_TERMS` — مين تراقب.
- `COUNTRIES` — الدول (افتراضي SA, AE, EG).
- `STORE` — سياق براندك (نبرة، فئة، سوق، حملات، رابحين سابقين) → بيتحقن في تفكير الـ Scout.
- `CONFIDENCE_FLOOR` — تحتها الوكيل ميطلّعش brief (افتراضي 0.60).

## تشغيل محلي (اختياري)
```
pip install -r requirements.txt
cp .env.example .env        # املأ القيم (DATABASE_URL ممكن يكون Railway public URL)
python main.py
```
بيطلّع `reports/scout-YYYY-MM-DD.md` وبيكتب الحدث في جدول `agent_events`.

## مهم
- **مصادر Apify:** أسماء الحقول بتختلف بين الـ actors. شغّل الـ actor مرة، وعدّل
  `_map()` في `sources/apify_meta.py` / `tiktok_cc.py` حسب مخرجاته.
- الكشط منطقة ToS رمادية — Apify بيشغّله على بنيته؛ قرارك حسب بزنسك.
- المصدر مرن: `sources/base.py` هو الواجهة. أي مصدر مدفوع جديد = class واحد.
- التقويم في `calendar_mena.py` تقريبي (هلالي) — راجعه سنويًا.
- "Claude 4.7" في الـ Playbook الأصلي مش موديل حقيقي؛ هنا بنستخدم Sonnet 4.6 + Haiku 4.5.

## البنية
| ملف | الدور |
|-----|-------|
| `sources/` | المحوّلات: `apify_meta`, `tiktok_cc`, `meta_api` (رسمي fallback) |
| `db.py` + `schema.sql` | Postgres+pgvector: لقطات، clusters، agent_events |
| `embeddings.py` | Voyage embeddings |
| `cluster.py` | HDBSCAN + تسمية الثيمات |
| `diff.py` | مقارنة الثيمات عبر الزمن |
| `calendar_mena.py` | التقويم الثقافي |
| `scout.py` | تفكير Claude + الـ brief |
| `report.py` | رندر الـ brief |
| `main.py` | المنسّق |

## الخطوة الجاية (Phase 3)
- agent **Creative** يسمع حدث `opportunity_brief` ويولّد الكرييتف (الجزء التالي من الـ Playbook).
- لوحة + alerts على إعلانات جديدة + قياس الأداء بأثر رجعي (precision@30d, time-to-market).
