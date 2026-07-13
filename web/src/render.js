// Pure (DOM-free) rendering + filtering for the course list.
// Imported by both list.js (browser, runtime) and the Vite prerender plugin
// (Node, build time) so the prerendered HTML matches what the client produces.

import {
  ROMAN,
  partsLabel,
  esc,
  TOOLTIP_QUALIFIER,
  TOOLTIP_APPROXIMATE,
  TOOLTIP_RANGE,
  TOOLTIP_HESSEN,
  ANMELDEGEBUEHR_NOTE,
  TRADE_SPECIFIC_EXAM_NOTE,
  REUTLINGEN_ADDITIONAL_EXAM_NOTE,
  SCHWABEN_ADDITIONAL_EXAM_NOTE,
  ERFFURT_EXAM_NOTE,
  HESSEN_CHAMBERS,
} from "./util.js";

export const fmtDate = (iso) => (iso ? iso.split("-").reverse().join(".") : "");

/** The initial, unfiltered view: future-only courses, page 1, 20 per page. */
export const defaultState = () => ({
  chamber: "", trade: "", format: "", available: false, parts: [],
  includeCombos: false, dateFrom: "", dateTo: "", perPage: "20", view: "list", page: 1,
});

// ── Filtering (port of the old courses/views.py _apply_filters) ─────────
export function applyFilters(courses, s, todayIso) {
  return courses.filter((c) => {
    if (s.chamber && c.chamber_slug !== s.chamber) return false;
    if (s.trade && c.trade_slug !== s.trade) return false;
    if (s.format && c.format !== s.format) return false;
    if (s.available && c.availability !== "available") return false;

    const sd = c.start_date;
    if (s.dateFrom) {
      if (!(sd && sd >= s.dateFrom)) return false;
    } else if (s.dateTo) {
      if (!(sd && sd <= s.dateTo)) return false;
    } else if (!(sd === null || sd >= todayIso)) {
      return false;
    }
    if (s.dateFrom && s.dateTo && !(sd && sd <= s.dateTo)) return false;

    if (s.parts.length) {
      const ok = s.parts.some((p) =>
        s.includeCombos ? c.parts.includes(p) : c.parts.length === 1 && c.parts[0] === p,
      );
      if (!ok) return false;
    }
    return true;
  });
}

/** The slice of `filtered` shown on the current page. */
export function pageItems(filtered, s) {
  if (s.perPage === "all") return filtered;
  const per = parseInt(s.perPage, 10) || 20;
  const pages = Math.max(1, Math.ceil(filtered.length / per));
  const page = Math.min(s.page, pages);
  const start = (page - 1) * per;
  return filtered.slice(start, start + per);
}

// ── Row rendering ───────────────────────────────────────────────────────
function availabilityBadge(a, small = false) {
  const style = small ? ' style="font-size:.65rem;padding:1px 6px"' : "";
  if (a === "full") return `<span class="badge badge-full"${style}>Ausgebucht</span>`;
  if (a === "waitlist") return `<span class="badge badge-waitlist"${style}>Warteliste</span>`;
  if (a === "available" || a === "few_spots")
    return `<span class="badge badge-available"${style}>${small ? "Frei" : "Freie Plätze"}</span>`;
  return small ? "" : '<span class="badge">–</span>';
}

/**
 * Renders the exam-fee table cell with the appropriate info button.
 * Tooltip text selection (matching util.js constants):
 *   Stuttgart courses incl. Teil I → TRADE_SPECIFIC_EXAM_NOTE
 *   Reutlingen Part I → REUTLINGEN_ADDITIONAL_EXAM_NOTE
 *   Schwaben / Südthüringen / Ostthüringen Parts I/II → SCHWABEN_ADDITIONAL_EXAM_NOTE
 *   Erfurt → ERFFURT_EXAM_NOTE
 *   qualifier set    → TOOLTIP_QUALIFIER  (e.g. HWK Koblenz "bis zu")
 *   fee_max set      → TOOLTIP_RANGE      (e.g. HWK Rheinhessen range)
 *   Hessen chamber   → TOOLTIP_HESSEN     (HWK Rhein-Main / Wiesbaden / Kassel)
 *   scraped fee      → no button (exact value stated on the course page)
 */
function examFeeCell(ef, chamberSlug = "", parts = []) {
  if (!ef || !ef.fee) return '<span class="price-na">—</span>';
  let btn = "";
  if (chamberSlug === "hwk-stuttgart" && parts.includes(1))
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TRADE_SPECIFIC_EXAM_NOTE)}" type="button">i</button>`;
  else if (chamberSlug === "hwk-reutlingen" && parts.includes(1))
    btn = `<button class="fee-info-btn" data-tooltip="${esc(REUTLINGEN_ADDITIONAL_EXAM_NOTE)}" type="button">i</button>`;
  else if (
    (chamberSlug === "hwk-schwaben"
      || chamberSlug === "hwk-suedthueringen-suhl"
      || chamberSlug === "hwk-ostthueringen-gera")
    && parts.some((part) => part === 1 || part === 2)
  )
    btn = `<button class="fee-info-btn" data-tooltip="${esc(SCHWABEN_ADDITIONAL_EXAM_NOTE)}" type="button">i</button>`;
  else if (chamberSlug === "hwk-erfurt")
    btn = `<button class="fee-info-btn" data-tooltip="${esc(ERFFURT_EXAM_NOTE)}" type="button">i</button>`;
  else if (ef.qualifier === "ca.")
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_APPROXIMATE)}" type="button">i</button>`;
  else if (ef.qualifier)
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_QUALIFIER)}" type="button">i</button>`;
  else if (ef.fee_max)
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_RANGE)}" type="button">i</button>`;
  else if (HESSEN_CHAMBERS.has(chamberSlug))
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_HESSEN)}" type="button">i</button>`;
  return `<span class="fee-info-wrap"><span class="price">${esc(ef.display)}</span>${btn}</span>`;
}

/**
 * Renders the course-fee table cell.
 * HWK Frankfurt-Rhein-Main may charge an additional Anmeldegebühr on top of
 * the listed Kursgebühr, so we add an info button for that chamber only.
 */
function courseFeeCell(c) {
  const priceSpan = `<span class="${c.course_fee ? "price" : "price-na"}">${esc(c.course_fee_display)}</span>`;
  if (c.chamber_slug === "hwk-rhein-main" && c.course_fee) {
    return `<span class="fee-info-wrap">${priceSpan}<button class="fee-info-btn" data-tooltip="${esc(ANMELDEGEBUEHR_NOTE)}" type="button">i</button></span>`;
  }
  return priceSpan;
}

function partsBadges(parts) {
  return parts.map((p) => `<span class="badge" style="display:block;margin-bottom:2px">${ROMAN[p] || p}</span>`).join("");
}

/** Sortable course-list columns (issue #56). */
export const SORTABLE_COLUMNS = {
  chamber: "Kammer",
  runtime: "Laufzeit",
  duration: "Dauer",
  course_fee: "Kursgebühr",
  exam_fee: "Prüfungsgebühr",
};

function sortValue(course, key) {
  switch (key) {
    case "chamber":
      return course.chamber_name || "";
    case "runtime":
      return course.start_date || "";
    case "duration":
      return course.duration_hours ?? null;
    case "course_fee":
      return course.course_fee ?? null;
    case "exam_fee":
      return course.exam_fee?.fee ?? null;
    default:
      return null;
  }
}

function compareSortValues(left, right) {
  const leftMissing = left === null || left === "";
  const rightMissing = right === null || right === "";
  if (leftMissing && rightMissing) return 0;
  if (leftMissing) return 1;
  if (rightMissing) return -1;
  if (typeof left === "number" && typeof right === "number") {
    return left - right;
  }
  return String(left).localeCompare(String(right), "de", { numeric: true });
}

export function sortCourses(courses, sortKey, sortDir = "asc") {
  if (!sortKey || !SORTABLE_COLUMNS[sortKey]) return courses;
  const direction = sortDir === "desc" ? -1 : 1;
  return [...courses].sort((left, right) => {
    const leftVal = sortValue(left, sortKey);
    const rightVal = sortValue(right, sortKey);
    const leftMissing = leftVal === null || leftVal === "";
    const rightMissing = rightVal === null || rightVal === "";
    if (leftMissing || rightMissing) {
      if (leftMissing && rightMissing) return 0;
      return leftMissing ? 1 : -1;
    }
    const cmp = compareSortValues(leftVal, rightVal);
    if (cmp !== 0) return direction * cmp;
    return compareSortValues(left.title || "", right.title || "");
  });
}

export function sortIndicator(sortKey, activeKey, sortDir) {
  if (sortKey !== activeKey) return "↕";
  return sortDir === "desc" ? "↓" : "↑";
}

export function rowHtml(c) {
  const titleLink = c.source_url
    ? `<a class="course-title link-icon" href="${esc(c.source_url)}" target="_blank" rel="noopener">${esc(c.title)} ↗</a>`
    : `<div class="course-title">${esc(c.title)}</div>`;
  const mobTitle = c.source_url
    ? `<a class="row-title" href="${esc(c.source_url)}" target="_blank" rel="noopener" style="color:var(--text);text-decoration:none" onclick="event.stopPropagation()">${esc(c.title)} ↗</a>`
    : `<div class="row-title">${esc(c.title)}</div>`;

  const laufzeit = c.start_date
    ? `<div style="white-space:nowrap">${fmtDate(c.start_date)}</div>` +
      (c.end_date
        ? `<div style="color:var(--text-lt);font-size:.72rem;line-height:1.2">bis</div><div style="white-space:nowrap">${fmtDate(c.end_date)}</div>`
        : "")
    : '<span style="color:var(--text-lt);font-style:italic">Termine n. v.</span>';

  const tradeMeta = c.trade_name ? `<div class="course-meta">${esc(c.trade_name)}</div>` : "";

  return `<tr>
    <td class="mob-summary" style="cursor:pointer">
      <div class="row-toggle">
        <div>${mobTitle}<div style="font-size:.75rem;color:var(--text-mid);margin-top:.15rem">${esc(c.chamber_name)}</div></div>
        <div style="display:flex;align-items:center;gap:.4rem;flex-shrink:0">
          ${availabilityBadge(c.availability, true)}
          <span class="chevron" style="font-size:.7rem;color:var(--text-lt)">▼</span>
        </div>
      </div>
    </td>
    <td data-label="Kurs" class="col-kurs">${titleLink}${tradeMeta}</td>
    <td data-label="Kammer" class="detail-cell chamber-cell">${esc(c.chamber_name)}</td>
    <td data-label="Teile" class="detail-cell" style="white-space:nowrap">${partsBadges(c.parts)}</td>
    <td data-label="Zeitmodell" class="detail-cell">${esc(c.format_display)}</td>
    <td data-label="Laufzeit" class="detail-cell" style="font-size:.82rem;font-variant-numeric:tabular-nums;">${laufzeit}</td>
    <td data-label="Dauer" class="detail-cell col-duration" style="white-space:nowrap;">${c.duration_hours ? c.duration_hours.toLocaleString("de-DE") + " Std." : "—"}</td>
    <td data-label="Kursgebühr" class="detail-cell">${courseFeeCell(c)}</td>
    <td data-label="Prüfungsgebühr" class="detail-cell">${examFeeCell(c.exam_fee, c.chamber_slug, c.parts)}</td>
    <td data-label="Ort" class="detail-cell">${esc(c.city || "—")}</td>
    <td data-label="Verfügbarkeit" class="detail-cell">${availabilityBadge(c.availability)}</td>
  </tr>`;
}

// ── Chamber filter (region accordion) ──────────────────────────────────
// Derived from data/chambers.json so the HWK list never drifts from the data.
// Rendered at build time (vite prerender) and re-rendered idempotently on the
// client, mirroring rowHtml's SSG-then-hydrate pattern.
const REGION_ORDER = ["Bayern", "Baden-Württemberg", "Hessen", "Rheinland-Pfalz", "Saarland"];

function regionSortKey(region) {
  const idx = REGION_ORDER.indexOf(region);
  return idx === -1 ? REGION_ORDER.length : idx;
}

export function chamberFilterHtml(chambers) {
  const byRegion = new Map();
  for (const c of chambers) {
    const region = c.region || "";
    if (!byRegion.has(region)) byRegion.set(region, []);
    byRegion.get(region).push(c);
  }
  const regions = [...byRegion.keys()].sort((a, b) => regionSortKey(a) - regionSortKey(b));
  return `<div class="region-accordion">${regions.map((region) => {
    const labels = byRegion.get(region).map((c) =>
      `<label><input type="checkbox" class="f-chamber" value="${esc(c.slug)}"> ${esc(c.name)}</label>`,
    ).join("");
    const summary = region ? esc(region) : "Sonstige";
    return `<details class="region-panel">
      <summary class="region-panel-summary">${summary}</summary>
      <div class="region-panel-body">${labels}</div>
    </details>`;
  }).join("")}</div>`;
}

export function emptyRow() {
  return `<tr><td colspan="10"><div class="empty-state">
    <div class="glyph" aria-hidden="true">⌖</div>
    <div class="title">Keine Kurse gefunden</div>
    <div class="hint">Passe die Filter an oder setze sie zurück, um mehr Ergebnisse zu sehen.</div>
  </div></td></tr>`;
}

// ── About-page coverage (region + chamber list, built from chambers.json) ──
// Rendered at build time (vite prerender) so the "Über"-page prose, its <ul>,
// and the SEO meta descriptions never drift from the data as chambers are added.
// Chambers are grouped by region (alphabetical, German collation) then by name.

const alphabetically = (a, b) => a.localeCompare(b, "de");

const byRegion = (chambers) => {
  const groups = new Map();
  for (const c of chambers) {
    const region = c.region || "";
    if (!groups.has(region)) groups.set(region, []);
    groups.get(region).push(c);
  }
  return groups;
};

// Bundesländer that carry a definite article in the dative "in …" phrase.
// German state names are otherwise article-less; only "das Saarland" needs one.
const REGION_DATIVE = { Saarland: "dem Saarland" };

/** Region names in German collation order, e.g. ["Hessen", "Rheinland-Pfalz", "Saarland"]. */
const regionsSorted = (chambers) => [...byRegion(chambers).keys()].sort(alphabetically);

/** "Hessen, Rheinland-Pfalz und dem Saarland" — dative enumeration for prose. */
export function regionsPhrase(chambers) {
  const regions = regionsSorted(chambers).map((r) => REGION_DATIVE[r] || r);
  if (regions.length <= 1) return regions.join("");
  return `${regions.slice(0, -1).join(", ")} und ${regions.at(-1)}`;
}

/** "Hessen & Rheinland-Pfalz & Saarland" — compact nominative list for title/eyebrow. */
export function regionsShort(chambers) {
  return regionsSorted(chambers).join(" & ");
}

/** "Hessen · Rheinland-Pfalz · Saarland" — nominative list for the page eyebrow. */
export function regionsEyebrow(chambers) {
  return regionsSorted(chambers).join(" · ");
}

/** <li> list of full chamber names ("HWK X" → "Handwerkskammer X"). */
export function coverageChambersHtml(chambers) {
  const groups = byRegion(chambers);
  return [...groups.keys()].sort(alphabetically).flatMap((region) =>
    groups.get(region)
      .sort((a, b) => alphabetically(a.name, b.name))
      .map((c) => `<li>${esc(c.name.replace(/^HWK /, "Handwerkskammer "))}</li>`),
  ).join("");
}
