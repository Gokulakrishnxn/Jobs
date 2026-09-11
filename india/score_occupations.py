"""
Score each Indian occupation for AI exposure, growth outlook, and relative
pay via an LLM (OpenRouter), grounded in real PLFS 2023-24 category-average
earnings since India has no official per-occupation wage or growth-outlook
data (unlike BLS for the US).

Reads india/occupations.json + india/pages/<slug>.md (from parse_nco.py) and
india/employment.json (from build_employment.py, for the employment category
each Division typically falls into). Writes india/scores.json.

Grounding used (both layers are LLM ESTIMATES, clearly labeled as such on
the site, same as the US site's AI Exposure caveat):
  - AI Exposure: same 0-10 rubric as the US site's score.py, occupation-
    description-driven, not country-specific.
  - Pay: LLM returns a multiplier (roughly 0.3-3.0x) against the real PLFS
    2023-24 category average for that occupation's typical employment type
    (self-employed / regular wage-salaried / casual labour), so the anchor
    is real even though the per-occupation adjustment is estimated.
  - Growth outlook: LLM estimate (-10% to +20% band, mirroring BLS's scale)
    informed by general, well-known structural trends in the Indian labour
    market (declining agriculture share, growing IT/services/construction,
    roughly flat traditional manufacturing, automation pressure on clerical
    work) rather than a live per-sector statistical feed.

Usage:
    uv run python india/score_occupations.py
    uv run python india/score_occupations.py --start 0 --end 10
"""

import argparse
import json
import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "gemini-3.5-flash-lite"
OUTPUT_FILE = "india/scores.json"
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Real PLFS 2023-24 Annual Report category-average monthly earnings (₹),
# annualized (x12). Anchors for the LLM's pay multiplier.
PLFS_ANCHORS_ANNUAL = {
    "self_employed": 13279 * 12,       # 159,348
    "regular_wage_salaried": 20702 * 12,  # 248,424
    "casual_labour": 12750 * 12,       # 153,000
}

# Default employment-category assignment by NCO Division, used unless the
# LLM's own judgment (grounded in the occupation description) says otherwise.
DIVISION_DEFAULT_CATEGORY = {
    "1": "regular_wage_salaried",
    "2": "regular_wage_salaried",
    "3": "regular_wage_salaried",
    "4": "regular_wage_salaried",
    "5": "self_employed",
    "6": "self_employed",
    "7": "self_employed",
    "8": "regular_wage_salaried",
    "9": "casual_labour",
}

SYSTEM_PROMPT = """\
You are an expert analyst evaluating Indian occupations along three axes, \
using the National Classification of Occupations (NCO-2015). You'll be \
given an occupation's title and description.

Return ONLY a JSON object with these fields:

{
  "ai_exposure": <0-10>,
  "ai_exposure_rationale": "<1-2 sentences>",
  "growth_outlook_pct": <integer, -10 to 20>,
  "growth_outlook_rationale": "<1-2 sentences>",
  "pay_multiplier": <float, 0.3 to 3.0>,
  "pay_rationale": "<1 sentence>",
  "employment_category": "<one of: self_employed, regular_wage_salaried, casual_labour>",
  "education": "<one of: Below Secondary, Secondary, Higher Secondary, Diploma/ITI, Graduate, Postgraduate or higher>"
}

## AI Exposure (0-10)
How much will AI reshape this occupation? Consider both direct automation \
and indirect effects (AI making each worker more productive, needing fewer \
workers). A key signal: if the job's output is fundamentally digital \
(writing, coding, analysis, communication from a computer), exposure is \
high (7+) because AI capability in digital domains is advancing fast. Jobs \
requiring physical presence, manual skill, or real-time human interaction \
have a natural ceiling on exposure.
- 0-1 Minimal: almost entirely physical/hands-on (e.g. farm labourer, mason)
- 2-3 Low: mostly physical/interpersonal, AI touches only paperwork
- 4-5 Moderate: mixed physical and knowledge work
- 6-7 High: predominantly knowledge work with some judgment/presence needed
- 8-9 Very high: almost entirely computer-based work
- 10 Maximum: routine digital information processing, no physical component

## Growth Outlook (-10% to +20%)
Estimate this occupation's employment growth trajectory in India over the \
next decade, as a rough analog to BLS-style outlook percentages. Ground \
your estimate in well-known structural trends in the Indian labour market: \
agriculture's employment share has been declining for decades as workers \
move to non-farm work; IT/software services, e-commerce/logistics, \
construction, and healthcare have been growing; traditional manufacturing \
employment has been roughly flat to slowly growing; clerical/routine \
paperwork roles face automation pressure; the informal/gig economy is \
expanding for many service roles. This is a rough estimate, not a \
government projection - say so implicitly by keeping rationale brief and \
qualitative.

## Pay
India has no official per-occupation wage table (unlike the US), but PLFS \
(India's official labour force survey) publishes real 2023-24 average \
monthly earnings by broad employment category:
- Self-employed workers: ~₹13,279/month
- Regular wage/salaried employees: ~₹20,702/month
- Casual labourers: ~₹12,750/month (~₹418/day)

First, classify the occupation's most typical `employment_category` in the \
Indian labour market (most workers in that occupation are usually one of \
these three types - use your knowledge of how work is actually organized in \
India, not assumptions from other countries). Then give a `pay_multiplier` \
(0.3 to 3.0) estimating how this SPECIFIC occupation's typical pay compares \
to its category's average (e.g. a senior software engineer classified as \
regular_wage_salaried might be 2.5x that category's average; an unskilled \
helper classified as casual_labour might be 0.8x).

## Education
Pick the typical entry-level education for this occupation in India, from: \
Below Secondary, Secondary, Higher Secondary, Diploma/ITI, Graduate, \
Postgraduate or higher.

Respond with ONLY the JSON object, no other text.\
"""


def score_occupation(client, text, model, retries=4):
    url = API_URL.format(model=model)
    last_error = None
    for attempt in range(retries):
        try:
            response = client.post(
                url,
                params={"key": os.environ["GEMINI_API_KEY"]},
                json={
                    "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
                    "contents": [{"role": "user", "parts": [{"text": text}]}],
                    "generationConfig": {
                        "temperature": 0.2,
                        "responseMimeType": "application/json",
                    },
                },
                timeout=60,
            )
            if response.status_code in (429, 503):
                last_error = RuntimeError(f"HTTP {response.status_code} from Gemini API")
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            data = response.json()
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()
            return json.loads(content)
        except Exception as e:
            last_error = e
            time.sleep(2 ** attempt)
    raise last_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    if "GEMINI_API_KEY" not in os.environ:
        raise SystemExit("GEMINI_API_KEY not set. Add it to .env before running this script.")

    with open("india/occupations.json") as f:
        occupations = json.load(f)

    # Include the two Census aggregate categories (Cultivators, Agricultural
    # Labourers) so they get outlook/exposure estimates too.
    employment = json.load(open("india/employment.json"))
    for code, agg in employment.get("aggregates", {}).items():
        occupations.append({
            "code": agg["code"], "title": agg["title"],
            "division": agg["division"], "description": agg["description"],
            "slug": agg["code"].lower(),
        })

    subset = occupations[args.start:args.end]

    scores = {}
    if os.path.exists(OUTPUT_FILE) and not args.force:
        with open(OUTPUT_FILE) as f:
            for entry in json.load(f):
                scores[entry["code"]] = entry

    print(f"Scoring {len(subset)} occupations with {args.model}")
    print(f"Already cached: {len(scores)}")

    errors = []
    client = httpx.Client()

    for i, occ in enumerate(subset):
        code = occ["code"]
        if code in scores:
            continue

        md_path = f"india/pages/{occ['slug']}.md"
        if os.path.exists(md_path):
            with open(md_path) as f:
                text = f.read()
        else:
            text = f"# {occ['title']}\n\n{occ.get('description', '')}"

        print(f"  [{i+1}/{len(subset)}] {occ['title']}...", end=" ", flush=True)
        try:
            result = score_occupation(client, text, args.model)
            scores[code] = {"code": code, "title": occ["title"], **result}
            print(f"exposure={result.get('ai_exposure')} "
                  f"outlook={result.get('growth_outlook_pct')}% "
                  f"pay_mult={result.get('pay_multiplier')}")
        except Exception as e:
            print(f"ERROR: {e}")
            errors.append(code)

        with open(OUTPUT_FILE, "w") as f:
            json.dump(list(scores.values()), f, indent=2)

        if i < len(subset) - 1:
            time.sleep(args.delay)

    client.close()
    print(f"\nDone. Scored {len(scores)} occupations, {len(errors)} errors.")
    if errors:
        print(f"Errors: {errors}")


if __name__ == "__main__":
    main()
