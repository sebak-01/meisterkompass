# Meistervergleich

A comparison platform for Meister preparation courses offered by
Handwerkskammern (HWK) in Germany.

The scraper enables direct comparison of prices, duration, and exam fees,
as well as statistical analysis of the Meister education landscape.

Initial scope: four chambers in Rhineland-Palatinate (Koblenz, Pfalz,
Rheinhessen, Trier). Designed to scale to all chambers nationwide.

**Currently live:** HWK Koblenz, HWK Trier.

---

## Features

- Filterable course listings per trade, chamber, format, and exam part
- Course fees and examination fees displayed side by side
- Multi-part filter with optional "include combination courses" toggle
- Interactive map with geocoded course location pins (Leaflet + OpenStreetMap)
- Automatic price/fee propagation from nearest dated course when missing
- Django admin for manual data entry and exam fee verification
- Weekly automated data updates via GitHub Actions

---

## Tech Stack

| Layer       | Technology                                      |
|-------------|-------------------------------------------------|
| Backend     | Django 6.x                                      |
| Database    | SQLite (dev) / PostgreSQL via Neon (prod)        |
| Scraping    | requests + BeautifulSoup (Playwright optional)  |
| Frontend    | Django Templates + Leaflet.js                   |
| Geocoding   | Nominatim / OpenStreetMap (no API key required) |
| Hosting     | Render (web app) + Neon (database)              |
| Cron        | GitHub Actions (every Friday 03:00 UTC)         |

---

## Project Structure

```
meistervergleich/
├── config/                   # Django project settings, URLs, WSGI
├── chambers/                 # Chamber and Trade models + admin
├── courses/                  # CourseOffer, ExamFee models + admin
│   ├── calculators.py        # Total cost calculation logic
│   └── views.py              # Course listing view with filters
├── scraper/                  # Scraper pipeline
│   ├── base.py               # Abstract base scraper + RawCourseOffer dataclass
│   ├── hwk_koblenz.py        # HWK Koblenz scraper ✓
│   ├── hwk_trier.py          # HWK Trier scraper ✓
│   ├── hwk_pfalz.py          # HWK Pfalz scraper (planned)
│   ├── hwk_rheinhessen.py    # HWK Rheinhessen scraper (planned)
│   └── management/
│       └── commands/
│           ├── run_scrapers.py    # python manage.py run_scrapers
│           └── geocode_offers.py  # python manage.py geocode_offers
├── templates/
│   ├── base.html
│   └── courses/list.html
├── .env                      # Local secrets — never commit to Git
├── requirements.txt
└── README.md
```

---

## Local Development Setup

### Prerequisites

- Python 3.11 or later
- Git

### Installation (Windows)

```bat
python -m venv .venv
.venv\Scripts\activate

pip install django dj-database-url python-decouple ^
  requests beautifulsoup4
```

### .env file

Create a `.env` file in the project root:

```
SECRET_KEY=replace-with-a-long-random-string
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
ALLOWED_HOSTS=127.0.0.1,localhost
```

### Database setup

```bat
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Admin interface: http://127.0.0.1:8000/admin/

---

## Data Model Overview

```
Chamber ──┐
          ├── CourseOffer   (one row per course listing on the chamber website)
Trade   ──┘
          └── ExamFee       (official exam fee per part, chamber and trade)
```

### CourseOffer

Each `CourseOffer` corresponds exactly to one listing on the chamber's website,
including its specific start date, price, location, and availability.

| Field              | Description                                                              |
|--------------------|--------------------------------------------------------------------------|
| `title`            | Normalised title, e.g. "Meistervorbereitungskurs: Metallbauer (Teile I + II)" |
| `has_part_1..4`    | Which exam parts this course covers                                      |
| `format`           | Vollzeit / Teilzeit / Teil- oder Vollzeit                                |
| `teaching_mode`    | Präsenz / Online / Hybrid (defaults to Präsenz)                          |
| `course_fee`       | Course fee in EUR                                                        |
| `exam_fee_scraped` | Exam fee directly from the course page (where available, e.g. HWK Trier) |
| `city`             | City for map pin (full address can be added later)                       |
| `source_url`       | Direct link to the course page on the chamber website                    |

### Exam parts

| Part | Content                             | Trade-specific? |
|------|-------------------------------------|-----------------|
| I    | Fachpraxis (practical)              | Yes             |
| II   | Fachtheorie (theory)                | Yes             |
| III  | BWL / Recht (business admin)        | No              |
| IV   | Berufspädagogik (vocational ed.)    | No              |

### ExamFee

Authoritative per-part exam fees used by the total-cost calculator.
Sources vary by chamber:

| Chamber     | Source                                    |
|-------------|-------------------------------------------|
| Trier       | Scraped directly from course detail pages |
| Koblenz     | Manual entry from PDF Gebührenverzeichnis |
| Pfalz       | TBD                                       |
| Rheinhessen | TBD                                       |

To protect a manually entered fee from being overwritten by the scraper,
set `scraper_may_overwrite = False` and `manually_verified = True` in the admin.

---

## Running the Scrapers

```bat
# Run all implemented scrapers
python manage.py run_scrapers

# Run a single chamber
python manage.py run_scrapers --chamber hwk-koblenz
python manage.py run_scrapers --chamber hwk-trier

# Dry run (parse and print without writing to DB)
python manage.py run_scrapers --chamber hwk-koblenz --dry-run

# Geocode course locations (city -> coordinates via Nominatim/OSM)
python manage.py geocode_offers
```

---

## Weekly Scraper (Production)

The scraper runs every Friday at 03:00 UTC via GitHub Actions
(`.github/workflows/weekly_scraper.yml`).
To trigger manually: GitHub -> Actions -> "Weekly Scraper" -> Run workflow.

---

## Trade Name Normalisation

Each scraper maps chamber-specific trade name variants to a shared canonical
name so that the same trade from different chambers is stored as one `Trade`
record. Mappings are defined in `TRADE_ALIASES` in each scraper file.

Example (`hwk_trier.py`):
```python
"Friseure":               "Friseur",
"KFZ-Techniker":          "Kfz.-Techniker",
"Kraftfahrzeugtechniker": "Kfz.-Techniker",
```

---

## Roadmap

### Completed
- [x] Django project structure and data model
- [x] Django admin with exam fee verification workflow
- [x] HWK Koblenz scraper (110+ courses)
- [x] HWK Trier scraper (22 courses, incl. exam fees)
- [x] Course listing frontend with filters
      (chamber, trade, format, teaching mode, parts, date range)
- [x] Per-page selector and pagination
- [x] Interactive Leaflet map with geocoded location pins
- [x] Trade name normalisation across chambers
- [x] Missing price propagation from nearest dated course

### In Progress / Planned
- [ ] HWK Pfalz scraper
- [ ] HWK Rheinhessen scraper
- [ ] Total cost comparison view (all four parts combined)
- [ ] GitHub Actions cron job setup
- [ ] Render + Neon deployment
- [ ] AFBG / Meister-BAföG funding calculator
- [ ] Berufenet links per trade (field already in model)
- [ ] Nationwide expansion (~53 HWK chambers)