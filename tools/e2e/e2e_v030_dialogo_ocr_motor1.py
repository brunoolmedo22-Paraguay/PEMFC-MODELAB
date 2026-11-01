import asyncio, json
from playwright.async_api import async_playwright
import os, pathlib
U = os.environ.get("PML_URL", "http://127.0.0.1:8501"); S = str(pathlib.Path(__file__).resolve().parents[2] / "docs" / "capturas" / "v0.3.0") + "/"; os.makedirs(S, exist_ok=True); R={}
FX = str(pathlib.Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "digitizer" / "01_curva_simple.png")
async def idle(pg, ms=900):
    await pg.wait_for_timeout(ms)
    for _ in range(160):
        if await pg.locator('[data-testid="stStatusWidget"]').count()==0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(500)
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-proxy-server"]); pg = await (await b.new_context(viewport={"width":1440,"height":1000})).new_page()
        errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(U); await idle(pg, 3000)
            await pg.locator(".cat-add").click(); await idle(pg)
            D=pg.locator('[role="dialog"]'); await D.get_by_label("Nombre del dispositivo *", exact=True).fill("Stack digitalizado"); await pg.keyboard.press("Tab"); await idle(pg,400)
            await pg.get_by_role("button", name="Crear dispositivo").click(); await idle(pg, 2000)
            await pg.get_by_role("button", name="Continuar →").click(); await idle(pg,1500)
            await pg.get_by_text("Imagen de una curva").click(); await idle(pg)
            await pg.get_by_role("button", name="Abrir digitalizador").click(); await idle(pg,1500)
            await pg.locator('[role="dialog"] input[type="file"]').first.set_input_files(FX); await idle(pg, 8000)
            t = await pg.locator('[role="dialog"]').inner_text()
            R["ejes"] = [l for l in t.splitlines() if l.startswith("Eje X ·") or l.startswith("Eje Y ·")]
            R["valores"] = await pg.evaluate("window.__pmlDigitizer && window.__pmlDigitizer.dz ? window.__pmlDigitizer.dz.anchors() : null")
            await pg.screenshot(path=S+"30_motor1_dialogo_ocr.png")
            await pg.locator('[role="dialog"]').get_by_role("tab", name="Condiciones y metadatos").click(); await idle(pg)
            for lab, val in [("Identificador de la curva *","auto_ocr"),("Temperatura *","343.15"),("Presión de cátodo *","1.5")]:
                loc = pg.locator('[role="dialog"]').get_by_label(lab, exact=True); await loc.fill(val); await loc.press("Enter"); await idle(pg,900)
            btn = pg.locator('[role="dialog"]').get_by_role("button", name="Confirmar y añadir curva")
            R["confirmar_habilitado"] = not await btn.is_disabled()
            await btn.click(); await idle(pg, 3000)
            body = await pg.inner_text("body")
            R["anadida"] = [l for l in body.splitlines() if "añadida" in l][:1]
            R["dialogo_cerrado"] = await pg.locator('[role="dialog"]').count() == 0
            await pg.screenshot(path=S+"31_motor1_curva_confirmada.png")
        finally:
            R["exc"]=await pg.locator('[data-testid="stException"]').count(); R["errs"]=errs[:4]
            print(json.dumps(R, indent=1, ensure_ascii=False)); await b.close()
asyncio.run(main())
