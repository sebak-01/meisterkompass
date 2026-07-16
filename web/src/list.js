import courses from "virtual:courses";  // courses.json with frontend-unused fields stripped
import chambers from "@data/chambers.json";
import trades from "@data/trades.json";
import { initNav } from "./nav.js";
import { ROMAN, partsLabel, esc } from "./util.js";
import { applyFilters, rowHtml, emptyRow, pageItems, fmtDate, chamberFilterHtml, sortCourses, sortIndicator } from "./render.js";

// Leaflet (~140 KB) + its CSS are loaded only when the map view is first opened,
// keeping the default list view's bundle small.
let _leafletCssLoaded = false;
async function showMap(mapData, listHref) {
  if (!_leafletCssLoaded) {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(link);
    _leafletCssLoaded = true;
  }
  const { renderMap } = await import("./map.js");
  renderMap(mapData, listHref);
}

const todayIso = (() => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
})();

const hasActiveFilters = (s) =>
  !!(s.chambers.length || s.trade || s.format || s.available || s.parts.length || s.dateFrom || s.dateTo);

// Past courses live in a separate chunk, fetched only when a date filter
// reaches into the past — keeps the default (upcoming) payload small.
let pool = courses;
let archiveLoaded = false;
const needsArchive = (s) =>
  (s.dateFrom && s.dateFrom < todayIso) || (s.dateTo && s.dateTo < todayIso);
async function ensureArchive() {
  if (archiveLoaded) return;
  const { default: archive } = await import("virtual:courses-archive");
  pool = courses.concat(archive);
  archiveLoaded = true;
}

// ── State (URL-driven for shareable links) ────────────────────────────
function readState() {
  const q = new URLSearchParams(location.search);
  return {
    chambers: q.getAll("chamber").filter(Boolean), // Array matching checked values
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
    sort: q.get("sort") || "",
    sortDir: q.get("order") === "desc" ? "desc" : "asc",
  };
}

// Append the filter params (everything except view/page) to a URLSearchParams.
function appendFilterParams(q, s) {
  s.chambers.forEach((c) => q.append("chamber", c));
  if (s.trade) q.set("trade", s.trade);
  if (s.format) q.set("format", s.format);
  if (s.available) q.set("available", "1");
  s.parts.forEach((p) => q.append("part", p));
  if (s.includeCombos) q.set("include_combos", "1");
  if (s.dateFrom) q.set("date_from", s.dateFrom);
  if (s.dateTo) q.set("date_to", s.dateTo);
}

function writeState(s, { resetPage = false } = {}) {
  if (resetPage) s.page = 1;
  const q = new URLSearchParams();
  appendFilterParams(q, s);
  if (s.perPage && s.perPage !== "20") q.set("per_page", s.perPage);
  if (s.view === "map") q.set("view", "map");
  if (s.page > 1) q.set("page", s.page);
  if (s.sort) {
    q.set("sort", s.sort);
    if (s.sortDir === "desc") q.set("order", "desc");
  }
  const qs = q.toString();
  history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
}

// Filter params excluding view/page (for the map "Zur Liste" link).
function filterParamString(s) {
  const q = new URLSearchParams();
  appendFilterParams(q, s);
  return q.toString();
}

function renderTags(s) {
  const box = document.getElementById("active-filters");
  const tags = [];
  const mk = (label, patch) => `<button class="filter-tag" data-patch='${esc(JSON.stringify(patch))}'>${esc(label)} ×</button>`;
  
  if (s.chambers.length) {
    const label = s.chambers.map((slug) => {
      const c = chambers.find((x) => x.slug === slug);
      return c ? c.name : slug;
    }).join(", ");
    tags.push(mk(label, { chambers: [] }));
  }
  if (s.trade) {
    const t = trades.find((x) => x.slug === s.trade);
    if (t) tags.push(mk(t.name, { trade: "" }));
  }
  if (s.format) tags.push(mk(s.format === "full_time" ? "Vollzeit" : "Teilzeit", { format: "" }));
  if (s.parts.length) {
    const label = s.parts.map((p) => "Teil " + ROMAN[p]).join(", ") + (s.includeCombos ? " +Kombi" : "");
    tags.push(mk(label, { parts: [], includeCombos: false }));
  }
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
function populateTradeSelect(s) {
  const sel = document.getElementById("f-trade");
  const available = new Set(
    courses.filter((c) => (s.chambers.length === 0 || s.chambers.includes(c.chamber_slug))).map((c) => c.trade_slug),
  );
  const cur = sel.value;
  sel.innerHTML = '<option value="">Beruf / Fachrichtung</option>';
  trades.filter((t) => available.has(t.slug)).forEach((t) => sel.add(new Option(t.name, t.slug)));
  if ([...sel.options].some((o) => o.value === cur)) sel.value = cur;
}

function syncControls(s) {
  document.querySelectorAll(".f-chamber").forEach((cb) => { cb.checked = s.chambers.includes(cb.value); });
  populateTradeSelect(s);
  document.getElementById("f-trade").value = s.trade;
  document.getElementById("f-format").value = s.format;
  document.getElementById("f-date-from").value = s.dateFrom;
  document.getElementById("f-date-to").value = s.dateTo;
  document.getElementById("f-per-page").value = s.perPage;
  document.querySelectorAll(".f-part").forEach((cb) => { cb.checked = s.parts.includes(Number(cb.value)); });
  document.getElementById("f-include-combos").checked = s.includeCombos;

  // ── Chambers Dropdown Button Text & Style ─────────────────
  const chambersBtn = document.getElementById("chambers-btn");
  const chambersActive = s.chambers.length > 0;
  chambersBtn.classList.toggle("active-filter", chambersActive);
  chambersBtn.textContent = "Kammern"; // Stays static
  chambersBtn.setAttribute("aria-expanded", String(document.getElementById("chambers-dropdown").classList.contains("open")));

  // ── Parts Dropdown Button Text & Style ────────────────────
  const partsBtn = document.getElementById("parts-btn");
  const partsActive = s.parts.length > 0;
  partsBtn.classList.toggle("active-filter", partsActive);
  partsBtn.textContent = "Teile"; // Stays static
  partsBtn.setAttribute("aria-expanded", String(document.getElementById("parts-dropdown").classList.contains("open")));

  const av = document.getElementById("btn-available");
  av.classList.toggle("btn-primary", s.available);
  av.classList.toggle("btn-ghost", !s.available);
  av.setAttribute("aria-pressed", String(s.available));

  document.getElementById("btn-reset").style.display = hasActiveFilters(s) ? "" : "none";

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

function syncSortHeaders(s) {
  document.querySelectorAll(".sort-btn[data-sort]").forEach((btn) => {
    const key = btn.dataset.sort;
    const active = key === s.sort;
    btn.setAttribute("aria-sort", active ? (s.sortDir === "desc" ? "descending" : "ascending") : "none");
    const indicator = btn.querySelector("[data-sort-indicator]");
    if (indicator) indicator.textContent = sortIndicator(key, s.sort, s.sortDir);
  });
}

// ── Master render ─────────────────────────────────────────────────────
let state = readState();

function render() {
  // Overriding applyFilters local chamber execution path here cleanly if your external render.js expects state.chamber as a string:
  const localStateCopy = { ...state };
  let filtered = pool;
  if (state.chambers.length > 0) {
    filtered = pool.filter(c => state.chambers.includes(c.chamber_slug));
    localStateCopy.chamber = ""; // reset fallback string so original applier avoids conflicts
  }
  filtered = applyFilters(filtered, localStateCopy, todayIso);
  filtered = sortCourses(filtered, state.sort, state.sortDir);

  // Clamp the current page to the available range before slicing.
  if (state.perPage !== "all") {
    const per = parseInt(state.perPage, 10) || 20;
    const pages = Math.max(1, Math.ceil(filtered.length / per));
    if (state.page > pages) state.page = pages;
  }

  document.getElementById("count-courses").textContent = filtered.length;
  document.getElementById("count-chambers").textContent = new Set(filtered.map((c) => c.chamber_slug)).size;
  document.getElementById("count-trades").textContent = new Set(filtered.map((c) => c.trade_slug)).size;
  document.getElementById("results-count").textContent = filtered.length;
  document.getElementById("results-noun").textContent = filtered.length === 1 ? "Kursangebot" : "Kursangebote";

  const items = pageItems(filtered, state);
  document.getElementById("course-tbody").innerHTML =
    items.length ? items.map(rowHtml).join("") : emptyRow();
  renderPagination(state, filtered.length);
  renderTags(state);
  syncSortHeaders(state);

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
        exam_fee_from_tariff: !!(c.exam_fee && c.exam_fee.from_tariff),
        format: c.format_display,
        parts: partsLabel(c.parts),
        start: fmtDate(c.start_date),
        url: c.source_url,
      }));
    const fp = filterParamString(state);
    showMap(mapData, "./index.html" + (fp ? "?" + fp : ""));
  }
}

// Render, first loading the past-courses archive if the filter reaches back.
function refresh() {
  if (needsArchive(state) && !archiveLoaded) ensureArchive().then(render);
  else render();
}

function update(patch, opts) {
  Object.assign(state, patch);
  writeState(state, opts);
  syncControls(state);
  refresh();
}

// ── Wiring ────────────────────────────────────────────────────────────
function wire() {
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
      { chambers: [], trade: "", format: "", available: false, parts: [], includeCombos: false, dateFrom: "", dateTo: "" },
      { resetPage: true },
    ),
  );

  // Chambers dropdown
  const chambersBtn = document.getElementById("chambers-btn");
  const chambersDrop = document.getElementById("chambers-dropdown");
  const syncChambersAria = () => chambersBtn.setAttribute("aria-expanded", String(chambersDrop.classList.contains("open")));
  chambersBtn.addEventListener("click", (e) => { e.stopPropagation(); chambersDrop.classList.toggle("open"); syncChambersAria(); });

  chambersDrop.addEventListener("change", (e) => {
    if (!e.target.classList.contains("f-chamber")) return;
    const selectedChambers = [...document.querySelectorAll(".f-chamber")].filter((cb) => cb.checked).map((cb) => cb.value);
    update({ chambers: selectedChambers, trade: "" }, { resetPage: true });
  });

  // Parts dropdown
  const partsBtn = document.getElementById("parts-btn");
  const partsDrop = document.getElementById("parts-dropdown");
  const syncPartsAria = () => partsBtn.setAttribute("aria-expanded", String(partsDrop.classList.contains("open")));
  partsBtn.addEventListener("click", (e) => { e.stopPropagation(); partsDrop.classList.toggle("open"); syncPartsAria(); });

  const applyPartsFilter = () => {
    const parts = [...document.querySelectorAll(".f-part")].filter((cb) => cb.checked).map((cb) => Number(cb.value));
    const includeCombos = document.getElementById("f-include-combos").checked;
    update({ parts, includeCombos }, { resetPage: true });
  };
  partsDrop.addEventListener("change", (e) => {
    if (e.target.classList.contains("f-part") || e.target.id === "f-include-combos") applyPartsFilter();
  });

  document.addEventListener("click", (e) => {
    if (!document.getElementById("parts-wrap").contains(e.target)) { partsDrop.classList.remove("open"); syncPartsAria(); }
    if (!document.getElementById("chambers-wrap").contains(e.target)) { chambersDrop.classList.remove("open"); syncChambersAria(); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (partsDrop.classList.contains("open")) { partsDrop.classList.remove("open"); syncPartsAria(); partsBtn.focus(); }
      if (chambersDrop.classList.contains("open")) { chambersDrop.classList.remove("open"); syncChambersAria(); chambersBtn.focus(); }
    }
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

  document.querySelectorAll(".sort-btn[data-sort]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      const nextDir = state.sort === key && state.sortDir === "asc" ? "desc" : "asc";
      update({ sort: key, sortDir: nextDir }, { resetPage: true });
    });
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
    const active = hasActiveFilters(state);
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
document.getElementById("chambers-options").innerHTML = chamberFilterHtml(chambers);
populateTradeSelect(state);
syncControls(state);
wire();
refresh();