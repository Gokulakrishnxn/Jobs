"""
Parse NCO-2015 (National Classification of Occupations) PDFs into a clean
occupation list with descriptions, at the "Family" (4-digit code) level.

Reads india/raw/nco_vol2a.pdf and nco_vol2b.pdf (Occupational Description
volumes), which use a two-column layout per page. Extracts text in reading
order (left column top-to-bottom, then right column), then regex-parses
Division / Group / Family boundaries out of the reconstructed text stream.

Writes india/occupations.json (list of {code, title, division, description})
and india/pages/<slug>.md (one Markdown file per occupation, mirroring the
US pipeline's pages/<slug>.md so the same LLM-scoring pattern can reuse it).

Usage:
    uv run python india/parse_nco.py
"""

import difflib
import json
import os
import re
import pdfplumber

RAW_DIR = "india/raw"
OUT_DIR = "india"

HEADER_RE = re.compile(r"^National Classification of Occupations\s*[–-]\s*2015$")
VOLUME_RE = re.compile(r"^VOLUME\s*(I|II)?\s*-?\s*[AB]?$", re.IGNORECASE)
PAGENUM_RE = re.compile(r"^\d{1,4}$")


def extract_two_col_text(page):
    """Extract page text in left-column-then-right-column reading order."""
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


VOLTAG_RE = re.compile(r"^I{1,3}\s*-?\s*[AB]?$", re.IGNORECASE)


def clean_lines(lines):
    """Drop repeating page furniture: running header, volume watermark/tag,
    bare page numbers, and the "Division N" margin decoration that repeats
    on every page of a division (not a real section-boundary signal — the
    Division a Family belongs to is recovered later from its code's first
    digit instead, since the margin text is too noisy to use structurally)."""
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if HEADER_RE.match(re.sub(r"Division\s*\d+\s*$", "", s).strip()):
            continue
        if "National Classification of Occupations" in s and len(s) < 60:
            continue
        if VOLUME_RE.match(s) or VOLTAG_RE.match(s):
            continue
        if PAGENUM_RE.match(s):
            continue
        if re.match(r"^Division\s+\d+\s*$", s):
            continue
        out.append(s)
    return out


def extract_volume_text(pdf_path):
    lines = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_lines = extract_two_col_text(page)
            lines.extend(clean_lines(page_lines))
    return lines


DIVISION_RE = re.compile(r"^Division\s+(\d+)\s*$")
FAMILY_RE = re.compile(r"^Family\s+(\d{4})\s*$")
OCC_CODE_RE = re.compile(r"^(\d{4})\.(\d{2,4})$")
GROUP_RE = re.compile(r"^Group\s+(\d{3})\s*$")
SUBDIV_RE = re.compile(r"^Sub\s*[- ]?\s*Division\s+(\d{2})\s*$")

DIVISION_NAMES = {
    "1": "Managers",
    "2": "Professionals",
    "3": "Technicians and Associate Professionals",
    "4": "Clerical Support Workers",
    "5": "Service and Sales Workers",
    "6": "Skilled Agricultural, Forestry and Fishery Workers",
    "7": "Craft and Related Trades Workers",
    "8": "Plant and Machine Operators and Assemblers",
    "9": "Elementary Occupations",
}


def split_repeated_prefix(words, max_title_words=14):
    """Split [title-words-repeated][description...] into (title, description).

    NCO's layout renders each Family as a word-wrapped heading immediately
    followed by a paragraph whose opening words restate that same heading
    (e.g. "Legislators" then "Legislators determine, formulate..."). The
    title is the shortest prefix P where words[:len(P)] == words[len(P):2*len(P)].

    Two fallbacks handle blocks that don't fit that exact pattern:
    - Near-exact repeats (e.g. title "Health Services Managers" vs body
      "Health Service Managers plan...", or British/American spelling
      variants like Adviser/Advisor) are caught with a fuzzy ratio check.
    - "Not Elsewhere Classified" families don't restate the heading at all;
      their body starts with the fixed phrase "This unit group covers", so
      that phrase is used as the split point instead.
    """
    lowered = [w.lower().strip(",.;:") for w in words]
    limit = min(max_title_words, len(words) // 2)

    for length in range(1, limit + 1):
        if lowered[:length] == lowered[length:2 * length]:
            return words[:length], words[length:]

    for length in range(1, limit + 1):
        a = " ".join(lowered[:length])
        b = " ".join(lowered[length:2 * length])
        if difflib.SequenceMatcher(None, a, b).ratio() >= 0.8:
            return words[:length], words[length:]

    for length in range(1, min(max_title_words, len(words) - 1) + 1):
        if lowered[length] != "this":
            continue
        following = lowered[length + 1:length + 4]
        if "covers" in following:
            return words[:length], words[length:]

    return words, []


def parse_families(lines):
    """Walk the cleaned line stream and pull out one entry per Family code."""
    occupations = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        m = FAMILY_RE.match(line)
        if m:
            code = m.group(1)
            i += 1
            # Collect every line up to the next header/occupation-code as one
            # block. The PDF's heading is followed by a word-wrapped repeat of
            # itself as the opening subject of the description's first
            # sentence (e.g. "Legislators" / "Legislators determine..."), so
            # the title is recoverable as the shortest repeated word-prefix.
            block_lines = []
            while i < n:
                nxt = lines[i]
                if (FAMILY_RE.match(nxt) or GROUP_RE.match(nxt) or
                        SUBDIV_RE.match(nxt) or DIVISION_RE.match(nxt) or
                        OCC_CODE_RE.match(nxt)):
                    break
                block_lines.append(nxt)
                i += 1

            words = " ".join(block_lines).split()
            title_words, desc_words = split_repeated_prefix(words)
            title = " ".join(title_words).strip()
            description = " ".join(desc_words).strip()
            # Trim the "Occupations in this Group are classified into the
            # following Families:" list that sometimes leaks into a
            # description when a Group has no free-text body of its own.
            description = re.sub(
                r"Occupations in this (Group|Sub[- ]?Division|Division) are classified into the following (Families|Groups|Sub[- ]?Divisions):.*$",
                "", description).strip()

            occupations.append({
                "code": code,
                "title": title,
                "division": DIVISION_NAMES.get(code[0], code[0]),
                "description": description,
            })
            continue

        i += 1

    return occupations


def slugify(title):
    s = title.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:80].rstrip("-")


def main():
    all_occupations = []
    for fname in ["nco_vol2a.pdf", "nco_vol2b.pdf"]:
        path = os.path.join(RAW_DIR, fname)
        print(f"Extracting text from {fname}...")
        lines = extract_volume_text(path)
        print(f"  {len(lines)} lines after cleanup")
        occs = parse_families(lines)
        print(f"  {len(occs)} Family entries parsed")
        all_occupations.append((fname, occs))

    merged = []
    seen_codes = set()
    for fname, occs in all_occupations:
        for occ in occs:
            if occ["code"] in seen_codes:
                continue
            if not occ["title"]:
                continue
            seen_codes.add(occ["code"])
            occ["slug"] = f"{occ['code']}-{slugify(occ['title'])}"
            merged.append(occ)

    merged.sort(key=lambda o: o["code"])

    os.makedirs(os.path.join(OUT_DIR, "pages"), exist_ok=True)
    with open(os.path.join(OUT_DIR, "occupations.json"), "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    for occ in merged:
        md = [
            f"# {occ['title']}",
            "",
            f"**NCO-2015 Family Code:** {occ['code']}",
            f"**Division:** {occ['division']}",
            "",
            "## Description",
            "",
            occ["description"] or "(no description extracted)",
            "",
        ]
        with open(os.path.join(OUT_DIR, "pages", f"{occ['slug']}.md"), "w") as f:
            f.write("\n".join(md))

    print(f"\nWrote {len(merged)} occupations to {OUT_DIR}/occupations.json")
    print(f"Wrote {len(merged)} Markdown files to {OUT_DIR}/pages/")

    empties = sum(1 for o in merged if not o["description"] or len(o["description"]) < 20)
    print(f"Occupations with thin/missing description: {empties}")

    print("\nSample:")
    for occ in merged[:5]:
        print(f"  {occ['code']} {occ['title']} [{occ['division']}]")
        print(f"    {occ['description'][:150]}")


if __name__ == "__main__":
    main()
