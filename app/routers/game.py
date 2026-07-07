"""Game table — the main VTT page with map, tokens, dice, chat, and video."""

import json
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from app.database import get_db
from app.templating import render as _render

router = APIRouter()

# Uploads directory
_UPLOADS = Path(__file__).resolve().parent.parent / "static" / "uploads"
_UPLOADS.mkdir(parents=True, exist_ok=True)


# ── In-memory connection registry ─────────────────────────────
# Maps campaign_id -> dict of {websocket: {"name": str, "is_dm": bool}}

class ConnectionManager:
    def __init__(self):
        self.rooms: dict[int, dict[WebSocket, dict]] = {}

    async def connect(self, campaign_id: int, ws: WebSocket, name: str, is_dm: bool):
        if campaign_id not in self.rooms:
            self.rooms[campaign_id] = {}
        self.rooms[campaign_id][ws] = {"name": name, "is_dm": is_dm}

    def disconnect(self, campaign_id: int, ws: WebSocket):
        if campaign_id in self.rooms:
            self.rooms[campaign_id].pop(ws, None)
            if not self.rooms[campaign_id]:
                del self.rooms[campaign_id]

    def get_info(self, campaign_id: int, ws: WebSocket) -> dict | None:
        return self.rooms.get(campaign_id, {}).get(ws)

    def is_dm(self, campaign_id: int, ws: WebSocket) -> bool:
        info = self.get_info(campaign_id, ws)
        return info["is_dm"] if info else False

    async def broadcast(self, campaign_id: int, message: dict, exclude: WebSocket | None = None):
        if campaign_id not in self.rooms:
            return
        dead = []
        for ws in self.rooms[campaign_id]:
            if ws == exclude:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(campaign_id, ws)


manager = ConnectionManager()


# ── Map Upload ─────────────────────────────────────────────────

@router.post("/{invite_code}/upload-map")
async def upload_map(invite_code: str, map_file: UploadFile = File(...)):
    """Upload a custom map image for this campaign."""
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return JSONResponse({"error": "Campaign not found"}, status_code=404)

    # Validate file type
    content_type = map_file.content_type or ""
    if not any(t in content_type for t in ("image/png", "image/jpeg", "image/webp", "image/gif")):
        return JSONResponse({"error": "Only PNG, JPEG, WebP, and GIF images are supported"}, status_code=400)

    # Save with unique filename
    ext = Path(map_file.filename).suffix if map_file.filename else ".png"
    if ext.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
        ext = ".png"
    filename = f"{uuid.uuid4().hex}{ext}"
    filepath = _UPLOADS / filename

    contents = await map_file.read()
    filepath.write_bytes(contents)

    # Save to database
    image_url = f"/static/uploads/{filename}"
    with get_db() as db:
        db.execute(
            "INSERT INTO map_images (campaign_id, image_url) VALUES (?, ?)",
            (campaign["id"], image_url),
        )

    return JSONResponse({"url": image_url, "filename": filename})


# ── Game table page ───────────────────────────────────────────

@router.get("/{invite_code}", response_class=HTMLResponse)
async def game_table(request: Request, invite_code: str):
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

        tokens = db.execute(
            "SELECT * FROM map_tokens WHERE campaign_id = ?", (campaign["id"],)
        ).fetchall()

        map_img = db.execute(
            "SELECT * FROM map_images WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign["id"],),
        ).fetchone()

    return _render(
        request,
        "game_table.html",
        campaign=campaign,
        characters=characters,
        tokens=tokens,
        map_image=map_img,
    )


# ── Streamer View (OBS-compatible, clean map only) ─────────────

@router.get("/{invite_code}/stream", response_class=HTMLResponse)
async def stream_view(request: Request, invite_code: str):
    """Clean view for OBS browser source — just the map, no UI chrome."""
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Campaign not found</h1>", status_code=404)

        tokens = db.execute(
            "SELECT * FROM map_tokens WHERE campaign_id = ?", (campaign["id"],)
        ).fetchall()

        map_img = db.execute(
            "SELECT * FROM map_images WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign["id"],),
        ).fetchone()

    return _render(
        request,
        "stream_view.html",
        campaign=campaign,
        tokens=tokens,
        map_image=map_img,
    )


# ── LiveKit token endpoint ────────────────────────────────────

@router.get("/{invite_code}/livekit-token")
async def get_livekit_token(invite_code: str, name: str = "Player"):
    """Generate a LiveKit access token for a participant to join the video room."""
    from app.config import LK_API_KEY as api_key, LK_API_SECRET as api_secret
    from app.services.livekit import generate_livekit_token

    if not api_key or not api_secret:
        return {"error": "LiveKit not configured"}

    token = generate_livekit_token(
        room_name=f"critforge-{invite_code}",
        participant_name=name,
        api_key=api_key,
        api_secret=api_secret,
    )
    return {"token": token}


# ── WebSocket endpoint ────────────────────────────────────────

@router.websocket("/{invite_code}/ws")
async def game_websocket(ws: WebSocket, invite_code: str):
    await ws.accept()

    # Wait for auth message
    try:
        auth_msg = await ws.receive_json()
    except Exception:
        await ws.close(code=4000)
        return

    player_name = auth_msg.get("name", "Unknown")
    is_dm = auth_msg.get("is_dm", False)

    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            await ws.close(code=4004)
            return
        campaign_id = campaign["id"]
        dm_name = campaign["dm_name"]

    # Verify DM status: name must match the campaign's dm_name
    if is_dm and player_name != dm_name:
        is_dm = False  # Don't trust client — enforce server-side

    # Re-verify: if name matches dm_name, they ARE the DM
    if player_name == dm_name:
        is_dm = True

    await manager.connect(campaign_id, ws, player_name, is_dm)

    # Send current state on connect
    with get_db() as db:
        tokens = db.execute(
            "SELECT * FROM map_tokens WHERE campaign_id = ?", (campaign_id,)
        ).fetchall()
        map_img = db.execute(
            "SELECT * FROM map_images WHERE campaign_id = ? ORDER BY id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()

    await ws.send_json({
        "type": "state",
        "tokens": [dict(t) for t in tokens],
        "map_image": dict(map_img) if map_img else None,
        "you_are_dm": is_dm,
        "your_name": player_name,
    })

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "")

            # ── DM-only operations ──────────────────────────
            if msg_type in ("token_add", "token_remove", "map_set", "map_reset"):
                if not manager.is_dm(campaign_id, ws):
                    await ws.send_json({"type": "error", "message": "DM only"})
                    continue

            if msg_type == "token_move":
                token_id = data.get("token_id")
                x = data.get("x", 0)
                y = data.get("y", 0)

                # DM can move any token. Players can only move their own character token.
                if not manager.is_dm(campaign_id, ws):
                    with get_db() as db:
                        token = db.execute(
                            "SELECT * FROM map_tokens WHERE id=?", (token_id,)
                        ).fetchone()
                    if token and token["character_id"]:
                        char = db.execute(
                            "SELECT * FROM characters WHERE id=?", (token["character_id"],)
                        ).fetchone()
                        if not char or char["player_name"] != player_name:
                            await ws.send_json({"type": "error", "message": "Not your token"})
                            continue
                    else:
                        await ws.send_json({"type": "error", "message": "DM only"})
                        continue

                with get_db() as db:
                    db.execute(
                        "UPDATE map_tokens SET x=?, y=? WHERE id=?",
                        (x, y, token_id),
                    )
                await manager.broadcast(campaign_id, {
                    "type": "token_move",
                    "token_id": token_id,
                    "x": x,
                    "y": y,
                    "sender": player_name,
                })

            elif msg_type == "token_add":
                name = data.get("name", "Token")
                char_id = data.get("character_id")
                with get_db() as db:
                    cursor = db.execute(
                        "INSERT INTO map_tokens (campaign_id, character_id, name, x, y) VALUES (?, ?, ?, 400, 300)",
                        (campaign_id, char_id, name),
                    )
                    token_id = cursor.lastrowid
                await manager.broadcast(campaign_id, {
                    "type": "token_add",
                    "token": {"id": token_id, "character_id": char_id, "name": name, "x": 400, "y": 300},
                })

            elif msg_type == "token_remove":
                token_id = data.get("token_id")
                with get_db() as db:
                    db.execute("DELETE FROM map_tokens WHERE id=?", (token_id,))
                await manager.broadcast(campaign_id, {
                    "type": "token_remove",
                    "token_id": token_id,
                })

            elif msg_type == "dice_roll":
                expression = data.get("expression", "")
                roller = data.get("roller", "Unknown")
                result = data.get("result", 0)
                rolls = data.get("rolls", [])
                with get_db() as db:
                    db.execute(
                        "INSERT INTO dice_rolls (campaign_id, roller_name, expression, result, rolls) VALUES (?, ?, ?, ?, ?)",
                        (campaign_id, roller, expression, result, json.dumps(rolls)),
                    )
                await manager.broadcast(campaign_id, {
                    "type": "dice_roll",
                    "roller": roller,
                    "expression": expression,
                    "result": result,
                    "rolls": rolls,
                })

            elif msg_type == "chat":
                sender = data.get("sender", "Unknown")
                message = data.get("message", "")
                with get_db() as db:
                    db.execute(
                        "INSERT INTO chat_messages (campaign_id, sender_name, message) VALUES (?, ?, ?)",
                        (campaign_id, sender, message),
                    )
                await manager.broadcast(campaign_id, {
                    "type": "chat",
                    "sender": sender,
                    "message": message,
                })

            elif msg_type == "map_set":
                image_url = data.get("image_url", "")
                with get_db() as db:
                    db.execute(
                        "INSERT INTO map_images (campaign_id, image_url) VALUES (?, ?)",
                        (campaign_id, image_url),
                    )
                await manager.broadcast(campaign_id, {
                    "type": "map_set",
                    "image_url": image_url,
                })

            elif msg_type == "map_reset":
                with get_db() as db:
                    db.execute("DELETE FROM map_images WHERE campaign_id=?", (campaign_id,))
                await manager.broadcast(campaign_id, {"type": "map_reset"})

            elif msg_type == "ping":
                await ws.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect(campaign_id, ws)
    except Exception:
        manager.disconnect(campaign_id, ws)


# ── Dice roll via HTTP (fallback) ─────────────────────────────

@router.post("/{invite_code}/roll")
async def http_roll(
    invite_code: str,
    roller: str = Form(...),
    expression: str = Form(...),
):
    import random, re

    total = 0
    rolls_list = []
    parts = re.findall(r"(\d*)d(\d+)([+-]\d+)?", expression.lower())
    if parts:
        for count_str, die_str, mod_str in parts:
            count = int(count_str) if count_str else 1
            die = int(die_str)
            for _ in range(count):
                r = random.randint(1, die)
                rolls_list.append(r)
                total += r
            if mod_str:
                total += int(mod_str)

    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return RedirectResponse("/", status_code=303)

        db.execute(
            "INSERT INTO dice_rolls (campaign_id, roller_name, expression, result, rolls) VALUES (?, ?, ?, ?, ?)",
            (campaign["id"], roller, expression, total, json.dumps(rolls_list)),
        )

    await manager.broadcast(campaign["id"], {
        "type": "dice_roll",
        "roller": roller,
        "expression": expression,
        "result": total,
        "rolls": rolls_list,
    })

    return RedirectResponse(f"/game/{invite_code}", status_code=303)
