import asyncio, json, sys, zipfile, io
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from pwlib import *
OUT=str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'docs' / 'capturas' / 'digitalizador') + '/'
R={}
async def tab(pg, name):
    await pg.get_by_role("tab", name=name).first.click(); await idle(pg)
async def main():
    async with async_playwright() as p:
        b,pg = await new_page(p)
        # ---- 0. dataset previo + ajuste vigente (OTEKON)
        await pg.get_by_text("Ejemplos documentados").click(); await idle(pg)
        await pg.get_by_role("button", name="Cargar: OTEKON Fig. 3 — 4 curvas digitalizadas").click(); await idle(pg,2000)
        await tab(pg,"2. Configurar identificación")
        await pg.get_by_role("button", name="Preset OTEKON (9 parámetros, reproducción del artículo)").click(); await idle(pg)
        await tab(pg,"3. Calibrar")
        await pg.get_by_role("button", name="Ejecutar identificación").click(); await idle(pg,4000)
        await tab(pg,"5. Exportar perfil")
        R["perfil_antes"] = [l for l in (await pg.inner_text("body")).splitlines() if "Perfil pml-" in l][:1]
        await tab(pg,"1. Importar curva")
        # ---- 1. abrir, cargar → overlay automático (capturas 1 y 2)
        await open_digitizer(pg)
        await pg.screenshot(path=OUT+"00_modal_vacio.png")
        await upload(pg, H+"01_curva_simple.png")
        await pg.screenshot(path=OUT+"01_modal_al_cargar.png")
        await scroll_to(pg, "Sin calibración no se muestran amperios")
        await pg.screenshot(path=OUT+"02_deteccion_automatica_en_pixeles.png")
        # ---- 2. Cancelar: el conjunto y el ajuste siguen intactos
        await pg.locator('[role="dialog"]').get_by_role("button", name="Cancelar", exact=True).click(); await idle(pg,2000)
        body = await pg.inner_text("body")
        R["tras_cancelar_mensaje"] = "Digitalización cancelada" in body
        await tab(pg,"5. Exportar perfil")
        R["perfil_tras_cancelar"] = [l for l in (await pg.inner_text("body")).splitlines() if "Perfil pml-" in l][:1]
        await tab(pg,"1. Importar curva")
        R["curvas_tras_cancelar"] = (await pg.inner_text("body")).count("pressao_") + (await pg.inner_text("body")).count("tensao_")
        # ---- 3. Reabrir, calibrar y corregir anclas
        await pg.get_by_role("button", name="Abrir digitalizador").click(); await idle(pg,1500)
        await upload(pg, H+"01_curva_simple.png")
        for lab,v in [("X1: valor","0"),("X2: valor","1.5"),("Y1: valor","0.4"),("Y2: valor","1.1")]:
            await fill(pg, lab, v)
        # corregir Y2 con el lienzo: modo Y2 y clic junto al tick superior (se ajusta al tick detectado)
        await pg.evaluate(f"{DZ}.setMode('Y2')")
        x,y = await pg.evaluate(f"{DZ}.toClient(150.5, 93.0)")
        old=await rev(pg); await pg.mouse.click(x,y); await wait_rev(pg,old); await idle(pg)
        R["Y2_tras_clic"] = (await pg.evaluate(f"{DZ}.anchors()"))["Y2"]
        # corregir X1 escribiendo la posición del manifiesto
        await fill(pg, "X1: px", "150")
        R["X1_tras_texto"] = (await pg.evaluate(f"{DZ}.anchors()"))["X1"]
        await pg.evaluate(f"{DZ}.setMode('select')")
        await pg.screenshot(path=OUT+"03_anclas_corregidas.png")
        # ---- 4. edición del trazo
        for pid,dy in [(8,-25),(20,30)]:
            await drag_point(pg, pid, 0, dy)
        await pg.evaluate(f"{DZ}.setMode('add')")
        x,y = await pg.evaluate(f"{DZ}.toClient(1060, 650)")
        old=await rev(pg); await pg.mouse.click(x,y); await wait_rev(pg,old); await idle(pg)
        await pg.evaluate(f"{DZ}.setMode('select')")
        old=await rev(pg); await pg.locator('[role="dialog"]').get_by_role("button", name="Deshacer").click(); await wait_rev(pg,old); await idle(pg)
        old=await rev(pg); await pg.locator('[role="dialog"]').get_by_role("button", name="Deshacer").click(); await wait_rev(pg,old); await idle(pg)
        R["n_puntos_tras_editar"] = len(await pg.evaluate(f"{DZ}.points()"))
        await pg.screenshot(path=OUT+"04_edicion_de_curva.png")
        # ---- 5. tabla física: editar V del punto (fila 3) a 0.9
        grid = pg.locator('[role="dialog"] [data-testid="stDataFrame"]').nth(1)
        await grid.scroll_into_view_if_needed(); await pg.wait_for_timeout(500)
        bb = await grid.bounding_box()
        R["intentos_editor"] = await edit_cell(pg, 1, 3, 0.555, "0.9")
        pts = await pg.evaluate(f"{DZ}.points()")
        R["punto3_tras_tabla"] = next((q for q in pts if q["id"]==3), None)
        print("PARCIAL", json.dumps(R, ensure_ascii=False, default=str), flush=True)
        await grid.scroll_into_view_if_needed(); await pg.wait_for_timeout(400)
        await pg.screenshot(path=OUT+"05_tabla_fisica.png")
        # ---- 6. metadatos y confirmación
        await pg.locator('[role="dialog"]').get_by_role("tab", name="Condiciones y metadatos").click(); await idle(pg)
        await fill(pg, "Identificador de la curva *", "fixture01_digitalizada")
        await fill(pg, "Temperatura *", "343.15")
        await fill(pg, "Presión de cátodo *", "1.5")
        await fill(pg, "Fuente (artículo, figura)", "Fixture sintético 01 del handoff (NO experimental)")
        btn = pg.locator('[role="dialog"]').get_by_role("button", name="Confirmar y añadir curva")
        await btn.scroll_into_view_if_needed()
        await pg.screenshot(path=OUT+"05b_antes_de_confirmar.png")
        await btn.click(); await idle(pg,3000)
        R["dialog_abierto_tras_confirmar"] = await pg.locator('[role="dialog"]').count()
        body = await pg.inner_text("body")
        R["mensaje_confirmado"] = [l for l in body.splitlines() if "añadida" in l][:1]
        await pg.get_by_text("Conjunto de curvas actual").scroll_into_view_if_needed(); await pg.wait_for_timeout(500)
        await pg.screenshot(path=OUT+"06_importacion_confirmada.png")
        R["fila_digitalizada"] = [l for l in body.splitlines() if "fixture01_digitalizada" in l][:2]
        # ---- 7. Motor 1 con la curva digitalizada incluida; exportar ZIP
        await tab(pg,"2. Configurar identificación")
        await pg.get_by_role("button", name="Preset OTEKON (9 parámetros, reproducción del artículo)").click(); await idle(pg)
        await tab(pg,"3. Calibrar")
        await pg.get_by_role("button", name="Ejecutar identificación").click(); await idle(pg,6000)
        R["estado_ajuste"] = [l for l in (await pg.inner_text("body")).splitlines() if "AJUSTADO" in l or "INSUFICIENTE" in l or "NO_CONVERGIDO" in l][:2]
        await tab(pg,"4. Resultados"); await pg.wait_for_timeout(1500)
        await pg.screenshot(path=OUT+"07_resultados_con_curva_digitalizada.png")
        await tab(pg,"5. Exportar perfil")
        await pg.get_by_role("button", name="Preparar ZIP del experimento").click(); await idle(pg,6000)
        async with pg.expect_download() as dl:
            await pg.get_by_role("button", name="Descargar ZIP del experimento").click()
        d = await dl.value; path = await d.path()
        z = zipfile.ZipFile(path); names = z.namelist()
        R["zip_digitalizacion"] = [n for n in names if "01_curva_simple" in n]
        prof = json.loads(z.read([n for n in names if n.endswith("profile.json")][0]))
        ds = next(x for x in prof["datasets"] if x["curve_id"]=="fixture01_digitalizada")
        R["perfil_dataset"] = {"quality": ds["metadata"]["quality"], "source_file": ds["source_file"], "sha": ds["source_sha256"][:16],
                               "mapping_keys": sorted(ds["mapping"].keys()), "n": ds["n_points"], "provenance": ds["metadata"]["provenance"]}
        R["perfil_estado"] = prof["status"]["code"]; R["perfil_validacion"] = prof["validation"]["status"]
        R["perfil_bytes"] = len(z.read([n for n in names if n.endswith("profile.json")][0]))
        import shutil; shutil.copy(path, "/tmp/zip_experimento_con_digitalizada.zip")
        await pg.screenshot(path=OUT+"08_exportar.png")
        R["errs"]=pg._errs[:5]; R["exc"]=await pg.locator('[data-testid="stException"]').count()
        await b.close()
    print(json.dumps(R, indent=1, ensure_ascii=False, default=str))
asyncio.run(main())
