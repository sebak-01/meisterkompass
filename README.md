# MeisterKompass

An independent, non-commercial comparison platform for Meister preparation
courses offered by Handwerkskammern (HWK) in Germany.

Enables direct comparison of prices, duration, and exam fees across chambers,
as well as statistical analysis of the Meister education landscape.

Initial scope: four chambers in Rhineland-Palatinate (Koblenz, Pfalz,
Rheinhessen, Trier). Designed to scale to all chambers nationwide.

**Currently live:** HWK Koblenz, HWK Trier, HWK Pfalz, HWK Rheinhessen.

---

## Features

- Filterable course listings per trade, chamber, format, and exam part
- Multi-part filter with optional "include combination courses" toggle
- Course fees and examination fees displayed side by side
- "bis zu" qualifier and fee ranges for maximum-fee entries (e.g. HWK Koblenz)
- Interactive map with geocoded course location pins (Leaflet + OpenStreetMap)
- Automatic price/fee propagation from nearest dated course when missing
- "Termine nicht verfügbar" indicator for courses without scheduled dates
- Tab navigation: Kursfinder, Über MeisterKompass, Zahlen zum Meister
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
meisterkompass/
├── config/                   # Django project settings, URLs, WSGI
├── chambers/                 # Chamber and Trade models + admin
├── courses/                  # CourseOffer, ExamFee models + admin
│   ├── calculators.py        # Total cost calculation logic
│   └── views.py              # Course listing view with filters
├── scraper/                  # Scraper pipeline
│   ├── base.py               # Abstract base scraper + RawCourseOffer + build_course_title
│   ├── hwk_koblenz.py        # HWK Koblenz scraper ✓
│   ├── hwk_trier.py          # HWK Trier scraper ✓  (incl. exam fees)
│   ├── hwk_pfalz.py          # HWK Pfalz scraper ✓  (incl. exam fees)
│   ├── hwk_rheinhessen.py    # HWK Rheinhessen scraper ✓
│   └── management/
│       └── commands/
│           ├── run_scrapers.py    # python manage.py run_scrapers
│           └── geocode_offers.py  # python manage.py geocode_offers
├── templates/
│   ├── base.html             # Single nav bar (brand + tabs), shared styles
│   ├── courses/
│   │   └── list.html         # Kursfinder (filterable list + map)
│   └── pages/
│       ├── about.html        # Über MeisterKompass
│       └── stat.html         # Zahlen zum Meister (statistics, planned)
│       └── imprint.html      # Imprint   
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

```
SECRET_KEY=replace-with-a-long-random-string
DEBUG=True
DATABASE_URL=sqlite:///db.sqlite3
ALLOWED_HOSTS=127.0.0.1,localhost
```

### Database setup

```bat
python manage.py makemigrations chambers courses scraper
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

| Field              | Description                                                       |
|--------------------|-------------------------------------------------------------------|
| `title`            | Normalised title, e.g. "Metallbauer (Teile I + II)"              |
| `has_part_1..4`    | Which exam parts this course covers                               |
| `format`           | Vollzeit / Teilzeit                                               |
| `teaching_mode`    | Präsenz / Online / Hybrid (defaults to Präsenz)                   |
| `course_fee`       | Course fee in EUR                                                 |
| `exam_fee_scraped` | Exam fee from the course page (HWK Trier, HWK Pfalz)             |
| `city`             | City for map pin                                                  |
| `source_url`       | Direct link to the course page on the chamber website             |

`start_date = None` → "Termine nicht verfügbar".

### ExamFee

| Chamber     | Source                                         |
|-------------|------------------------------------------------|
| Trier       | Scraped directly from course detail pages      |
| Pfalz       | Scraped directly from course detail pages      |
| Koblenz     | Manual entry from PDF Gebührenverzeichnis      |
| Rheinhessen | Manual entry (exam fee pages per trade)        |

- `fee_qualifier = "bis zu"` → displays "bis zu 380 €" with ⓘ tooltip
- `fee_max` set → displays "600 bis 2.000 €" with ⓘ tooltip
- `trade = null` → fee applies to all trades at this chamber for the given part

---

## Running the Scrapers

```bat
python manage.py run_scrapers
python manage.py run_scrapers --chamber hwk-koblenz --dry-run
python manage.py geocode_offers
```

---

## Roadmap

### Completed
- [x] All four RLP chambers scraped and live
- [x] Exam fees with "bis zu" qualifier and range display
- [x] Filterable course list + interactive map
- [x] Tab navigation (Kursfinder, Über, Zahlen)
- [x] Trade name normalisation across chambers

### Planned
- [ ] Statistics page (Zahlen zum Meister)
- [ ] GitHub Actions cron job + Render/Neon deployment
- [ ] AFBG / Meister-BAföG funding calculator
- [ ] Nationwide expansion (~53 HWK chambers)