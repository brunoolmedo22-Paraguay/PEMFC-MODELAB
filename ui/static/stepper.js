// Flujo guiado: indicador de progreso con estados por etapa y navegación directa.
// Estados: pendiente | progreso | completa | atencion | bloqueada. Evento: {type:"goto", step}.
const GLYPH = { completa: "✓", atencion: "!", bloqueada: "🔒" };
const LABEL = { pendiente: "No iniciada", progreso: "En progreso", completa: "Completa", atencion: "Requiere atención", bloqueada: "Bloqueada" };
function el(t, c, x) { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; }
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector(".stp");
  if (!root) { root = el("nav", "pml stp"); root.setAttribute("aria-label", "Etapas de la identificación"); parentElement.appendChild(root); }
  root.innerHTML = "";
  const list = el("ol", "stp-list");
  const n = data.steps.length;
  let last = -1;                                   // última etapa de la racha inicial de etapas completas
  for (let i = 0; i < n; i++) { if (data.steps[i].state === "completa") last = i; else break; }
  root.style.setProperty("--fill", `${Math.max(0, last) / (n - 1) * 100}%`);
  data.steps.forEach((s, i) => {
    const li = el("li", `stp-item st-${s.state}${s.n === data.current ? " is-current" : ""}`);
    const b = el("button", "stp-btn"); b.type = "button";
    b.disabled = s.state === "bloqueada";
    b.setAttribute("aria-current", s.n === data.current ? "step" : "false");
    b.title = `${s.title} — ${LABEL[s.state]}${s.reason ? ": " + s.reason : ""}`;
    const dot = el("span", "stp-dot", GLYPH[s.state] || String(s.n).padStart(2, "0"));
    const txt = el("span", "stp-txt");
    txt.append(el("span", "stp-num", String(s.n).padStart(2, "0")), el("span", "stp-ttl", s.title), el("span", "stp-state", s.reason ? `${LABEL[s.state]} · ${s.reason}` : LABEL[s.state]));
    b.append(dot, txt);
    b.addEventListener("click", () => { if (!b.disabled && s.n !== data.current) setTriggerValue("action", { type: "goto", step: s.n, t: Date.now() }); });
    li.appendChild(b);
    list.appendChild(li);
  });
  root.appendChild(list);
}
