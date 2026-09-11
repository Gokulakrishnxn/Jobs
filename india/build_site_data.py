"""
Build the compact JSON for the India site by merging:
  - india/occupations.json      (NCO-2015 titles/descriptions, parse_nco.py)
  - india/employment.json       (Census 2011 employment counts, build_employment.py)
  - india/scores.json           (LLM exposure/outlook/pay estimates, score_occupations.py)

Writes india/site/data.json in the same shape the US site/index.html expects,
so the same frontend rendering code works unmodified.

Usage:
    uv run python india/build_site_data.py
"""

import json
import os

PLFS_ANCHORS_ANNUAL = {
    "self_employed": 13279 * 12,
    "regular_wage_salaried": 20702 * 12,  # national flat fallback
    "casual_labour": 12750 * 12,
}


def division_digit(code):
    """Recover the NCO-2015 Division (1-9) a tile's code belongs to, for
    looking up PLFS's real per-Division wage figures. Returns None for
    codes with no real Division (the Census "not reported/classifiable"
    residual bucket)."""
    if code[0].isdigit():
        return code[0]
    if code == "CULT":
        return "6"
    if code == "AGLAB":
        return "9"
    if code.startswith("UNCL"):
        suffix = code[4:]
        return suffix if suffix.isdigit() else None
    return None


def outlook_bucket(pct):
    """Mirror BLS's own outlook-description buckets, for the tooltip text."""
    if pct is None:
        return ""
    if pct < 0:
        return "Decline"
    if pct <= 3:
        return "Slower than average"
    if pct <= 7:
        return "Average"
    if pct <= 14:
        return "Faster than average"
    return "Much faster than average"


def main():
    occupations = json.load(open("india/occupations.json"))
    employment = json.load(open("india/employment.json"))
    scores_list = json.load(open("india/scores.json"))
    scores = {s["code"]: s for s in scores_list}
    plfs_division_wages = json.load(open("india/plfs_division_wages.json"))

    by_family = employment["by_family"]
    aggregates = employment["aggregates"]
    unclassified = employment["unclassified"]

    # Occupations from parse_nco.py, plus the two Census aggregates (which
    # aren't NCO occupations but need tiles too), plus the per-Division
    # unclassified residual buckets.
    all_entries = list(occupations)
    for agg in aggregates.values():
        all_entries.append({**agg, "slug": agg["code"].lower()})
    for unc in unclassified.values():
        all_entries.append({**unc, "slug": unc["code"].lower()})

    data = []
    skipped_no_jobs = 0
    skipped_no_score = 0
    for occ in all_entries:
        code = occ["code"]
        jobs = by_family.get(code) or occ.get("persons")
        if not jobs:
            skipped_no_jobs += 1
            continue

        score = scores.get(code)
        if not score:
            skipped_no_score += 1

        pay = None
        if score:
            category = score.get("employment_category", "self_employed")
            if category == "regular_wage_salaried":
                div = division_digit(code)
                anchor = plfs_division_wages.get(div, PLFS_ANCHORS_ANNUAL["regular_wage_salaried"])
            else:
                anchor = PLFS_ANCHORS_ANNUAL.get(category, PLFS_ANCHORS_ANNUAL["self_employed"])
            mult = score.get("pay_multiplier", 1.0)
            pay = round(anchor * mult)

        outlook = score.get("growth_outlook_pct") if score else None

        data.append({
            "title": occ["title"],
            "slug": occ["slug"],
            "code": code,
            "category": occ["division"],
            "description": occ.get("description") or "",
            "pay": pay,
            "pay_rationale": score.get("pay_rationale") if score else None,
            "employment_category": score.get("employment_category") if score else None,
            "jobs": jobs,
            "outlook": outlook,
            "outlook_desc": outlook_bucket(outlook),
            "outlook_rationale": score.get("growth_outlook_rationale") if score else None,
            "education": score.get("education") if score else None,
            "exposure": score.get("ai_exposure") if score else None,
            "exposure_rationale": score.get("ai_exposure_rationale") if score else None,
            "url": "",
        })

    os.makedirs("india/site", exist_ok=True)
    with open("india/site/data.json", "w") as f:
        json.dump(data, f)

    total_jobs = sum(d["jobs"] for d in data if d["jobs"])
    print(f"Wrote {len(data)} occupations to india/site/data.json")
    print(f"Skipped (no employment count): {skipped_no_jobs}")
    print(f"Missing LLM score: {skipped_no_score}")
    print(f"Total jobs represented: {total_jobs:,}")


if __name__ == "__main__":
    main()
