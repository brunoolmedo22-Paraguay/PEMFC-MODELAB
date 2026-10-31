import asyncio, json, os, pathlib
from playwright.async_api import async_playwright
URL = os.environ.get("PML_URL", "http://127.0.0.1:8501")
ROOT = pathlib.Path(__file__).resolve().parents[2]
H = str(ROOT / "tests" / "fixtures" / "digitizer") + "/"
DZ="window.__pmlDigitizer.dz"
async def new_page(p):
    b = await p.chromium.launch(args=["--no-proxy-server"])
    pg = await b.new_page(viewport={"width":1440,"height":1000})
    pg._errs=[]
    pg.on("pageerror", lambda e: pg._errs.append(str(e)))
    pg.on("console", lambda m: pg._errs.append("console:"+m.text) if m.type=="error" else None)
    await pg.goto(URL); await pg.wait_for_timeout(4000)
    return b, pg
async def rev(pg): return await pg.evaluate(f"{DZ}.rev()")
async def wait_rev(pg, old, t=15000):
    for _ in range(t//250):
        await pg.wait_for_timeout(250)
        try:
            if await rev(pg) != old: 
                await pg.wait_for_timeout(500); return True
        except Exception: pass
    return False
async def idle(pg, ms=800):
    await pg.wait_for_timeout(ms)
    for _ in range(80):
        if await pg.locator('[data-testid="stStatusWidget"]').count()==0: break
        await pg.wait_for_timeout(250)
    await pg.wait_for_timeout(300)
async def open_digitizer(pg):
    await pg.get_by_text("Imagen de una curva").click(); await idle(pg)
    await pg.get_by_role("button", name="Abrir digitalizador").click(); await idle(pg,1500)
async def upload(pg, path):
    await pg.locator('[role="dialog"] input[type="file"]').first.set_input_files(path)
    for _ in range(60):
        await pg.wait_for_timeout(500)
        if await pg.evaluate("!!(window.__pmlDigitizer && window.__pmlDigitizer.dz)"): break
    await idle(pg, 1500)
async def fill(pg, label, value):
    loc = pg.locator('[role="dialog"]').get_by_label(label, exact=True)
    await loc.fill(str(value)); await loc.press("Enter"); await idle(pg, 900)
async def drag_point(pg, pid, dx, dy):
    try:
        await pg.locator('[role="dialog"]').get_by_text("Rueda: zoom", exact=False).first.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    await pg.wait_for_timeout(300)
    pts = await pg.evaluate(f"{DZ}.points()")
    p = next(q for q in pts if q["id"]==pid)
    x0,y0 = await pg.evaluate(f"{DZ}.toClient({p['px']},{p['py']})")
    old = await rev(pg)
    await pg.mouse.move(x0,y0); await pg.mouse.down()
    for k in range(1,9): await pg.mouse.move(x0+dx*k/8, y0+dy*k/8)
    await pg.mouse.up(); await wait_rev(pg, old); await idle(pg)
    return p
async def dialog_shot(pg, path, locator_text=None):
    if locator_text:
        await pg.locator('[role="dialog"]').get_by_text(locator_text, exact=False).first.scroll_into_view_if_needed()
        await pg.wait_for_timeout(400)
    await pg.screenshot(path=path)
async def scroll_to(pg, text):
    try:
        await pg.locator('[role="dialog"]').get_by_text(text, exact=False).first.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    await pg.wait_for_timeout(400)
async def edit_cell(pg, grid_index, row, col_frac, value, header=48, row_h=32):
    """Abre el editor de la celda (fila 1-based) con doble clic, espera al editor real y escribe."""
    grid = pg.locator('[role="dialog"] [data-testid="stDataFrame"]').nth(grid_index)
    await grid.scroll_into_view_if_needed(); await pg.wait_for_timeout(600)
    ed = pg.locator("textarea.gdg-input, input.gdg-input, [data-testid='glide-cell-editor'] input, #portal textarea")
    for attempt in range(4):
        bb = await grid.bounding_box()
        x, y = bb["x"] + col_frac * bb["width"], bb["y"] + header + (row - 1) * row_h
        await pg.mouse.click(x, y); await pg.wait_for_timeout(250)
        await pg.mouse.dblclick(x, y)
        try:
            await ed.first.wait_for(state="visible", timeout=2500)
            await ed.first.fill(str(value)); await pg.keyboard.press("Enter")
            await idle(pg, 2500)
            return attempt + 1
        except Exception:
            await pg.keyboard.press("Escape"); await pg.wait_for_timeout(400)
    return 0
