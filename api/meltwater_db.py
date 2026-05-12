"""Meltwater sync state database."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "arc.db"


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_meltwater_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mw_sync_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type     TEXT NOT NULL,
            source        TEXT,
            records_synced INTEGER DEFAULT 0,
            status        TEXT DEFAULT 'ok',
            message       TEXT,
            synced_at     TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS mw_search_configs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            search_id   TEXT NOT NULL UNIQUE,
            search_name TEXT,
            auto_sync   INTEGER DEFAULT 0,
            last_synced TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
        """)


def log_sync(sync_type: str, source: str, records: int, status: str = 'ok', message: str = ''):
    with _conn() as c:
        c.execute(
            "INSERT INTO mw_sync_log (sync_type, source, records_synced, status, message) VALUES (?,?,?,?,?)",
            (sync_type, source or '', records, status, message or '')
        )


def get_sync_log(limit: int = 30) -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM mw_sync_log ORDER BY synced_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_search_config(search_id: str, search_name: str, auto_sync: bool = False):
    with _conn() as c:
        c.execute(
            """INSERT INTO mw_search_configs (search_id, search_name, auto_sync)
               VALUES (?,?,?)
               ON CONFLICT(search_id) DO UPDATE SET
                 search_name=excluded.search_name,
                 auto_sync=excluded.auto_sync""",
            (search_id, search_name, 1 if auto_sync else 0)
        )


def list_search_configs() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM mw_search_configs ORDER BY auto_sync DESC, search_name"
        ).fetchall()
        return [dict(r) for r in rows]


def update_last_synced(search_id: str):
    with _conn() as c:
        c.execute(
            "UPDATE mw_search_configs SET last_synced=datetime('now') WHERE search_id=?",
            (search_id,)
        )


def sync_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT SUM(records_synced) FROM mw_sync_log WHERE status='ok'").fetchone()[0] or 0
        last  = c.execute("SELECT synced_at FROM mw_sync_log ORDER BY synced_at DESC LIMIT 1").fetchone()
        art   = c.execute("SELECT SUM(records_synced) FROM mw_sync_log WHERE sync_type='articles' AND status='ok'").fetchone()[0] or 0
        jour  = c.execute("SELECT SUM(records_synced) FROM mw_sync_log WHERE sync_type='journalists' AND status='ok'").fetchone()[0] or 0
        return {
            'total_records': total,
            'articles_synced': art,
            'journalists_synced': jour,
            'last_sync': dict(last)['synced_at'] if last else None,
        }
