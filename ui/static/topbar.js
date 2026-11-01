// Barra superior: marca, navegación principal e indicador de guardado. Evento: {type:"nav", view}.
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; }
const LOGO = `<svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true"><rect x="2" y="6" width="28" height="20" rx="5" fill="currentColor" opacity=".14"/>
<rect x="2" y="6" width="28" height="20" rx="5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M9 6v20M14 6v20M18 6v20M23 6v20" stroke="currentColor" stroke-width="1.4" opacity=".6"/>
<path d="M16 2v4M16 26v4" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`;
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector(".tb");
  if (!root) {
    root = el("header", "pml tb");
    const brand = el("button", "tb-brand"); brand.type = "button";
    const logo = el("span", "tb-logo"); logo.innerHTML = LOGO;
    const name = el("span", "tb-name"); name.append(el("b", null, "PEMFC ModelLab"), el("small", "tb-ver"));
    brand.append(logo, name);
    brand.addEventListener("click", () => setTriggerValue("action", { type: "nav", view: "catalog", t: Date.now() }));
    const nav = el("nav", "tb-nav"); nav.setAttribute("aria-label", "Navegación principal");
    const save = el("div", "tb-save"); save.setAttribute("role", "status"); save.setAttribute("aria-live", "polite");
    root.append(brand, nav, save);
    parentElement.appendChild(root);
    root.__ctl = { nav, save, ver: name.querySelector(".tb-ver") };
  }
  const c = root.__ctl;
  c.ver.textContent = `v${data.version}`;
  c.nav.innerHTML = "";
  for (const [v, t] of data.items) {
    const b = el("button", `tb-link${v === data.view ? " on" : ""}`, t); b.type = "button";
    b.setAttribute("aria-current", v === data.view ? "page" : "false");
    b.addEventListener("click", () => { if (v !== data.view) setTriggerValue("action", { type: "nav", view: v, t: Date.now() }); });
    c.nav.appendChild(b);
  }
  const s = data.save || {};
  c.save.className = `tb-save s-${s.state || "none"}`;
  c.save.textContent = s.text || "";
  c.save.title = s.title || "";
}
