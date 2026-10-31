import asyncio, json, sys, io
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent)); sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'tests'))
from pwlib import *
from digitizer_synth import render
OUT=str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'docs' / 'capturas' / 'digitalizador') + '/'
R={}
async def main():
    png,_,_ = render(axes=False); open("/tmp/sin_ejes.png","wb").write(png)
    open("/tmp/roto.png","wb").write(b"\x89PNG\r\n\x1a\n"+b"basura"*200)
    async with async_playwright() as p:
        b,pg = await new_page(p)
        await open_digitizer(pg)
        # imagen corrupta
        await pg.locator('[role="dialog"] input[type="file"]').first.set_input_files("/tmp/roto.png"); await idle(pg,2500)
        t = await pg.locator('[role="dialog"]').inner_text()
        R["corrupta"] = [l for l in t.splitlines() if "rechazada" in l][:1]
        await pg.screenshot(path=OUT+"11_imagen_corrupta.png")
        # sin ejes: subir sobre el mismo uploader (no hay borrador)
        await pg.locator('[role="dialog"] input[type="file"]').first.set_input_files("/tmp/sin_ejes.png")
        for _ in range(40):
            await pg.wait_for_timeout(500)
            if await pg.evaluate("!!(window.__pmlDigitizer && window.__pmlDigitizer.dz)"): break
        await idle(pg,1500)
        t = await pg.locator('[role="dialog"]').inner_text()
        R["sin_ejes_estado"] = [l for l in t.splitlines() if "REQUIERE" in l][:1]
        R["sin_ejes_confirmar_bloqueado"] = await pg.locator('[role="dialog"]').get_by_role("button", name="Confirmar y añadir curva").is_disabled()
        R["sin_ejes_anclas"] = await pg.evaluate(f"{DZ}.anchors()")
        R["sin_ejes_puntos"] = len(await pg.evaluate(f"{DZ}.points()"))
        await pg.screenshot(path=OUT+"12_imagen_sin_ejes.png")
        await pg.locator('[role="dialog"]').get_by_role("button", name="Cancelar", exact=True).click(); await idle(pg,2000)
        # dos curvas: elegir el otro candidato
        await pg.get_by_role("button", name="Abrir digitalizador").click(); await idle(pg,1500)
        await upload(pg, H+"02_dos_curvas.png")
        p0 = await pg.evaluate(f"{DZ}.points()")
        await pg.locator('[role="dialog"] [data-testid="stSelectbox"]').first.click(); await pg.wait_for_timeout(500)
        opts = await pg.get_by_role("option").all_inner_texts(); R["candidatos"]=opts
        await pg.get_by_role("option", name=[o for o in opts if "C2" in o][0]).click(); await idle(pg,1500)
        p1 = await pg.evaluate(f"{DZ}.points()")
        R["dos_curvas_y_medio_antes_despues"] = (round(sum(q["py"] for q in p0)/len(p0),1), round(sum(q["py"] for q in p1)/len(p1),1), len(p1))
        await pg.screenshot(path=OUT+"10_dos_curvas_seleccion.png")
        await pg.locator('[role="dialog"]').get_by_role("button", name="Cancelar", exact=True).click(); await idle(pg,2000)
        # figura real OTEKON con el botón de ejemplo
        await pg.get_by_role("button", name="Abrir digitalizador").click(); await idle(pg,1500)
        await pg.locator('[role="dialog"]').get_by_role("button", name="Figura publicada OTEKON Fig. 3").click()
        for _ in range(40):
            await pg.wait_for_timeout(500)
            if await pg.evaluate("!!(window.__pmlDigitizer && window.__pmlDigitizer.dz)"): break
        await idle(pg,2000)
        for lab,v in [("X1: valor","0"),("X2: valor","1,2"),("Y1: valor","0,5"),("Y2: valor","1,1")]:
            await fill(pg, lab, v)
        t = await pg.locator('[role="dialog"]').inner_text()
        R["otekon_estado"] = [l for l in t.splitlines() if "REVISION" in l][:1]
        R["otekon_avisos"] = [l for l in t.splitlines() if "paneles" in l][:1]
        await pg.screenshot(path=OUT+"09_figura_real_otekon.png")
        R["errs"]=pg._errs[:5]; R["exc"]=await pg.locator('[data-testid="stException"]').count()
        await b.close()
    print(json.dumps(R, indent=1, ensure_ascii=False, default=str))
asyncio.run(main())
