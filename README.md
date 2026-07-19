# MeisterKompass

An independent, non-commercial comparison platform for Meister preparation
courses offered by Handwerkskammern (HWK) in Germany.

Enables direct comparison of prices, duration, and exam fees across chambers,
as well as calculation of AFBG (Aufstiegs-BAföG) funding.

Current scope: **53 chambers** across **sixteen Bundesländer** —

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
- **Niedersachsen:** Braunschweig-Lüneburg-Stade, Hannover,
  Hildesheim-Südniedersachsen, Oldenburg, Osnabrück-Emsland-Grafschaft Bentheim,
  Ostfriesland
- **Nordrhein-Westfalen:** Aachen, Dortmund, Düsseldorf, Köln, Münster,
  Ostwestfalen-Lippe zu Bielefeld, Südwestfalen


---

## Architecture

MeisterKompass is a **static site backed by checked-in JSON data** — no server,
no database.

```
Python scrapers ──▶ data/*.json (committed) ──▶ Vite static site ──▶ GitHub Pages
   (daily CI)          (git is the audit log)      (build-time import + prerender)
```

1. **Scrapers** (`scrapers/`, Python) fetch each chamber's course pages and write
   the dataset to `data/*.json`. A daily GitHub Action scrapes four regional
   batches in parallel, merges the partial results, geocodes once, and commits
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
│   ├── hwk_{berlin,hamburg,bremen}.py
│   ├── hwk_{braunschweig_lueneburg_stade,hannover,hildesheim_suedniedersachsen,
│   │         oldenburg,osnabrueck_emsland_grafschaft_bentheim,ostfriesland}.py
│   ├── hwk_{koeln,duesseldorf,aachen,ostwestfalen_lippe_zu_bielefeld,muenster,
│   │         suedwestfalen,dortmund}.py
│   ├── hwk_universal_kdb.py    # shared BUE universal-kdb REST client (SH + NI)
│   ├── fees.py                # exam-fee resolution (scraped + manual overlay, combo-bundle keys)
│   ├── geocode.py             # Photon geocoder + committed cache
│   ├── pipeline.py            # scrape → merge → geocode → resolve → split → write JSON
│   └── run.py                 # CLI: python -m scrapers.run [--chamber|--group|--rebake|…]
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
├── tests/test_{base,fees,scrape_pipeline,bw,bayern,thueringen,sachsen_anhalt,sachsen,
│              brandenburg,mecklenburg_vorpommern,schleswig_holstein,city_states,
│              niedersachsen,nrw,rheinhessen}_scrapers.py
├── requirements.txt             # requests, beautifulsoup4, pypdf, cloudscraper
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

#### Niedersachsen — ODAV and universal-kdb

| Chamber | Slug | Source |
|---|---|---|
| Braunschweig-Lüneburg-Stade | `hwk-braunschweig-lueneburg-stade` | weiterbildung.hwk-bls.de (ODAV) |
| Hannover | `hwk-hannover` | hwk-hannover.de (ODAV) |
| Hildesheim-Südniedersachsen | `hwk-hildesheim-suedniedersachsen` | hwk-hildesheim.de (ODAV) |
| Oldenburg | `hwk-oldenburg` | hwk-oldenburg.de (universal-kdb, mandant `ol`) |
| Osnabrück-Emsland-Grafschaft Bentheim | `hwk-osnabrueck-emsland-grafschaft-bentheim` | btz-osnabrueck.de (BTZ overview + detail pages) |
| Ostfriesland | `hwk-ostfriesland` | hwk-aurich.de (universal-kdb, mandant `of`) |

Oldenburg and Ostfriesland share the same BUE REST API as Schleswig-Holstein
(`hwk_universal_kdb.py`). Osnabrück courses are published by the BTZ on its own
site; exam fees come from the chamber's Gebührenordnung PDF.

#### Nordrhein-Westfalen — ODAV, WooCommerce, and BBZ Arnsberg

| Chamber | Slug | Source |
|---|---|---|
| Aachen | `hwk-aachen` | hwk-aachen.de (ODAV) |
| Köln | `hwk-koeln` | hwk-koeln.de (ODAV) |
| Düsseldorf | `hwk-duesseldorf` | hwk-duesseldorf.de (ODAV) |
| Münster | `hwk-muenster` | hwk-muenster.de (Meisterschule overview + detail pages) |
| Ostwestfalen-Lippe zu Bielefeld | `hwk-ostwestfalen-lippe-zu-bielefeld` | bbz.handwerk-owl.de (ODAV) |
| Dortmund | `hwk-dortmund` | hwk-do.de (WooCommerce Events; per-variation availability) |
| Südwestfalen | `hwk-suedwestfalen` | bbz-arnsberg.de (Meister courses via BBZ Arnsberg) |

NRW-specific notes:

- **OWL** exam fees for Teile I+II use the published all-four-parts package range,
  not the sum of separate Part I and Part II rows.
- **Dortmund** reads WooCommerce `data-product_variations` to match each Termin
  to its variation and parse `availability_html` (`Plätze verfügbar`, `ausgebucht`,
  `Warteliste`).
- **Südwestfalen** course pages sit behind Cloudflare; the scraper uses
  `cloudscraper` for `bbz-arnsberg.de` and reads availability from each
  `div.tx-wisumcourses-course` row (`ausgebucht`, `Jetzt Buchen`, `Warteliste`).
  Exam fees are parsed from the chamber's Gebührentarif PDF on hwk-swf.de.

#### City states — Berlin, Hamburg, Bremen

| Chamber | Slug | Source |
|---|---|---|
| Berlin | `hwk-berlin` | bildung4u.de (same ODAV-style CMS as Koblenz) |
| Hamburg | `hwk-hamburg` | elbcampus.de (schema.org `Course` JSON-LD per trade page) |
| Bremen | `hwk-bremen` | universal-kdb bulk feed + handwerkbremen.de Meisterkurs pages |

Berlin exam fees are curated manually (not on course pages). Hamburg reads
structured `hasCourseInstance` / `offers` arrays from JSON-LD. Bremen merges
scheduled KDB runs with dateless overview placeholders when no Termin is published
yet.

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
python -m scrapers.run --group west         # regional batch (see pipeline.SCRAPE_GROUPS)
python -m scrapers.run --group west --partial-out partial-west.json   # CI partial
python -m scrapers.run --merge-partials partials/partial-*.json       # merge + write
python -m scrapers.run --dry-run            # scrape + log counts, write nothing
python -m scrapers.run --rebake             # re-apply manual fees, no scraping

# examples — run chambers individually (stops on first failure)
python -m scrapers.run --chamber hwk-suedwestfalen
python -m scrapers.run --chamber hwk-dortmund

python -m unittest discover -s tests        # offline parser + fee tests
```

Local full runs cap parallel chamber scrapes at 15 workers to avoid egress
connection limits. CI uses four matrix jobs (`west`, `south`, `east`, `north`)
with ~13 chambers each on separate runners (~7–10 min wall time).

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

- `.github/workflows/scrape.yml` — **daily** (03:00 UTC) + manual. Four parallel
  matrix jobs scrape regional batches (`west` / `south` / `east` / `north`),
  upload JSON partials, then a merge job geocodes, resolves fees, writes
  `data/*.json`, and commits. Typical wall time ~7–10 minutes.
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