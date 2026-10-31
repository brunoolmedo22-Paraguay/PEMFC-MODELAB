import asyncio, json, sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from pwlib import *
R={}
async def click_img(pg, px, py):
    x,y = await pg.evaluate(f"{DZ}.toClient({px},{py})"); old=await rev(pg)
    await pg.mouse.click(x,y); await wait_rev(pg,old); await idle(pg)
async def drag_img(pg, a, b_, steps=10):
    x0,y0 = await pg.evaluate(f"{DZ}.toClient({a[0]},{a[1]})"); x1,y1 = await pg.evaluate(f"{DZ}.toClient({b_[0]},{b_[1]})")
    await pg.mouse.move(x0,y0); await pg.mouse.down()
    for k in range(1,steps+1): await pg.mouse.move(x0+(x1-x0)*k/steps, y0+(y1-y0)*k/steps)
    await pg.mouse.up()
async def main():
    async with async_playwright() as p:
        b,pg = await new_page(p)
        await open_digitizer(pg); await upload(pg, H+"02_dos_curvas.png")
        await pg.locator('[role="dialog"]').get_by_text("Rueda: zoom", exact=False).first.scroll_into_view_if_needed()
        pts = await pg.evaluate(f"{DZ}.points()"); n0=len(pts)
        # borrar en modo Borrar
        await pg.evaluate(f"{DZ}.setMode('delete')"); q=pts[10]
        await click_img(pg, q["px"], q["py"])
        R["borrar_modo"] = (n0, len(await pg.evaluate(f"{DZ}.points()")))
        # borrar con Supr: seleccionar en modo Mover y pulsar Delete
        await pg.evaluate(f"{DZ}.setMode('select')"); q=(await pg.evaluate(f"{DZ}.points()"))[5]
        x,y = await pg.evaluate(f"{DZ}.toClient({q['px']},{q['py']})"); await pg.mouse.click(x,y); await pg.wait_for_timeout(300)
        old=await rev(pg); await pg.keyboard.press("Delete"); await wait_rev(pg,old); await idle(pg)
        R["borrar_supr"] = len(await pg.evaluate(f"{DZ}.points()"))
        # Ctrl+Z desde el teclado del lienzo
        old=await rev(pg); await pg.keyboard.press("Control+z"); await wait_rev(pg,old); await idle(pg)
        R["ctrl_z"] = len(await pg.evaluate(f"{DZ}.points()"))
        # exclusión por recuadro: excluir los puntos con px < 300
        await pg.evaluate(f"{DZ}.setMode('exclude')"); old=await rev(pg)
        await drag_img(pg, (155, 95), (300, 664)); await wait_rev(pg,old); await idle(pg)
        pp = await pg.evaluate(f"{DZ}.points()")
        R["excluidos_recuadro"] = (sum(1 for q in pp if not q["inc"]), sum(1 for q in pp if q["px"]<=300))
        # desplazamiento (pan) con modo Mano: la vista cambia, los puntos no
        await pg.evaluate(f"{DZ}.setMode('pan')"); v0 = await pg.evaluate(f"{DZ}.view()"); r0 = await rev(pg)
        await drag_img(pg, (600,400), (500,350)); await pg.wait_for_timeout(500)
        R["dialogo_abierto_tras_pan"] = await pg.locator('[role="dialog"]').count()
        v1 = await pg.evaluate(f"{DZ}.view()")
        R["pan"] = {"dx_img": round(v1["ox"]-v0["ox"],2), "dy_img": round(v1["oy"]-v0["oy"],2), "rev_sin_cambio": r0 == await rev(pg)}
        await pg.locator('[role="dialog"]').get_by_role("button", name="Ajustar").click(); await pg.wait_for_timeout(400)
        # ROI: recuadro alrededor de la curva superior (roja) en su tramo final + reidentificar
        await pg.evaluate(f"{DZ}.setMode('roi')"); old=await rev(pg)
        await drag_img(pg, (600, 250), (1070, 520)); await wait_rev(pg,old); await idle(pg)
        old=await rev(pg)
        btn = pg.locator('[role="dialog"]').get_by_role("button", name="Identificar automáticamente")
        await btn.click(); await idle(pg,2000)
        yes = pg.locator('[role="dialog"]').get_by_role("button", name="Sí, reidentificar")
        R["pide_confirmacion_por_ediciones"] = await yes.count() > 0
        if await yes.count(): await yes.click(); await wait_rev(pg,old); await idle(pg,1500)
        pp = await pg.evaluate(f"{DZ}.points()")
        R["roi_puntos_px_rango"] = (round(min(q["px"] for q in pp),1), round(max(q["px"] for q in pp),1), len(pp))
        t = await pg.locator('[role="dialog"]').inner_text()
        R["candidatos_tras_roi"] = [l for l in t.splitlines() if l.startswith("C1:") or l.startswith("C2:")][:2]
        await pg.screenshot(path=str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'docs' / 'capturas' / 'digitalizador' / '13_roi_reidentificado.png'))
        R["errs"]=pg._errs[:5]; R["exc"]=await pg.locator('[data-testid="stException"]').count()
        await b.close()
    print(json.dumps(R, indent=1, ensure_ascii=False))
asyncio.run(main())
