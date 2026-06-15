import chambersData from "@data/chambers.json";
import tradesData from "@data/trades.json";
import courseFeesData from "@data/course_fees.json";
import examFeesData from "@data/exam_fees.json";
import { initNav } from "./nav.js";
import { partsLabel } from "./util.js";

const partsKey = (parts) => parts.slice().sort((a, b) => a - b).join(",");
const makeGroup = (parts, opts = {}) => ({
  parts, courseFee: null, examFee: null, examFeeMin: null, examFeeMax: null,
  qualifier: "", isAuto: false, isCombo: false, ...opts,
});

// Slugs are the stable ids now (no integer DB ids).
const CHAMBERS = chambersData.map((c) => ({ id: c.slug, name: c.name, slug: c.slug }));
const COURSE_FEES = courseFeesData.map((o) => ({
  chamber_id: o.chamber_slug,
  trade_id: o.trade_slug,
  parts: o.parts,
  fee: o.fee,
  exam_fee_scraped: o.exam_fee_scraped,
  is_generic: o.is_generic,
}));
const EXAM_FEES = examFeesData.nested;
// Only trades that have a Part I/II course offer (mirrors the old AfbgView filter).
const tradeIds12 = new Set(
  COURSE_FEES.filter((o) => o.trade_id && o.parts.some((p) => p === 1 || p === 2)).map((o) => o.trade_id),
);
const TRADES = tradesData.filter((t) => tradeIds12.has(t.slug)).map((t) => ({ id: t.slug, name: t.name, slug: t.slug }));

const PART_LABELS = { 1: "Teil I", 2: "Teil II", 3: "Teil III", 4: "Teil IV" };
const MAX_FOERDERBAR = 15000;
let currentMode = "auto";
let currentCid = null;
let currentTid = null;
let feeGroups = [];

function setMode(mode) {
  currentMode = mode;
  document.getElementById("mode-auto").style.display = mode === "auto" ? "" : "none";
  const ba = document.getElementById("btn-mode-auto");
  const bm = document.getElementById("btn-mode-manual");
  ba.classList.toggle("active", mode === "auto");
  bm.classList.toggle("active", mode === "manual");
  ba.setAttribute("aria-pressed", String(mode === "auto"));
  bm.setAttribute("aria-pressed", String(mode === "manual"));
  if (mode === "manual") {
    feeGroups = [];
    [1, 2, 3, 4].forEach((p) => { document.getElementById("chk" + p).checked = false; });
  }
  renderFeeInputs();
}

function resetComboOptions() {
  const el = document.getElementById("prefer-singles");
  if (el) el.checked = false;
}

function onChamberChange() {
  resetComboOptions();
  currentCid = document.getElementById("auto-chamber").value || null;
  currentTid = null;
  feeGroups = [];
  const sel = document.getElementById("auto-trade");
  sel.innerHTML = '<option value="">– Beruf/Fachrichtung wählen –</option>';
  [1, 2, 3, 4].forEach((p) => { document.getElementById("chk" + p).checked = false; });

  if (!currentCid) { sel.disabled = true; renderFeeInputs(); return; }

  const tradeIds = {};
  COURSE_FEES.forEach((o) => {
    if (o.chamber_id === currentCid && o.trade_id) tradeIds[o.trade_id] = true;
  });
  const filtered = TRADES.filter((t) => tradeIds[t.id]);
  filtered.forEach((t) => { const opt = document.createElement("option"); opt.value = t.id; opt.text = t.name; sel.add(opt); });
  sel.disabled = filtered.length === 0;
  renderFeeInputs();
}

function onTradeChange() {
  currentTid = document.getElementById("auto-trade").value || null;
  feeGroups = [];
  [1, 2, 3, 4].forEach((p) => { document.getElementById("chk" + p).checked = false; });
  if (!currentCid) { renderFeeInputs(); return; }

  if (currentTid) {
    const tradeOffers = COURSE_FEES.filter((o) => o.chamber_id === currentCid && o.trade_id === currentTid);
    buildGroupsFromOffers(tradeOffers, true);
  }

  const genericOffers = COURSE_FEES.filter((o) => o.chamber_id === currentCid && o.is_generic);
  buildGroupsFromOffers(genericOffers, true);

  fillExamFees();

  feeGroups.forEach((g) => { g.parts.forEach((p) => { document.getElementById("chk" + p).checked = true; }); });
  renderFeeInputs();
}

function buildGroupsFromOffers(offers, isAuto) {
  offers.forEach((o) => {
    const alreadyCovered = feeGroups.some((g) => partsKey(g.parts) === partsKey(o.parts));
    if (alreadyCovered) return;
    feeGroups.push(makeGroup(o.parts.slice().sort(), {
      courseFee: o.fee, isAuto, isCombo: o.parts.length > 1,
    }));
  });
}

function fillExamFees() {
  if (!currentCid) return;
  const cidStr = String(currentCid);
  const efChamber = EXAM_FEES[cidStr] || {};
  const tidStr = currentTid ? String(currentTid) : null;

  const efByPart = {};
  const efNull = efChamber["null"] || {};
  const efTrade = tidStr && efChamber[tidStr] ? efChamber[tidStr] : {};
  Object.keys(efNull).forEach((k) => { efByPart[parseInt(k)] = efNull[k]; });
  Object.keys(efTrade).forEach((k) => { efByPart[parseInt(k)] = efTrade[k]; });

  feeGroups.forEach((g) => {
    let totalFee = 0, totalMin = 0, totalMax = 0;
    let hasMax = false, qualifier = "", hasAny = false;

    g.parts.forEach((p) => {
      const ef = efByPart[p];
      if (ef) {
        hasAny = true;
        const fee = ef.fee_max ? Math.round((ef.fee + ef.fee_max) / 2) : ef.fee;
        totalFee += fee;
        totalMin += ef.fee;
        if (ef.fee_max) { totalMax += ef.fee_max; hasMax = true; }
        else { totalMax += ef.fee; }
        if (ef.qualifier) qualifier = ef.qualifier;
      }
    });

    if (!hasAny) {
      const matchingOffers = COURSE_FEES.filter((o) => {
        if (o.chamber_id !== currentCid) return false;
        if (o.exam_fee_scraped == null) return false;
        const sameParts = partsKey(o.parts) === partsKey(g.parts);
        const isGeneric = o.is_generic;
        const tradeMatch = isGeneric || (currentTid && o.trade_id === currentTid);
        return sameParts && tradeMatch;
      });
      if (matchingOffers.length > 0 && matchingOffers[0].exam_fee_scraped) {
        hasAny = true;
        totalFee = matchingOffers[0].exam_fee_scraped;
        totalMin = totalFee;
      }
    }

    if (hasAny) {
      g.examFee = totalFee;
      g.examFeeMin = totalMin;
      g.examFeeMax = hasMax ? totalMax : null;
      g.qualifier = qualifier;
    }
  });
}

function onPartCheck(p) {
  const checked = document.getElementById("chk" + p).checked;
  const preferSinglesEl = document.getElementById("prefer-singles");
  const preferSingles = preferSinglesEl ? preferSinglesEl.checked : false;
  if (!preferSingles) {
    feeGroups.forEach((g) => {
      if (g.isCombo && g.parts.indexOf(p) >= 0) {
        g.parts.forEach((sibling) => { document.getElementById("chk" + sibling).checked = checked; });
      }
    });
  }
  if (currentMode === "manual" && checked) {
    const inGroup = feeGroups.some((g) => g.parts.indexOf(p) >= 0);
    if (!inGroup) feeGroups.push(makeGroup([p]));
  }
  renderFeeInputs();
}

function renderFeeInputs() {
  const parts = [1, 2, 3, 4].filter((p) => document.getElementById("chk" + p).checked);
  const container = document.getElementById("fee-inputs");
  container.innerHTML = "";

  if (parts.length === 0 && feeGroups.length === 0) {
    container.innerHTML = '<p style="font-size:.82rem;color:var(--text-lt);margin-bottom:.75rem">Bitte mindestens einen Teil auswählen.</p>';
    return;
  }

  const candidateGroups = feeGroups.filter((g) => g.parts.every((p) => parts.indexOf(p) >= 0));
  const allComboGroups = candidateGroups.filter((g) => g.parts.length > 1);

  const comboOpts = document.getElementById("combo-options");
  const anyCombo = allComboGroups.length > 0;
  if (comboOpts) comboOpts.style.display = anyCombo ? "block" : "none";

  const preferSinglesEl = document.getElementById("prefer-singles");
  const preferSingles = preferSinglesEl ? preferSinglesEl.checked : false;

  let groupsToRender;
  if (preferSingles) {
    const shownGroups = [];
    parts.forEach((p) => {
      const indiv = candidateGroups.find((g) => g.parts.length === 1 && g.parts[0] === p);
      if (indiv) {
        shownGroups.push(indiv);
      } else {
        const fallback = allComboGroups
          .filter((g) => g.parts.indexOf(p) >= 0)
          .sort((a, b) => a.parts.length - b.parts.length)[0];
        if (fallback && shownGroups.indexOf(fallback) < 0) shownGroups.push(fallback);
      }
    });
    groupsToRender = shownGroups;
  } else {
    const activeComboGroups = allComboGroups;
    groupsToRender = candidateGroups.filter((g) => {
      if (g.parts.length === 1) {
        return !activeComboGroups.some((combo) => combo.parts.indexOf(g.parts[0]) >= 0);
      }
      return true;
    });
  }

  if (feeGroups.length === 0) {
    groupsToRender = parts.map((p) => makeGroup([p]));
  }
  groupsToRender.sort((a, b) => a.parts[0] - b.parts[0]);

  if (groupsToRender.length === 0) {
    container.innerHTML = '<p style="font-size:.82rem;color:var(--text-lt);margin-bottom:.75rem">Bitte mindestens einen Teil auswählen.</p>';
    return;
  }

  let html = "";
  groupsToRender.forEach((g, idx) => {
    const cFee = g.courseFee != null ? g.courseFee : "";
    const eFee = g.examFee != null ? g.examFee : "";
    const partsStr = partsLabel(g.parts);
    const title = g.parts.length > 1
      ? "Teile " + partsStr + (g.isAuto ? '<span class="auto-badge">Auto</span>' : '') + ' <span class="combo-note">(Kombikurs)</span>'
      : PART_LABELS[g.parts[0]] + (g.isAuto ? '<span class="auto-badge">Auto</span>' : '');

    html +=
      '<div class="part-fee-block' + (g.isCombo ? " combo-block" : "") + '">' +
        '<div class="part-title">' + title + "</div>" +
        '<div class="field-row">' +
          '<div class="field"><label for="g-course-' + idx + '">Kursgebühr (€)</label>' +
          '<input type="number" id="g-course-' + idx + '" aria-label="Kursgebühr ' + partsStr + '" value="' + cFee + '" min="0" step="10" placeholder="z. B. 7.300"></div>' +
          '<div class="field"><label for="g-exam-' + idx + '">' + buildExamLabel(g) + "</label>" +
          '<input type="number" id="g-exam-' + idx + '" aria-label="Prüfungsgebühr ' + partsStr + '" value="' + eFee + '" min="0" step="10" placeholder="z. B. 1.130"></div>' +
        "</div>" +
      "</div>";
  });
  container.innerHTML = html;
  window._currentGroups = groupsToRender;
}

function buildExamLabel(g) {
  let label = "Prüfungsgebühr (€)";
  if (g.examFeeMax) {
    const tt = "Die Spanne der Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Die genaue Gebühr innerhalb dieser Spanne wird von der Kammer festgelegt. Erkundige dich gerne bei der jeweiligen Kammer.";
    const span = Math.round(g.examFeeMin).toLocaleString("de-DE") + " bis " + Math.round(g.examFeeMax).toLocaleString("de-DE") + " €";
    label += ' <span class="fee-info-wrap-calc"><small style="color:var(--text-lt)">' + span + '</small><button class="fee-info-btn-calc" type="button" data-tooltip="' + tt + '">i</button></span>';
  } else if (g.qualifier) {
    const tt2 = "Die Prüfungsgebühr je Teil entstammt dem offiziellen Gebührenverzeichnis. Dies ist die Gebühr, die maximal erhoben werden kann. Häufig ist die Prüfungsgebühr tatsächlich niedriger. Erkundige dich gerne bei der jeweiligen Kammer.";
    label += ' <span class="fee-info-wrap-calc"><small style="color:var(--text-lt)">' + g.qualifier + '</small><button class="fee-info-btn-calc" type="button" data-tooltip="' + tt2 + '">i</button></span>';
  }
  return label;
}

function fmt(v) {
  return v.toLocaleString("de-DE", { minimumFractionDigits: 0, maximumFractionDigits: 0 }) + " €";
}

function calculate() {
  const groups = window._currentGroups || [];
  if (groups.length === 0) { alert("Bitte mindestens einen Teil auswählen."); return; }

  let totalCourse = 0, totalExam = 0, missing = false;
  groups.forEach((g, idx) => {
    const cEl = document.getElementById("g-course-" + idx);
    const eEl = document.getElementById("g-exam-" + idx);
    const c = cEl ? parseFloat(cEl.value) || 0 : 0;
    const e = eEl ? parseFloat(eEl.value) || 0 : 0;
    totalCourse += c;
    totalExam += e;
    if (!c) missing = true;
  });

  const projektKosten = parseFloat(document.getElementById("fee-projekt").value) || 0;

  const total = totalCourse + totalExam;
  const foerderbar = Math.min(total, MAX_FOERDERBAR);
  const zuschuss = foerderbar * 0.5;
  const darlehen = foerderbar * 0.5;
  const erlass = darlehen * 0.5;
  const darlehenNach = darlehen - erlass;
  const eigenanteil = total - zuschuss - erlass;
  const notFoerder = Math.max(0, total - MAX_FOERDERBAR);

  let allParts = [];
  groups.forEach((g) => { allParts = allParts.concat(g.parts); });
  allParts.sort();
  const partsStr = partsLabel(allParts);

  let html =
    '<div class="result-row"><span class="label">Lehrgangsgebühren (Teile ' + partsStr + ')</span><span class="value">' + fmt(totalCourse) + "</span></div>" +
    '<div class="result-row"><span class="label">Prüfungsgebühren</span><span class="value">' + fmt(totalExam) + "</span></div>" +
    '<div class="result-row highlight"><span class="label">Gesamtkosten</span><span class="value">' + fmt(total) + "</span></div>";

  if (notFoerder > 0) {
    html += '<div class="result-row deduct"><span class="label">Davon nicht förderbar (über 15.000 €)</span><span class="value">− ' + fmt(notFoerder) + "</span></div>";
  }
  html +=
    '<hr class="result-divider">' +
    '<div class="result-row positive"><span class="label"><span class="icon">✅</span>Zuschuss (50 % – nicht rückzahlbar)</span><span class="value">+ ' + fmt(zuschuss) + "</span></div>" +
    '<div class="result-row loan"><span class="label"><span class="icon">🏦</span>KfW-Darlehen (50 %)</span><span class="value">' + fmt(darlehen) + "</span></div>" +
    '<div class="result-row positive"><span class="label"><span class="icon">🎓</span>Darlehenserlass bei Bestehen (50 %)</span><span class="value">+ ' + fmt(erlass) + "</span></div>" +
    '<div class="result-row deduct"><span class="label"><span class="icon">↩</span>Verbleibendes Darlehen nach Bestehen</span><span class="value">' + fmt(darlehenNach) + "</span></div>" +
    '<hr class="result-divider">' +
    '<div class="result-row highlight"><span class="label"><span class="icon">💡</span>Effektiver Eigenanteil (bei Bestehen)</span><span class="value" style="color:var(--amber-lt)">' + fmt(eigenanteil) + "</span></div>";

  if (total > 0) {
    html += '<div class="result-row deduct"><span class="label"><span class="icon">≈</span>Entspricht ca.</span><span class="value">' + Math.round((eigenanteil / total) * 100) + " % der Gesamtkosten</span></div>";
  }
  html += '<p class="result-note">' + (missing ? "&#9888; Einige Lehrgangsgebühren fehlen – das Ergebnis ist unvollständig.<br>" : "") + "Ohne Aufstiegs-BAföG: " + fmt(total) + " · Mit Aufstiegs-BAföG (bei Bestehen): " + fmt(eigenanteil) + ".</p>";

  let pFoerderbar = 0, pZuschuss = 0, pDarlehen = 0, pEigenanteil = 0;
  if (projektKosten > 0) {
    pFoerderbar = Math.min(projektKosten, 2000);
    pZuschuss = pFoerderbar * 0.5;
    pDarlehen = pFoerderbar * 0.5;
    pEigenanteil = projektKosten - pZuschuss;

    const pHtml =
      '<div class="result-row"><span class="label"><span class="icon">🔧</span>Materialkosten Projekt</span><span class="value">' + fmt(projektKosten) + "</span></div>" +
      '<div class="result-row deduct"><span class="label"><span class="icon">✦</span>Davon förderbar (max. 2.000 €)</span><span class="value">' + fmt(pFoerderbar) + "</span></div>" +
      '<div class="result-row positive"><span class="label"><span class="icon">✅</span>Zuschuss (50 % der Förderung)</span><span class="value">+ ' + fmt(pZuschuss) + "</span></div>" +
      '<div class="result-row loan"><span class="label"><span class="icon">🏦</span>KfW-Darlehen (50 % der Förderung)</span><span class="value">' + fmt(pDarlehen) + "</span></div>" +
      '<hr class="result-divider">' +
      '<div class="result-row highlight"><span class="label"><span class="icon">💡</span>Eigenanteil Meisterprojekt</span><span class="value" style="color:#D4A8FF">' + fmt(pEigenanteil) + "</span></div>" +
      '<p class="result-note">Kein Darlehenserlass beim Meisterprojekt – das KfW-Darlehen (' + fmt(pDarlehen) + ") ist vollständig zurückzuzahlen.</p>";

    document.getElementById("result-box-projekt").style.display = "";
    document.getElementById("result-projekt-content").innerHTML = pHtml + '<p style="font-size:.72rem;color:var(--text-lt);margin-top:.75rem;line-height:1.5">Angaben ohne Gewähr. Es handelt sich um eine Annäherung auf Basis der verfügbaren Daten. Weitere Kosten oder Gebühren können hinzukommen.</p>';
  } else {
    document.getElementById("result-box-projekt").style.display = "none";
  }

  const totalEigenanteil = eigenanteil + pEigenanteil;
  const totalDarlehen = darlehenNach + pDarlehen;
  const tHtml =
    '<div class="result-row"><span class="label"><span class="icon">📌</span>Eigenanteil Lehrgangs-/Prüfungsgebühren</span><span class="value">' + fmt(eigenanteil) + "</span></div>" +
    (projektKosten > 0 ? '<div class="result-row"><span class="label"><span class="icon">📌</span>Eigenanteil Meisterprojekt</span><span class="value">' + fmt(pEigenanteil) + "</span></div>" : "") +
    '<hr class="result-divider">' +
    '<div class="result-row highlight"><span class="label"><span class="icon">💶</span>Gesamter Eigenanteil</span><span class="value" style="color:var(--amber-lt)">' + fmt(totalEigenanteil) + "</span></div>" +
    '<div class="result-row loan"><span class="label"><span class="icon">🏦</span>Davon KfW-Darlehen (gesamt)</span><span class="value">' + fmt(totalDarlehen) + "</span></div>";

  document.getElementById("result-box-total").style.display = "";
  document.getElementById("result-total-content").innerHTML = tHtml + '<p style="font-size:.72rem;color:var(--text-lt);margin-top:.75rem;line-height:1.5">Angaben ohne Gewähr. Es handelt sich um eine Annäherung auf Basis der verfügbaren Daten. Weitere Kosten oder Gebühren können hinzukommen.</p>';

  document.getElementById("result-empty").style.display = "none";
  document.getElementById("result-content").style.display = "";
  document.getElementById("result-content").innerHTML = html + '<p style="font-size:.72rem;color:var(--text-lt);margin-top:.75rem;line-height:1.5">Angaben ohne Gewähr. Es handelt sich um eine Annäherung auf Basis der verfügbaren Daten. Weitere Kosten oder Gebühren können hinzukommen.</p>';
}

// ── Init + wiring ─────────────────────────────────────────────────────
initNav();
(function initChamberSelect() {
  const sel = document.getElementById("auto-chamber");
  CHAMBERS.forEach((c) => { const opt = document.createElement("option"); opt.value = c.id; opt.text = c.name; sel.add(opt); });
})();

document.getElementById("btn-mode-auto").addEventListener("click", () => setMode("auto"));
document.getElementById("btn-mode-manual").addEventListener("click", () => setMode("manual"));
document.getElementById("auto-chamber").addEventListener("change", onChamberChange);
document.getElementById("auto-trade").addEventListener("change", onTradeChange);
document.getElementById("prefer-singles").addEventListener("change", renderFeeInputs);
[1, 2, 3, 4].forEach((p) => document.getElementById("chk" + p).addEventListener("change", () => onPartCheck(p)));
document.getElementById("btn-calc").addEventListener("click", calculate);

renderFeeInputs();
