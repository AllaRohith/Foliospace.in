from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import os

from app.routers import waitlist

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="FolioSpace",
    description="A portfolio for everyone. Built for WhatsApp, LinkedIn, and the Indian web.",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(waitlist.router)


@app.get("/")
async def landing(request: Request):
    return templates.TemplateResponse(
        request,
        "landing.html",
        {
            "site_name": "FolioSpace",
            "tagline": "Your story. One link. Done.",
            "page_title": "FolioSpace — Your portfolio. Your link. Done.",
            "description": "Stop sending CVs. Send a link. FolioSpace turns your work into a beautiful page that shines on WhatsApp and LinkedIn. ₹150 setup, ₹99/month.",
        },
    )


@app.get("/robots.txt")
async def robots():
    from fastapi.responses import PlainTextResponse
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    content = (
        "User-agent: *\n"
        "Allow: /\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(content=content, media_type="text/plain")


@app.get("/sitemap.xml")
async def sitemap():
    from fastapi.responses import PlainTextResponse
    base = os.getenv("PUBLIC_BASE_URL", "https://foliospace.in").rstrip("/")
    today = "2026-08-11"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{base}/</loc><lastmod>{today}</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>\n'
        '</urlset>\n'
    )
    return PlainTextResponse(content=body, media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
