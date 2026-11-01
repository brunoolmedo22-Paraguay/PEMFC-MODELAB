import asyncio, json, io, zipfile, os, sys
from playwright.async_api import async_playwright
U = os.environ.get("PML_URL", "http://127.0.0.1:8811"); S = os.environ.get("PML_SHOTS", str(__import__("pathlib").Path(__file__).resolve().parents[2] / "docs" / "capturas" / "v0.3.1") + "/"); R = {}
async def idle(pg, ms=900):
    await pg.wait_for_timeout(ms)
    for _ in range(160):
        if await pg.locator('[data-testid="stStatusWidget"]').count() == 0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(450)
async def shadow_click(pg, selector, text=None):
    return await pg.evaluate("""([sel, txt]) => { for (const h of document.querySelectorAll('*')) { if (!h.shadowRoot) continue;
        for (const e of h.shadowRoot.querySelectorAll(sel)) { if (!txt || e.textContent.includes(txt)) {
          e.scrollIntoView({block: "center", inline: "nearest"}); const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; } } } return null; }""", [selector, text])
async def tap(pg, selector, text=None):
    xy = await shadow_click(pg, selector, text)
    await pg.wait_for_timeout(350)
    xy = await shadow_click(pg, selector, text) or xy
    assert xy, f"no encontrado {selector} {text}"
    await pg.touchscreen.tap(xy[0], xy[1])
async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-proxy-server"])
        ctx = await b.new_context(**p.devices["iPad (gen 7) landscape"], accept_downloads=True)
        pg = await ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(U); await idle(pg, 4000)
            await pg.screenshot(path=S + "01_inicio_tablet.png", full_page=True)
            R["inicio"] = "Bienvenido a PEMFC ModelLab" in await pg.inner_text("body")
            # navegación superior por TOQUE (antes bloqueada)
            await tap(pg, ".tb-link", "Digitalizador"); await idle(pg, 2000)
            R["toque_digitalizador"] = "Digitalizador de figuras científicas" in await pg.inner_text("body")
            await tap(pg, ".tb-link", "Alcance"); await idle(pg, 2000)
            R["toque_alcance"] = (await pg.evaluate("location.search")).find("about") >= 0
            await tap(pg, ".tb-brand"); await idle(pg, 2000)
            await tap(pg, ".eng-card", "Motor 2"); await idle(pg, 2000)
            t = await pg.inner_text("body"); R["motor2"] = "Motor 2 — Laboratorio Virtual" in t  # v0.4.0: laboratorio real
            await pg.screenshot(path=S + "02_motor2_tablet.png", full_page=True)
            await tap(pg, ".tb-brand"); await idle(pg, 2000)  # v0.4.0: la página del Motor 2 ya no es provisional
            R["regreso_inicio"] = "¿qué deseas hacer hoy?" in (await pg.inner_text("body")).lower()
            await pg.get_by_role("tab", name="Modelo implementado").tap(); await idle(pg, 1500)
            await pg.screenshot(path=S + "03_modelo_implementado.png", full_page=True)
            R["n_ecuaciones"] = await pg.locator(".katex-display").count()
            await tap(pg, ".eng-card", "Motor 1"); await idle(pg, 2500)
            R["motor1_encabezado"] = "Bienvenido al Motor 1" in await pg.inner_text("body")
            await pg.screenshot(path=S + "04_motor1_vacio_tablet.png")
            # crear y calibrar
            await tap(pg, ".cat-add"); await idle(pg)
            D = pg.locator('[role="dialog"]'); await D.get_by_label("Nombre del dispositivo *", exact=True).fill("Stack exportable")
            await D.get_by_label("Fabricante", exact=True).fill("Lab PEM"); await pg.keyboard.press("Tab"); await idle(pg, 400)
            await pg.get_by_role("button", name="Crear dispositivo").tap(); await idle(pg, 2000)
            await pg.get_by_role("button", name="Continuar →").tap(); await idle(pg, 1500)
            await pg.get_by_text("Ejemplos documentados").tap(); await idle(pg)
            await pg.get_by_role("button", name="Cargar: OTEKON Fig. 3 — 4 curvas digitalizadas").tap(); await idle(pg, 2500)
            await pg.get_by_role("button", name="Continuar →").tap(); await idle(pg, 1500)
            await pg.get_by_role("button", name="Preset OTEKON (9 parámetros, reproducción del artículo)").tap(); await idle(pg, 1500)
            await pg.get_by_role("button", name="Continuar →").tap(); await idle(pg, 1500)
            await pg.get_by_role("button", name="Ejecutar identificación").tap(); await idle(pg, 6000)
            await tap(pg, ".tb-link", "Motor 1"); await idle(pg, 2500)
            await pg.screenshot(path=S + "05_motor1_catalogo_tablet.png")
            # gestionar
            await tap(pg, ".cat-manage"); await idle(pg, 2000)
            await pg.screenshot(path=S + "06_gestionar_dispositivos.png")
            await pg.get_by_role("button", name="Exportar ZIP").tap(); await idle(pg, 2000)
            async with pg.expect_download() as dl: await pg.get_by_role("button", name="Descargar ZIP").tap()
            d = await dl.value; data = open(await d.path(), "rb").read(); R["zip"] = (d.suggested_filename, len(data))
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
            R["zip_contenido"] = sorted({n.split("/")[0] + "/" + (n.split("/")[1].split("_")[0] if n.count("/") else "") for n in names})[:12]
            man = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("manifest.json"))
            R["manifest"] = {k: man.get(k) for k in ("schema", "schema_version", "app_version", "device_ids")}
            await pg.get_by_role("button", name="Eliminar…").tap(); await idle(pg, 1200)
            await pg.screenshot(path=S + "07_confirmar_eliminacion.png")
            R["boton_bloqueado_sin_nombre"] = await pg.get_by_role("button", name="Eliminar definitivamente").is_disabled()
            inp = pg.locator('[role="dialog"]').get_by_label("Escriba el nombre exacto para confirmar: Stack exportable", exact=True)
            await inp.fill("Stack exportable"); await inp.press("Enter"); await idle(pg, 1200)
            await pg.get_by_role("button", name="Eliminar definitivamente").tap(); await idle(pg, 2000)
            R["msg_eliminado"] = [l for l in (await pg.inner_text("body")).splitlines() if "eliminado" in l][:1]
            await pg.get_by_role("button", name="Cerrar").tap(); await idle(pg, 2500)
            await pg.reload(); await idle(pg, 4500)
            R["tras_recarga_tarjetas"] = await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.cat-grid'));return h?h.shadowRoot.querySelectorAll('.cat-card:not(.cat-add)').length:null})()")
            # importar
            await tap(pg, ".cat-manage"); await idle(pg, 2000)
            await pg.get_by_role("tab", name="Importar").tap(); await idle(pg)
            open("/tmp/pkg.pmldevice.zip", "wb").write(data)
            await pg.locator('[role="dialog"] input[type="file"]').first.set_input_files("/tmp/pkg.pmldevice.zip"); await idle(pg, 2500)
            await pg.screenshot(path=S + "08_importar_analisis.png")
            await pg.get_by_role("button", name="Importar", exact=True).tap(); await idle(pg, 2500)
            R["msg_importado"] = [l for l in (await pg.inner_text("body")).splitlines() if "registro(s) añadidos" in l][:1]
            await pg.get_by_role("button", name="Cerrar").tap(); await idle(pg, 2500)
            await pg.reload(); await idle(pg, 4500)
            R["tras_importar_y_recargar"] = await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.cat-grid'));return h?[...h.shadowRoot.querySelectorAll('.cat-card:not(.cat-add)')].map(c=>c.innerText.replace(/\\n/g,' | ').slice(0,160)):null})()")
            await pg.screenshot(path=S + "09_catalogo_tras_importar.png")
        finally:
            R["exc"] = await pg.locator('[data-testid="stException"]').count(); R["errs"] = errs[:4]
            print(json.dumps(R, indent=1, ensure_ascii=False)); await b.close()
asyncio.run(main())
