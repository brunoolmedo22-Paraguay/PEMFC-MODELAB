// Catálogo de dispositivos: cuadrícula adaptable, búsqueda/filtrado/ordenación en el cliente
// (sin recargas), tarjeta «+ Agregar dispositivo» dentro de la cuadrícula y estado vacío.
// Eventos hacia Python: {type:"open", id} | {type:"add"}.
const FMT = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function rel(iso) {
  const t = Date.parse(iso); if (!isFinite(t)) return "";
  const s = (Date.now() - t) / 1000;
  if (s < 60) return "hace un momento"; if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`; if (s < 86400 * 30) return `hace ${Math.round(s / 86400)} d`;
  return FMT.format(new Date(t));
}
const ICON = `<svg viewBox="0 0 48 48" width="40" height="40" aria-hidden="true"><rect x="6" y="10" width="36" height="28" rx="5" fill="none" stroke="currentColor" stroke-width="2.4"/>
<path d="M14 10v28M20 10v28M26 10v28M32 10v28" stroke="currentColor" stroke-width="1.6" opacity=".55"/><path d="M4 18h4M4 30h4M40 18h4M40 30h4" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>`;

function build(parent) {
  const root = el("div", "pml cat");
  const bar = el("div", "cat-bar");
  const search = el("input", "pml-input cat-search"); search.type = "search"; search.placeholder = "Buscar por nombre, fabricante, modelo o id…";
  search.setAttribute("aria-label", "Buscar dispositivos");
  const fStatus = el("select", "pml-select"); fStatus.setAttribute("aria-label", "Filtrar por estado");
  const fMan = el("select", "pml-select"); fMan.setAttribute("aria-label", "Filtrar por fabricante");
  const sort = el("select", "pml-select"); sort.setAttribute("aria-label", "Ordenar");
  for (const [v, t] of [["recientes", "Más recientes"], ["nombre", "Nombre"], ["fabricante", "Fabricante"], ["estado", "Estado"]]) {
    const o = el("option", null, t); o.value = v; sort.appendChild(o);
  }
  const count = el("span", "cat-count");
  bar.append(search, fStatus, fMan, sort, count);
  const grid = el("div", "cat-grid"); grid.setAttribute("role", "list");
  root.append(bar, grid);
  parent.appendChild(root);
  const ctl = { root, grid, search, fStatus, fMan, sort, count, data: null, send: null };
  root.__ctl = ctl;
  const rerender = () => render(ctl);
  search.addEventListener("input", rerender); fStatus.addEventListener("change", rerender);
  fMan.addEventListener("change", rerender); sort.addEventListener("change", rerender);
  return root;
}

function fillSelect(sel, items, allLabel) {
  const cur = sel.value; sel.innerHTML = "";
  const all = el("option", null, allLabel); all.value = ""; sel.appendChild(all);
  for (const [v, t] of items) { const o = el("option", null, t); o.value = v; sel.appendChild(o); }
  sel.value = items.some(([v]) => v === cur) ? cur : "";
}

function card(d, send, i) {
  const c = el("article", "cat-card"); c.setAttribute("role", "listitem"); c.tabIndex = 0;
  c.style.animationDelay = `${Math.min(i, 12) * 35}ms`;
  c.dataset.id = d.id;
  const head = el("div", "cat-head");
  const ttl = el("div", "cat-ttl");
  ttl.append(el("h3", "cat-name", d.name), el("div", "cat-sub", [d.manufacturer, d.model].filter(Boolean).join(" · ") || "Fabricante y modelo sin declarar"));
  const ic = el("div", "cat-icon"); ic.innerHTML = ICON;
  head.append(ttl, ic);
  const meta = el("div", "cat-meta");
  const kv = (k, v, unit) => { const b = el("div", "cat-kv"); b.append(el("span", "k", k), el("span", "v", v === null || v === undefined ? "—" : `${v}${unit || ""}`)); return b; };
  meta.append(kv("Celdas", d.n_cells), kv("Área activa", d.active_area_cm2 === null ? null : Number(d.active_area_cm2).toLocaleString(), " cm²"),
              kv("Calibraciones", d.n_calibrations), kv("Borradores", d.n_drafts));
  const status = el("div", "cat-status");
  const b = el("span", `pml-badge s-${d.admin_status}`, d.admin_text); b.title = "Estado administrativo de la caracterización";
  status.appendChild(b);
  const sci = el("div", "cat-sci");
  if (d.active_profile) {
    sci.append(el("span", "lbl", "Perfil activo"), el("span", `sci-code ${d.active_profile.status_code === "VALIDADO_EXPERIMENTALMENTE" ? "ok" : ""}`, d.active_profile.status_code));
    sci.title = `Calidad científica del perfil ${d.active_profile.profile_id} (independiente del estado administrativo)`;
  } else {
    sci.append(el("span", "lbl", "Perfil activo"), el("span", "sci-code none", "ninguno"));
  }
  const foot = el("div", "cat-foot");
  const ts = el("span", "cat-time", `Modificado ${rel(d.last_modified_utc)}`); ts.title = FMT.format(new Date(d.last_modified_utc));
  foot.append(el("span", "pml-chip", d.id), ts);
  c.append(head, status, meta, sci, foot);
  const open = () => send && send("action", { type: "open", id: d.id, t: Date.now() });
  c.addEventListener("click", open);
  c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
  return c;
}

function addCard(send, empty) {
  const c = el("article", `cat-card cat-add${empty ? " big" : ""}`); c.setAttribute("role", "listitem"); c.tabIndex = 0;
  c.setAttribute("aria-label", "Agregar dispositivo");
  const plus = el("div", "plus", "+");
  c.append(plus, el("div", "add-t", "Agregar dispositivo"),
    el("div", "add-s", empty ? "Todavía no hay dispositivos. Cree el primero: basta con un nombre; el resto se completa después."
                             : "Nombre obligatorio; fabricante y modelo opcionales."));
  const go = () => send && send("action", { type: "add", t: Date.now() });
  c.addEventListener("click", go);
  c.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  return c;
}

function render(ctl) {
  const d = ctl.data; if (!d) return;
  const q = ctl.search.value.trim().toLowerCase();
  let rows = d.devices.filter((x) => (!q || [x.name, x.manufacturer, x.model, x.id].join(" ").toLowerCase().includes(q))
    && (!ctl.fStatus.value || x.admin_status === ctl.fStatus.value) && (!ctl.fMan.value || x.manufacturer === ctl.fMan.value));
  const key = ctl.sort.value;
  const cmp = { recientes: (a, b) => b.last_modified_utc.localeCompare(a.last_modified_utc),
    nombre: (a, b) => a.name.localeCompare(b.name), fabricante: (a, b) => (a.manufacturer || "~").localeCompare(b.manufacturer || "~") || a.name.localeCompare(b.name),
    estado: (a, b) => a.admin_status.localeCompare(b.admin_status) || a.name.localeCompare(b.name) }[key];
  rows = rows.slice().sort(cmp);
  ctl.grid.innerHTML = "";
  const empty = d.devices.length === 0;
  ctl.root.classList.toggle("is-empty", empty);
  rows.forEach((x, i) => ctl.grid.appendChild(card(x, ctl.send, i)));
  if (!q && !ctl.fStatus.value && !ctl.fMan.value) ctl.grid.appendChild(addCard(ctl.send, empty));
  else if (!rows.length) { const n = el("div", "cat-none", "Ningún dispositivo coincide con la búsqueda o los filtros."); ctl.grid.appendChild(n); }
  ctl.count.textContent = empty ? "" : `${rows.length} de ${d.devices.length}`;
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector(".cat");
  if (!root) root = build(parentElement);
  const ctl = root.__ctl;
  ctl.send = setTriggerValue; ctl.data = data;
  fillSelect(ctl.fStatus, data.statuses, "Todos los estados");
  fillSelect(ctl.fMan, [...new Set(data.devices.map((x) => x.manufacturer).filter(Boolean))].sort().map((m) => [m, m]), "Todos los fabricantes");
  render(ctl);
}
