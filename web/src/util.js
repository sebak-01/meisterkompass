// Shared helpers used across the Kursfinder, map, and AFBG pages.

export const ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV" };

export const partsLabel = (parts) => parts.map((p) => ROMAN[p] || p).join(" + ");

/** German euro formatting, no decimals, non-breaking space: 1234 → "1.234 €". */
export const eur = (value) =>
  Number(value).toLocaleString("de-DE", { maximumFractionDigits: 0 }) + " €";

/** Escape a string for safe interpolation into innerHTML. */
export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ── Exam-fee tooltip texts ─────────────────────────────────────────────

/** Fee from Gebührenverzeichnis (manual entry or PDF scrape), not the course page. */
export const TOOLTIP_TARIFF =
  "Die Prüfungsgebühren wurden aus dem Gebührenverzeichnis der Kammer übernommen. Diese können sich ändern. Teilweise kommen gewerkspezifische oder andere Gebühren hinzu.";

/** HWK Frankfurt-Rhein-Main charges an additional registration fee on top of the course fee. */
export const ANMELDEGEBUEHR_NOTE =
  "Die HWK Frankfurt-Rhein-Main erhebt möglicherweise eine zusätzliche Anmeldegebühr. Informiere dich zu den genauen Gebühren bei der HWK Frankfurt-Rhein-Main.";

/** Start date published as month/year only — exact day not yet fixed. */
export const TENTATIVE_START_DATE_NOTE = "Genauer Termin steht noch nicht fest.";