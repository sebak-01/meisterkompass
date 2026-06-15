import courses from "@data/courses.json";
import chambers from "@data/chambers.json";
import trades from "@data/trades.json";
import { initNav } from "./nav.js";
import { renderMap } from "./map.js";

const PER_PAGE_OPTIONS = [10, 20, 30, 40, 60];
const ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV" };

const TOOLTIP_QUALIFIER =
  "Die Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Dies ist die Gebühr, die maximal erhoben werden kann. Häufig ist die Prüfungsgebühr tatsächlich niedriger. Erkundige dich bitte bei der jeweiligen Kammer.";
const TOOLTIP_RANGE =
  "Die Spanne der Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Die genaue Gebühr innerhalb dieser Spanne wird von der Kammer festgelegt. Erkundige dich bitte bei der jeweiligen Kammer.";

const todayIso = (() => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
})();

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDate = (iso) => (iso ? iso.split("-").reverse().join(".") : "");
const partsLabel = (parts) => parts.map((p) => ROMAN[p] || p).join(" + ");

// ── State (URL-driven for shareable links) ────────────────────────────
function readState() {
  const q = new URLSearchParams(location.search);
  return {
    chamber: q.get("chamber") || "",
    trade: q.get("trade") || "",
    format: q.get("format") || "",
    available: q.get("available") === "1",
    parts: q.getAll("part").map(Number).filter((n) => [1, 2, 3, 4].includes(n)),
    includeCombos: q.get("include_combos") === "1",
    dateFrom: q.get("date_from") || "",
    dateTo: q.get("date_to") || "",
    perPage: q.get("per_page") || "20",
    view: q.get("view") === "map" ? "map" : "list",
    page: Math.max(1, parseInt(q.get("page") || "1", 10) || 1),
  };
}

function writeState(s, { resetPage = false } = {}) {
  if (resetPage) s.page = 1;
  const q = new URLSearchParams();
  if (s.chamber) q.set("chamber", s.chamber);
  if (s.trade) q.set("trade", s.trade);
  if (s.format) q.set("format", s.format);
  if (s.available) q.set("available", "1");
  s.parts.forEach((p) => q.append("part", p));
  if (s.includeCombos) q.set("include_combos", "1");
  if (s.dateFrom) q.set("date_from", s.dateFrom);
  if (s.dateTo) q.set("date_to", s.dateTo);
  if (s.perPage && s.perPage !== "20") q.set("per_page", s.perPage);
  if (s.view === "map") q.set("view", "map");
  if (s.page > 1) q.set("page", s.page);
  const qs = q.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

// Filter params excluding view/page (for the map "Zur Liste" link + tags).
function filterParamString(s) {
  const q = new URLSearchParams();
  if (s.chamber) q.set("chamber", s.chamber);
  if (s.trade) q.set("trade", s.trade);
  if (s.format) q.set("format", s.format);
  if (s.available) q.set("available", "1");
  s.parts.forEach((p) => q.append("part", p));
  if (s.includeCombos) q.set("include_combos", "1");
  if (s.dateFrom) q.set("date_from", s.dateFrom);
  if (s.dateTo) q.set("date_to", s.dateTo);
  return q.toString();
}

// ── Filtering (port of courses/views.py _apply_filters) ───────────────
function applyFilters(s) {
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

// ── Rendering ─────────────────────────────────────────────────────────
function availabilityBadge(a, small = false) {
  const style = small ? ' style="font-size:.65rem;padding:1px 6px"' : "";
  if (a === "full") return `<span class="badge badge-full"${style}>Ausgebucht</span>`;
  if (a === "waitlist") return `<span class="badge badge-waitlist"${style}>${small ? "Warteliste" : "Warteliste"}</span>`;
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

function rowHtml(c) {
  const titleLink = c.source_url
    ? `<a class="course-title link-icon" href="${esc(c.source_url)}" target="_blank">${esc(c.title)} ↗</a>`
    : `<div class="course-title">${esc(c.title)}</div>`;
  const mobTitle = c.source_url
    ? `<a class="row-title" href="${esc(c.source_url)}" target="_blank" style="color:var(--text);text-decoration:none" onclick="event.stopPropagation()">${esc(c.title)} ↗</a>`
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

function emptyRow() {
  return `<tr><td colspan="10"><div class="empty-state">
    <div class="glyph" aria-hidden="true">⌖</div>
    <div class="title">Keine Kurse gefunden</div>
    <div class="hint">Passe die Filter an oder setze sie zurück, um mehr Ergebnisse zu sehen.</div>
  </div></td></tr>`;
}

function renderTags(s) {
  const box = document.getElementById("active-filters");
  const tags = [];
  const mk = (label, patch) => `<button class="filter-tag" data-patch='${esc(JSON.stringify(patch))}'>${esc(label)} ×</button>`;
  if (s.chamber) {
    const c = chambers.find((x) => x.slug === s.chamber);
    if (c) tags.push(mk(c.name, { chamber: "" }));
  }
  if (s.trade) {
    const t = trades.find((x) => x.slug === s.trade);
    if (t) tags.push(mk(t.name, { trade: "" }));
  }
  if (s.format) tags.push(mk(s.format === "full_time" ? "Vollzeit" : "Teilzeit", { format: "" }));
  if (s.available) tags.push(mk("Nur freie Plätze", { available: false }));
  if (s.dateFrom) tags.push(mk("ab " + s.dateFrom, { dateFrom: "" }));
  box.innerHTML = tags.join("");
  box.style.display = tags.length ? "flex" : "none";
}

function renderPagination(s, total) {
  const el = document.getElementById("pagination");
  if (s.perPage === "all") { el.innerHTML = ""; return; }
  const per = parseInt(s.perPage, 10) || 20;
  const pages = Math.ceil(total / per);
  if (pages <= 1) { el.innerHTML = ""; return; }
  let html = "";
  if (s.page > 1) html += `<a data-page="${s.page - 1}" role="button" tabindex="0" aria-label="Vorherige Seite">‹</a>`;
  html += `<span class="current" aria-current="page">${s.page}</span><span style="color:var(--text-lt)">von ${pages}</span>`;
  if (s.page < pages) html += `<a data-page="${s.page + 1}" role="button" tabindex="0" aria-label="Nächste Seite">›</a>`;
  el.innerHTML = html;
}

// ── Trade dropdown depends on selected chamber ────────────────────────
function populateChamberSelect() {
  const sel = document.getElementById("f-chamber");
  chambers.forEach((c) => sel.add(new Option(c.name, c.slug)));
}
function populateTradeSelect(s) {
  const sel = document.getElementById("f-trade");
  const available = new Set(
    courses.filter((c) => (!s.chamber || c.chamber_slug === s.chamber)).map((c) => c.trade_slug),
  );
  const cur = sel.value;
  sel.innerHTML = '<option value="">Beruf / Fachrichtung</option>';
  trades.filter((t) => available.has(t.slug)).forEach((t) => sel.add(new Option(t.name, t.slug)));
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

function syncControls(s) {
  document.getElementById("f-chamber").value = s.chamber;
  populateTradeSelect(s);
  document.getElementById("f-trade").value = s.trade;
  document.getElementById("f-format").value = s.format;
  document.getElementById("f-date-from").value = s.dateFrom;
  document.getElementById("f-date-to").value = s.dateTo;
  document.getElementById("f-per-page").value = s.perPage;
  document.querySelectorAll(".f-part").forEach((cb) => { cb.checked = s.parts.includes(Number(cb.value)); });
  document.getElementById("f-include-combos").checked = s.includeCombos;

  const partsBtn = document.getElementById("parts-btn");
  partsBtn.classList.toggle("active-filter", s.parts.length > 0);
  partsBtn.textContent = s.parts.length
    ? s.parts.map((p) => "Teil " + ROMAN[p]).join(", ") + (s.includeCombos ? " +Kombi" : "") + " ▾"
    : "Teile ▾";

  const av = document.getElementById("btn-available");
  av.classList.toggle("btn-primary", s.available);
  av.classList.toggle("btn-ghost", !s.available);
  av.setAttribute("aria-pressed", String(s.available));

  const partsBtnEl = document.getElementById("parts-btn");
  partsBtnEl.setAttribute("aria-expanded", String(document.getElementById("parts-dropdown").classList.contains("open")));

  document.getElementById("btn-reset").style.display =
    s.chamber || s.trade || s.format || s.available || s.parts.length || s.dateFrom || s.dateTo ? "" : "none";

  const isMap = s.view === "map";
  const btnList = document.getElementById("btn-list");
  const btnMap = document.getElementById("btn-map");
  btnList.classList.toggle("active", !isMap);
  btnMap.classList.toggle("active", isMap);
  btnList.setAttribute("aria-pressed", String(!isMap));
  btnMap.setAttribute("aria-pressed", String(isMap));
  document.getElementById("view-list").style.display = isMap ? "none" : "";
  document.getElementById("view-map").style.display = isMap ? "" : "none";
}

// ── Master render ─────────────────────────────────────────────────────
let state = readState();

function render() {
  const filtered = applyFilters(state);

  document.getElementById("count-courses").textContent = filtered.length;
  document.getElementById("count-chambers").textContent = new Set(filtered.map((c) => c.chamber_slug)).size;
  document.getElementById("results-count").textContent = filtered.length;
  document.getElementById("results-noun").textContent = filtered.length === 1 ? "Kursangebot" : "Kursangebote";

  // Pagination slice
  let pageItems = filtered;
  if (state.perPage !== "all") {
    const per = parseInt(state.perPage, 10) || 20;
    const pages = Math.max(1, Math.ceil(filtered.length / per));
    if (state.page > pages) state.page = pages;
    const start = (state.page - 1) * per;
    pageItems = filtered.slice(start, start + per);
  }

  document.getElementById("course-tbody").innerHTML =
    pageItems.length ? pageItems.map(rowHtml).join("") : emptyRow();
  renderPagination(state, filtered.length);
  renderTags(state);

  if (state.view === "map") {
    const mapData = filtered
      .filter((c) => c.latitude != null && c.longitude != null)
      .map((c) => ({
        title: c.title,
        trade: c.trade_name || "Allgemein",
        chamber: c.chamber_name,
        city: c.city,
        lat: +c.latitude,
        lng: +c.longitude,
        fee: c.course_fee,
        exam_fee_display: c.exam_fee ? c.exam_fee.display : "",
        format: c.format_display,
        parts: partsLabel(c.parts),
        start: fmtDate(c.start_date),
        url: c.source_url,
      }));
    const fp = filterParamString(state);
    renderMap(mapData, "./index.html" + (fp ? "?" + fp : ""));
  }
}

function update(patch, opts) {
  Object.assign(state, patch);
  writeState(state, opts);
  syncControls(state);
  render();
}

// ── Wiring ────────────────────────────────────────────────────────────
function wire() {
  document.getElementById("f-chamber").addEventListener("change", (e) =>
    update({ chamber: e.target.value, trade: "" }, { resetPage: true }),
  );
  document.getElementById("f-trade").addEventListener("change", (e) =>
    update({ trade: e.target.value }, { resetPage: true }),
  );
  document.getElementById("f-format").addEventListener("change", (e) =>
    update({ format: e.target.value }, { resetPage: true }),
  );
  document.getElementById("f-date-from").addEventListener("change", (e) =>
    update({ dateFrom: e.target.value }, { resetPage: true }),
  );
  document.getElementById("f-date-to").addEventListener("change", (e) =>
    update({ dateTo: e.target.value }, { resetPage: true }),
  );
  document.getElementById("f-per-page").addEventListener("change", (e) =>
    update({ perPage: e.target.value }, { resetPage: true }),
  );
  document.getElementById("btn-available").addEventListener("click", () =>
    update({ available: !state.available }, { resetPage: true }),
  );
  document.getElementById("btn-reset").addEventListener("click", () =>
    update(
      { chamber: "", trade: "", format: "", available: false, parts: [], includeCombos: false, dateFrom: "", dateTo: "" },
      { resetPage: true },
    ),
  );

  // Parts dropdown
  const partsBtn = document.getElementById("parts-btn");
  const partsDrop = document.getElementById("parts-dropdown");
  const syncPartsAria = () => partsBtn.setAttribute("aria-expanded", String(partsDrop.classList.contains("open")));
  partsBtn.addEventListener("click", (e) => { e.stopPropagation(); partsDrop.classList.toggle("open"); syncPartsAria(); });
  document.addEventListener("click", (e) => {
    if (!document.getElementById("parts-wrap").contains(e.target)) { partsDrop.classList.remove("open"); syncPartsAria(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && partsDrop.classList.contains("open")) { partsDrop.classList.remove("open"); syncPartsAria(); partsBtn.focus(); }
  });
  document.getElementById("parts-apply").addEventListener("click", () => {
    const parts = [...document.querySelectorAll(".f-part")].filter((cb) => cb.checked).map((cb) => Number(cb.value));
    const includeCombos = document.getElementById("f-include-combos").checked;
    partsDrop.classList.remove("open");
    update({ parts, includeCombos }, { resetPage: true });
  });

  // View toggle
  document.getElementById("btn-list").addEventListener("click", () => update({ view: "list" }));
  document.getElementById("btn-map").addEventListener("click", () => update({ view: "map" }));

  // Active-filter tags (delegated)
  document.getElementById("active-filters").addEventListener("click", (e) => {
    const t = e.target.closest(".filter-tag");
    if (t) update(JSON.parse(t.dataset.patch), { resetPage: true });
  });

  // Pagination (delegated)
  const goPage = (a) => { update({ page: parseInt(a.dataset.page, 10) }); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const pager = document.getElementById("pagination");
  pager.addEventListener("click", (e) => { const a = e.target.closest("a[data-page]"); if (a) goPage(a); });
  pager.addEventListener("keydown", (e) => {
    const a = e.target.closest("a[data-page]");
    if (a && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); goPage(a); }
  });

  // Mobile accordion (delegated)
  document.getElementById("course-tbody").addEventListener("click", (e) => {
    const summary = e.target.closest(".mob-summary");
    if (summary && !e.target.closest("a")) summary.closest("tr").classList.toggle("open");
  });

  // Mobile filter toggle
  const ftb = document.getElementById("filter-toggle-btn");
  const panel = document.getElementById("filter-panel-mobile");
  ftb.addEventListener("click", () => {
    const open = panel.classList.toggle("open");
    ftb.querySelector(".ftb-chevron").style.transform = open ? "rotate(180deg)" : "";
    ftb.setAttribute("aria-expanded", String(open));
  });
  function initMobileFilter() {
    const active = state.chamber || state.trade || state.format || state.available || state.parts.length || state.dateFrom || state.dateTo;
    document.getElementById("filter-badge").style.display = active ? "" : "none";
    if (window.innerWidth <= 640) {
      ftb.style.display = "flex";
      if (active) { panel.classList.add("open"); ftb.querySelector(".ftb-chevron").style.transform = "rotate(180deg)"; }
    } else {
      ftb.style.display = "none";
      panel.classList.add("open");
    }
  }
  window.addEventListener("resize", () => {
    initMobileFilter();
    if (window.innerWidth > 640) document.querySelectorAll(".course-table tr.open").forEach((tr) => tr.classList.remove("open"));
  });
  initMobileFilter();

  // Back to top
  const btt = document.getElementById("back-to-top");
  btt.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  window.addEventListener("scroll", () => { btt.style.display = window.scrollY > 400 ? "flex" : "none"; });
}

initNav();
populateChamberSelect();
syncControls(state);
wire();
render();
