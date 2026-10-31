import asyncio, json, sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from pwlib import *
async def server_n(pg):
    async with pg.expect_download() as dl:
        await pg.locator('[role="dialog"]').get_by_role("button", name="Descargar CSV de la digitalización").click()
    d = await dl.value; txt = open(await d.path(), encoding="utf-8").read()
    return len([l for l in txt.splitlines() if l and not l.startswith("#")]) - 1
async def main():
    mode = sys.argv[1]
    async with async_playwright() as p:
        b,pg = await new_page(p)
        await open_digitizer(pg); await upload(pg, H+"02_dos_curvas.png")
        await pg.locator('[role="dialog"]').get_by_text("Rueda: zoom", exact=False).first.scroll_into_view_if_needed(); await pg.wait_for_timeout(400)
        q=min(await pg.evaluate(f"{DZ}.points()"), key=lambda r: abs(r["px"]-600)+abs(r["py"]-400))
        x,y = await pg.evaluate(f"{DZ}.toClient({q['px']},{q['py']})")
        c0 = await pg.evaluate(f"{DZ}.calls()"); i0 = await pg.evaluate(f"{DZ}.instance()")
        await pg.evaluate(f"{DZ}.view()")
        cx,cy = await pg.evaluate(f"{DZ}.toClient(600,400)"); await pg.mouse.move(cx,cy)
        for _ in range(3): await pg.mouse.wheel(0,-240); await pg.wait_for_timeout(100)
        v0 = await pg.evaluate(f"{DZ}.view()")
        q=min(await pg.evaluate(f"{DZ}.points()"), key=lambda r: abs(r["px"]-600)+abs(r["py"]-400))
        x,y = await pg.evaluate(f"{DZ}.toClient({q['px']},{q['py']})")
        if mode == "mouse":
            await pg.evaluate(f"{DZ}.setMode('delete')"); await pg.mouse.click(x,y)
        else:
            await pg.mouse.click(x,y); await pg.wait_for_timeout(500); await pg.keyboard.press("Delete")
        t=0
        while t<8000 and await pg.evaluate(f"{DZ}.calls()")==c0 and await pg.locator('[role=dialog]').count():
            await pg.wait_for_timeout(100); t+=100
        await pg.wait_for_timeout(600)
        ACT="(()=>{const a=document.activeElement; return a? a.tagName+'['+(a.getAttribute('aria-label')||'')+']':''})()"
        print(mode, "reinvocación:", t, "ms; misma instancia:", i0 == await pg.evaluate(f"{DZ}.instance()"),
              "; zoom conservado:", abs(v0["scale"] - (await pg.evaluate(f"{DZ}.view()"))["scale"]) < 1e-9,
              "; foco en lienzo:", await pg.evaluate(f"{DZ}.hasFocus()"), await pg.evaluate(ACT),
              "; lienzo", len(await pg.evaluate(f"{DZ}.points()")), flush=True)
        await pg.wait_for_timeout(500)
        print(mode, "servidor:", await server_n(pg), flush=True)
        await b.close()
asyncio.run(main())
