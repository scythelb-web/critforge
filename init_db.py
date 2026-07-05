"""Initialize the CritForge database."""

from app.database import get_db


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                dm_name TEXT NOT NULL,
                invite_code TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS characters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                player_name TEXT NOT NULL,
                character_name TEXT NOT NULL,
                class_name TEXT NOT NULL,
                race TEXT NOT NULL,
                level INTEGER DEFAULT 1,
                background TEXT DEFAULT '',
                alignment TEXT DEFAULT '',
                stats TEXT NOT NULL DEFAULT '{}',
                hp_max INTEGER DEFAULT 10,
                hp_current INTEGER DEFAULT 10,
                ac INTEGER DEFAULT 10,
                initiative_bonus INTEGER DEFAULT 0,
                speed INTEGER DEFAULT 30,
                proficiencies TEXT DEFAULT '[]',
                features TEXT DEFAULT '[]',
                equipment TEXT DEFAULT '[]',
                spells TEXT DEFAULT '[]',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );

            CREATE TABLE IF NOT EXISTS map_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                character_id INTEGER,
                name TEXT NOT NULL,
                image_url TEXT DEFAULT '',
                x REAL DEFAULT 0,
                y REAL DEFAULT 0,
                size TEXT DEFAULT 'medium',
                visible INTEGER DEFAULT 1,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
                FOREIGN KEY (character_id) REFERENCES characters(id)
            );

            CREATE TABLE IF NOT EXISTS map_images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                width INTEGER DEFAULT 1920,
                height INTEGER DEFAULT 1080,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );

            CREATE TABLE IF NOT EXISTS dice_rolls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                roller_name TEXT NOT NULL,
                expression TEXT NOT NULL,
                result INTEGER NOT NULL,
                rolls TEXT NOT NULL DEFAULT '[]',
                rolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL,
                sender_name TEXT NOT NULL,
                message TEXT NOT NULL,
                is_system INTEGER DEFAULT 0,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id)
            );
        """)
    print("✓ Database initialized")


if __name__ == "__main__":
    init_db()
