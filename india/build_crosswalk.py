"""
Build a NCO-2004 -> NCO-2015 Family-code crosswalk from Vol I's Alphabetical
Index (pages 250-382), so Census 2011 employment data (coded in NCO-2004,
the classification in use at the time) can be summed up to NCO-2015 Family
codes (the level parse_nco.py extracts titles/descriptions at).

Each row of the Alphabetical Index directly states, per occupation:
    <Title>  <NCO-2015 8-digit code>  <NCO-2004 code, if one exists>
e.g. "Cardiologist 2212.0500 2221.50" - unlike the Concordance Table (which
groups entries under "Family NNNN" headers and requires tracking which
Family is "current" as you scan), every row here is self-contained, so
there's no state to get out of sync. (An earlier version of this script
used the Concordance Table and had exactly that bug: it never detected the
transition from the Concordance Table into the following Alphabetical
Index section, so tracking of the "current family" ran on past page ~249
into fundamentally differently-structured text, misattributing thousands of
Alphabetical Index rows to whatever Concordance Table family happened to be
last seen - e.g. every doctor code got folded into an unrelated family from
Division 9. Reading each row's own explicit NCO-2015 code avoids that whole
class of bug.)

We take a majority vote per NCO-2004 family across all its occurrences to
stay robust to stray noise in the PDF extraction.

Some NCO-2004 families split into several NCO-2015 families (e.g. NCO-2004
"2221" alone became NCO-2015's separate "2211 Generalist Medical
Practitioners" and "2212 Specialist Medical Practitioners"). A single
majority-vote mapping would silently zero out the loser, so instead this
writes a fractional distribution per NCO-2004 code, weighted by how many of
its individual occupations the Alphabetical Index shows landing in each
NCO-2015 family - e.g. 2221 -> {2211: 0.33, 2212: 0.67} - so Census's
employment count for that code splits proportionally across all of its
NCO-2015 successors rather than going entirely to just one.

Writes india/nco2004_to_2015.json:
    {nco2004_family_code: {nco2015_family_code: weight, ...}}
(weights for each nco2004_family_code sum to 1.0)

Usage:
    uv run python india/build_crosswalk.py
"""

import json
import re
from collections import Counter, defaultdict
import pdfplumber

FIRST_INDEX_PAGE = 250
LAST_INDEX_PAGE = 382

NCO2015_CODE_RE = re.compile(r"^(\d{4})\.\d{2,4}$")
NCO2004_CODE_RE = re.compile(r"^(\d{3,4})(?:\.\d{1,4})?$")
HEADER_NOISE = (
    "National Classification of Occupations",
    "Occupational NCO NCO",
    "Title 2015 2004",
    "ALPHABETICAL INDEX",
    "OF",
    "NCO 2015",
    "With Occupational Titles and Equivalent NCO 2004 Codes",
)


def extract_two_col_text(page):
    """Left-column-then-right-column reading order (mirrors parse_nco.py)."""
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    mid = page.width / 2
    left = [w for w in words if w["x0"] < mid]
    right = [w for w in words if w["x0"] >= mid]

    def to_lines(ws):
        lines = {}
        for w in ws:
            key = round(w["top"])
            lines.setdefault(key, []).append(w)
        out = []
        for k in sorted(lines):
            row = sorted(lines[k], key=lambda w: w["x0"])
            out.append(" ".join(w["text"] for w in row))
        return out

    return to_lines(left) + to_lines(right)


def clean_lines(lines):
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if any(s.startswith(h) or s == h for h in HEADER_NOISE):
            continue
        if re.match(r"^VOLUME\s+I\b", s, re.IGNORECASE):
            continue
        if re.match(r"^I{1,3}\s*-?\s*[AB]?$", s, re.IGNORECASE):
            continue
        if re.match(r"^\d{1,4}$", s):
            continue
        out.append(s)
    return out


def main():
    votes = defaultdict(Counter)

    with pdfplumber.open("india/raw/nco_vol1.pdf") as pdf:
        pages = pdf.pages[FIRST_INDEX_PAGE:LAST_INDEX_PAGE + 1]
        words = []
        for page in pages:
            lines = clean_lines(extract_two_col_text(page))
            words.extend(" ".join(lines).split())

    i = 0
    n = len(words)
    entries_found = 0
    while i < n:
        m = NCO2015_CODE_RE.match(words[i])
        if not m:
            i += 1
            continue
        family_2015 = m.group(1)
        entries_found += 1
        # The next token is the NCO-2004 code IF it looks like one; otherwise
        # this occupation has no old-code predecessor (new in NCO-2015) and
        # the next token starts the following entry's title.
        if i + 1 < n:
            m2 = NCO2004_CODE_RE.match(words[i + 1])
            if m2:
                family_2004 = m2.group(1)
                votes[family_2004][family_2015] += 1
                i += 2
                continue
        i += 1

    crosswalk = {}
    split_examples = []
    for code, counter in votes.items():
        total = sum(counter.values())
        crosswalk[code] = {fam: round(n / total, 4) for fam, n in counter.items()}
        if len(counter) > 1:
            split_examples.append((code, crosswalk[code]))

    with open("india/nco2004_to_2015.json", "w") as f:
        json.dump(crosswalk, f, indent=2, sort_keys=True)

    print(f"Scanned {entries_found} NCO-2015 code occurrences in the Alphabetical Index")
    print(f"Built crosswalk with {len(crosswalk)} NCO-2004 family codes mapped")
    print(f"{len(split_examples)} NCO-2004 codes split across multiple NCO-2015 families")

    # Sanity checks: the worked examples from the docs, and the doctors gap.
    for code in ["1111", "1112", "1113", "1119", "2221"]:
        print(f"  {code} -> {crosswalk.get(code)}")


if __name__ == "__main__":
    main()
