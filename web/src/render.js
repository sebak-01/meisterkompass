// Pure (DOM-free) rendering + filtering for the course list.
// Imported by both list.js (browser, runtime) and the Vite prerender plugin
// (Node, build time) so the prerendered HTML matches what the client produces.

import { ROMAN, partsLabel, esc, TOOLTIP_QUALIFIER, TOOLTIP_RANGE } from "./util.js";

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

function examFeeCell(ef) {
  if (!ef || !ef.fee) return '<span class="price-na">—</span>';
  let btn = "";
  if (ef.qualifier)
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_QUALIFIER)}" type="button">i</button>`;
  else if (ef.fee_max)
    btn = `<button class="fee-info-btn" data-tooltip="${esc(TOOLTIP_RANGE)}" type="button">i</button>`;
  return `<span class="fee-info-wrap"><span class="price">${esc(ef.display)}</span>${btn}</span>`;
}

function partsBadges(parts) {
  return parts.map((p) => `<span class="badge" style="display:block;margin-bottom:2px">${ROMAN[p] || p}</span>`).join("");
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
    <td data-label="Kammer" class="detail-cell" style="white-space:nowrap;font-size:.82rem;">${esc(c.chamber_name)}</td>
    <td data-label="Teile" class="detail-cell" style="white-space:nowrap">${partsBadges(c.parts)}</td>
    <td data-label="Zeitmodell" class="detail-cell">${esc(c.format_display)}</td>
    <td data-label="Laufzeit" class="detail-cell" style="font-size:.82rem;font-variant-numeric:tabular-nums;">${laufzeit}</td>
    <td data-label="Dauer" class="detail-cell col-duration" style="white-space:nowrap;">${c.duration_hours ? c.duration_hours + " Std." : "—"}</td>
    <td data-label="Kursgebühr" class="detail-cell"><span class="${c.course_fee ? "price" : "price-na"}">${esc(c.course_fee_display)}</span></td>
    <td data-label="Prüfungsgebühr" class="detail-cell">${examFeeCell(c.exam_fee)}</td>
    <td data-label="Ort" class="detail-cell">${esc(c.city || "—")}</td>
    <td data-label="Verfügbarkeit" class="detail-cell">${availabilityBadge(c.availability)}</td>
  </tr>`;
}

export function emptyRow() {
  return `<tr><td colspan="10"><div class="empty-state">
    <div class="glyph" aria-hidden="true">⌖</div>
    <div class="title">Keine Kurse gefunden</div>
    <div class="hint">Passe die Filter an oder setze sie zurück, um mehr Ergebnisse zu sehen.</div>
  </div></td></tr>`;
}
