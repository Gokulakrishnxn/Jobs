# India Job Market Visualizer

A research tool for visually exploring India's labour market, adapted from
the [US Job Market Visualizer](../README.md). Same treemap idea — each
rectangle's **area** is total employment, **color** is the selected metric —
but India has no single source like BLS's Occupational Outlook Handbook, so
this assembles the closest real government sources for each layer, and is
explicit about which layers are official data vs. LLM estimates.

**Run it:**
```bash
cd site && python -m http.server 8001
```

## Data sources

| Layer | Source | Notes |
|---|---|---|
| Occupation taxonomy + descriptions | [NCO-2015](https://labour.gov.in/) (National Classification of Occupations), 3 official PDF volumes | 436 occupations at the "Family" (4-digit code) level |
| Employment (tile size) | [Census of India 2011](https://censusindia.gov.in/), table B-25A + Primary Census Abstract | Detailed occupational *shape* from Census 2011 (most recent full census); each Division's *total* rescaled to its real 2023-24 share from PLFS Table 25 |
| Est. Annual Pay | [PLFS Annual Report 2023-24](https://www.mospi.gov.in/) | Regular wage/salaried: real average earnings by NCO-2015 Division (Table 50). Self-employed/casual labour: national PLFS averages (no official occupation-level breakdown exists). LLM adjusts within these real anchors per occupation. |
| Growth Outlook, Digital AI Exposure | LLM estimate (Gemini) | No official per-occupation growth data exists for India at all |

## Pipeline

1. `parse_nco.py` — extracts occupations.json + pages/*.md from the NCO-2015 PDFs (two-column layout, needs `pdfplumber`)
2. `build_crosswalk.py` — builds the NCO-2004↔NCO-2015 code crosswalk from Vol I's concordance table (Census used the older NCO-2004 codes)
3. `build_employment.py` — merges Census B-25A + Primary Census Abstract into employment.json via the crosswalk
4. `apply_plfs_2023_24.py` — rescales each Division's total to its real PLFS 2023-24 share, and extracts real per-Division wages (Table 50) into plfs_division_wages.json
5. `score_occupations.py` — LLM-scores each occupation for AI exposure, growth outlook, and a pay multiplier (needs `GEMINI_API_KEY` in `.env`)
6. `build_site_data.py` — merges everything into `site/data.json`

Re-run in that order after changing any upstream step. `raw/` holds the
downloaded PDFs/Excel files so nothing needs re-fetching.

## Known limitations

- Census used NCO-2004, one classification revision behind NCO-2015. The
  crosswalk (`build_crosswalk.py`) is built from Vol I's Alphabetical Index,
  which states each NCO-2015 occupation's NCO-2004 equivalent directly (no
  fragile state-tracking needed, unlike the Concordance Table's
  Family-header layout). About 80 of NCO-2015's ~440 occupations still
  couldn't be matched to any NCO-2004 code at all (genuinely new in 2015)
  and are bucketed as "unclassified" per Division rather than appearing
  individually. Where one NCO-2004 code split into several NCO-2015
  occupations (e.g. doctors), its Census count is divided across them by
  weight rather than assigned to just one. Total employment always
  reconciles to the real Census figure regardless.
- ~15% of Census B-25A's workers fall under NCO-2004 codes with no crosswalk
  match at all and are bucketed as "unclassified" per Division; a further
  ~25.5M workers whose Census response was not reported/classifiable form a
  separate "Not Reported / Unclassifiable" tile.
- Growth Outlook and Digital AI Exposure are LLM estimates, not government
  projections.
