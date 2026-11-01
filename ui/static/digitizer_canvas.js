// PEMFC ModelLab — lienzo de digitalización (st.components.v2, JS local sin dependencias ni CDN).
//
// Todo se dibuja en el espacio de PÍXELES DE LA IMAGEN ORIGINAL mediante una única
// transformación (escala + desplazamiento): imagen y superposición no pueden desalinearse
// con zoom, desplazamiento o cambio de tamaño. Convención: origen arriba-izquierda,
// y hacia abajo, coordenadas continuas (centro del píxel (c, f) = (c+0.5, f+0.5)).
//
// Python es la fuente de verdad: este código solo envía EVENTOS DISCRETOS
// (setTriggerValue("edit", {...})) al soltar el ratón; nunca durante mousemove.

const MODES = [
  ["select", "↖ Mover", "Seleccionar / arrastrar puntos y anclas; arrastrar el fondo desplaza (V)"],
  ["add", "＋ Añadir", "Clic: añadir punto manual (A)"],
  ["delete", "✕ Borrar", "Clic sobre un punto: borrarlo (D / Supr)"],
  ["exclude", "⊘ Excluir", "Clic: excluir/incluir punto; arrastrar: excluir los puntos del recuadro (Mayús: incluir) (E)"],
  ["roi", "▭ ROI", "Arrastrar: nueva región de interés para la detección (R)"],
  ["X1", "X1", "Clic: posición de la referencia X1 (se ajusta a ticks detectados; Alt evita el ajuste)"],
  ["X2", "X2", "Clic: posición de la referencia X2"],
  ["Y1", "Y1", "Clic: posición de la referencia Y1"],
  ["Y2", "Y2", "Clic: posición de la referencia Y2"],
  ["pan", "✥ Mano", "Arrastrar: desplazar la vista (H)"],
];

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

function fmt(v) {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(3);
  return Number(v.toPrecision(5)).toString();
}

function axisValue(c, p) {
  if (!c) return null;
  const t1 = c.log ? Math.log10(c.v1) : c.v1;
  const t2 = c.log ? Math.log10(c.v2) : c.v2;
  const t = t1 + (p - c.p1) * (t2 - t1) / (c.p2 - c.p1);
  return c.log ? Math.pow(10, t) : t;
}

function build(parent) {
  const root = el("div", "pml-dz");
  root.tabIndex = 0;
  const bar = el("div", "pml-bar");
  const modeBtns = {};
  for (const [m, label, title] of MODES) {
    const b = el("button", "pml-btn", label);
    b.type = "button";
    b.title = title;
    b.dataset.mode = m;
    if (m === "X1" || m === "Y1") bar.appendChild(el("span", "pml-sep"));
    bar.appendChild(b);
    modeBtns[m] = b;
  }
  bar.appendChild(el("span", "pml-sep"));
  const zoomOut = el("button", "pml-btn", "−"); zoomOut.title = "Alejar (-)";
  const zoomIn = el("button", "pml-btn", "+"); zoomIn.title = "Acercar (+)";
  const fitBtn = el("button", "pml-btn", "Ajustar"); fitBtn.title = "Ajustar la imagen a la vista (0)";
  const oneBtn = el("button", "pml-btn", "1:1"); oneBtn.title = "Un píxel de imagen = un píxel de pantalla";
  const ocrBtn = el("button", "pml-btn on", "OCR"); ocrBtn.title = "Mostrar/ocultar las etiquetas de ejes reconocidas (verde: coherente; rojo: atípica; gris: excluida; azul: título)";
  const undoBtn = el("button", "pml-btn", "↶"); undoBtn.title = "Deshacer (Ctrl+Z)";
  const redoBtn = el("button", "pml-btn", "↷"); redoBtn.title = "Rehacer (Ctrl+Y)";
  for (const b of [zoomOut, zoomIn, fitBtn, oneBtn]) bar.appendChild(b);
  bar.appendChild(el("span", "pml-sep"));
  bar.appendChild(undoBtn); bar.appendChild(redoBtn);
  bar.appendChild(el("span", "pml-sep")); bar.appendChild(ocrBtn);
  for (const b of [zoomOut, zoomIn, fitBtn, oneBtn, undoBtn, redoBtn, ocrBtn]) b.type = "button";
  const wrap = el("div", "pml-wrap");
  const canvas = el("canvas", "pml-canvas");
  wrap.appendChild(canvas);
  const status = el("div", "pml-status");
  const sMode = el("span", "pml-s-mode");
  const sZoom = el("span", "pml-s-zoom");
  const sPos = el("span", "pml-s-pos");
  const sInfo = el("span", "pml-s-info");
  status.append(sMode, sZoom, sPos, sInfo);
  root.append(bar, wrap, status);
  parent.appendChild(root);

  const ctl = {
    instanceId: Math.random().toString(36).slice(2),
    root, canvas, wrap, data: null, send: null, img: new Image(), imgKey: null, imgReady: false,
    view: { scale: 1, ox: 0, oy: 0, fitted: false }, mode: "select", sel: null, drag: null,
    hover: null, pts: [], anchors: {}, seq: 0, raf: 0, dpr: window.devicePixelRatio || 1, showOcr: true,
  };
  root.__ctl = ctl;

  function emit(payload) {
    ctl.lastInteraction = Date.now();
    ctl.seq += 1;
    payload.seq = Date.now() * 1000 + ctl.seq;
    if (ctl.send) ctl.send("edit", payload);
  }

  function setMode(m) {
    ctl.mode = m;
    for (const k in modeBtns) modeBtns[k].classList.toggle("on", k === m);
    canvas.style.cursor = m === "pan" ? "grab" : (m === "select" ? "default" : "crosshair");
    root.dataset.mode = m;
    schedule();
  }

  // ---------------- transformaciones
  const toScreen = (px, py) => [(px - ctl.view.ox) * ctl.view.scale, (py - ctl.view.oy) * ctl.view.scale];
  const toImage = (sx, sy) => [sx / ctl.view.scale + ctl.view.ox, sy / ctl.view.scale + ctl.view.oy];
  function evPos(e) {
    const r = canvas.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  }
  function fit() {
    const d = ctl.data; if (!d || !d.image) return;
    const cw = canvas.clientWidth, ch = canvas.clientHeight;
    if (!d.image || cw < 20 || ch < 20 || !d.image.w) { ctl.view.fitted = false; return; }   // aún sin tamaño real: reintentar al redimensionar
    const s = Math.min(cw / d.image.w, ch / d.image.h) * 0.98;
    ctl.view.scale = s;
    ctl.view.ox = -(cw / s - d.image.w) / 2;
    ctl.view.oy = -(ch / s - d.image.h) / 2;
    ctl.view.fitted = true;
    schedule();
  }
  function zoomAt(f, sx, sy) {
    const [ix, iy] = toImage(sx, sy);
    const ns = Math.min(40, Math.max(0.05, ctl.view.scale * f));
    ctl.view.scale = ns;
    ctl.view.ox = ix - sx / ns;
    ctl.view.oy = iy - sy / ns;
    schedule();
  }
  ctl.fit = fit; ctl.zoomAt = zoomAt; ctl.toScreen = toScreen; ctl.toImage = toImage; ctl.setMode = setMode;

  // ---------------- tamaño
  function resize() {
    const w = Math.max(200, wrap.clientWidth);
    const h = Math.max(260, wrap.clientHeight);
    const cx = (canvas.clientWidth || w) / 2, cy = (canvas.clientHeight || h) / 2;
    const [icx, icy] = toImage(cx, cy);
    ctl.dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(w * ctl.dpr);
    canvas.height = Math.round(h * ctl.dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    if (!ctl.view.fitted || ctl.view.scale <= 0) { fit(); return; }
    ctl.view.ox = icx - (w / 2) / ctl.view.scale;   // mantener el centro de la vista
    ctl.view.oy = icy - (h / 2) / ctl.view.scale;
    schedule();
  }
  const ro = new ResizeObserver(() => resize());
  ro.observe(wrap);
  ctl.ro = ro;

  // ---------------- búsqueda de elementos bajo el cursor
  function hitPoint(sx, sy, r = 9) {
    let best = null, bd = r * r;
    for (const p of ctl.pts) {
      const [x, y] = toScreen(p.px, p.py);
      const d = (x - sx) ** 2 + (y - sy) ** 2;
      if (d <= bd) { bd = d; best = p; }
    }
    return best;
  }
  function hitAnchor(sx, sy) {
    for (const n of ["X1", "X2", "Y1", "Y2"]) {
      const a = ctl.anchors[n];
      if (!a || a.px === null || a.py === null) continue;
      const [x, y] = toScreen(a.px, a.py);
      if (Math.abs(x - sx) <= 9 && Math.abs(y - sy) <= 9) return n;
    }
    return null;
  }
  function snap(name, ix, iy, alt) {
    const d = ctl.data;
    if (alt || !d || !d.ticks) return [ix, iy];
    const list = d.ticks[name[0]] || [];
    const tol = 8 / ctl.view.scale;
    let best = null, bd = tol;
    for (const t of list) {
      const dd = Math.abs((name[0] === "X" ? ix : iy) - t);
      if (dd <= bd) { bd = dd; best = t; }
    }
    if (best === null) return [ix, iy];
    return name[0] === "X" ? [best, iy] : [ix, best];
  }

  // ---------------- ratón / táctil (Pointer Events)
  canvas.addEventListener("pointerdown", (e) => {
    ctl.lastInteraction = Date.now();
    root.focus({ preventScroll: true });
    const [sx, sy] = evPos(e);
    const [ix, iy] = toImage(sx, sy);
    canvas.setPointerCapture(e.pointerId);
    const panAlways = e.button === 1 || ctl.spaceDown || ctl.mode === "pan";
    const base = { sx, sy, ix, iy, moved: false, shift: e.shiftKey, alt: e.altKey };
    if (panAlways) { ctl.drag = { ...base, kind: "pan", ox: ctl.view.ox, oy: ctl.view.oy }; canvas.style.cursor = "grabbing"; return; }
    const m = ctl.mode;
    if (m === "select") {
      const p = hitPoint(sx, sy);
      if (p) { ctl.sel = p.id; ctl.drag = { ...base, kind: "point", id: p.id, px0: p.px, py0: p.py }; schedule(); return; }
      const a = hitAnchor(sx, sy);
      if (a) { ctl.drag = { ...base, kind: "anchor", name: a }; return; }
      ctl.sel = null;
      ctl.drag = { ...base, kind: "pan", ox: ctl.view.ox, oy: ctl.view.oy };
    } else if (m === "exclude" || m === "roi") {
      ctl.drag = { ...base, kind: "box", x1: ix, y1: iy };
    } else {
      ctl.drag = { ...base, kind: "click" };
    }
    schedule();
  });
  canvas.addEventListener("pointermove", (e) => {
    const [sx, sy] = evPos(e);
    const [ix, iy] = toImage(sx, sy);
    ctl.hover = [ix, iy];
    const g = ctl.drag;
    if (g) {
      if (Math.abs(sx - g.sx) + Math.abs(sy - g.sy) > 3) g.moved = true;
      if (g.kind === "pan") {
        ctl.view.ox = g.ox - (sx - g.sx) / ctl.view.scale;
        ctl.view.oy = g.oy - (sy - g.sy) / ctl.view.scale;
      } else if (g.kind === "point") {
        const p = ctl.pts.find((q) => q.id === g.id);
        if (p) { p.px = ix; p.py = iy; }
      } else if (g.kind === "anchor") {
        const [ax, ay] = snap(g.name, ix, iy, e.altKey);
        ctl.anchors[g.name] = { ...ctl.anchors[g.name], px: ax, py: ay };
      } else if (g.kind === "box") {
        g.x1 = ix; g.y1 = iy;
      }
    }
    updateStatus();
    schedule();
  });
  function endDrag(e) {
    const g = ctl.drag; ctl.drag = null;
    if (!g) return;
    canvas.style.cursor = ctl.mode === "pan" ? "grab" : (ctl.mode === "select" ? "default" : "crosshair");
    const [sx, sy] = evPos(e);
    const [ix, iy] = toImage(sx, sy);
    const W = ctl.data.image.w, H = ctl.data.image.h;
    const inImg = ix >= 0 && iy >= 0 && ix <= W && iy <= H;
    if (g.kind === "point" && g.moved) {
      const p = ctl.pts.find((q) => q.id === g.id);
      if (p) {
        p.px = Math.min(Math.max(p.px, 0), W); p.py = Math.min(Math.max(p.py, 0), H);
        emit({ type: "move_point", id: g.id, px: p.px, py: p.py });
      }
    } else if (g.kind === "anchor" && g.moved) {
      const a = ctl.anchors[g.name];
      emit({ type: "set_anchor", name: g.name, px: a.px, py: a.py });
    } else if (g.kind === "box") {
      const box = { x0: g.ix, y0: g.iy, x1: g.x1, y1: g.y1 };
      if (ctl.mode === "roi" && g.moved) emit({ type: "set_roi", ...box });
      else if (ctl.mode === "exclude" && g.moved) emit({ type: "set_include_box", ...box, include: !!g.shift });
      else if (ctl.mode === "exclude") {
        const p = hitPoint(sx, sy);
        if (p) emit({ type: "toggle_include", id: p.id });
      }
    } else if (g.kind === "click" && !g.moved) {
      const m = ctl.mode;
      if (m === "add" && inImg) {
        ctl.pts.push({ id: -1, px: ix, py: iy, inc: 1, mod: 1 });
        emit({ type: "add_point", px: ix, py: iy });
      } else if (m === "delete") {
        const p = hitPoint(sx, sy);
        if (p) { ctl.pts = ctl.pts.filter((q) => q !== p); emit({ type: "delete_point", id: p.id }); }
      } else if (["X1", "X2", "Y1", "Y2"].includes(m) && inImg) {
        const [ax, ay] = snap(m, ix, iy, g.alt);
        ctl.anchors[m] = { ...(ctl.anchors[m] || {}), px: ax, py: ay };
        emit({ type: "set_anchor", name: m, px: ax, py: ay });
      }
    }
    schedule();
  }
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", () => { ctl.drag = null; schedule(); });
  canvas.addEventListener("pointerleave", () => { ctl.hover = null; updateStatus(); schedule(); });
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const [sx, sy] = evPos(e);
    zoomAt(Math.pow(1.0015, -e.deltaY), sx, sy);
  }, { passive: false });
  canvas.addEventListener("dblclick", (e) => { const [sx, sy] = evPos(e); zoomAt(2, sx, sy); });

  // ---------------- teclado
  root.addEventListener("keydown", (e) => {
    ctl.lastInteraction = Date.now();
    const k = e.key;
    if ((e.ctrlKey || e.metaKey) && (k === "z" || k === "Z")) { e.preventDefault(); emit({ type: e.shiftKey ? "redo" : "undo" }); return; }
    if ((e.ctrlKey || e.metaKey) && (k === "y" || k === "Y")) { e.preventDefault(); emit({ type: "redo" }); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if ((k === "Delete" || k === "Backspace") && ctl.sel !== null) {
      e.preventDefault();
      const id = ctl.sel; ctl.sel = null;
      ctl.pts = ctl.pts.filter((q) => q.id !== id);
      emit({ type: "delete_point", id }); schedule(); return;
    }
    const map = { v: "select", a: "add", d: "delete", e: "exclude", r: "roi", h: "pan" };
    if (map[k]) { setMode(map[k]); e.preventDefault(); return; }
    const c = [canvas.clientWidth / 2, canvas.clientHeight / 2];
    if (k === "+" || k === "=") { zoomAt(1.25, ...c); e.preventDefault(); }
    else if (k === "-") { zoomAt(0.8, ...c); e.preventDefault(); }
    else if (k === "0") { fit(); e.preventDefault(); }
    else if (k === "Escape") { ctl.sel = null; setMode("select"); }
    else if (k === " ") { ctl.spaceDown = true; e.preventDefault(); }
  });
  root.addEventListener("keyup", (e) => { if (e.key === " ") ctl.spaceDown = false; });

  // ---------------- botones
  for (const m in modeBtns) modeBtns[m].addEventListener("click", () => setMode(m));
  zoomIn.addEventListener("click", () => zoomAt(1.25, canvas.clientWidth / 2, canvas.clientHeight / 2));
  zoomOut.addEventListener("click", () => zoomAt(0.8, canvas.clientWidth / 2, canvas.clientHeight / 2));
  fitBtn.addEventListener("click", fit);
  oneBtn.addEventListener("click", () => {
    const [cx, cy] = [canvas.clientWidth / 2, canvas.clientHeight / 2];
    zoomAt(1 / ctl.view.scale, cx, cy);
  });
  undoBtn.addEventListener("click", () => emit({ type: "undo" }));
  ocrBtn.addEventListener("click", () => { ctl.showOcr = !ctl.showOcr; ocrBtn.classList.toggle("on", ctl.showOcr); schedule(); });
  redoBtn.addEventListener("click", () => emit({ type: "redo" }));

  // ---------------- estado
  function updateStatus() {
    const d = ctl.data;
    const label = (MODES.find((x) => x[0] === ctl.mode) || [0, ctl.mode])[1];
    sMode.textContent = "Modo: " + label;
    sZoom.textContent = "Zoom " + Math.round(ctl.view.scale * 100) + " %";
    if (ctl.hover && d) {
      const [x, y] = ctl.hover;
      let t = `px (${x.toFixed(1)}, ${y.toFixed(1)})`;
      if (d.calib) {
        t += ` → x = ${fmt(axisValue(d.calib.x, x))} ${d.calib.xunit}, V = ${fmt(axisValue(d.calib.y, y))} ${d.calib.yunit}`;
      } else {
        t += " · coordenadas en píxeles / calibración pendiente";
      }
      sPos.textContent = t;
    } else {
      sPos.textContent = d && d.calib ? "" : "Coordenadas en píxeles / calibración pendiente";
    }
    const n = ctl.pts.length, ex = ctl.pts.filter((p) => !p.inc).length;
    sInfo.textContent = `${n} punto(s)` + (ex ? `, ${ex} excluido(s)` : "") + (d && d.edited ? " · ✎ intervenido manualmente" : "");
    sInfo.classList.toggle("pml-edited", !!(d && d.edited));
    root.dataset.view = JSON.stringify({ scale: ctl.view.scale, ox: ctl.view.ox, oy: ctl.view.oy });
  }
  ctl.updateStatus = updateStatus;

  // ---------------- dibujo
  function schedule() {
    if (ctl.raf) return;
    ctl.raf = requestAnimationFrame(() => { ctl.raf = 0; draw(); });
  }
  ctl.schedule = schedule;

  function draw() {
    const d = ctl.data;
    const ctx = canvas.getContext("2d");
    const dpr = ctl.dpr, s = ctl.view.scale;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = "#e9ebef";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (!d || !d.image) return;
    ctx.setTransform(dpr * s, 0, 0, dpr * s, -ctl.view.ox * s * dpr, -ctl.view.oy * s * dpr);
    const u = 1 / s;  // un píxel de pantalla en unidades de imagen
    ctx.imageSmoothingEnabled = s < 3;
    if (ctl.imgReady) ctx.drawImage(ctl.img, 0, 0, d.image.w, d.image.h);
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    // área de trazado y ROI
    if (d.plot_box) {
      const [x0, y0, x1, y1] = d.plot_box;
      ctx.setLineDash([4 * u, 4 * u]); ctx.strokeStyle = "rgba(90,90,90,0.55)"; ctx.lineWidth = 1 * u;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
    if (d.roi) {
      const [x0, y0, x1, y1] = d.roi;
      ctx.setLineDash([7 * u, 4 * u]); ctx.strokeStyle = "rgba(230,140,0,0.9)"; ctx.lineWidth = 1.5 * u;
      ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
    ctx.setLineDash([]);
    // trazos densos candidatos
    for (const c of d.candidates || []) {
      if (!c.dense || c.dense.length < 2) continue;
      ctx.beginPath();
      ctx.moveTo(c.dense[0][0], c.dense[0][1]);
      for (const [x, y] of c.dense) ctx.lineTo(x, y);
      ctx.strokeStyle = c.selected ? "rgba(255,0,200,0.55)" : "rgba(120,120,120,0.45)";
      ctx.lineWidth = (c.selected ? 1.2 : 1) * u;
      ctx.setLineDash(c.selected ? [] : [3 * u, 3 * u]);
      ctx.stroke();
      ctx.setLineDash([]);
      const [lx, ly] = c.dense[0];
      ctx.font = `${11 * u}px sans-serif`;
      ctx.fillStyle = c.selected ? "#c0008f" : "#666";
      ctx.fillText(c.id, lx + 4 * u, ly - 6 * u);
    }
    // polilínea de los puntos incluidos
    const inc = ctl.pts.filter((p) => p.inc).slice().sort((a, b) => a.px - b.px);
    if (inc.length >= 2) {
      ctx.beginPath();
      ctx.moveTo(inc[0].px, inc[0].py);
      for (const p of inc) ctx.lineTo(p.px, p.py);
      ctx.strokeStyle = "rgba(0,0,0,0.65)"; ctx.lineWidth = 4 * u; ctx.stroke();
      ctx.strokeStyle = "#16d38a"; ctx.lineWidth = 2 * u; ctx.stroke();
    }
    // puntos
    for (const p of ctl.pts) {
      const r = (p.id === ctl.sel ? 6.5 : 4.5) * u;
      ctx.beginPath(); ctx.arc(p.px, p.py, r, 0, Math.PI * 2);
      if (!p.inc) {
        ctx.fillStyle = "rgba(255,255,255,0.7)"; ctx.fill();
        ctx.strokeStyle = "#777"; ctx.lineWidth = 1.5 * u; ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(p.px - r, p.py - r); ctx.lineTo(p.px + r, p.py + r);
        ctx.moveTo(p.px + r, p.py - r); ctx.lineTo(p.px - r, p.py + r);
        ctx.stroke();
      } else {
        ctx.fillStyle = p.mod ? "#ff8c00" : "#16d38a"; ctx.fill();
        ctx.strokeStyle = "#111"; ctx.lineWidth = 1.2 * u; ctx.stroke();
      }
      if (p.id === ctl.sel) {
        ctx.beginPath(); ctx.arc(p.px, p.py, r + 3 * u, 0, Math.PI * 2);
        ctx.strokeStyle = "#ff00c8"; ctx.lineWidth = 1.5 * u; ctx.stroke();
      }
    }
    // ticks detectados (en modos de ancla)
    if (["X1", "X2", "Y1", "Y2"].includes(ctl.mode) && d.ticks) {
      ctx.fillStyle = "rgba(255,0,200,0.85)";
      const pb = d.plot_box || [0, 0, d.image.w, d.image.h];
      for (const t of d.ticks.X || []) { ctx.beginPath(); ctx.moveTo(t, pb[3]); ctx.lineTo(t - 5 * u, pb[3] + 9 * u); ctx.lineTo(t + 5 * u, pb[3] + 9 * u); ctx.fill(); }
      for (const t of d.ticks.Y || []) { ctx.beginPath(); ctx.moveTo(pb[0], t); ctx.lineTo(pb[0] - 9 * u, t - 5 * u); ctx.lineTo(pb[0] - 9 * u, t + 5 * u); ctx.fill(); }
    }
    // anclas
    for (const n of ["X1", "X2", "Y1", "Y2"]) {
      const a = ctl.anchors[n];
      if (!a || a.px === null || a.py === null) continue;
      const col = n[0] === "X" ? "#d4007f" : "#0060e0";
      ctx.setLineDash([6 * u, 4 * u]); ctx.strokeStyle = col; ctx.lineWidth = 1 * u;
      ctx.beginPath();
      if (n[0] === "X") { ctx.moveTo(a.px, 0); ctx.lineTo(a.px, d.image.h); }
      else { ctx.moveTo(0, a.py); ctx.lineTo(d.image.w, a.py); }
      ctx.stroke(); ctx.setLineDash([]);
      ctx.fillStyle = "rgba(255,255,255,0.85)"; ctx.strokeStyle = col; ctx.lineWidth = 2 * u;
      ctx.fillRect(a.px - 5 * u, a.py - 5 * u, 10 * u, 10 * u);
      ctx.strokeRect(a.px - 5 * u, a.py - 5 * u, 10 * u, 10 * u);
      const txt = `${n} = ${a.label}`;
      ctx.font = `bold ${12 * u}px sans-serif`;
      const tw = ctx.measureText(txt).width;
      const tx = a.px + 8 * u, ty = n[0] === "X" ? a.py + 22 * u : a.py - 8 * u;
      ctx.fillStyle = "rgba(255,255,255,0.88)"; ctx.fillRect(tx - 2 * u, ty - 12 * u, tw + 4 * u, 15 * u);
      ctx.fillStyle = col; ctx.fillText(txt, tx, ty);
    }
    // etiquetas de ejes reconocidas (OCR + verificación geométrica)
    if (ctl.showOcr && d.ocr) {
      ctx.font = `${10.5 * u}px sans-serif`;
      for (const b of d.ocr) {
        const [x0, y0, x1, y1] = b.bbox;
        const col = b.title ? (b.inlier ? "#2f6fed" : "#7a8796") : b.excluded ? "#8a8a8a" : b.inlier ? "#14a05a" : "#d0304f";
        ctx.strokeStyle = col; ctx.lineWidth = 1.4 * u; ctx.setLineDash(b.excluded ? [3 * u, 2 * u] : []);
        ctx.strokeRect(x0 - 1.5 * u, y0 - 1.5 * u, x1 - x0 + 3 * u, y1 - y0 + 3 * u); ctx.setLineDash([]);
        const tag = b.title ? (b.unit ? `unidad: ${b.unit}` : "título") : (b.value === null || b.value === undefined ? "?" : `${b.value}${b.user ? " ✎" : ""}`);
        const tw = ctx.measureText(tag).width;
        const ty = b.axis === "X" && !b.title ? y1 + 12 * u : y0 - 4 * u;
        ctx.fillStyle = "rgba(255,255,255,0.86)"; ctx.fillRect(x0 - 1 * u, ty - 10 * u, tw + 4 * u, 12.5 * u);
        ctx.fillStyle = col; ctx.fillText(tag, x0 + 1 * u, ty);
      }
    }
    // recuadro en curso
    const g = ctl.drag;
    if (g && g.kind === "box") {
      ctx.setLineDash([4 * u, 3 * u]);
      ctx.strokeStyle = ctl.mode === "roi" ? "#e08c00" : "#555"; ctx.lineWidth = 1.5 * u;
      ctx.strokeRect(Math.min(g.ix, g.x1), Math.min(g.iy, g.y1), Math.abs(g.x1 - g.ix), Math.abs(g.y1 - g.iy));
      ctx.setLineDash([]);
    }
    updateStatus();
  }
  setMode("select");
  return root;
}

export default function (component) {
  const { setTriggerValue, parentElement } = component;
  let data = component.data;
  if (typeof data === "string") {           // defensa: datos serializados como texto JSON
    try { data = JSON.parse(data); } catch (e) { return; }
  }
  if (!data || !data.image) return;
  let root = parentElement.querySelector(".pml-dz");
  if (!root) root = build(parentElement);
  const ctl = root.__ctl;
  ctl.send = setTriggerValue;
  const prevKey = ctl.imgKey;
  ctl.data = data;
  if (!ctl.drag) {
    ctl.pts = (data.points || []).map((p) => ({ id: p[0], px: p[1], py: p[2], inc: p[3], mod: p[4] }));
    ctl.anchors = {};
    for (const n in data.anchors || {}) ctl.anchors[n] = { ...data.anchors[n] };
    if (ctl.sel !== null && !ctl.pts.some((p) => p.id === ctl.sel)) ctl.sel = null;
  }
  root.dataset.rev = String(data.rev);
  if (data.image && data.image.key !== prevKey) {
    ctl.imgKey = data.image.key;
    ctl.imgReady = false;
    ctl.view.fitted = false;
    ctl.img = new Image();
    ctl.img.onload = () => { ctl.imgReady = true; root.dataset.ready = "1"; ctl.fit(); };
    ctl.img.src = data.image.url;   // data: URL generada en Python; nunca HTML del usuario
  }
  if (!window.__pmlDigitizer) window.__pmlDigitizer = {};
  window.__pmlDigitizer[data.instance || "default"] = {
    toClient(px, py) {
      const r = ctl.canvas.getBoundingClientRect();
      const [sx, sy] = ctl.toScreen(px, py);
      return [r.left + sx, r.top + sy];
    },
    view: () => ({ ...ctl.view }),
    points: () => ctl.pts.map((p) => ({ ...p })),
    anchors: () => JSON.parse(JSON.stringify(ctl.anchors)),
    setMode: (m) => ctl.setMode(m),
    rev: () => data.rev,
    focus: () => root.focus({ preventScroll: true }),
    hasFocus: () => root.getRootNode().activeElement === root,
    calls: () => (ctl.calls || 0),
    instance: () => ctl.instanceId,
  };
  ctl.calls = (ctl.calls || 0) + 1;
  // Tras cada reejecución, la gestión de foco del modal lleva el foco al botón «Close»: si el usuario
  // estaba trabajando en el lienzo (últimos 8 s), se le devuelve para que Supr/Ctrl+Z sigan llegando aquí
  // y para que Espacio/Intro no cierren el diálogo por accidente.
  if (ctl.lastInteraction && Date.now() - ctl.lastInteraction < 8000) {
    for (const ms of [0, 60, 200, 500]) {
      setTimeout(() => {
        const act = document.activeElement;
        const inRoot = root.getRootNode() && root.getRootNode().activeElement === root;
        if (!inRoot && (!act || act === document.body || (act.getAttribute && act.getAttribute("aria-label") === "Close"))) {
          root.focus({ preventScroll: true });
        }
      }, ms);
    }
  }
  ctl.schedule();
  return () => { /* el lienzo persiste entre reejecuciones; se libera al desmontar */ };
}
