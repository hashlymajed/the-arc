import sqlite3, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'arc.db')

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS drafts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL DEFAULT 'Untitled Draft',
            channel     TEXT NOT NULL DEFAULT 'Press Release',
            audience    TEXT,
            tone        TEXT,
            brief       TEXT,
            vault_context TEXT,
            content     TEXT,
            status      TEXT NOT NULL DEFAULT 'draft',
            review_notes TEXT,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP DEFAULT NULL,
            author      TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );

        CREATE TABLE IF NOT EXISTS draft_activity (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            draft_id   INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            author     TEXT    NOT NULL DEFAULT 'system',
            action     TEXT    NOT NULL,
            notes      TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_draft_activity_draft_id ON draft_activity(draft_id);

        CREATE TABLE IF NOT EXISTS tags (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            color      TEXT    NOT NULL DEFAULT '#6B7280',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS draft_tags (
            draft_id INTEGER NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
            tag_id   INTEGER NOT NULL REFERENCES tags(id)   ON DELETE CASCADE,
            PRIMARY KEY (draft_id, tag_id)
        );

        CREATE TRIGGER IF NOT EXISTS drafts_updated
        AFTER UPDATE ON drafts
        BEGIN
            UPDATE drafts SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
    """)
    conn.commit()
    conn.close()

# ── Drafts ────────────────────────────────────────────────────────────────────

def list_drafts(status=None, limit=50):
    conn = get_conn()
    q = "SELECT * FROM drafts"
    args = []
    if status:
        q += " WHERE status = ?"; args.append(status)
    q += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_draft(draft_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def create_draft(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO drafts (title, channel, audience, tone, brief, vault_context, content, status, author)
        VALUES (:title, :channel, :audience, :tone, :brief, :vault_context, :content, 'draft', :author)
    """, {**data, 'author': data.get('author')})
    conn.commit()
    draft_id = cur.lastrowid
    conn.close()
    return draft_id

def update_draft(draft_id, data: dict):
    allowed = {'title','channel','audience','tone','brief','vault_context','content','status','review_notes','author'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields['id'] = draft_id
    conn = get_conn()
    conn.execute(f"UPDATE drafts SET {set_clause} WHERE id = :id", fields)
    conn.commit()
    conn.close()

def drafts_by_status():
    conn = get_conn()
    all_rows = conn.execute("SELECT * FROM drafts ORDER BY updated_at DESC").fetchall()
    conn.close()
    buckets = {'draft': [], 'review': [], 'approved': [], 'published': []}
    for r in all_rows:
        d = dict(r)
        d['updated_at'] = d['updated_at'][:16] if d['updated_at'] else '—'
        buckets.setdefault(d['status'], []).append(d)
    return buckets

# ── Settings ──────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    conn = get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

def save_settings(data: dict):
    conn = get_conn()
    for k, v in data.items():
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (k, str(v) if v is not None else '')
        )
    conn.commit()
    conn.close()

# ── Activity log ──────────────────────────────────────────────────────────────

def log_activity(draft_id: int, author: str, action: str, notes: str = ''):
    conn = get_conn()
    conn.execute(
        "INSERT INTO draft_activity (draft_id, author, action, notes) VALUES (?, ?, ?, ?)",
        (draft_id, author or 'system', action, notes or '')
    )
    conn.commit()
    conn.close()

def get_draft_activity(draft_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM draft_activity WHERE draft_id = ? ORDER BY created_at ASC",
        (draft_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── Tags ───────────────────────────────────────────────────────────────────────

def list_tags():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tags ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_tag(name: str, color: str = '#6B7280'):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tags (name, color) VALUES (?, ?)",
        (name.strip(), color)
    )
    conn.commit()
    tag_id = cur.lastrowid
    conn.close()
    return tag_id

def delete_tag(tag_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()

def get_draft_tags(draft_id: int):
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.* FROM tags t
        JOIN draft_tags dt ON dt.tag_id = t.id
        WHERE dt.draft_id = ?
        ORDER BY t.name
    """, (draft_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_draft_tag(draft_id: int, tag_id: int):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO draft_tags (draft_id, tag_id) VALUES (?, ?)",
        (draft_id, tag_id)
    )
    conn.commit()
    conn.close()

def remove_draft_tag(draft_id: int, tag_id: int):
    conn = get_conn()
    conn.execute(
        "DELETE FROM draft_tags WHERE draft_id = ? AND tag_id = ?",
        (draft_id, tag_id)
    )
    conn.commit()
    conn.close()
