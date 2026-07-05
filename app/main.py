"""CritForge — Custom D&D Virtual Tabletop"""

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from app.templating import render

app = FastAPI(title="CritForge", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return render(request, "index.html")


# Routers
from app.routers import campaigns, characters, game

app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(characters.router, prefix="/characters", tags=["characters"])
app.include_router(game.router, prefix="/game", tags=["game"])

# Static files — served as route for Render compatibility
_STATIC_DIR = Path(__file__).resolve().parent / "static"

@app.get("/static/{filename:path}")
async def serve_static(filename: str):
    from fastapi.responses import FileResponse
    filepath = _STATIC_DIR / filename
    if not filepath.exists():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("", status_code=404)
    return FileResponse(str(filepath))
