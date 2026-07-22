import assert from "node:assert/strict";
import { sortCourses, sortIndicator, chamberFilterHtml, rowHtml } from "../web/src/render.js";
import { ANMELDEGEBUEHR_NOTE } from "../web/src/util.js";

const sample = [
  {
    title: "Z Course",
    chamber_name: "HWK B",
    start_date: "2027-01-01",
    duration_hours: 900,
    course_fee: 5000,
    exam_fee: { fee: 300 },
  },
  {
    title: "A Course",
    chamber_name: "HWK A",
    start_date: "2026-06-01",
    duration_hours: 1200,
    course_fee: 7000,
    exam_fee: { fee: 500 },
  },
  {
    title: "M Course",
    chamber_name: "HWK C",
    start_date: null,
    duration_hours: null,
    course_fee: null,
    exam_fee: null,
  },
];

const byChamber = sortCourses(sample, "chamber", "asc").map((c) => c.chamber_name);
assert.deepEqual(byChamber, ["HWK A", "HWK B", "HWK C"]);

const byRuntime = sortCourses(sample, "runtime", "asc").map((c) => c.start_date);
assert.deepEqual(byRuntime, ["2026-06-01", "2027-01-01", null]);

const byFeeDesc = sortCourses(sample, "course_fee", "desc").map((c) => c.course_fee);
assert.deepEqual(byFeeDesc, [7000, 5000, null]);

assert.equal(sortIndicator("chamber", "chamber", "asc"), "↑");
assert.equal(sortIndicator("chamber", "chamber", "desc"), "↓");
assert.equal(sortIndicator("chamber", "runtime", "asc"), "↕");

const filterHtml = chamberFilterHtml([
  { slug: "hwk-potsdam", name: "HWK Potsdam", region: "Brandenburg" },
  { slug: "hwk-cottbus", name: "HWK Cottbus", region: "Brandenburg" },
  { slug: "hwk-muenchen", name: "HWK München", region: "Bayern" },
  { slug: "hwk-freiburg", name: "HWK Freiburg", region: "Baden-Württemberg" },
]);
const regionSummaries = [...filterHtml.matchAll(/region-panel-summary">([^<]+)</g)].map((m) => m[1]);
assert.deepEqual(regionSummaries, ["Baden-Württemberg", "Bayern", "Brandenburg"]);
const brandenburgLabels = filterHtml
  .split("Brandenburg")[1]
  .match(/f-chamber" value="[^"]+"> ([^<]+)<\/label>/g)
  .map((label) => label.replace(/^f-chamber" value="[^"]+"> ([^<]+)<\/label>$/, "$1"));
assert.deepEqual(brandenburgLabels, ["HWK Cottbus", "HWK Potsdam"]);

const baseCourse = {
  title: "Test Course",
  chamber_name: "HWK Test",
  chamber_slug: "hwk-test",
  trade_name: "",
  parts: [1],
  format_display: "Vollzeit",
  duration_hours: 900,
  course_fee: 5000,
  course_fee_display: "5.000 €",
  exam_fee: null,
  city: "Berlin",
  availability: "available",
  source_url: "",
};

const monthOnlyHtml = rowHtml({
  ...baseCourse,
  start_date: "2027-09-01",
  end_date: "2029-01-01",
  start_date_note: "Genauer Termin steht noch nicht fest.",
});
assert.match(monthOnlyHtml, /09\.2027/);
assert.match(monthOnlyHtml, />bis</);
assert.match(monthOnlyHtml, /01\.2029/);
assert.match(monthOnlyHtml, /Genauer Termin steht noch nicht fest\./);
assert.doesNotMatch(monthOnlyHtml, /09\.2027 - 01\.2029/);

const exactHtml = rowHtml({
  ...baseCourse,
  start_date: "2027-09-15",
  end_date: "2029-01-20",
  start_date_note: "",
});
assert.match(exactHtml, /15\.09\.2027/);
assert.doesNotMatch(exactHtml, /09\.2027 - 01\.2029/);

const frankfurtHtml = rowHtml({
  ...baseCourse,
  chamber_slug: "hwk-rhein-main",
  start_date: "2027-09-15",
  end_date: null,
  start_date_note: "",
});
const courseFeeCell = frankfurtHtml.split('data-label="Kursgebühr"')[1].split("</td>")[0];
assert.doesNotMatch(courseFeeCell, /fee-info-btn/);
assert.doesNotMatch(courseFeeCell, new RegExp(ANMELDEGEBUEHR_NOTE.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));

console.log("sortCourses tests passed");
