"""
Recalibrate employment.json's Division-level totals to real PLFS 2023-24
figures, and replace the flat regular-wage-salaried pay anchor with real
per-Division wages — both from the official PLFS Annual Report 2023-24
(July 2023 - June 2024), Ministry of Statistics and Programme
Implementation (mospi.gov.in), Appendix-A.

Why: employment.json (build_employment.py) is built from Census 2011 -
India's most recent full census, but 13 years old. PLFS is MoSPI's current
annual labour force survey and publishes, natively in NCO-2015 codes:

  - Table (25): % distribution of workers by occupation Division (2023-24)
  - Table (50): average monthly wage/salary earnings (Rs.) of regular
    wage/salaried employees by occupation Division (2023-24)

This keeps the total workforce anchored to the Census-reconciled figure
(so nothing is invented) but rescales each Division's share of that total
to match the current PLFS distribution, then redistributes each Division's
new total across its constituent NCO-2015 Families in the SAME relative
proportions the Census data already established (2011 shape, 2023-24
scale) - the best available combination of "current" and "detailed".

Usage:
    uv run python india/apply_plfs_2023_24.py
"""

import json

# Table (25), rural+urban person column, all-India, PLFS 2023-24
# (Annual Report PLFS 2023-24, Appendix-A, p.209-211, mospi.gov.in)
PLFS_DIVISION_SHARE_PCT = {
    "1": 3.16, "2": 5.28, "3": 2.26, "4": 2.11, "5": 11.54,
    "6": 37.97, "7": 11.09, "8": 5.32, "9": 21.28,
}

# Table (50)/(33), rural+urban person column, monthly Rs., PLFS 2023-24
PLFS_DIVISION_REGULAR_WAGE_MONTHLY = {
    "1": 42993, "2": 35776, "3": 24199, "4": 23616, "5": 14628,
    "6": 11319, "7": 15350, "8": 15906, "9": 10667,
}


def main():
    employment = json.load(open("india/employment.json"))
    by_family = employment["by_family"]
    aggregates = employment["aggregates"]
    unclassified = employment["unclassified"]

    # Every "unit" that carries employment: NCO families, the two Census
    # aggregates (Cultivators -> Division 6, Agricultural Labourers ->
    # Division 9), and the per-Division unclassified buckets.
    units = {code: {"division": code[0], "persons": persons} for code, persons in by_family.items()}
    units["CULT"] = {"division": "6", "persons": aggregates["CULT"]["persons"]}
    units["AGLAB"] = {"division": "9", "persons": aggregates["AGLAB"]["persons"]}
    for code, unc in unclassified.items():
        units[code] = {"division": code.replace("UNCL", ""), "persons": unc["persons"]}

    old_total = sum(u["persons"] for u in units.values())

    # "UNCLX" (Census rows with no reported/classifiable occupation, ~25.5M
    # workers) isn't a Division at all and has no PLFS Table 25 counterpart -
    # it must be excluded from the Division 1-9 redistribution base and kept
    # untouched, or its value gets redistributed into 1-9 as well as kept
    # separately (silently inflating total workforce).
    real_division_units = {code: u for code, u in units.items() if u["division"] in PLFS_DIVISION_SHARE_PCT}
    non_division_total = old_total - sum(u["persons"] for u in real_division_units.values())

    # Current (2011-derived) share per Division, for comparison/logging.
    old_division_totals = {}
    for u in real_division_units.values():
        old_division_totals[u["division"]] = old_division_totals.get(u["division"], 0) + u["persons"]

    # Redistribution base excludes the unclassifiable/non-reported chunk,
    # which is added back untouched at the end.
    redistributable_total = old_total - non_division_total
    new_division_totals = {d: redistributable_total * pct / 100 for d, pct in PLFS_DIVISION_SHARE_PCT.items()}

    print(f"Non-Division (unclassifiable/not reported) workers kept as-is: {non_division_total:,}")
    print("Division  2011-shape share   2023-24 PLFS share   old total    new total")
    for d in sorted(PLFS_DIVISION_SHARE_PCT):
        old_pct = old_division_totals.get(d, 0) / redistributable_total * 100
        print(f"  {d}       {old_pct:6.2f}%              {PLFS_DIVISION_SHARE_PCT[d]:6.2f}%           "
              f"{old_division_totals.get(d, 0):>12,.0f} {new_division_totals[d]:>12,.0f}")

    # Redistribute each Division's new total across its units, preserving
    # each unit's relative share *within* its own Division from the Census
    # data (2011 shape, 2023-24 scale).
    rescaled_by_family = {}
    rescaled_aggregates = {"CULT": dict(aggregates["CULT"]), "AGLAB": dict(aggregates["AGLAB"])}
    rescaled_unclassified = {k: dict(v) for k, v in unclassified.items()}

    for division, new_total in new_division_totals.items():
        division_units = {code: u for code, u in units.items() if u["division"] == division}
        old_division_total = sum(u["persons"] for u in division_units.values())
        for code, u in division_units.items():
            share = u["persons"] / old_division_total if old_division_total > 0 else 0
            new_value = round(new_total * share)
            if code == "CULT":
                rescaled_aggregates["CULT"]["persons"] = new_value
            elif code == "AGLAB":
                rescaled_aggregates["AGLAB"]["persons"] = new_value
            elif code in rescaled_unclassified:
                rescaled_unclassified[code]["persons"] = new_value
            else:
                rescaled_by_family[code] = new_value

    employment["by_family"] = rescaled_by_family
    employment["aggregates"] = rescaled_aggregates
    employment["unclassified"] = rescaled_unclassified
    employment["source"] = (
        employment["source"] +
        "; Division-level totals recalibrated to PLFS Annual Report 2023-24 "
        "(Table 25 occupation shares, Table 50 regular wage/salary earnings "
        "by NCO-2015 Division), Ministry of Statistics and Programme "
        "Implementation - internal per-occupation shape kept from Census 2011"
    )

    new_total_check = (sum(rescaled_by_family.values()) + sum(a["persons"] for a in rescaled_aggregates.values())
                        + sum(u["persons"] for u in rescaled_unclassified.values()))
    print(f"\nTotal workforce before: {old_total:,}  after: {new_total_check:,} (should match)")

    with open("india/employment.json", "w") as f:
        json.dump(employment, f, indent=2)

    # Real per-Division wage anchors for regular wage/salaried, annualized.
    wage_anchors = {d: round(v * 12) for d, v in PLFS_DIVISION_REGULAR_WAGE_MONTHLY.items()}
    with open("india/plfs_division_wages.json", "w") as f:
        json.dump(wage_anchors, f, indent=2)
    print("\nWrote india/plfs_division_wages.json (annual Rs. by NCO-2015 Division):")
    for d, v in wage_anchors.items():
        print(f"  Division {d}: Rs.{v:,}/year")


if __name__ == "__main__":
    main()
