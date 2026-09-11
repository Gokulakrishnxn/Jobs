# India Job Market Visualizer

An interactive treemap of India's labour market — **367 occupations**, **~362.5M workers**, colored by growth outlook, pay, education, or AI exposure. Built from official Government of India statistics wherever they exist, and explicit about the two layers where they don't.

This is a research and exploration tool, not an official statistic. It exists to make a large, messy dataset easy to look at — not to be cited as a labour market report.

## Why this exists

The US has a single document — the Bureau of Labor Statistics' [Occupational Outlook Handbook](https://www.bls.gov/ooh/) — that publishes duties, pay, education, and a ten-year growth projection together for every occupation. **India has no equivalent.** No single Indian publication states pay, growth, and education by occupation in one place.

So this project assembles the closest official source for each layer separately — a census for who does what, a labour survey for how much they earn, an occupation classification for what the jobs are called — and is explicit, on the site itself, about which numbers are sourced and which are estimated.

## What each layer actually is

| Layer | Source | Status |
|---|---|---|
| Occupation list | [NCO-2015](https://labour.gov.in/) — National Classification of Occupations, Ministry of Labour & Employment | Official |
| Employment (tile size) | [Census of India 2011](https://censusindia.gov.in/), table B-25A + Primary Census Abstract | Official, rescaled to a real 2023-24 share per Division |
| Est. Annual Pay | [PLFS Annual Report 2023-24](https://www.mospi.gov.in/), MoSPI | Official anchor, per-occupation adjustment is LLM-estimated |
| Growth Outlook | — | Fully LLM-estimated (no official Indian source exists) |
| Digital AI Exposure | — | Fully LLM-estimated, same rubric as the original US visualizer |

**At a glance:** 355 of 436 NCO-2015 occupations are matched to real Census employment data (81%); the rest are folded into a per-Division "unclassified" tile rather than dropped, so total employment always reconciles to the real Census figure. Average estimated pay across all workers is **₹1.95L/year**; total estimated annual wages are **₹65.3 lakh crore**.

A full explanatory FAQ — what each tile means, why some occupations split or merge, what the known gaps are — lives at [`india/README.md`](india/README.md).

## Run it

```bash
uv sync
cd india/site && python -m http.server 8001
```

Open `http://localhost:8001`.

## Rebuild the data

Needs a Gemini API key in `.env`:

```
GEMINI_API_KEY=your_key_here
```

Then, from the repo root, in order:

```bash
uv run python india/parse_nco.py            # NCO-2015 PDFs -> occupations.json
uv run python india/build_crosswalk.py       # NCO-2004 <-> NCO-2015 code crosswalk
uv run python india/build_employment.py      # Census 2011 -> employment.json
uv run python india/apply_plfs_2023_24.py    # rescale to real 2023-24 PLFS shares
uv run python india/score_occupations.py     # LLM: outlook, exposure, pay multiplier
uv run python india/build_site_data.py       # merge everything -> site/data.json
```

Each step is documented in detail — including why the pipeline is shaped this way — in [`india/README.md`](india/README.md).

## Project structure

```
india/
├── raw/                       downloaded NCO-2015 PDFs, Census & PLFS Excel files
├── pages/                     one Markdown file per occupation, for LLM scoring
├── occupations.json           436 NCO-2015 occupations: code, title, description
├── nco2004_to_2015.json       old-code -> new-code crosswalk
├── employment.json            real employment counts per occupation
├── scores.json                LLM-estimated outlook / exposure / pay multiplier
├── plfs_division_wages.json   real PLFS wages by NCO Division
├── site/                      the static treemap (index.html + data.json)
└── *.py                       the pipeline scripts, run in the order above
```

## Limitations

- Census 2011 is India's most recent full census (2021's was deferred), so occupation-level *detail* is thirteen years old even though each Division's *total* is rescaled to 2023-24.
- Growth Outlook and Digital AI Exposure are LLM estimates, not government projections — treat them as an exploratory lens, not a forecast.
- ~81 occupations have no confident match to a 2011-era occupation code and are grouped rather than shown individually; a further 25.5M workers are Census respondents whose occupation was never reported or couldn't be classified at all.

## Credits

Adapted from the original [US Job Market Visualizer](https://karpathy.ai/jobs/), built by Andrej Karpathy on BLS data. Indian sourcing, pipeline, and site: NCO-2015 (Ministry of Labour & Employment), Census of India 2011 (ORGI), PLFS Annual Report 2023-24 (MoSPI), and Gemini for the two estimated layers.
