// PEMFC ModelLab — puente de persistencia en el navegador (IndexedDB), sin servicios externos.
// Garantías: datos por navegador y por origen (dominio); sobreviven a recargas y a la pérdida de la
// sesión del servidor; se pierden si el usuario borra los datos del sitio. No se sincronizan entre equipos.
const DB_NAME = "pemfc-modellab";
const DB_VERSION = 1;
const STORE = "records";

function openDb() {
  return new Promise((resolve, reject) => {
    if (!("indexedDB" in window)) { reject(new Error("IndexedDB no disponible en este navegador")); return; }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => { if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE); };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error || new Error("No se pudo abrir IndexedDB"));
    req.onblocked = () => reject(new Error("IndexedDB bloqueada por otra pestaña"));
  });
}

async function snapshot() {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const out = {}, blobs = {};
    const tx = db.transaction(STORE, "readonly");
    const cur = tx.objectStore(STORE).openCursor();
    cur.onsuccess = () => {
      const c = cur.result;
      if (!c) return;
      const k = String(c.key);
      if (k.startsWith("blob:")) blobs[k] = (c.value && c.value.size) || 0;   // binarios: bajo demanda
      else out[k] = c.value;
      c.continue();
    };
    tx.oncomplete = () => resolve({ records: out, blobs });
    tx.onerror = () => reject(tx.error);
  });
}

async function getMany(keys) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const out = {};
    const tx = db.transaction(STORE, "readonly");
    const st = tx.objectStore(STORE);
    for (const k of keys) { const r = st.get(k); r.onsuccess = () => { if (r.result) out[k] = r.result; }; }
    tx.oncomplete = () => resolve(out);
    tx.onerror = () => reject(tx.error);
  });
}

// Escritura transaccional con control de revisión:
// - inmutables: si ya existen con otro contenido → conflicto (no se escribe)
// - mutables: si la revisión almacenada es mayor que la revisión base de esta sesión → conflicto
async function putMany(items) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const saved = [], conflicts = [];
    const tx = db.transaction(STORE, "readwrite");
    const st = tx.objectStore(STORE);
    for (const it of items) {
      const g = st.get(it.key);
      g.onsuccess = () => {
        const cur = g.result;
        if (cur && cur.value === it.value) { saved.push(it.key); return; }
        if (cur && it.immutable) { conflicts.push({ key: it.key, reason: "inmutable", stored_rev: cur.rev || 0 }); return; }
        if (cur && !it.immutable && (cur.rev || 0) > (it.base_rev || 0)) {
          conflicts.push({ key: it.key, reason: "revision", stored_rev: cur.rev || 0 }); return;
        }
        const val = { rev: it.rev || 0, value: it.value, saved_at: new Date().toISOString() };
        if (it.key.startsWith("blob:")) val.size = it.value.length;
        st.put(val, it.key);
        saved.push(it.key);
      };
    }
    tx.oncomplete = () => resolve({ saved, conflicts });
    tx.onerror = () => reject(tx.error || new Error("Error de escritura"));
    tx.onabort = () => reject(tx.error || new Error("Transacción abortada (¿cuota excedida?)"));
  });
}

async function storageInfo() {
  const info = { persisted: null, usage: null, quota: null };
  try {
    if (navigator.storage && navigator.storage.persist) info.persisted = await navigator.storage.persist();
    if (navigator.storage && navigator.storage.estimate) {
      const e = await navigator.storage.estimate(); info.usage = e.usage; info.quota = e.quota;
    }
  } catch (e) { /* informativo */ }
  return info;
}

export default function (component) {
  const { data, setStateValue } = component;
  const g = window.__pmlStorage || (window.__pmlStorage = { session: null, lastWrite: -1, lastRead: -1 });
  if (data.session && data.session !== g.session) {      // sesión nueva del servidor → reenviar instantánea
    g.session = data.session; g.lastWrite = -1; g.lastRead = -1;
    Promise.all([snapshot(), storageInfo()])
      .then(([s, info]) => setStateValue("snapshot", { session: data.session, ...s, info, at: Date.now() }))
      .catch((e) => setStateValue("error", { session: data.session, message: String(e && e.message || e), at: Date.now() }));
  }
  if (data.write && data.write.seq > g.lastWrite) {
    g.lastWrite = data.write.seq;
    putMany(data.write.items)
      .then((r) => setStateValue("ack", { seq: data.write.seq, ...r, at: Date.now() }))
      .catch((e) => setStateValue("ack", { seq: data.write.seq, saved: [], conflicts: [], error: String(e && e.message || e), at: Date.now() }));
  }
  if (data.read && data.read.seq > g.lastRead) {
    g.lastRead = data.read.seq;
    getMany(data.read.keys)
      .then((items) => setStateValue("blobs", { seq: data.read.seq, items, at: Date.now() }))
      .catch((e) => setStateValue("error", { session: data.session, message: String(e && e.message || e), at: Date.now() }));
  }
}
