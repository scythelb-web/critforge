import os
import sqlite3
from pathlib import Path
from contextlib import contextmanager

from app.config import DB_PATH, TURSO_URL, TURSO_TOKEN

_use_turso = bool(TURSO_URL and TURSO_TOKEN)

if _use_turso:
    import libsql_experimental as libsql


class RowDict:
    """Make a tuple look like sqlite3.Row for dict() and [] access."""

    def __init__(self, row, columns):
        self._row = row
        self._cols = columns
        self._map = {col.lower(): val for col, val in zip(columns, row)}

    def keys(self):
        return [c.lower() for c in self._cols]

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return self._map[key.lower()]

    def __iter__(self):
        return iter(self._map.values())

    def __contains__(self, key):
        return key.lower() in self._map

    def __repr__(self):
        return f"RowDict({self._map})"


class TursoWrapper:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        if params:
            cur.execute(sql, params)
        else:
            cur.execute(sql)
        return TursoCursor(cur, cur.description)

    def executescript(self, sql):
        self._conn.executescript(sql)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


class TursoCursor:
    def __init__(self, cursor, description):
        self._cursor = cursor
        self._columns = [d[0] for d in description] if description else []
        self.lastrowid = cursor.lastrowid if hasattr(cursor, "lastrowid") else None

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return RowDict(row, self._columns)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [RowDict(r, self._columns) for r in rows]


@contextmanager
def get_db():
    if _use_turso:
        conn = TursoWrapper(libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN))
    else:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
