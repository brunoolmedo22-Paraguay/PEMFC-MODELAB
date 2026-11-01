import asyncio, json, io, zipfile, os
from playwright.async_api import async_playwright
import pathlib
U=os.environ.get("PML_URL","http://127.0.0.1:8501"); S=os.environ.get("PML_SHOTS", str(pathlib.Path(__file__).resolve().parents[2]/"docs"/"capturas"/"v0.4.0")+"/"); os.makedirs(S, exist_ok=True); R={}
PROF=str(pathlib.Path(__file__).resolve().parents[2]/"tests"/"fixtures"/"compat"/"profile_v020.json")
async def idle(pg, ms=900):
    await pg.wait_for_timeout(ms)
    for _ in range(240):
        if await pg.locator('[data-testid="stStatusWidget"]').count()==0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(500)
async def body(pg): return await pg.inner_text("body")
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(args=["--no-proxy-server"]); ctx=await b.new_context(viewport={"width":1440,"height":1000}, accept_downloads=True)
        pg=await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        try:
            await pg.goto(U+"/?view=catalog"); await idle(pg,4000)
            await pg.get_by_text("Proyectos, copias de seguridad y compatibilidad").click(); await idle(pg)
            await pg.locator('input[type="file"][accept*="json"]').first.set_input_files(PROF); await idle(pg,1500)
            await pg.get_by_role("button", name="Migrar como dispositivo nuevo").click(); await idle(pg,3000)
            R["migrado"]=[l for l in (await body(pg)).splitlines() if "migr" in l.lower()][:1]
            await pg.wait_for_timeout(2500)
            await pg.goto(U+"/?view=motor2"); await idle(pg,5000)           # sesión nueva: datos desde IndexedDB
            t=await body(pg); R["lab"]="Motor 2 — Laboratorio Virtual" in t; R["perfil_tarjeta"]="AJUSTADO_A_CURVA" in t
            R["tarjetas_futuras"]=t.count("PRÓXIMAMENTE")
            await pg.screenshot(path=S+"01_motor2_laboratorio.png", full_page=True)
            await pg.get_by_role("button", name="Abrir bancada").nth(1).click(); await idle(pg,2500)
            await pg.get_by_role("button", name="▶ Ejecutar experimento").click(); await idle(pg,6000)
            t=await body(pg); R["carga_kpis"]=[l for l in t.splitlines() if l.startswith("Energía demandada") or l.startswith("Energía no atendida")][:2]
            R["carga_graficos"]=await pg.locator('[data-testid="stPlotlyChart"]').count()
            await pg.screenshot(path=S+"02_bancada_carga.png", full_page=True)
            await pg.get_by_role("button", name="Preparar exportaciones (ZIP, PDF, CSV, Excel, JSON, PNG, SVG)").click(); await idle(pg,9000)
            for lab in ("ZIP completo","Informe PDF"):
                async with pg.expect_download() as dl: await pg.get_by_role("button", name=lab, exact=True).click()
                d=await dl.value; data=open(await d.path(),"rb").read(); R[f"dl_{lab}"]=(d.suggested_filename,len(data))
                if lab=="ZIP completo": R["zip"]=sorted(zipfile.ZipFile(io.BytesIO(data)).namelist())[:14]
                else: R["pdf_ok"]=data[:5]==b"%PDF-"; pass
                await idle(pg,800)
            await pg.get_by_role("button", name="← Bancadas").click(); await idle(pg,2000)
            await pg.get_by_role("button", name="Abrir bancada").nth(0).click(); await idle(pg,2000)
            await pg.get_by_role("button", name="▶ Ejecutar experimento").click(); await idle(pg,5000)
            t=await body(pg); R["repro"]=[l for l in t.splitlines() if "Consistente con el Motor 1" in l][:1]
            await pg.screenshot(path=S+"03_bancada_reproduccion.png", full_page=True)
            await pg.reload(); await idle(pg,5000)
            await pg.get_by_text("Historial", exact=True).click(); await idle(pg,2500)
            t=await body(pg); R["historial_tras_recarga"]=t.count("Seguimiento de carga ·")>0 and t.count("Reproducción experimental ·")>0
            await pg.screenshot(path=S+"04_historial.png", full_page=True)
            await pg.set_viewport_size({"width":1024,"height":768}); await idle(pg,1000)
            await pg.get_by_text("Bancadas", exact=True).click(); await idle(pg,1500)
            await pg.screenshot(path=S+"05_tablet_bancadas.png")
            box=await pg.get_by_role("button", name="Abrir bancada").nth(3).bounding_box()
            await pg.mouse.click(box["x"]+box["width"]/2, box["y"]+box["height"]/2); await idle(pg,2000)
            R["tablet_optimizacion"]="Optimización operacional" in await body(pg) and "Objetivo y restricciones".upper() in (await body(pg)).upper()
            await pg.screenshot(path=S+"06_tablet_optimizacion.png")
        finally:
            R["exc"]=await pg.locator('[data-testid="stException"]').count(); R["errs"]=errs[:4]
            print(json.dumps(R, ensure_ascii=False, indent=1)); await b.close()
asyncio.run(main())
