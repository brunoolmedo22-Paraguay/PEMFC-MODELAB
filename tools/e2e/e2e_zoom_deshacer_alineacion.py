import asyncio, json, sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from pwlib import *
from PIL import Image
R={}
async def main():
    async with async_playwright() as p:
        b,pg = await new_page(p)
        await open_digitizer(pg); await upload(pg, H+"01_curva_simple.png")
        for lab,v in [("X1: valor","0"),("X2: valor","1.5"),("Y1: valor","0.4"),("Y2: valor","1.1")]:
            await fill(pg, lab, v)
        # --- arrastrar 3 puntos
        before = {q["id"]:(q["px"],q["py"]) for q in await pg.evaluate(f"{DZ}.points()")}
        for pid,dy in [(8,-25),(20,30),(32,-20)]:
            await drag_point(pg, pid, 0, dy)
        after = {q["id"]:(q["px"],q["py"],q["mod"]) for q in await pg.evaluate(f"{DZ}.points()")}
        R["drag"] = {pid: {"antes":before[pid],"despues":after[pid][:2],"mod":after[pid][2]} for pid in (8,20,32)}
        # --- deshacer uno y rehacer (botones del lienzo vía teclado Ctrl+Z / Ctrl+Y)
        old=await rev(pg); await pg.locator('[role="dialog"]').get_by_role("button", name="Deshacer").click(); await wait_rev(pg,old); await idle(pg)
        u = {q["id"]:(q["px"],q["py"]) for q in await pg.evaluate(f"{DZ}.points()")}
        R["undo_32_restaurado"] = abs(u[32][1]-before[32][1])<1e-6 and abs(u[20][1]-after[20][1])<1e-6
        old=await rev(pg); await pg.locator('[role="dialog"]').get_by_role("button", name="Rehacer").click(); await wait_rev(pg,old); await idle(pg)
        r_ = {q["id"]:(q["px"],q["py"]) for q in await pg.evaluate(f"{DZ}.points()")}
        R["redo_32_reaplicado"] = abs(r_[32][1]-after[32][1])<1e-6
        # --- zoom y comprobación de alineación imagen/overlay
        cx,cy = await pg.evaluate(f"{DZ}.toClient(600,400)")
        await pg.mouse.move(cx,cy)
        for _ in range(6): await pg.mouse.wheel(0,-240); await pg.wait_for_timeout(120)
        await pg.wait_for_timeout(600)
        v = await pg.evaluate(f"{DZ}.view()"); R["zoom_scale"]=v["scale"]
        await pg.screenshot(path="/tmp/t_zoom.png"); await pg.screenshot(path=str(__import__('pathlib').Path(__file__).resolve().parents[2] / 'docs' / 'capturas' / 'digitalizador' / '04b_zoom_alineacion.png'))
        im = Image.open("/tmp/t_zoom.png").convert("RGB")
        def px(x,y):
            x,y=round(x),round(y)
            return im.getpixel((x,y)) if 0<=x<im.width and 0<=y<im.height else None
        gx,gy = await pg.evaluate(f"{DZ}.toClient(522.5, 380)")
        R["gridline_x522_en_pantalla"] = px(gx,gy); R["vecino_+6px_imagen"] = px(*(await pg.evaluate(f"{DZ}.toClient(528.5, 380)")))
        hx,hy = await pg.evaluate(f"{DZ}.toClient(560, 420.5)")
        R["gridline_y420_en_pantalla"] = px(hx,hy); R["vecino_y+6"] = px(*(await pg.evaluate(f"{DZ}.toClient(560, 426.5)")))
        pts = await pg.evaluate(f"{DZ}.points()")
        q = min(pts, key=lambda q: abs(q["px"]-600))
        R["punto_cercano"]=(q["id"],round(q["px"],2),round(q["py"],2)); R["color_marcador"]=px(*(await pg.evaluate(f"{DZ}.toClient({q['px']},{q['py']})")))
        # pan
        await pg.locator('[role="dialog"]').get_by_role("button", name="Ajustar").click(); await pg.wait_for_timeout(400)
        await dialog_shot(pg, "/tmp/t_edited.png")
        R["errs"]=pg._errs[:5]; R["exc"]=await pg.locator('[data-testid="stException"]').count()
        await b.close()
    print(json.dumps(R, indent=1, default=str))
asyncio.run(main())
