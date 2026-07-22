import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "vite";

// Repo root holds the checked-in data/ dir, which we import at build time.
const repoRoot = resolve(__dirname, "..");

// Base path: "/" for a custom domain (meisterkompass.de). For a GitHub Pages
// project site (user.github.io/<repo>/) set VITE_BASE=/<repo>/ in CI.
const base = process.env.VITE_BASE || "/";

const readChambers = () =>
  JSON.parse(readFileSync(resolve(repoRoot, "data/chambers.json"), "utf8"));

// Pre-render the default Kursfinder table into index.html at build time (SSG):
// instant first paint, crawlable content, works without JS. The runtime JS
// re-renders idempotently on load using the same render.js module. The page's
// meta descriptions, JSON-LD and eyebrow also carry region tokens filled from
// chambers.json so they never drift.
function prerenderList() {
  return {
    name: "prerender-list",
    async transformIndexHtml(html, ctx) {
      if (!ctx.filename.replace(/\\/g, "/").endsWith("/index.html")) return html;
      const courses = JSON.parse(readFileSync(resolve(repoRoot, "data/courses.json"), "utf8"));
      const {
        applyFilters,
        rowHtml,
        emptyRow,
        pageItems,
        defaultState,
        chamberFilterHtml,
        regionsPhrase,
      } = await import("./src/render.js");
      const { esc } = await import("./src/util.js");
      const today = new Date().toISOString().slice(0, 10);
      const state = defaultState();
      const filtered = applyFilters(courses, state, today);
      const items = pageItems(filtered, state);
      const rows = items.length ? items.map(rowHtml).join("") : emptyRow();
      const chamberData = readChambers();
      const chambers = new Set(filtered.map((c) => c.chamber_slug)).size;
      const trades = new Set(filtered.map((c) => c.trade_slug)).size;
      return html
        .replace('<tbody id="course-tbody"></tbody>', `<tbody id="course-tbody">${rows}</tbody>`)
        .replace('<div id="chambers-options"><!-- populated from data/chambers.json (build-time SSG + runtime) --></div>', `<div id="chambers-options">${chamberFilterHtml(chamberData)}</div>`)
        .replace('id="count-courses">0<', `id="count-courses">${filtered.length}<`)
        .replace('id="count-chambers">0<', `id="count-chambers">${chambers}<`)
        .replace('id="count-trades">0<', `id="count-trades">${trades}<`)
        .replace('id="results-count">0<', `id="results-count">${filtered.length}<`)
        .replaceAll("{{REGIONS}}", esc(regionsPhrase(chamberData)));
    },
  };
}

// Pre-render the "Über MeisterKompass" coverage into about.html at build time:
// its prose and SEO meta descriptions are derived from data/chambers.json so
// none of them drift as chambers are added.
// The page ships no runtime script beyond nav, so this is pure SSG (no hydrate).
function prerenderAbout() {
  return {
    name: "prerender-about",
    async transformIndexHtml(html, ctx) {
      if (!ctx.filename.replace(/\\/g, "/").endsWith("/about.html")) return html;
      const { regionsPhrase } = await import("./src/render.js");
      const { esc } = await import("./src/util.js");
      const chambers = readChambers();
      return html.replaceAll("{{REGIONS}}", esc(regionsPhrase(chambers)));
    },
  };
}

// Expose the course datasets to the bundle with frontend-unused fields stripped.
// The data/*.json files stay full (the scraper pipeline's state); only the
// shipped payload is trimmed. virtual:courses = upcoming (bundled);
// virtual:courses-archive = past (lazy dynamic-imported on demand).
// Keep DROP in sync with the fields render.js / map.js actually read.
function trimmedCourses() {
  const DROP = new Set([
    "teaching_mode", "street", "zip_code", "chamber_region",
    "exam_fee_scraped", "exam_fee_qualifier",
  ]);
  const SOURCES = {
    "virtual:courses": "data/courses.json",
    "virtual:courses-archive": "data/courses_archive.json",
  };
  const resolved = (id) => "\0" + id;
  return {
    name: "trimmed-courses",
    resolveId(id) { return id in SOURCES ? resolved(id) : null; },
    load(id) {
      for (const [vid, file] of Object.entries(SOURCES)) {
        if (id !== resolved(vid)) continue;
        const path = resolve(repoRoot, file);
        const all = existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : [];
        const trimmed = all.map((c) => Object.fromEntries(Object.entries(c).filter(([k]) => !DROP.has(k))));
        return `export default ${JSON.stringify(trimmed)};`;
      }
      return null;
    },
  };
}

export default defineConfig({
  root: __dirname,
  base,
  plugins: [prerenderList(), prerenderAbout(), trimmedCourses()],
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
        privacy: resolve(__dirname, "privacy.html"),
      },
    },
  },
});
