"""Character creation and management — full homebrew support."""

import json
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.database import get_db
from app.templating import render as _render

router = APIRouter()

DND_STATS = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
DND_SKILLS = [
    "Acrobatics", "Animal Handling", "Arcana", "Athletics",
    "Deception", "History", "Insight", "Intimidation",
    "Investigation", "Medicine", "Nature", "Perception",
    "Performance", "Persuasion", "Religion", "Sleight of Hand",
    "Stealth", "Survival",
]
DND_ALIGNMENTS = [
    "Lawful Good", "Neutral Good", "Chaotic Good",
    "Lawful Neutral", "True Neutral", "Chaotic Neutral",
    "Lawful Evil", "Neutral Evil", "Chaotic Evil",
]


# ═══ STANDALONE CHARACTER BUILDER (no campaign needed) ═══════

@router.get("/new", response_class=HTMLResponse)
async def new_character_page(request: Request):
    """Create a character without tying it to a campaign yet."""
    return _render(
        request,
        "character_create_standalone.html",
        stats=DND_STATS,
        skills=DND_SKILLS,
        alignments=DND_ALIGNMENTS,
    )


@router.post("/new")
async def create_standalone_character(
    request: Request,
    player_name: str = Form(...),
    character_name: str = Form(...),
    class_name: str = Form(...),
    race: str = Form(...),
    level: int = Form(1),
    background: str = Form(""),
    alignment: str = Form("True Neutral"),
    hp_max: int = Form(10),
    ac: int = Form(10),
    initiative_bonus: int = Form(0),
    speed: int = Form(30),
    stat_STR: int = Form(10),
    stat_DEX: int = Form(10),
    stat_CON: int = Form(10),
    stat_INT: int = Form(10),
    stat_WIS: int = Form(10),
    stat_CHA: int = Form(10),
    proficiencies: str = Form(""),
    features: str = Form(""),
    equipment: str = Form(""),
    spells: str = Form(""),
    notes: str = Form(""),
):
    stats = {
        "STR": stat_STR, "DEX": stat_DEX, "CON": stat_CON,
        "INT": stat_INT, "WIS": stat_WIS, "CHA": stat_CHA,
    }
    prof_list = [p.strip() for p in proficiencies.split(",") if p.strip()]
    feat_list = [f.strip() for f in features.split("\n") if f.strip()]
    equip_list = [e.strip() for e in equipment.split("\n") if e.strip()]
    spell_list = [s.strip() for s in spells.split("\n") if s.strip()]

    with get_db() as db:
        cursor = db.execute(
            """
            INSERT INTO characters
            (campaign_id, player_name, character_name, class_name, race, level,
             background, alignment, stats, hp_max, hp_current, ac,
             initiative_bonus, speed, proficiencies, features, equipment, spells, notes)
            VALUES (NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player_name, character_name, class_name, race, level,
                background, alignment, json.dumps(stats), hp_max, hp_max, ac,
                initiative_bonus, speed, json.dumps(prof_list), json.dumps(feat_list),
                json.dumps(equip_list), json.dumps(spell_list), notes,
            ),
        )
        char_id = cursor.lastrowid

    return RedirectResponse(f"/characters/{char_id}", status_code=303)


@router.get("/stash", response_class=HTMLResponse)
async def character_stash(request: Request):
    """Show all unassigned characters (players' personal roster)."""
    with get_db() as db:
        chars = db.execute(
            "SELECT * FROM characters WHERE campaign_id IS NULL ORDER BY created_at DESC"
        ).fetchall()

    return _render(
        request,
        "character_stash.html",
        characters=chars,
    )


# ═══ CAMPAIGN-LINKED CHARACTERS ═══════════════════════════════

@router.get("/create/{invite_code}", response_class=HTMLResponse)
async def create_character_page(request: Request, invite_code: str):
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Campaign not found</h1>", status_code=404)

    return _render(
        request,
        "character_create.html",
        campaign=campaign,
        stats=DND_STATS,
        skills=DND_SKILLS,
        alignments=DND_ALIGNMENTS,
    )


@router.post("/{invite_code}")
async def create_character(
    request: Request,
    invite_code: str,
    player_name: str = Form(...),
    character_name: str = Form(...),
    class_name: str = Form(...),
    race: str = Form(...),
    level: int = Form(1),
    background: str = Form(""),
    alignment: str = Form("True Neutral"),
    hp_max: int = Form(10),
    ac: int = Form(10),
    initiative_bonus: int = Form(0),
    speed: int = Form(30),
    # Stats come as form fields: stat_STR, stat_DEX, etc.
    stat_STR: int = Form(10),
    stat_DEX: int = Form(10),
    stat_CON: int = Form(10),
    stat_INT: int = Form(10),
    stat_WIS: int = Form(10),
    stat_CHA: int = Form(10),
    proficiencies: str = Form(""),
    features: str = Form(""),
    equipment: str = Form(""),
    spells: str = Form(""),
    notes: str = Form(""),
):
    with get_db() as db:
        campaign = db.execute(
            "SELECT * FROM campaigns WHERE invite_code = ?", (invite_code,)
        ).fetchone()
        if not campaign:
            return HTMLResponse("<h1>Campaign not found</h1>", status_code=404)

        stats = {
            "STR": stat_STR,
            "DEX": stat_DEX,
            "CON": stat_CON,
            "INT": stat_INT,
            "WIS": stat_WIS,
            "CHA": stat_CHA,
        }

        prof_list = [p.strip() for p in proficiencies.split(",") if p.strip()]
        feat_list = [f.strip() for f in features.split("\n") if f.strip()]
        equip_list = [e.strip() for e in equipment.split("\n") if e.strip()]
        spell_list = [s.strip() for s in spells.split("\n") if s.strip()]

        cursor = db.execute(
            """
            INSERT INTO characters
            (campaign_id, player_name, character_name, class_name, race, level,
             background, alignment, stats, hp_max, hp_current, ac,
             initiative_bonus, speed, proficiencies, features, equipment, spells, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campaign["id"],
                player_name,
                character_name,
                class_name,
                race,
                level,
                background,
                alignment,
                json.dumps(stats),
                hp_max,
                hp_max,
                ac,
                initiative_bonus,
                speed,
                json.dumps(prof_list),
                json.dumps(feat_list),
                json.dumps(equip_list),
                json.dumps(spell_list),
                notes,
            ),
        )
        char_id = cursor.lastrowid

        # Auto-create a token for this character on the map
        db.execute(
            "INSERT INTO map_tokens (campaign_id, character_id, name) VALUES (?, ?, ?)",
            (campaign["id"], char_id, character_name),
        )

    return RedirectResponse(f"/characters/{char_id}", status_code=303)


@router.get("/{character_id}", response_class=HTMLResponse)
async def view_character(request: Request, character_id: int):
    with get_db() as db:
        char = db.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        campaign = db.execute(
            "SELECT * FROM campaigns WHERE id = ?", (char["campaign_id"],)
        ).fetchone()

    # Parse JSON fields
    stats = json.loads(char["stats"]) if isinstance(char["stats"], str) else char["stats"]
    proficiencies = json.loads(char["proficiencies"]) if isinstance(char["proficiencies"], str) else char["proficiencies"]
    features = json.loads(char["features"]) if isinstance(char["features"], str) else char["features"]
    equipment = json.loads(char["equipment"]) if isinstance(char["equipment"], str) else char["equipment"]
    spells = json.loads(char["spells"]) if isinstance(char["spells"], str) else char["spells"]

    # Calculate modifiers
    def mod(score):
        return (score - 10) // 2

    return _render(
        request,
        "character_sheet.html",
        character=char,
        campaign=campaign,
        stats=stats,
        proficiencies=proficiencies,
        features=features,
        equipment=equipment,
        spells=spells,
        mod=mod,
    )


@router.get("/{character_id}/edit", response_class=HTMLResponse)
async def edit_character_page(request: Request, character_id: int):
    with get_db() as db:
        char = db.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        campaign = db.execute(
            "SELECT * FROM campaigns WHERE id = ?", (char["campaign_id"],)
        ).fetchone()

    stats = json.loads(char["stats"]) if isinstance(char["stats"], str) else char["stats"]
    proficiencies = json.loads(char["proficiencies"]) if isinstance(char["proficiencies"], str) else char["proficiencies"]
    features = json.loads(char["features"]) if isinstance(char["features"], str) else char["features"]
    equipment = json.loads(char["equipment"]) if isinstance(char["equipment"], str) else char["equipment"]
    spells = json.loads(char["spells"]) if isinstance(char["spells"], str) else char["spells"]

    return _render(
        request,
        "character_edit.html",
        character=char,
        campaign=campaign,
        stats=stats,
        proficiencies=proficiencies,
        features=features,
        equipment=equipment,
        spells=spells,
        all_stats=DND_STATS,
        all_skills=DND_SKILLS,
        all_alignments=DND_ALIGNMENTS,
    )


@router.post("/{character_id}/update")
async def update_character(
    request: Request,
    character_id: int,
    player_name: str = Form(...),
    character_name: str = Form(...),
    class_name: str = Form(...),
    race: str = Form(...),
    level: int = Form(1),
    background: str = Form(""),
    alignment: str = Form("True Neutral"),
    hp_max: int = Form(10),
    hp_current: int = Form(10),
    ac: int = Form(10),
    initiative_bonus: int = Form(0),
    speed: int = Form(30),
    stat_STR: int = Form(10),
    stat_DEX: int = Form(10),
    stat_CON: int = Form(10),
    stat_INT: int = Form(10),
    stat_WIS: int = Form(10),
    stat_CHA: int = Form(10),
    proficiencies: str = Form(""),
    features: str = Form(""),
    equipment: str = Form(""),
    spells: str = Form(""),
    notes: str = Form(""),
):
    with get_db() as db:
        char = db.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        stats = {
            "STR": stat_STR, "DEX": stat_DEX, "CON": stat_CON,
            "INT": stat_INT, "WIS": stat_WIS, "CHA": stat_CHA,
        }

        prof_list = [p.strip() for p in proficiencies.split(",") if p.strip()]
        feat_list = [f.strip() for f in features.split("\n") if f.strip()]
        equip_list = [e.strip() for e in equipment.split("\n") if e.strip()]
        spell_list = [s.strip() for s in spells.split("\n") if s.strip()]

        db.execute(
            """
            UPDATE characters SET
                player_name=?, character_name=?, class_name=?, race=?, level=?,
                background=?, alignment=?, stats=?, hp_max=?, hp_current=?, ac=?,
                initiative_bonus=?, speed=?, proficiencies=?, features=?, equipment=?,
                spells=?, notes=?
            WHERE id=?
            """,
            (
                player_name, character_name, class_name, race, level,
                background, alignment, json.dumps(stats), hp_max, hp_current, ac,
                initiative_bonus, speed, json.dumps(prof_list), json.dumps(feat_list),
                json.dumps(equip_list), json.dumps(spell_list), notes,
                character_id,
            ),
        )

        # Update token name
        db.execute(
            "UPDATE map_tokens SET name=? WHERE character_id=?",
            (character_name, character_id),
        )

    return RedirectResponse(f"/characters/{character_id}", status_code=303)
