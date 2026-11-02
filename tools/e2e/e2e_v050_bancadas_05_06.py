"""Navegador real: Bancadas 05 y 06 (escenarios → mapa → clic en el mapa → Bancada 04), escritorio y tablet."""
import asyncio, json, os, pathlib
from playwright.async_api import async_playwright
ROOT = pathlib.Path(__file__).resolve().parents[2]
U = os.environ.get("PML_URL", "http://127.0.0.1:8501")
S = os.environ.get("PML_SHOTS", str(ROOT / "docs" / "capturas" / "v0.5.0") + "/"); os.makedirs(S, exist_ok=True)
PROF = str(ROOT / "tests" / "fixtures" / "compat" / "profile_v020.json")
R = {}
async def idle(pg, ms=900):
    await pg.wait_for_timeout(ms)
    for _ in range(240):
        if await pg.locator('[data-testid="stStatusWidget"]').count() == 0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(500)
async def run(viewport, touch, tag):
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-proxy-server"])
        pg = await (await b.new_context(viewport=viewport, has_touch=touch)).new_page()
        errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(U + "/?view=catalog"); await idle(pg, 4000)
            await pg.get_by_text("Proyectos, copias de seguridad y compatibilidad").click(); await idle(pg)
            await pg.locator('input[type="file"][accept*="json"]').first.set_input_files(PROF); await idle(pg, 1500)
            await pg.get_by_role("button", name="Migrar como dispositivo nuevo").click(); await idle(pg, 3500)
            await pg.goto(U + "/?view=motor2"); await idle(pg, 5000)
            R[f"{tag}_seis_bancadas"] = await pg.get_by_role("button", name="Abrir bancada").count()
            btn = pg.get_by_role("button", name="Abrir bancada").nth(4)
            await btn.scroll_into_view_if_needed(); await btn.click(); await idle(pg, 2500)
            run_ = pg.get_by_role("button", name="▶ Ejecutar experimento"); await run_.scroll_into_view_if_needed(); await run_.click(); await idle(pg, 5000)
            R[f"{tag}_escenarios_graficos"] = await pg.locator('[data-testid="stPlotlyChart"]').count()
            await pg.screenshot(path=S + f"{tag}_01_bancada05_escenarios.png")
            gm = pg.get_by_role("button", name="Generar mapa con él"); await gm.scroll_into_view_if_needed(); await gm.click(); await idle(pg, 3000)
            run_ = pg.get_by_role("button", name="▶ Ejecutar experimento"); await run_.scroll_into_view_if_needed(); await run_.click(); await idle(pg, 6000)
            ch = pg.locator('[data-testid="stPlotlyChart"]').first
            await ch.scroll_into_view_if_needed(); await idle(pg, 1500)
            await ch.screenshot(path=S + f"{tag}_02_bancada06_mapa.png")
            xin = pg.get_by_label("Densidad de corriente", exact=True)
            before = await xin.input_value()
            bb = await ch.bounding_box()
            cx, cy = bb["x"] + bb["width"] * 0.62, bb["y"] + bb["height"] * 0.42
            if touch: await pg.touchscreen.tap(cx, cy)
            else: await pg.mouse.click(cx, cy)
            await idle(pg, 3000)
            xin = pg.get_by_label("Densidad de corriente", exact=True)
            after = await xin.input_value()
            R[f"{tag}_clic_selecciona_punto"] = (before, after, before != after)
            await pg.screenshot(path=S + f"{tag}_03_punto_seleccionado.png")
            to4 = pg.get_by_role("button", name="Enviar a la Bancada 04 (potencia objetivo)")
            await to4.scroll_into_view_if_needed(); await to4.click(); await idle(pg, 3000)
            t = await pg.inner_text("body"); R[f"{tag}_en_bancada04"] = "BANCADA 04" in t
            run_ = pg.get_by_role("button", name="▶ Ejecutar experimento"); await run_.scroll_into_view_if_needed(); await run_.click(); await idle(pg, 4000)
            t = await pg.inner_text("body"); R[f"{tag}_b04_ejecutada"] = "Punto factible para una potencia objetivo" in t or "Densidad de corriente" in t
            await pg.screenshot(path=S + f"{tag}_04_bancada04_desde_mapa.png")
        finally:
            R[f"{tag}_exc"] = await pg.locator('[data-testid="stException"]').count(); R[f"{tag}_errs"] = errs[:3]
            await b.close()
async def main():
    await run({"width": 1440, "height": 1000}, False, "pc")
    await run({"width": 1024, "height": 768}, True, "tablet")
    print(json.dumps(R, ensure_ascii=False, indent=1))
asyncio.run(main())
