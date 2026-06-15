// Leaflet map rendering, ported from the original list.html initMap().
import L from "leaflet";
import { esc, eur } from "./util.js";

let map = null;

export function renderMap(mapData, listHref) {
  const notice = document.getElementById("map-notice");
  if (mapData.length > 0 && notice) notice.style.display = "none";

  // Leaflet can't initialise into a hidden container cleanly; (re)create each time.
  if (map) {
    map.remove();
    map = null;
  }
  map = L.map("map").setView([50.0, 7.0], 8);
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution:
      '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
  }).addTo(map);

  const chamberColors = {};
  const palette = ["#1B3A5C", "#C97B1A", "#2E6E4A", "#8B2635", "#4A3B6B"];
  let colorIdx = 0;

  const groups = {};
  mapData.forEach((o) => {
    const key = o.lat.toFixed(4) + "," + o.lng.toFixed(4);
    if (!groups[key]) groups[key] = { lat: o.lat, lng: o.lng, offers: [] };
    groups[key].offers.push(o);
  });

  Object.values(groups).forEach((group) => {
    const offers = group.offers;
    const firstChamber = offers[0].chamber;
    if (!chamberColors[firstChamber]) chamberColors[firstChamber] = palette[colorIdx++ % palette.length];
    const color = chamberColors[firstChamber];

    const marker = L.circleMarker([group.lat, group.lng], {
      radius: 9, color, fillColor: color, fillOpacity: 0.85, weight: 2,
    }).addTo(map);

    const visible = offers.slice(0, 3);
    const extra = offers.length - visible.length;
    let html = `<div class="mv-popup"><strong style="font-size:.9rem;color:#1B3A5C">📍 ${esc(visible[0].city)}</strong>
      <div style="font-size:.75rem;color:#888;margin-bottom:.4rem">${esc(firstChamber)}</div>`;

    visible.forEach((o) => {
      const fee = o.fee ? eur(o.fee) : "k.A.";
      const examFeeDisplay = o.exam_fee_display || null;
      const titleEl = o.url
        ? `<a href="${esc(o.url)}" target="_blank" rel="noopener" style="color:#1B3A5C;font-weight:500;font-size:.85rem;display:block;line-height:1.3;text-decoration:none">${esc(o.title)} ↗</a>`
        : `<strong style="font-size:.85rem;color:#1B3A5C;display:block;line-height:1.3">${esc(o.title)}</strong>`;
      html += `<div class="mv-popup-course">
        ${titleEl}
        <div class="meta">${esc(o.parts)} · ${esc(o.format)}</div>
        <div class="meta">Startdatum: ${esc(o.start) || "–"}</div>
        <div class="meta">Kursgebühr: ${fee}</div>
        ${examFeeDisplay ? `<div class="meta">Prüfungsgebühr: ${esc(examFeeDisplay)}</div>` : ""}
      </div>`;
    });

    html += `<div class="mv-popup-footer">`;
    if (extra > 0)
      html += `<div style="font-size:.75rem;color:#888;margin-bottom:.4rem;width:100%">+ ${extra} weitere Kurs${extra !== 1 ? "e" : ""} an diesem Standort</div>`;
    html += `<a href="${esc(listHref)}">☰ Zur Liste</a></div></div>`;

    marker.bindPopup(html, { maxWidth: 290 });
  });

  const legend = L.control({ position: "bottomright" });
  legend.onAdd = function () {
    const div = L.DomUtil.create("div");
    div.style.cssText = "background:#fff;padding:8px 12px;border-radius:6px;font-size:.8rem;box-shadow:0 1px 4px rgba(0,0,0,.15)";
    div.innerHTML = "<strong>Kammer</strong><br>" +
      Object.entries(chamberColors).map(([n, c]) =>
        `<span style="display:inline-block;width:10px;height:10px;background:${c};border-radius:50%;margin-right:5px"></span>${esc(n)}`,
      ).join("<br>");
    return div;
  };
  legend.addTo(map);

  // Container may have been sized while hidden — recalc once visible.
  setTimeout(() => map && map.invalidateSize(), 50);
}
