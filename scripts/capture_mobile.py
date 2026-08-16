from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path("/Users/rohithnaidualla/Desktop/FolioSpace/scripts/mobile_shots")
OUT.mkdir(parents=True, exist_ok=True)

PAGES = [
    ("landing", "http://127.0.0.1:8780/"),
    ("features", "http://127.0.0.1:8780/features"),
    ("space-community", "http://127.0.0.1:8780/space-community"),
    ("privacy", "http://127.0.0.1:8780/privacy"),
    ("terms", "http://127.0.0.1:8780/terms"),
]

VIEWPORTS = [
    ("iphone-se", 375, 667),
    ("pixel-7", 412, 915),
    ("iphone-15-pro-max", 430, 932),
    ("tablet-portrait", 768, 1024),
]

with sync_playwright() as p:
    browser = p.chromium.launch()
    for vp_name, w, h in VIEWPORTS:
        ctx = browser.new_context(
            viewport={"width": w, "height": h},
            device_scale_factor=2,
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            is_mobile=True,
            has_touch=True,
        )
        for page_name, url in PAGES:
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=15000)
            except Exception as e:
                page.goto(url, wait_until="load", timeout=15000)
            page.wait_for_timeout(3500)
            full = OUT / f"{page_name}_{vp_name}_full.png"
            above = OUT / f"{page_name}_{vp_name}_fold.png"
            page.screenshot(path=str(full), full_page=True)
            page.screenshot(path=str(above), full_page=False)
            print(f"{vp_name} {page_name}: {full.stat().st_size//1024}KB")
            page.close()
        ctx.close()
    browser.close()
print("done")