# MeisterKompass

An independent, non-commercial comparison platform for Meister preparation
courses offered by Handwerkskammern (HWK) in Germany.

Enables direct comparison of prices, duration, and exam fees across chambers,
as well as calculation of AFBG (Aufstiegs-BAföG) funding.

**Live:** https://boredland.github.io/meisterkompass/

Current scope: five chambers — four in Rhineland-Palatinate (Koblenz, Pfalz,
Rheinhessen, Trier) and HWK des Saarlandes.

---

## Architecture

MeisterKompass is a **static site backed by checked-in JSON data** — no server,
no database.

```
Python scrapers ──▶ data/*.json (committed) ──▶ Vite static site ──▶ GitHub Pages
   (daily CI)          (git is the audit log)      (build-time import + prerender)
```

1. **Scrapers** (`scrapers/`, Python) fetch each chamber's course pages and write
   the dataset to `data/*.json`. A daily GitHub Action runs them and commits the
   changed JSON.
2. **Static site** (`web/`, Vite multi-page app) imports the JSON at build time,
   prerenders the default course table into the HTML, and renders the Kursfinder,
   map, and AFBG calculator client-side.
3. A push to `data/**` or `web/**` triggers a GitHub Pages deploy.

### Repo layout

```
meisterkompass/
├── scrapers/                 # Python scrapers + pipeline (no framework)
│   ├── base.py               # BaseScraper, dataclasses, slugify, build_course_title
│   ├── hwk_*.py              # five chamber scrapers (parsing logic)
│   ├── fees.py               # exam-fee resolution (scraped + manual overlay)
│   ├── geocode.py            # Photon geocoder + committed cache
│   ├── pipeline.py           # scrape → merge → geocode → resolve → split → write JSON
│   └── run.py                # CLI: python -m scrapers.run [--chamber X|--dry-run|--rebake]
├── data/                     # checked-in dataset (consumed by web, written by CI)
│   ├── courses.json          # UPCOMING + undated offers (resolved exam_fee baked in)
│   ├── courses_archive.json  # PAST offers (lazy-loaded by the site on demand)
│   ├── course_fees.json      # AFBG "next available" fee projection
│   ├── exam_fees.json        # per-part fee table (nested) for the AFBG calculator
│   ├── chambers.json  trades.json
│   ├── manual/exam_fees_manual.json   # hand-edited curated fees (Koblenz, Rheinhessen)
│   └── cache/geocode_cache.json       # CI-maintained address → [lat,lng]
├── web/                      # Vite static MPA
│   ├── index.html afbg.html about.html imprint.html
│   ├── public/               # favicon.svg, og-image.png, fonts/, sitemap.xml, robots.txt
│   └── src/                  # base/list/afbg.css + nav/list/map/afbg/util/render.js
├── scripts/import_manual_fees_from_live.py  # recover curated fees from old site
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
uv venv && uv pip install -r requirements.txt

python -m scrapers.run                      # all chambers → write data/*.json
python -m scrapers.run --chamber hwk-pfalz  # one chamber
python -m scrapers.run --dry-run            # scrape + log counts, write nothing
python -m scrapers.run --rebake             # re-apply manual fees, no scraping
```

The pipeline:
- **merges** the fresh scrape with the existing dataset, retaining past courses as
  history and dropping future courses no longer offered;
- **geocodes** new addresses via Photon (Komoot/OSM), caching results in
  `data/cache/geocode_cache.json`, with hardcoded coordinates for HWK Saarland and
  HWK Rheinhessen;
- **resolves** each course's exam fee from scraped fees overlaid with the curated
  `data/manual/exam_fees_manual.json` (manual entries always win);
- **splits** the result into `courses.json` (upcoming, bundled) and
  `courses_archive.json` (past, lazy-loaded) so the shipped payload stays small as
  history accumulates.

Manually-curated exam fees (HWK Koblenz "bis zu", HWK Rheinhessen ranges) are edited
by hand in `data/manual/exam_fees_manual.json`; run `--rebake` to apply them.

---

## Static site (Vite)

```bash
cd web
npm ci
npm run dev      # local dev server
npm run build    # → web/dist (deployed to GitHub Pages)
```

Pages: **Kursfinder** (filterable list + Leaflet/CartoDB map), **AFBG-Rechner**,
**Über MeisterKompass**, **Impressum**.

Key build behaviour:
- **`base` path:** the deploy sets `VITE_BASE=/meisterkompass/` (GitHub Pages project
  site). Defaults to `/` for a custom domain.
- **Prerender:** a Vite plugin renders the default course table into `index.html` at
  build time (`web/src/render.js` is shared by build + runtime) for instant first
  paint and crawlable content; the runtime JS re-renders idempotently.
- **Trimmed payload:** `virtual:courses` strips frontend-unused fields; the full
  `data/courses.json` remains the pipeline's state file.
- **Lazy Leaflet:** the map library + its CSS load only when the map view is opened.
- **Self-hosted fonts:** Fraunces / DM Sans / JetBrains Mono (variable, `font-display:
  optional`) in `web/public/fonts` — no Google Fonts round-trip, zero font CLS.

---

## Performance, accessibility & SEO

Lighthouse (desktop): **index & AFBG 100 / 100 / 100 / 100**; About 98 perf; Impressum
is intentionally `noindex` (legal page). Highlights:

- LCP ~0.5 s, **CLS 0**, TBT 0 ms; design language "Werkstatt Ledger" (parchment / ink /
  brass; Fraunces + DM Sans + JetBrains Mono).
- **Accessibility:** skip links, landmarks, `aria-current/pressed/expanded`, AA contrast,
  keyboard-operable controls, `prefers-reduced-motion`, every table cell mapped to a header.
- **SEO:** per-page titles/descriptions, canonical links, JSON-LD (`WebSite`,
  `Organization`, `WebApplication`), Open Graph + Twitter cards with a branded
  `og-image.png`, `sitemap.xml`, `robots.txt`.
- Note: GitHub Pages serves assets with `cache-control: max-age=600` (not configurable),
  which Lighthouse's cache-TTL audit flags but does not prevent a 100 performance score.

---

## CI

- `.github/workflows/scrape.yml` — **daily** (03:00 UTC) + manual; runs the scrapers
  and commits changed `data/`.
- `.github/workflows/deploy.yml` — on push to `data/**` or `web/**`; builds `web/` and
  deploys to GitHub Pages.

---

## Migration from the old Django app (historical)

The previous version was a Django + PostgreSQL app. Its hand-curated exam fees were
the only data the scrapers can't regenerate; they were recovered from the old live
site's AFBG page (which embedded the full per-part fee table as JSON) via
`scripts/import_manual_fees_from_live.py` + `python -m scrapers.run --rebake`. Django
has since been removed entirely.

---

## Roadmap

### Done
- [x] Migrated from Django/Postgres to a static site (checked-in JSON + GitHub Pages)
- [x] All four RLP chambers + HWK des Saarlandes scraped and live
- [x] Exam fees with "bis zu" qualifier, ranges and tooltips (scraped + manual overlay)
- [x] Filterable course list + interactive map; AFBG-Rechner with Meisterprojekt
- [x] Daily automated scrape; upcoming/archived split for a scalable payload
- [x] Distinctive design language, full accessibility pass, perfect Lighthouse (indexed pages)
- [x] SEO: structured data, Open Graph image, sitemap; self-hosted fonts; build-time prerender

### Planned
- [ ] Berufenet links per trade (field already in the model)
- [ ] Nationwide expansion — add the remaining German Handwerkskammern (48 of 53)

#### Remaining Handwerkskammern by Bundesland

> Covered: RLP (Koblenz, Trier, Pfalz, Rheinhessen) + Saarland.

- **Baden-Württemberg:** Freiburg · Heilbronn-Franken · Karlsruhe · Konstanz · Mannheim
  Rhein-Neckar-Odenwald · Reutlingen · Region Stuttgart · Ulm
- **Bayern:** München und Oberbayern · Niederbayern-Oberpfalz · Oberfranken ·
  Mittelfranken · Unterfranken · Schwaben
- **Berlin:** Berlin
- **Brandenburg:** Cottbus · Frankfurt (Oder) / Ostbrandenburg · Potsdam
- **Bremen:** Bremen
- **Hamburg:** Hamburg
- **Hessen:** Frankfurt-Rhein-Main · Kassel · Wiesbaden
- **Mecklenburg-Vorpommern:** Schwerin · Ostmecklenburg-Vorpommern
- **Niedersachsen:** Braunschweig-Lüneburg-Stade · Hannover · Hildesheim-Südniedersachsen ·
  Oldenburg · Osnabrück-Emsland-Grafschaft Bentheim · Ostfriesland
- **Nordrhein-Westfalen:** Aachen · Dortmund · Düsseldorf · Köln · Münster ·
  Ostwestfalen-Lippe zu Bielefeld · Südwestfalen
- **Sachsen:** Dresden · Chemnitz · Leipzig
- **Sachsen-Anhalt:** Halle (Saale) · Magdeburg
- **Schleswig-Holstein:** Flensburg · Lübeck
- **Thüringen:** Erfurt · Ostthüringen (Gera) · Südthüringen (Suhl)
