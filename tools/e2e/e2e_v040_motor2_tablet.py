import asyncio, json, os
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
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(args=["--no-proxy-server"]); ctx=await b.new_context(viewport={"width":1024,"height":768}, has_touch=True)
        pg=await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        await pg.goto(U+"/?view=catalog"); await idle(pg,4000)
        await pg.get_by_text("Proyectos, copias de seguridad y compatibilidad").tap(); await idle(pg)
        await pg.locator('input[type="file"][accept*="json"]').first.set_input_files(PROF); await idle(pg,1500)
        await pg.get_by_role("button", name="Migrar como dispositivo nuevo").tap(); await idle(pg,3000)
        top=pg.locator(".tb-link", has_text="Motor 2") if await pg.locator(".tb-link").count() else None
        await pg.goto(U+"/?view=motor2"); await idle(pg,5000)
        btn=pg.get_by_role("button", name="Abrir bancada").nth(3)
        await btn.scroll_into_view_if_needed(); await idle(pg,500); await btn.tap(); await idle(pg,2500)
        t=await pg.inner_text("body"); R["tablet_bancada_04"]="BANCADA 04" in t and "Optimización operacional" in t
        sel=pg.get_by_role("button", name="▶ Ejecutar experimento")
        await sel.scroll_into_view_if_needed(); await sel.tap(); await idle(pg,4000)
        t=await pg.inner_text("body"); R["tablet_resultado"]="Punto seleccionado" in t or "Densidad de corriente" in t
        await pg.screenshot(path=S+"06_tablet_optimizacion.png", full_page=True)
        R["version"]=await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.tb-ver, [class*=ver]'));return h?h.shadowRoot.querySelector('.tb-ver, [class*=ver]').textContent:null})()")
        R["exc"]=await pg.locator('[data-testid="stException"]').count(); R["errs"]=errs[:3]
        print(json.dumps(R, ensure_ascii=False)); await b.close()
asyncio.run(main())
