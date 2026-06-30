"""
The Scout's reasoning step (Claude). Turns the diffed clusters + store context +
cultural calendar into ONE high-confidence opportunity brief.

Adapted from the GCC Playbook prompt, using current Claude models and honest
confidence gating (below CONFIDENCE_FLOOR => emit nothing).
"""

import json
from anthropic import Anthropic

from claude_retry import call_claude

SCOUT_SYSTEM = """You are the Scout agent for a MENA e-commerce brand.
Your job: examine the competitive landscape and identify ONE high-confidence
positioning or creative gap the brand should capture in the next 7-14 days.

INPUT you receive (JSON):
- STORE_CONTEXT: brand voice, category, country, current campaigns, past winners
- TODAY: today's competitor ad themes, each with status
  (new | rising | stable | declining | saturated)
- PREVIOUS: the same themes ~14 days ago
- CULTURAL_CALENDAR: upcoming MENA events with suggested angle bias

REASONING:
1. From TODAY, note themes that are NEW or RISING (opportunity) and ones that are
   SATURATED or DECLINING (avoid / creative fatigue).
2. For each candidate, weigh: alignment with STORE_CONTEXT brand voice, competitive
   density (lower = more whitespace), and resonance for the store's country.
3. Pick the SINGLE best theme = strong fit x low density x cultural timing.
4. Write the brief.

CRITICAL RULES:
- If CULTURAL_CALENDAR has an event within its window, bias toward its angle_bias.
- Arabic hooks required if store country in [SA, AE, QA, KW, BH, OM]; use the
  right dialect (Khaleeji for Gulf, Egyptian for EG) — not generic MSA.
- Do NOT mimic a single competitor; aim for category whitespace.
- Be honest about confidence (0-1). If below 0.6, set "confidence" accordingly and
  set "emit": false.

OUTPUT: strict JSON only, this schema:
{
  "emit": true/false,
  "theme": "...",
  "confidence": 0.0,
  "reasoning": "why this gap, why now (reference the data)",
  "target_angle": "...",
  "hooks": ["...", "..."],
  "creative_directions": ["...", "...", "..."],
  "avoid": ["saturated themes to stay away from"],
  "window_days": 14
}"""


def reason(store: dict, diff_result: dict, previous: list[dict],
           calendar: list[dict], api_key: str, model: str,
           floor: float) -> dict:
    payload = {
        "STORE_CONTEXT": store,
        "TODAY": diff_result["today"],
        "PREVIOUS": [{"theme": p.get("theme"), "size": p.get("size"),
                      "competitor_count": p.get("competitor_count")} for p in previous],
        "CULTURAL_CALENDAR": calendar,
    }
    client = Anthropic(api_key=api_key) if api_key else Anthropic()
    try:
        msg = call_claude(
            client,
            model=model,
            max_tokens=1500,
            system=SCOUT_SYSTEM,
            messages=[{"role": "user",
                       "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
        )
        text = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        brief = json.loads(text)
    except Exception as e:
        return {"emit": False, "confidence": 0.0, "error": str(e)[:200]}

    # Enforce the floor regardless of what the model said about "emit".
    if float(brief.get("confidence", 0)) < floor:
        brief["emit"] = False
    return brief
