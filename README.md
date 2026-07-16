# MeisterKompass

An independent, non-commercial comparison platform for Meister preparation
courses offered by Handwerkskammern (HWK) in Germany.

Enables direct comparison of prices, duration, and exam fees across chambers,
as well as calculation of AFBG (Aufstiegs-BAföG) funding.

Current scope: 40 chambers across fourteen Bundesländer —

- **Bayern:** München und Oberbayern, Niederbayern-Oberpfalz, Oberfranken,
  Mittelfranken, Unterfranken, Schwaben
- **Baden-Württemberg:** all eight chambers
- **Hessen:** Frankfurt-Rhein-Main, Kassel, Wiesbaden
- **Rheinland-Pfalz:** Koblenz, der Pfalz, Rheinhessen, Trier
- **Saarland:** HWK des Saarlandes
- **Thüringen:** Erfurt, Ostthüringen (Gera), Südthüringen (Suhl)
- **Sachsen-Anhalt:** Halle (Saale), Magdeburg
- **Sachsen:** Dresden, Chemnitz, Leipzig
- **Brandenburg:** Cottbus, Frankfurt (Oder) / Ostbrandenburg, Potsdam
- **Mecklenburg-Vorpommern:** Schwerin, Ostmecklenburg-Vorpommern
- **Schleswig-Holstein:** Flensburg, Lübeck
- **Berlin:** HWK Berlin
- **Hamburg:** HWK Hamburg
- **Bremen:** HWK Bremen


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
3. A push to `data/**` or `web/**` triggers a GitHub Pages deploy. Deploy is also
   chained off a successful scheduled scrape run.

The site is served from the custom domain **meisterkompass.eu** (GitHub Pages
with `VITE_BASE=/`), not a `user.github.io/<repo>/` project path.

### Repo layout

```
meisterkompass/
├── scrapers/                  # Python scrapers + pipeline (no framework)
│   ├── base.py                # BaseScraper, dataclasses, slugify, build_course_title
│   ├── hwk_koblenz.py         # HWK Koblenz
│   ├── hwk_pfalz.py           # HWK der Pfalz
│   ├── hwk_rheinhessen.py     # HWK Rheinhessen (WordPress)
│   ├── hwk_trier.py           # HWK Trier
│   ├── hwk_saarland.py        # HWK des Saarlandes
│   ├── hwk_kassel.py          # HWK Kassel — multi-provider (see below)
│   ├── hwk_rhein_main.py      # HWK Frankfurt-Rhein-Main — tabbed multi-module pages
│   ├── hwk_wiesbaden.py       # HWK Wiesbaden
│   ├── hwk_{freiburg,heilbronn,karlsruhe,konstanz,mannheim,reutlingen,stuttgart,ulm}.py
│   ├── hwk_bayern.py          # shared ODAV catalogue/detail parser for Bavaria
│   ├── hwk_{muenchen_und_oberbayern,niederbayern_oberpfalz,oberfranken}.py
│   ├── hwk_{mittelfranken,unterfranken,schwaben}.py
│   ├── hwk_{erfurt,ostthueringen_gera,suedthueringen_suhl}.py
│   ├── hwk_{halle_saale,magdeburg}.py
│   ├── hwk_{dresden,chemnitz,leipzig}.py
│   ├── hwk_{cottbus,potsdam,frankfurt_oder_ostbrandenburg}.py
│   ├── hwk_{schwerin,ostmecklenburg_vorpommern}.py
│   ├── fees.py                # exam-fee resolution (scraped + manual overlay, combo-bundle keys)
│   ├── geocode.py             # Photon geocoder + committed cache
│   ├── pipeline.py            # scrape → merge → geocode → resolve → split → write JSON
│   └── run.py                 # CLI: python -m scrapers.run [--chamber X|--dry-run|--rebake]
├── data/                       # checked-in dataset (consumed by web, written by CI)
│   ├── courses.json            # UPCOMING + undated offers (resolved exam_fee baked in)
│   ├── courses_archive.json    # PAST offers (lazy-loaded by the site on demand)
│   ├── course_fees.json        # AFBG "next available" fee projection
│   ├── exam_fees.json          # per-part (+ combo-bundle) fee table for the AFBG calculator
│   ├── chambers.json  trades.json
│   ├── manual/exam_fees_manual.json   # hand-edited curated fees (Koblenz "bis zu", Rheinhessen
│   │                                    ranges, Hessen chambers incl. combo-bundle keys)
│   └── cache/geocode_cache.json       # CI-maintained address → [lat,lng]
├── web/                        # Vite static MPA
│   ├── index.html afbg.html about.html imprint.html
│   ├── public/                 # favicon.svg, og-image.png, fonts/, sitemap.xml, robots.txt
│   └── src/                    # base/list/afbg.css + nav/list/map/afbg/render/util.js
├── scripts/import_manual_fees_from_live.py  # recover curated fees from old site
├── tests/test_{bw,bayern,thueringen,sachsen_anhalt,sachsen,brandenburg,mecklenburg_vorpommern}_scrapers.py
├── mise.toml                    # pins python 3.12 + node 22
└── .github/workflows/{scrape.yml, deploy.yml}
```

#### Bayern — shared ODAV catalogue architecture

All six Bavarian chambers publish Meister courses through the same server-rendered
ODAV course CMS (paginated `courselist.html` + per-run `coursedetail.html?id=…`).
`hwk_bayern.py` implements the shared catalogue parser and optional detail-page
enrichment; each chamber file only sets metadata, catalogue URL, and any
chamber-specific hooks:

| Chamber | Slug | Source |
|---|---|---|
| München und Oberbayern | `hwk-muenchen-und-oberbayern` | hwk-muenchen.de |
| Niederbayern-Oberpfalz | `hwk-niederbayern-oberpfalz` | hwkno.de |
| Oberfranken | `hwk-oberfranken` | hwk-oberfranken.de |
| Mittelfranken | `hwk-mittelfranken` | hwk-akademie.de (chamber host blocks bots) |
| Unterfranken | `hwk-unterfranken` | hwk-ufr.de |
| Schwaben | `hwk-schwaben` | bildungschwaben.de |

Caveats worth knowing when scraping or interpreting the data:

- **Unterfranken** lists combined prices on the catalogue page (`inkl. Prüfung`);
  the scraper always fetches detail pages to split `Kurs:` and `Prüfung:`.
- **Niederbayern-Oberpfalz** is listing-only: its cards already contain every
  required changing field, while a curated education-centre map supplies exact
  addresses. This avoids roughly 265 redundant detail requests per run.
- **Oberfranken** and **Unterfranken** publish per-run exam fees on detail pages;
  other Bavarian chambers rely on scraped `Prüfung:` where present, or curated
  schedules (Mittelfranken, Schwaben Parts III/IV in `exam_fees_manual.json`).
- **Mittelfranken** shares one booking for a combined Feinwerkmechaniker/Metallbauer
  run — the scraper emits two offers with distinct `source_url` fragments.
- **Schwaben** trade Meisterkurse often omit explicit part numbers in the title;
  `*-Meisterkurs` titles are mapped to Parts I+II.
- Month-only start dates (e.g. `September 2027`) are stored as `YYYY-MM-01`.

#### HWK Kassel — multi-provider architecture

Unlike the other chambers, HWK Kassel has no single course-listing CMS of its
own; courses are delivered by up to eight independent education providers.
`hwk_kassel.py` implements one self-contained fetch method per provider, with
failures in one provider logged and skipped rather than aborting the whole
chamber scrape:

- **BZ Bildungszentrum Kassel GmbH** (bz-kassel.de) — implemented
- **Berufsbildungszentrum Marburg GmbH** (bbz-marburg.de) — implemented
- **Bubiza** (bubiza.de) — implemented (Zimmerer/Dachdecker; per-part fees,
  combined-run fee = sum of component parts)
- **BBZ Mitte GmbH** (bbz-mitte.de) — implemented (its `/de/kursfinder` list is
  JS-rendered, but the underlying `/de/seminar-navigator/search-results` AJAX
  endpoint returns the same results server-side as a static HTML fragment)
- **Holzfachschule Bad Wildungen** (holzfachschule.de) — implemented (courses
  live on the `veranstaltung.holzfachschule.de` booking system; PrimeFaces/JSF
  but the seminar list and detail pages are fully server-rendered)
- **FTZ / Innung Kfz-Gewerbe Kassel** (kfz-innung-kassel.de) — implemented with
  caveats: its Seminare page is server-rendered and is the *only* source of
  Kfz-Meister courses (BZ Kassel has none), but FTZ publishes no dates or
  prices there — all three courses are "auf Anfrage", so each yields a
  dateless, priceless placeholder offer
- Kreishandwerkerschaft Waldeck-Frankenberg (khkb.de) — blocked: its
  Meistervorbereitungslehrgänge are published only as a PDF, no structured
  HTML to scrape

Exam fees for HWK Kassel are chamber-wide rather than per-offer, so they're
injected via an overridden `collect()` rather than `exam_fee_scraped` on
individual offers.

#### Thüringen — three independent catalogues

Each Thuringian chamber publishes Meister courses on its own CMS; exam fees are
parsed from each chamber's Gebührenverzeichnis PDF and cited via the relevant
legal/fees page:

| Chamber | Slug | Source |
|---|---|---|
| Erfurt | `hwk-erfurt` | hwk-erfurt.de |
| Ostthüringen (Gera) | `hwk-ostthueringen-gera` | hwk-gera.de |
| Südthüringen (Suhl) | `hwk-suedthueringen-suhl` | hwk-suhl.de |

#### Sachsen-Anhalt — WordPress + ODAV

| Chamber | Slug | Source |
|---|---|---|
| Halle (Saale) | `hwk-halle-saale` | hwk-halle.de (WordPress seminar pages) |
| Magdeburg | `hwk-magdeburg` | hwk-magdeburg.de (ODAV article catalogue) |

Exam fees for both chambers are parsed from the published Gebührenverzeichnis PDF.

#### Sachsen — ODAV, custom term blocks, and njumii

| Chamber | Slug | Source |
|---|---|---|
| Leipzig | `hwk-leipzig` | hwk-leipzig.de (ODAV catalogue; exam fees from the [Gebührenordnung page](https://www.hwk-leipzig.de/artikel/gebuehrenordnung-die-rechtliche-basis-fuer-die-erhebung-von-gebuehren-3,0,99.html)) |
| Chemnitz | `hwk-chemnitz` | hwk-chemnitz.de (Bildungsprogramm + Meisterschule `<details id="termin_*">` blocks) |
| Dresden | `hwk-dresden` | njumii.de (HWK Dresden's Bildungszentrum; exam fees from the [Meisterprüfungen page](https://www.hwk-dresden.de/ausbildung/pruefungen/meisterpruefungen.html#c20204)) |

Dresden-specific parsing notes:

- Course pages expose a featured run plus additional accordion runs; duration
  hours are shared across runs on the same page when only one run publishes
  `Teilnehmerstunden`.
- Availability defaults to `available` when a booking button is present and the
  run is not marked as fully booked (including waitlist + booking button).

#### Brandenburg — ODAV and WordPress Meisterschule

| Chamber | Slug | Source |
|---|---|---|
| Cottbus | `hwk-cottbus` | hwk-cottbus.de (ODAV `search-type=6`; exam fees from the [Rechtsgrundlagen page](https://www.hwk-cottbus.de/artikel/rechtsgrundlagen-7,719,154.html); Part I base fee note in tooltip) |
| Potsdam | `hwk-potsdam` | hwk-potsdam.de (ODAV `search-type=6`; exam fees from the [Gebühren page](https://www.hwk-potsdam.de/artikel/gebuehren-9,783,2654.html), `zzgl. Auslagen`) |
| Frankfurt (Oder) / Ostbrandenburg | `hwk-frankfurt-oder-ostbrandenburg` | weiterbildung-ostbrandenburg.de (WordPress Meisterschule; `Prüfungskosten` scraped from course pages when published, otherwise per-part fees from the [Gebührenverzeichnis PDF](https://www.hwk-ff.de/wp-content/uploads/2025/08/Gebuehrenverzeichnis.pdf)) |

Cottbus runs are spread across Gallinchen, Großräschen, and Wildau; the scraper
maps known campus keywords to addresses and prefers detail-page `Lehrgangsort`
when available.

#### Mecklenburg-Vorpommern — ODAV

| Chamber | Slug | Source |
|---|---|---|
| Schwerin | `hwk-schwerin` | hwk-schwerin.de (ODAV `search-type=6`; exam fees from [Gebührenverzeichnis PDF](https://www.hwk-schwerin.de/downloads/gebuehrenverzeichnis-19,8.pdf)) |
| Ostmecklenburg-Vorpommern | `hwk-ostmecklenburg-vorpommern` | hwk-omv.de (ODAV `search-type=6`; course fees from detail pages; exam fees from [Gebühren page](https://www.hwk-omv.de/artikel/gebuehren-und-beitraege-18,945,2052.html)) |

Schwerin runs are mostly at the BTZ in Schwerin; some Teil IV courses run in Güstrow.
OMV courses are offered in Rostock, Neubrandenburg, and Neustrelitz — the scraper
reads the city from the listing card (`| Neubrandenburg`) or detail-page address.

#### Schleswig-Holstein — BUE universal-kdb REST

Both chambers embed the same Angular `bueKursWebclient` widget (Neos CMS shell +
`hwk-universal.de` REST API). Course listings are fetched from
`https://www.hwk-universal.de/universal-kdb-rest/v1/bereiche/{mandant}`; each
scheduled run comes from the vorlage detail endpoint.

| Chamber | Slug | Mandant | Source |
|---|---|---|---|
| Flensburg | `hwk-flensburg` | `fl` | [Kurse & Seminare](https://www.hwk-flensburg.de/weiterbildung/kurse-seminare#/) |
| Lübeck | `hwk-luebeck` | `hl` | [Fort- und Weiterbildungskurse](https://www.hwk-luebeck.de/weiterbildung/fort-und-weiterbildungskurse#/) |

Exam fees are parsed from each chamber's Meisterprüfung fees page
([Flensburg](https://www.hwk-flensburg.de/weiterbildung/weiterbildung/der-weg-zum-meister),
[Lübeck](https://www.hwk-luebeck.de/weiterbildung/der-weg-zum-meister/pruefung-gebuehren)).

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

# all six Bavarian chambers (stops on first failure)
python -m scrapers.run --chamber hwk-muenchen-und-oberbayern && \
python -m scrapers.run --chamber hwk-niederbayern-oberpfalz && \
python -m scrapers.run --chamber hwk-oberfranken && \
python -m scrapers.run --chamber hwk-mittelfranken && \
python -m scrapers.run --chamber hwk-unterfranken && \
python -m scrapers.run --chamber hwk-schwaben

# eastern chambers (Sachsen, Sachsen-Anhalt, Thüringen)
python -m scrapers.run --chamber hwk-dresden && \
python -m scrapers.run --chamber hwk-chemnitz && \
python -m scrapers.run --chamber hwk-leipzig && \
python -m scrapers.run --chamber hwk-halle-saale && \
python -m scrapers.run --chamber hwk-magdeburg && \
python -m scrapers.run --chamber hwk-erfurt && \
python -m scrapers.run --chamber hwk-ostthueringen-gera && \
python -m scrapers.run --chamber hwk-suedthueringen-suhl

# Brandenburg chambers
python -m scrapers.run --chamber hwk-cottbus && \
python -m scrapers.run --chamber hwk-potsdam && \
python -m scrapers.run --chamber hwk-frankfurt-oder-ostbrandenburg

# Mecklenburg-Vorpommern chambers
python -m scrapers.run --chamber hwk-schwerin && \
python -m scrapers.run --chamber hwk-ostmecklenburg-vorpommern

# Schleswig-Holstein chambers
python -m scrapers.run --chamber hwk-flensburg && \
python -m scrapers.run --chamber hwk-luebeck

python -m unittest discover -s tests        # offline parser + fee tests
```

The pipeline:
- **merges** the fresh scrape with the existing dataset, retaining past courses as
  history and dropping future courses no longer offered;
- **geocodes** new addresses via Photon (Komoot/OSM), caching results in
  `data/cache/geocode_cache.json`, with hardcoded coordinates for HWK Saarland and
  HWK Rheinhessen;
- **resolves** each course's exam fee from scraped fees overlaid with the curated
  `data/manual/exam_fees_manual.json` (manual entries always win). Fees can be
  keyed per part or as an exact combo-bundle (e.g. `{1,2}` booked together at a
  flat discounted price — used by several Hessen chambers);
- **splits** the result into `courses.json` (upcoming, bundled) and
  `courses_archive.json` (past, lazy-loaded) so the shipped payload stays small as
  history accumulates.

Manually-curated exam fees (HWK Koblenz "bis zu", HWK Rheinhessen ranges, the
three Hessen chambers' fee schedules incl. combo-bundle keys, Mittelfranken and
Schwaben generic Parts III/IV) are edited by hand in
`data/manual/exam_fees_manual.json`; run `--rebake` to apply them.

---

## Static site (Vite)

```bash
cd web
npm ci
npm run dev      # local dev server
npm run build    # → web/dist (deployed to GitHub Pages)
```

Pages: **Kursfinder** (filterable list + Leaflet/CartoDB map, multi-select
chamber filter), **AFBG-Rechner** (auto-fill from Kursfinder data or manual
entry, per-part and combo-bundle fee handling, Meisterprojekt funding),
**Über MeisterKompass**, **Impressum**.

Key build behaviour:
- **`base` path:** `VITE_BASE=/` for the custom domain (meisterkompass.eu).
  Set `VITE_BASE=/<repo>/` instead if ever deployed to a GitHub Pages project
  path (`user.github.io/<repo>/`).
- **Prerender:** a Vite plugin renders the default course table into `index.html` at
  build time (`web/src/render.js` is shared by build + runtime) for instant first
  paint and crawlable content; the runtime JS re-renders idempotently.
- **Trimmed payload:** `virtual:courses` strips frontend-unused fields; the full
  `data/courses.json` remains the pipeline's state file.
- **Lazy Leaflet:** the map library + its CSS load only when the map view is opened.
- **Self-hosted fonts:** Fraunces / DM Sans / JetBrains Mono (variable, `font-display:
  optional`) in `web/public/fonts` — no Google Fonts round-trip, zero font CLS.

### Exam-fee display & tooltips

Tooltip copy lives in JS constants (`web/src/util.js`), not in the JSON data:

- `TOOLTIP_QUALIFIER` — HWK Koblenz "bis zu" (maximum chargeable fee)
- `TOOLTIP_RANGE` — HWK Rheinhessen fee ranges
- `TOOLTIP_HESSEN` — HWK Frankfurt-Rhein-Main / Wiesbaden / Kassel (`HESSEN_CHAMBERS`
  set), exact fee from the official schedule, subject to change
- `ANMELDEGEBUEHR_NOTE` — HWK Frankfurt-Rhein-Main may charge an additional
  registration fee on top of the listed Kursgebühr

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
- `.github/workflows/deploy.yml` — on push to `data/**` or `web/**`, or chained off a
  successful scrape run; builds `web/` and deploys to GitHub Pages
  (meisterkompass.eu).

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
- [x] Four RLP chambers + HWK des Saarlandes scraped and live
- [x] Hessen expansion: HWK Frankfurt-Rhein-Main, HWK Kassel (6 of 8 providers), HWK Wiesbaden
- [x] HWK Frankfurt-Rhein-Main: reconciled module handling on tabbed detail pages
      (`with-modul` selectors + per-run `<tbody>`), so each module yields its own
      correctly-parted offer with its own fee
- [x] All chambers in Baden-Württemberg and Bayern integrated
- [x] Thüringen: HWK Erfurt, Ostthüringen (Gera), Südthüringen (Suhl)
- [x] Sachsen-Anhalt: HWK Halle (Saale), Magdeburg
- [x] Sachsen: HWK Dresden, Chemnitz, Leipzig
- [x] Brandenburg: HWK Cottbus, Frankfurt (Oder) / Ostbrandenburg, Potsdam
- [x] Mecklenburg-Vorpommern: HWK Schwerin, Ostmecklenburg-Vorpommern
- [x] Exam fees with "bis zu" qualifier, ranges, combo-bundle prices, and tooltips
      (scraped + manual overlay)
- [x] Filterable course list (multi-select chambers) + interactive map;
      AFBG-Rechner with per-part/combo-bundle fees and Meisterprojekt funding
- [x] Daily automated scrape; upcoming/archived split for a scalable payload
- [x] Distinctive design language, full accessibility pass, perfect Lighthouse (indexed pages)
- [x] SEO: structured data, Open Graph image, sitemap; self-hosted fonts; build-time prerender
- [x] Custom domain (meisterkompass.eu)

### In progress
- [ ] HWK Kassel: 6 of 8 providers implemented (BZ Kassel, BBZ Marburg, Bubiza,
      BBZ Mitte, Holzfachschule Bad Wildungen, FTZ/Innung Kfz-Gewerbe Kassel —
      the last dateless/priceless, "auf Anfrage" only). Kreishandwerkerschaft
      Waldeck-Frankenberg remains blocked (Meisterlehrgänge published only as
      a PDF); Beratungsstelle Denkmalpflege offers none

### Planned
- [ ] Berufenet links per trade (field already in the model)
- [ ] Nationwide expansion — add the remaining German Handwerkskammern (18 of 53)

#### Remaining Handwerkskammern by Bundesland

> Covered: Bayern · Baden-Württemberg · Hessen (Frankfurt-Rhein-Main, Kassel,
> Wiesbaden) · RLP (Koblenz, Trier, Pfalz, Rheinhessen) · Saarland ·
> Thüringen · Sachsen-Anhalt · Sachsen · Brandenburg · Mecklenburg-Vorpommern.

- **Berlin:** Berlin
- **Bremen:** Bremen
- **Hamburg:** Hamburg
- **Niedersachsen:** Braunschweig-Lüneburg-Stade · Hannover · Hildesheim-Südniedersachsen ·
  Oldenburg · Osnabrück-Emsland-Grafschaft Bentheim · Ostfriesland
- **Nordrhein-Westfalen:** Aachen · Dortmund · Düsseldorf · Köln · Münster ·
  Ostwestfalen-Lippe zu Bielefeld · Südwestfalen
- **Schleswig-Holstein:** Flensburg · Lübeck