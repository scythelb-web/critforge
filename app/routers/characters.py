"""Character creation and management — full homebrew support."""

import io
import json
import re

import pymupdf

from fastapi import APIRouter, Request, Form, UploadFile, File
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


# ═══ PDF CHARACTER SHEET PARSER ═══════════════════════════════

def _find_section(text: str, label: str, next_labels: list[str] | None = None) -> str:
    """Capture multi-line content after a section header until EOF or next known label."""
    # Find the label line
    m = re.search(rf"^{re.escape(label)}[\s:]*(.*)", text, re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    remainder = text[start:]

    # If we know next section labels, stop at the first one found
    if next_labels:
        earliest = len(remainder)
        for nl in next_labels:
            pos = remainder.find(nl)
            if pos != -1 and pos < earliest:
                # Check it's at start of a line
                if pos == 0 or remainder[pos - 1] == "\n":
                    earliest = pos
        remainder = remainder[:earliest]

    # Combine the label line remainder + following content
    content = (m.group(1) + " " + remainder).strip()
    return re.sub(r"\s+", " ", content)


def _find_stat(text: str, labels: list[str]) -> str | None:
    """Find a field value by trying multiple label patterns."""
    for label in labels:
        # Pattern: "Label: value" or "Label value" (case insensitive)
        m = re.search(rf"{re.escape(label)}[\s:]+(.+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip("0123456789 ").strip() or m.group(1).strip()
    return None


def _find_number(text: str, labels: list[str]) -> int | None:
    """Extract a number after a label."""
    for label in labels:
        m = re.search(rf"{re.escape(label)}[\s:]*(\d+)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def _find_stat_score(text: str, stat: str) -> int | None:
    """Find an ability score. Looks for 'STR' / 'Strength' near a number."""
    patterns = [
        rf"{stat}\s*[:=]?\s*(\d+)",           # STR 16 or STR: 16
        rf"{stat}\S*\s+(\d+)\s*[\(\[].*?[+-]",  # STR 16 (+3)
        rf"\b{stat}\S*\b.*?(\d+)",             # Strength 16
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if 1 <= val <= 30:
                return val
    return None


def parse_character_sheet_pdf(pdf_bytes: bytes) -> dict:
    """Extract text from a PDF character sheet and parse D&D fields.

    Returns a dict with any/all recognized fields:
        character_name, class_name, race, level, background, alignment,
        hp_max, ac, initiative_bonus, speed, stats dict, proficiencies list,
        features list, equipment list, spells list, notes
    Also includes 'raw_text' for debugging and manual review.
    """
    result = {
        "character_name": "",
        "class_name": "",
        "race": "",
        "level": 1,
        "background": "",
        "alignment": "True Neutral",
        "hp_max": 10,
        "ac": 10,
        "initiative_bonus": 0,
        "speed": 30,
        "stats": {"STR": 10, "DEX": 10, "CON": 10, "INT": 10, "WIS": 10, "CHA": 10},
        "proficiencies": [],
        "features": [],
        "equipment": [],
        "spells": [],
        "notes": "",
        "raw_text": "",
        "parse_confidence": 0,  # 0-100
    }

    # Extract text
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            pages.append(page.get_text("text"))
        doc.close()
    except Exception:
        result["raw_text"] = "[Could not read PDF — file may be corrupted or scanned/image-only]"
        return result

    full_text = "\n".join(pages)
    result["raw_text"] = full_text

    if not full_text.strip():
        return result

    hits = 0  # track successful parses for confidence
    lines = [l.strip() for l in full_text.split("\n") if l.strip()]

    # ── Single-line field patterns ──────────────────────────
    single_patterns = [
        # (field_key, [regex patterns to try])
        ("character_name", [r"Character\s*Name\s*:?\s*(.+)", r"^Name\s*:?\s*(.+)"],
         lambda v: v.strip().rstrip("0123456789 ").strip() or v.strip()),
        ("race", [r"Race\s*:?\s*(.+)", r"Species\s*:?\s*(.+)", r"Ancestry\s*:?\s*(.+)"],
         lambda v: v.strip()),
        ("background", [r"Background\s*:?\s*(.+)"],
         lambda v: v.strip()),
        ("alignment", [r"Alignment\s*:?\s*(.+)"],
         lambda v: v.strip()),
        ("class_name", [r"Class\s*(?:&|and)\s*Level\s*:?\s*(.+)",
                        r"Class\s*:?\s*(.+)"],
         lambda v: v.strip()),
    ]

    for field, patterns, transform in single_patterns:
        found = False
        for line in lines:
            for pat in patterns:
                m = re.match(pat, line, re.IGNORECASE)
                if m:
                    val = transform(m.group(1))
                    # For class_name, try to split level off the end
                    if field == "class_name":
                        lvl_match = re.search(r"(\d+)$", val)
                        if lvl_match:
                            result["level"] = int(lvl_match.group(1))
                            val = val[:lvl_match.start()].strip()
                            if not val:
                                val = m.group(1).strip()
                    if val and val != result.get(field, ""):
                        result[field] = val
                        hits += 1
                        found = True
                    break
            if found:
                break

    # ── Level (standalone) ──────────────────────────────────
    for line in lines:
        m = re.match(r"Level\s*:?\s*(\d+)", line, re.IGNORECASE)
        if m:
            lvl = int(m.group(1))
            if result["level"] == 1 or lvl > 1:
                result["level"] = lvl
                hits += 1
            break

    # ── Numeric fields ──────────────────────────────────────
    num_patterns = [
        ("hp_max", [r"Hit\s*Point\s*Maximum\s*:?\s*(\d+)",
                     r"Hit\s*Points?\s*:?\s*(\d+)",
                     r"HP\s*Max\s*:?\s*(\d+)",
                     r"Max\s*HP\s*:?\s*(\d+)",
                     r"^HP\s*:?\s*(\d+)"]),
        ("ac", [r"Armor\s*Class\s*:?\s*(\d+)",
                r"^AC\s*:?\s*(\d+)"]),
        ("initiative_bonus", [r"Initiative\s*:?\s*([+-]?\d+)",
                               r"^Init\s*:?\s*([+-]?\d+)"]),
        ("speed", [r"Speed\s*:?\s*(\d+)"]),
    ]

    for field, patterns in num_patterns:
        found = False
        for line in lines:
            for pat in patterns:
                m = re.match(pat, line, re.IGNORECASE)
                if m:
                    result[field] = int(m.group(1))
                    hits += 1
                    found = True
                    break
            if found:
                break

    # ── Ability Scores ──────────────────────────────────────
    stat_map = {"STR": "STR", "DEX": "DEX", "CON": "CON",
                "INT": "INT", "WIS": "WIS", "CHA": "CHA"}
    stat_aliases = {
        "STR": ["STR", "Strength"],
        "DEX": ["DEX", "Dexterity"],
        "CON": ["CON", "Constitution"],
        "INT": ["INT", "Intelligence"],
        "WIS": ["WIS", "Wisdom"],
        "CHA": ["CHA", "Charisma"],
    }
    for key, aliases in stat_aliases.items():
        for alias in aliases:
            for line in lines:
                # Pattern: "STR: 16" or "STR 16 (+3)" or "Strength 16"
                m = re.search(rf"\b{re.escape(alias)}\s*:?\s*(\d+)", line, re.IGNORECASE)
                if m:
                    val = int(m.group(1))
                    if 1 <= val <= 30:
                        result["stats"][key] = val
                        hits += 1
                        break
            if result["stats"][key] != 10:
                break

    # ── Multi-line sections (search in full text) ───────────
    # All known section labels for boundary detection
    all_section_labels = [
        "Proficiencies", "Skill Proficiencies", "Saving Throws",
        "Features & Traits", "Features and Traits", "Class Features", "Feats",
        "Equipment", "Inventory", "Gear",
        "Spells", "Spellcasting", "Spell List", "Cantrips", "Prepared Spells",
    ]

    # Proficiencies
    prof_section = _find_section(full_text, "Proficiencies", all_section_labels)
    if not prof_section:
        prof_section = _find_section(full_text, "Skill Proficiencies", all_section_labels)
    if not prof_section:
        prof_section = _find_section(full_text, "Saving Throws", all_section_labels)
    if prof_section:
        prof_list = re.split(r"[,;•●○◆◇]", prof_section)
        result["proficiencies"] = [p.strip() for p in prof_list if p.strip() and len(p.strip()) > 2]
        if result["proficiencies"]:
            hits += 1

    # Features
    feat_section = _find_section(full_text, "Features & Traits", all_section_labels)
    if not feat_section:
        feat_section = _find_section(full_text, "Features and Traits", all_section_labels)
    if not feat_section:
        feat_section = _find_section(full_text, "Class Features", all_section_labels)
    if feat_section:
        result["features"] = [f.strip() for f in feat_section.split(".") if f.strip()]
        if result["features"]:
            hits += 1

    # Equipment
    equip_section = _find_section(full_text, "Equipment", all_section_labels)
    if not equip_section:
        equip_section = _find_section(full_text, "Inventory", all_section_labels)
    if equip_section:
        result["equipment"] = [e.strip() for e in re.split(r"[,;•●○]", equip_section) if e.strip()]
        if result["equipment"]:
            hits += 1

    # Spells
    spell_section = _find_section(full_text, "Spells", all_section_labels)
    if not spell_section:
        spell_section = _find_section(full_text, "Spellcasting", all_section_labels)
    if not spell_section:
        spell_section = _find_section(full_text, "Cantrips", all_section_labels)
    if spell_section:
        result["spells"] = [s.strip() for s in re.split(r"[,;•●○]", spell_section) if s.strip()]
        if result["spells"]:
            hits += 1

    # ── Confidence ──────────────────────────────────────────
    result["parse_confidence"] = min(100, hits * 7)

    return result


# ═══ PDF CHARACTER SHEET IMPORT ═══════════════════════════════

@router.get("/import", response_class=HTMLResponse)
async def import_character_page(request: Request):
    """Show the PDF upload + pre-fill form."""
    return _render(
        request,
        "character_import.html",
        stats=DND_STATS,
        skills=DND_SKILLS,
        alignments=DND_ALIGNMENTS,
        pre_fill=None,
    )


@router.post("/import", response_class=HTMLResponse)
async def import_character_upload(request: Request, pdf_file: UploadFile = File(...)):
    """Handle PDF upload, parse it, and return the pre-filled review form."""
    pdf_bytes = await pdf_file.read()

    if not pdf_bytes:
        return _render(
            request, "character_import.html",
            stats=DND_STATS, skills=DND_SKILLS, alignments=DND_ALIGNMENTS,
            pre_fill=None, error="No file uploaded or file was empty.",
        )

    # Check it's actually a PDF
    if not pdf_bytes[:4] == b"%PDF":
        return _render(
            request, "character_import.html",
            stats=DND_STATS, skills=DND_SKILLS, alignments=DND_ALIGNMENTS,
            pre_fill=None, error="Uploaded file is not a valid PDF.",
        )

    parsed = parse_character_sheet_pdf(pdf_bytes)
    return _render(
        request,
        "character_import.html",
        stats=DND_STATS,
        skills=DND_SKILLS,
        alignments=DND_ALIGNMENTS,
        pre_fill=parsed,
        error=None,
    )

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


# ═══ CHARACTER NOTEBOOK ═══════════════════════════════════════

@router.get("/{character_id}/notebook", response_class=HTMLResponse)
async def character_notebook(request: Request, character_id: int):
    with get_db() as db:
        char = db.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        notes = db.execute(
            "SELECT * FROM character_notes WHERE character_id = ? ORDER BY created_at DESC",
            (character_id,),
        ).fetchall()

    return _render(
        request,
        "character_notebook.html",
        character=char,
        notes=notes,
    )


@router.post("/{character_id}/notebook")
async def add_note(
    character_id: int,
    title: str = Form("Session Note"),
    content: str = Form(""),
):
    with get_db() as db:
        char = db.execute(
            "SELECT * FROM characters WHERE id = ?", (character_id,)
        ).fetchone()
        if not char:
            return HTMLResponse("<h1>Character not found</h1>", status_code=404)

        db.execute(
            "INSERT INTO character_notes (character_id, title, content) VALUES (?, ?, ?)",
            (character_id, title, content),
        )

    return RedirectResponse(f"/characters/{character_id}/notebook", status_code=303)
