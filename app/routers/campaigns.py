"""Campaign management — create, join, lobby."""

import secrets
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.templating import render as _render

router = APIRouter()


@router.get("/join")
async def join_campaign_page(request: Request, code: str = ""):
    """Join a campaign by invite code — redirects to lobby, or show join form."""
    if code:
        return RedirectResponse(f"/campaigns/{code.strip()}", status_code=303)
    return _render(request, "campaign_join.html")


def _generate_invite_code() -> str:
    return secrets.token_hex(4)  # 8-char hex code


@router.get("/create", response_class=HTMLResponse)
async def create_campaign_page(request: Request):
    return _render(request, "campaign_create.html")


@router.post("/create")
async def create_campaign(
    request: Request,
    name: str = Form(...),
    dm_name: str = Form(...),
):
    invite_code = _generate_invite_code()
    with get_db() as db:
        # Ensure unique
        while True:
            existing = db.execute(
                "SELECT id FROM campaigns WHERE invite_code = ?", (invite_code,)
            ).fetchone()
            if not existing:
                break
            invite_code = _generate_invite_code()

        db.execute(
            "INSERT INTO campaigns (name, dm_name, invite_code) VALUES (?, ?, ?)",
            (name, dm_name, invite_code),
        )
    return RedirectResponse(f"/campaigns/{invite_code}", status_code=303)


@router.get("/{invite_code}", response_class=HTMLResponse)
async def campaign_lobby(request: Request, invite_code: str):
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Campaign not found</h1>", status_code=404)

        characters = db.execute(
            "SELECT * FROM characters WHERE campaign_id = ? ORDER BY created_at",
            (campaign["id"],),
        ).fetchall()

        # Also get unassigned characters for the "bring existing" option
        unassigned = db.execute(
            "SELECT * FROM characters WHERE campaign_id IS NULL ORDER BY created_at DESC"
        ).fetchall()

    return _render(
        request,
        "campaign_lobby.html",
        campaign=campaign,
        characters=characters,
        unassigned=unassigned,
    )


@router.post("/{invite_code}/join")
async def join_campaign(invite_code: str, character_id: int = Form(...)):
    """Bring an existing standalone character into this campaign."""
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Campaign not found</h1>", status_code=404)

        char = db.execute("SELECT * FROM characters WHERE id = ?", (character_id,)).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        # Attach to campaign
        db.execute(
            "UPDATE characters SET campaign_id = ? WHERE id = ?",
            (campaign["id"], character_id),
        )

        # Auto-create a token
        db.execute(
            "INSERT INTO map_tokens (campaign_id, character_id, name) VALUES (?, ?, ?)",
            (campaign["id"], character_id, char["character_name"]),
        )

    return RedirectResponse(f"/campaigns/{invite_code}", status_code=303)


@router.get("/{invite_code}/api")
async def campaign_api(invite_code: str):
    """JSON API for the frontend to poll campaign data."""
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return {"error": "not found"}

        characters = db.execute(
            "SELECT * FROM characters WHERE campaign_id = ? ORDER BY created_at",
            (campaign["id"],),
        ).fetchall()

        tokens = db.execute(
            "SELECT * FROM map_tokens WHERE campaign_id = ?", (campaign["id"],)
        ).fetchall()

        map_img = db.execute(
            "SELECT * FROM map_images WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign["id"],),
        ).fetchone()

        rolls = db.execute(
            "SELECT * FROM dice_rolls WHERE campaign_id = ? ORDER BY rolled_at DESC LIMIT 30",
            (campaign["id"],),
        ).fetchall()

        messages = db.execute(
            "SELECT * FROM chat_messages WHERE campaign_id = ? ORDER BY sent_at ASC LIMIT 100",
            (campaign["id"],),
        ).fetchall()

    def row_to_dict(r):
        return dict(r)

    return {
        "campaign": row_to_dict(campaign),
        "characters": [row_to_dict(c) for c in characters],
        "tokens": [row_to_dict(t) for t in tokens],
        "map_image": row_to_dict(map_img) if map_img else None,
        "rolls": [row_to_dict(r) for r in rolls],
        "messages": [row_to_dict(m) for m in messages],
    }
