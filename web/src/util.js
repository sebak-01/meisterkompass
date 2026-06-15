// Shared helpers used across the Kursfinder, map, and AFBG pages.

export const ROMAN = { 1: "I", 2: "II", 3: "III", 4: "IV" };

export const partsLabel = (parts) => parts.map((p) => ROMAN[p] || p).join(" + ");

/** German EUR, no decimals, non-breaking space: 1234 → "1.234 €". */
export const eur = (value) =>
  Number(value).toLocaleString("de-DE", { maximumFractionDigits: 0 }) + " €";

/** Escape a string for safe interpolation into innerHTML. */
export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const TOOLTIP_QUALIFIER =
  "Die Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Dies ist die Gebühr, die maximal erhoben werden kann. Häufig ist die Prüfungsgebühr tatsächlich niedriger. Erkundige dich bitte bei der jeweiligen Kammer.";
export const TOOLTIP_RANGE =
  "Die Spanne der Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Die genaue Gebühr innerhalb dieser Spanne wird von der Kammer festgelegt. Erkundige dich bitte bei der jeweiligen Kammer.";
