// Página principal: selector de motores (dos tarjetas grandes y equilibradas). Evento: {type:"open", view}.
const ICONS = {
  // Motor 1: curva de polarización con puntos experimentales y ajuste (identificación).
  identify: `<svg viewBox="0 0 64 64" aria-hidden="true"><path d="M8 8v48h48" fill="none" stroke="currentColor" stroke-width="2.4" stroke-opacity=".45"/>
    <path d="M11 14c4 8 8 11 15 13s17 4 22 8 6 9 8 15" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"/>
    <g fill="currentColor"><circle cx="15" cy="20" r="2.6"/><circle cx="25" cy="26" r="2.6"/><circle cx="36" cy="30" r="2.6"/><circle cx="46" cy="36" r="2.6"/><circle cx="53" cy="46" r="2.6"/></g></svg>`,
  // Motor 2: stack con señales de operación (simulación de condiciones operativas).
  simulate: `<svg viewBox="0 0 64 64" aria-hidden="true"><rect x="8" y="16" width="22" height="32" rx="3" fill="none" stroke="currentColor" stroke-width="2.6"/>
    <path d="M13 16v32M18 16v32M23 16v32" stroke="currentColor" stroke-width="1.6" stroke-opacity=".55"/>
    <path d="M30 26h6M30 38h6" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>
    <path d="M38 40c3-10 5-14 8-14s4 10 7 10 3-6 5-8" fill="none" stroke="currentColor" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M38 50h20" stroke="currentColor" stroke-width="2" stroke-opacity=".45" stroke-linecap="round"/></svg>`,
};
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; }
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector(".eng");
  if (!root) { root = el("div", "pml eng"); parentElement.appendChild(root); }
  root.innerHTML = "";
  for (const c of data.cards) {
    const card = el("button", `eng-card eng-${c.kind}`); card.type = "button";
    card.setAttribute("aria-label", `${c.eyebrow}: ${c.title}. ${c.action}`);
    const head = el("div", "eng-head");
    const ic = el("span", "eng-icon"); ic.innerHTML = ICONS[c.icon] || "";
    const pill = el("span", `eng-pill ${c.available ? "ok" : "dev"}`, c.available ? "Disponible" : "En desarrollo");
    head.append(ic, pill);
    card.append(head, el("span", "eng-eyebrow", c.eyebrow), el("span", "eng-title", c.title), el("span", "eng-desc", c.description));
    const act = el("span", "eng-action"); act.append(el("span", "", c.action), el("span", "eng-arrow", "→"));
    card.appendChild(act);
    card.addEventListener("click", () => setTriggerValue("action", { type: "open", view: c.view, t: Date.now() }));
    root.appendChild(card);
  }
}
