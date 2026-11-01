import asyncio, json
from playwright.async_api import async_playwright
import os, pathlib
U = os.environ.get("PML_URL", "http://127.0.0.1:8501"); S = str(pathlib.Path(__file__).resolve().parents[2] / "docs" / "capturas" / "v0.3.0") + "/"; os.makedirs(S, exist_ok=True)
R={}
async def idle(pg, ms=900):
    await pg.wait_for_timeout(ms)
    for _ in range(120):
        if await pg.locator('[data-testid="stStatusWidget"]').count()==0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(400)
async def exc(pg):
    n = await pg.locator('[data-testid="stException"]').count()
    if n: R.setdefault("excepciones", []).append((await pg.locator('[data-testid="stException"]').first.inner_text())[:500])
    return n
async def step(pg, name, fn):
    try:
        await fn(); R[name]="ok"
    except Exception as e:
        R[name]=f"FALLO: {str(e)[:200]}"; await pg.screenshot(path=S+f"fallo_{name}.png"); raise
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-proxy-server"]); ctx = await b.new_context(viewport={"width":1440,"height":1000})
        pg = await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(U); await idle(pg, 3500)
            await pg.screenshot(path=S+"01_catalogo_vacio.png"); await exc(pg)
            async def crear():
                await pg.locator(".cat-add").click(); await idle(pg)
                D=pg.locator('[role="dialog"]'); await D.get_by_label("Nombre del dispositivo *", exact=True).fill("Stack de laboratorio OTEKON")
                await D.get_by_label("Fabricante", exact=True).fill("Grupo PEM-FC"); await D.get_by_label("Modelo", exact=True).fill("Ref. Fig. 3"); await pg.keyboard.press("Tab"); await idle(pg,500)
                await pg.screenshot(path=S+"02_crear_dispositivo.png")
                await pg.get_by_role("button", name="Crear dispositivo").click(); await idle(pg, 2000)
            await step(pg, "crear", crear); R["url"]=pg.url; await pg.screenshot(path=S+"03_etapa01.png"); await exc(pg)
            async def e1():
                await pg.get_by_label("Número de celdas", exact=True).fill("41"); await pg.get_by_label("Área activa [cm²]", exact=True).fill("232"); await pg.keyboard.press("Tab"); await idle(pg,600)
                await pg.get_by_role("button", name="Guardar cambios del dispositivo").click(); await idle(pg,1500)
                await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
            await step(pg, "etapa1", e1)
            async def e2():
                await pg.get_by_text("Ejemplos documentados").click(); await idle(pg)
                await pg.get_by_role("button", name="Cargar: OTEKON Fig. 3 — 4 curvas digitalizadas").click(); await idle(pg,2500)
                await pg.screenshot(path=S+"04_etapa02_datos.png"); await exc(pg)
                await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
            await step(pg, "etapa2", e2)
            async def e3():
                await pg.get_by_role("button", name="Preset OTEKON (9 parámetros, reproducción del artículo)").click(); await idle(pg,1500)
                await pg.screenshot(path=S+"05_etapa03_config.png"); await exc(pg)
                await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
            await step(pg, "etapa3", e3)
            async def e4():
                await pg.get_by_role("button", name="Ejecutar identificación").click(); await idle(pg,6000)
                R["estado_ajuste"]=[l for l in (await pg.inner_text("body")).splitlines() if "Estado:" in l][:1]
                await pg.screenshot(path=S+"06_etapa04_calibracion.png"); await exc(pg)
                await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,2500)
                await pg.screenshot(path=S+"07_etapa05_analisis.png"); await exc(pg)
                await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,2500)
            await step(pg, "etapa4_5", e4)
            async def e6():
                async with pg.expect_download() as dl: await pg.get_by_role("button", name="Descargar profile.json").first.click()
                d=await dl.value; R["perfil_descargado"]=d.suggested_filename; await idle(pg,2500)
                await pg.screenshot(path=S+"08_etapa06_perfil.png"); await exc(pg)
                R["indicador"]=await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.tb-save')); return h? h.shadowRoot.querySelector('.tb-save').textContent : null})()")
            await step(pg, "etapa6", e6)
            async def cat():
                await pg.get_by_role("button", name="← Dispositivos").click(); await idle(pg,2000)
                await pg.screenshot(path=S+"09_catalogo_con_dispositivo.png")
                await pg.reload(); await idle(pg,4500)
                R["tras_recarga_tarjeta"]=await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.cat-card'));return h?[...h.shadowRoot.querySelectorAll('.cat-card:not(.cat-add)')].map(c=>c.innerText.replace(/\\n/g,' | ')):null})()")
            await step(pg, "recarga", cat)
            async def reab():
                await pg.locator(".cat-card:not(.cat-add)").first.click(); await idle(pg,3500)
                R["etapa_reabierta"]=[l for l in (await pg.inner_text("body")).splitlines() if l.startswith("Etapa ")][:1]
                await pg.screenshot(path=S+"10_reabierto_tras_recarga.png"); await exc(pg)
                await pg.get_by_text("Historial y perfiles").click(); await idle(pg,2500)
                await pg.screenshot(path=S+"11_historial.png"); await exc(pg)
                R["historial"]=[l for l in (await pg.inner_text("body")).splitlines() if "Calibración 1" in l or "Calibraciones" in l][:4]
            await step(pg, "reabrir_historial", reab)
        finally:
            R["errs"]=errs[:5]
            print(json.dumps(R, indent=1, ensure_ascii=False))
            await b.close()
asyncio.run(main())
