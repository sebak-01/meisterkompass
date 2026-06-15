import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// Repo root holds the checked-in data/ dir, which we import at build time.
const repoRoot = resolve(__dirname, "..");

// Base path: "/" for a custom domain (meisterkompass.de). For a GitHub Pages
// project site (user.github.io/<repo>/) set VITE_BASE=/<repo>/ in CI.
const base = process.env.VITE_BASE || "/";

// Pre-render the default Kursfinder table into index.html at build time (SSG):
// instant first paint, crawlable content, works without JS. The runtime JS
// re-renders idempotently on load using the same render.js module.
function prerenderList() {
  return {
    name: "prerender-list",
    async transformIndexHtml(html, ctx) {
      if (!ctx.filename.replace(/\\/g, "/").endsWith("/index.html")) return html;
      const courses = JSON.parse(readFileSync(resolve(repoRoot, "data/courses.json"), "utf8"));
      const { applyFilters, rowHtml, emptyRow, pageItems, defaultState } = await import("./src/render.js");
      const today = new Date().toISOString().slice(0, 10);
      const state = defaultState();
      const filtered = applyFilters(courses, state, today);
      const items = pageItems(filtered, state);
      const rows = items.length ? items.map(rowHtml).join("") : emptyRow();
      const chambers = new Set(filtered.map((c) => c.chamber_slug)).size;
      return html
        .replace('<tbody id="course-tbody"></tbody>', `<tbody id="course-tbody">${rows}</tbody>`)
        .replace('id="count-courses">0<', `id="count-courses">${filtered.length}<`)
        .replace('id="count-chambers">0<', `id="count-chambers">${chambers}<`)
        .replace('id="results-count">0<', `id="results-count">${filtered.length}<`);
    },
  };
}

// Expose courses.json to the bundle with frontend-unused fields stripped.
// data/courses.json stays full (it's the scraper pipeline's state file); only
// the shipped payload is trimmed. Keep this DROP set in sync with what
// render.js / map.js actually read.
function trimmedCourses() {
  const VID = "virtual:courses";
  const RESOLVED = "\0" + VID;
  const DROP = new Set(["teaching_mode", "street", "zip_code", "chamber_region", "exam_fee_scraped"]);
  return {
    name: "trimmed-courses",
    resolveId(id) { return id === VID ? RESOLVED : null; },
    load(id) {
      if (id !== RESOLVED) return null;
      const all = JSON.parse(readFileSync(resolve(repoRoot, "data/courses.json"), "utf8"));
      const trimmed = all.map((c) => Object.fromEntries(Object.entries(c).filter(([k]) => !DROP.has(k))));
      return `export default ${JSON.stringify(trimmed)};`;
    },
  };
}

export default defineConfig({
  root: __dirname,
  base,
  plugins: [prerenderList(), trimmedCourses()],
  resolve: {
    alias: { "@data": resolve(repoRoot, "data") },
  },
  server: {
    fs: { allow: [repoRoot] },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(__dirname, "index.html"),
        afbg: resolve(__dirname, "afbg.html"),
        about: resolve(__dirname, "about.html"),
        imprint: resolve(__dirname, "imprint.html"),
      },
    },
  },
});
