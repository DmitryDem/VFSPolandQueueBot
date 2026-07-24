"""Вытягивает ключевые страницы сайта VFS (Польша/Беларусь) через Playwright."""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("vfs_dump")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://visa.vfsglobal.by/blr/ru/pol/"
PAGES = {
    "index": BASE + "index.html",
    "apply_visa": BASE + "apply-visa.html",
    "visa_type": BASE + "visa-type.html",
    "additional_services": BASE + "additional-services.html",
    "news": BASE + "news-page.html",
}
PDF_URL = BASE + "assets/pdf/Terms-and-tariffs.pdf"


async def grab(page, name: str, url: str) -> None:
    for attempt in range(3):
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:
            await page.wait_for_timeout(3000)
        await page.wait_for_timeout(9000)
        body = await page.inner_text("body")
        if len(body) > 600 and "Checking" not in body[:200]:
            (OUT / f"{name}.txt").write_text(f"URL: {url}\n\n{body}", encoding="utf-8")
            print(f"{name}: {len(body)} симв.")
            return
        print(f"{name}: попытка {attempt + 1} — {len(body)} симв., жду ещё...")
        await page.wait_for_timeout(7000)
    (OUT / f"{name}.txt").write_text(f"URL: {url}\n\nFAILED:\n{body}", encoding="utf-8")
    print(f"{name}: НЕ УДАЛОСЬ")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1400, "height": 900},
        )
        page = await ctx.new_page()
        for name, url in PAGES.items():
            await grab(page, name, url)

        # PDF с тарифами — качаем в контексте браузера (куки CF уже есть)
        try:
            resp = await ctx.request.get(PDF_URL)
            if resp.ok:
                (OUT / "tariffs.pdf").write_bytes(await resp.body())
                print(f"tariffs.pdf: {(OUT / 'tariffs.pdf').stat().st_size} байт")
            else:
                print(f"tariffs.pdf: HTTP {resp.status}")
        except Exception as e:
            print(f"tariffs.pdf: ошибка {e}")

        await browser.close()


asyncio.run(main())
