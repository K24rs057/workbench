"""確認用:各場面の終わり近くの1コマを撮る(先に python build.py --timing)。

python stills.py            … 全場面 → out/stills/sNNN.jpg
python stills.py 12.5 30    … 指定した秒
"""
import json
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
OUT = HERE / "out" / "stills"
OUT.mkdir(parents=True, exist_ok=True)
timing = json.loads((HERE / "out" / "timing.json").read_text(encoding="utf-8"))
times = [float(x) for x in sys.argv[1:]] or [s["end"] - 1.2 for s in timing["scenes"]]

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1080, "height": 1920})
    page.goto((HERE / "video.html").as_uri())
    page.wait_for_function("window.READY === true")
    for i, t in enumerate(times):
        page.evaluate(f"window.render({t})")
        page.screenshot(path=str(OUT / f"s{i:03d}.jpg"), type="jpeg", quality=80)
    b.close()
print(len(times), "stills in", OUT)
