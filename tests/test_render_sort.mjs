import assert from "node:assert/strict";
import { sortCourses, sortIndicator } from "../web/src/render.js";

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

console.log("sortCourses tests passed");
