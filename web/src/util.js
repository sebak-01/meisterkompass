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

/** HWK Koblenz: fee carries a "bis zu" qualifier — maximal amount. */
export const TOOLTIP_QUALIFIER =
  "Die Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Dies ist die Gebühr, die maximal erhoben werden kann. Häufig ist die Prüfungsgebühr tatsächlich niedriger. Erkundige dich bitte bei der jeweiligen Kammer.";

/** Published fee contains an explicitly approximate component. */
export const TOOLTIP_APPROXIMATE =
  "Die angegebene Prüfungsgebühr enthält einen von der Kammer als circa-Betrag veröffentlichten Bestandteil. Die tatsächliche Gebühr kann abweichen.";

/** HWK Rheinhessen: fee is a range (fee … fee_max). */
export const TOOLTIP_RANGE =
  "Die Spanne der Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Die genaue Gebühr innerhalb dieser Spanne wird von der Kammer festgelegt. Erkundige dich bitte bei der jeweiligen Kammer.";

/** HWK Frankfurt-Rhein-Main, HWK Wiesbaden, HWK Kassel: exact fee from fee schedule, subject to change. */
export const TOOLTIP_HESSEN =
  "Die Prüfungsgebühren entstammen dem offiziellen Gebührenverzeichnis der Kammer. Die Prüfungsgebühren können sich ändern. Für genauere Informationen erkundige dich bitte bei der Kammer.";

/** HWK Frankfurt-Rhein-Main charges an additional registration fee on top of the course fee. */
export const ANMELDEGEBUEHR_NOTE =
  "Die HWK Frankfurt-Rhein-Main erhebt möglicherweise eine zusätzliche Anmeldegebühr. Informiere dich zu den genauen Gebühren bei der HWK Frankfurt-Rhein-Main.";

/** HWK Region Stuttgart charges a separate practical-exam fee for Part I. */
export const STUTTGART_PRACTICAL_EXAM_NOTE =
  "Die HWK Region Stuttgart erhebt zusätzlich für die Abnahme der praktischen Prüfung eine Sondergebühr in Höhe von 250 €.";

/** HWK Reutlingen may pass on additional practical-exam expenses for Part I. */
export const REUTLINGEN_ADDITIONAL_EXAM_NOTE =
  "Bei Meisterprüfungen, für die von der HWK Reutlingen zusätzlich Personal-, Material-, Raum- und Sachkosten geleistet werden, ist die Gebühr entsprechend zu erhöhen. Je nach Gewerk liegt der Rahmen zwischen 300 € und 1.500 €";

/** Slugs of the three Hessen chambers — used by render.js and afbg.js to select TOOLTIP_HESSEN. */
export const HESSEN_CHAMBERS = new Set(["hwk-rhein-main", "hwk-wiesbaden", "hwk-kassel"]);