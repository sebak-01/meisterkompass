// Shared mobile hamburger menu behaviour (ported from base.html).
export function initNav() {
  const btn = document.getElementById("hamburger-btn");
  const menu = document.getElementById("mobile-menu");
  if (!btn || !menu) return;

  btn.addEventListener("click", () => {
    const open = menu.classList.toggle("open");
    btn.textContent = open ? "✕" : "☰";
    btn.setAttribute("aria-expanded", String(open));
    btn.setAttribute("aria-label", open ? "Menü schließen" : "Menü öffnen");
  });
  menu.querySelectorAll("a").forEach((a) =>
    a.addEventListener("click", () => {
      menu.classList.remove("open");
      btn.textContent = "☰";
      btn.setAttribute("aria-expanded", "false");
      btn.setAttribute("aria-label", "Menü öffnen");
    }),
  );
}
