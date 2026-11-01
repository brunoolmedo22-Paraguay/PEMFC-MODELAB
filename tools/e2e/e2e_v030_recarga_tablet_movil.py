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
async def body(pg): return await pg.inner_text("body")
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-proxy-server"]); ctx = await b.new_context(viewport={"width":1440,"height":1000})
        pg = await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U); await idle(pg, 3000)
        await pg.locator(".cat-add").click(); await idle(pg)
        D=pg.locator('[role="dialog"]'); await D.get_by_label("Nombre del dispositivo *", exact=True).fill("Stack recarga"); await pg.keyboard.press("Tab"); await idle(pg,400)
        await pg.get_by_role("button", name="Crear dispositivo").click(); await idle(pg, 2000)
        await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
        await pg.get_by_text("Ejemplos documentados").click(); await idle(pg)
        await pg.get_by_role("button", name="Cargar: OTEKON Fig. 3 — 4 curvas digitalizadas").click(); await idle(pg,2500)
        await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
        await pg.get_by_role("button", name="Preset OTEKON (9 parámetros, reproducción del artículo)").click(); await idle(pg,1500)
        await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
        await pg.get_by_role("button", name="Ejecutar identificación").click(); await idle(pg,6000)
        await pg.wait_for_timeout(2500)
        url = pg.url; R["url_antes"]=url
        # --- recarga dura en la misma URL (sesión de servidor nueva)
        await pg.reload(); await idle(pg, 5000)
        t = await body(pg)
        R["tras_recarga_etapa4_registrada"] = "Mostrando la calibración registrada" in t
        R["tras_recarga_estado"] = [l for l in t.splitlines() if "AJUSTADO_A_CURVA" in l][:1]
        await pg.screenshot(path=S+"12_recarga_calibracion_registrada.png")
        await pg.get_by_role("button", name="← Anterior").click(); await idle(pg,2500)
        t = await body(pg); R["config_preservada"] = [l for l in t.splitlines() if "OTEKON" in l and ("preset" in l.lower() or "Preset" in l)][:2]
        R["stepper"] = await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.stp'));return h?[...h.shadowRoot.querySelectorAll('.stp-item')].map(i=>i.className.replace('stp-item ','')):null})()")
        # --- tablet
        await pg.set_viewport_size({"width":1024,"height":768}); await idle(pg,1200)
        await pg.screenshot(path=S+"13_tablet_flujo.png")
        await pg.get_by_role("button", name="← Dispositivos").click(); await idle(pg,2000)
        await pg.screenshot(path=S+"14_tablet_catalogo.png")
        await pg.set_viewport_size({"width":390,"height":844}); await idle(pg,1200)
        await pg.screenshot(path=S+"15_movil_catalogo.png", full_page=True)
        R["exc"]=await pg.locator('[data-testid="stException"]').count(); R["errs"]=errs[:4]
        await b.close()
    print(json.dumps(R, indent=1, ensure_ascii=False))
asyncio.run(main())
