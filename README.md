# MeisterKompass

An independent, non-commercial comparison platform for Meister preparation
courses offered by Handwerkskammern (HWK) in Germany.

Enables direct comparison of prices, duration, and exam fees across chambers,
as well as calculation of AFBG (Aufstiegs-BAföG) funding.

Current scope: five chambers — four in Rhineland-Palatinate (Koblenz, Pfalz,
Rheinhessen, Trier) and HWK des Saarlandes.

---

## Architecture

MeisterKompass is a **static site backed by checked-in JSON data** — no server,
no database.

```
Python scrapers ──▶ data/*.json (committed) ──▶ Vite static site ──▶ GitHub Pages
   (weekly CI)         (git is the audit log)      (build-time import)
```

1. **Scrapers** (`scrapers/`, Python) fetch each chamber's course pages and write
   the dataset to `data/*.json`. A weekly GitHub Action runs them and commits the
   changed JSON.
2. **Static site** (`web/`, Vite multi-page app) imports the JSON at build time and
   renders the Kursfinder, map, and AFBG calculator entirely client-side.
3. A push to `data/**` or `web/**` triggers a GitHub Pages deploy.

### Repo layout

```
meisterkompass/
├── scrapers/                 # Python scrapers + pipeline (no Django)
│   ├── base.py               # BaseScraper, dataclasses, slugify, build_course_title
│   ├── hwk_*.py              # five chamber scrapers (parsing logic)
│   ├── fees.py               # exam-fee resolution (scraped + manual overlay)
│   ├── geocode.py            # Photon geocoder + committed cache
│   ├── pipeline.py           # scrape → merge → geocode → resolve → write JSON
│   └── run.py                # CLI: python -m scrapers.run
├── data/                     # checked-in dataset (consumed by web, written by CI)
│   ├── courses.json          # course offers (with resolved exam_fee baked in)
│   ├── course_fees.json      # AFBG "next available" fee projection
│   ├── exam_fees.json        # raw per-part fee table (nested + flat)
│   ├── chambers.json  trades.json
│   ├── manual/exam_fees_manual.json   # hand-edited curated fees (Koblenz, Rheinhessen)
│   └── cache/geocode_cache.json       # CI-maintained address → [lat,lng]
├── web/                      # Vite static MPA
│   ├── index.html afbg.html about.html imprint.html
│   └── src/{base.css,list.css,afbg.css,nav.js,list.js,map.js,afbg.js}
├── scripts/export_legacy_data.py  # ONE-TIME Django→JSON migration helper
├── mise.toml                 # pins python 3.12 + node 22
└── .github/workflows/{scrape.yml, deploy.yml}
```

---

## Toolchain

Runtimes are managed with **mise**; Python packages with **uv**; frontend packages
with **npm** (Node from mise).

```bash
mise install                 # provision python 3.12 + node 22
```

---

## Scrapers (Python)

```bash
uv venv
uv pip install -r requirements.txt

python -m scrapers.run                     # all chambers → write data/*.json
python -m scrapers.run --chamber hwk-pfalz # one chamber
python -m scrapers.run --dry-run           # scrape + log counts, write nothing
```

The pipeline:
- **merges** the fresh scrape with the existing `data/courses.json`, retaining past
  courses (history) and dropping future courses no longer offered;
- **geocodes** new addresses via Photon (Komoot/OSM), caching results in
  `data/cache/geocode_cache.json`, and applies hardcoded coordinates for HWK Saarland
  and HWK Rheinhessen;
- **resolves** each course's exam fee from scraped fees overlaid with the curated
  `data/manual/exam_fees_manual.json` (manual entries always win).

Manually-curated exam fees (HWK Koblenz "bis zu", HWK Rheinhessen) are edited by hand
in `data/manual/exam_fees_manual.json` and committed via PR.

---

## Static site (Vite)

```bash
cd web
npm ci
npm run dev      # local dev server
npm run build    # → web/dist (deployed to GitHub Pages)
```

Data is imported at build time from `../data/*.json`. The `base` path defaults to `/`
(custom domain). For a `*.github.io/<repo>/` project site, set `VITE_BASE=/<repo>/`.

Pages: **Kursfinder** (filterable list + Leaflet/CartoDB map), **AFBG-Rechner**,
**Über MeisterKompass**, **Impressum**.

---

## Migration from the old Django app (one-time)

The previous version was a Django + PostgreSQL app. Its hand-curated exam fees
(HWK Koblenz "bis zu", HWK Rheinhessen ranges) are the only data the scrapers
can't regenerate. These were recovered directly from the old live site's AFBG
page (which embeds the full per-part fee table as JSON) — no database access
needed:

```bash
python scripts/import_manual_fees_from_live.py   # → data/manual/exam_fees_manual.json
python -m scrapers.run --rebake                  # re-apply manual fees to data/*.json
```

`data/manual/exam_fees_manual.json` is thereafter edited by hand and committed via
PR; `--rebake` re-applies it without re-scraping.

(An alternative `scripts/export_legacy_data.py` exports the same data — plus past
courses and geocodes — straight from the database if you still have `DATABASE_URL`
access and Django installed.)

---

## CI

- `.github/workflows/scrape.yml` — weekly (Fri 03:00 UTC) + manual; runs the scrapers
  and commits changed `data/`.
- `.github/workflows/deploy.yml` — on push to `data/**` or `web/**`; builds `web/` and
  deploys to GitHub Pages.
