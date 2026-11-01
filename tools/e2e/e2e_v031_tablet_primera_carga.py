import asyncio, json
from playwright.async_api import async_playwright
import os, pathlib
U=os.environ.get("PML_URL","http://127.0.0.1:8501"); FX=str(pathlib.Path(__file__).resolve().parents[2]/"tests"/"fixtures"/"digitizer"/"01_curva_simple.png"); R={}
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(args=["--no-proxy-server"])
        for run in (1,2):   # dos navegadores nuevos (proceso del servidor recién arrancado en el 1.º)
            ctx=await b.new_context(viewport={"width":1024,"height":768}, has_touch=True, is_mobile=False)
            pg=await ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
            await pg.goto(U+"/?view=digitizer"); await pg.wait_for_timeout(4000)
            await pg.locator('input[type="file"]').first.set_input_files(FX)
            ok=False
            for i in range(60):
                await pg.wait_for_timeout(500)
                st=await pg.evaluate("(()=>{const h=[...document.querySelectorAll('*')].find(e=>e.shadowRoot&&e.shadowRoot.querySelector('.pml-dz'));return h?h.shadowRoot.querySelector('.pml-dz').dataset.ready:null})()")
                if st=="1": ok=True; break
            t=await pg.inner_text("body")
            R[f"carga_unica_{run}"]={"lienzo_listo":ok,"segundos":(i+1)/2,"ejes_confiables":t.count("Reconocimiento confiable"),
                                     "error_visible":"No se pudo procesar" in t or "rechazada" in t,"errs":errs[:2]}
            await pg.screenshot(path=f""+str(pathlib.Path(__file__).resolve().parents[2]/"docs"/"capturas"/"v0.3.1")+"/40_tablet_primera_carga_{run}.png"); await ctx.close()
        await b.close()
    print(json.dumps(R, ensure_ascii=False))
asyncio.run(main())
