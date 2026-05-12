"""Meeting Intelligence database layer."""
import json, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "arc.db"


def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_meetings_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            meeting_date TEXT,
            context TEXT,
            participant_names TEXT DEFAULT '[]',
            status TEXT DEFAULT 'processing',
            vault_archived INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS meeting_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL UNIQUE REFERENCES meetings(id) ON DELETE CASCADE,
            summary_en TEXT,
            summary_ar TEXT,
            key_topics TEXT DEFAULT '[]',
            updates_shared TEXT,
            vault_keywords TEXT DEFAULT '[]',
            vault_category TEXT
        );
        CREATE TABLE IF NOT EXISTS meeting_transcript_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            position INTEGER DEFAULT 0,
            timestamp_str TEXT,
            speaker_label TEXT,
            language TEXT DEFAULT 'English',
            text TEXT
        );
        CREATE TABLE IF NOT EXISTS meeting_action_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            task TEXT NOT NULL,
            owner TEXT,
            deadline TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS meeting_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            decision TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meeting_risks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            description TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS meeting_followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            description TEXT NOT NULL,
            status TEXT DEFAULT 'open'
        );
        """)


def create_meeting(data: dict) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO meetings (title, meeting_date, context, participant_names, status) VALUES (?,?,?,?,?)",
            (data['title'], data.get('meeting_date', ''), data.get('context', ''),
             json.dumps(data.get('participant_names', [])), data.get('status', 'processing'))
        )
        return cur.lastrowid


def update_meeting_status(mid: int, status: str, title: str = None):
    with _conn() as c:
        if title:
            c.execute("UPDATE meetings SET status=?, title=? WHERE id=?", (status, title, mid))
        else:
            c.execute("UPDATE meetings SET status=? WHERE id=?", (status, mid))


def save_meeting_results(mid: int, result: dict):
    with _conn() as c:
        c.execute("""
            INSERT INTO meeting_summaries
              (meeting_id, summary_en, summary_ar, key_topics, updates_shared, vault_keywords, vault_category)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(meeting_id) DO UPDATE SET
              summary_en=excluded.summary_en, summary_ar=excluded.summary_ar,
              key_topics=excluded.key_topics, updates_shared=excluded.updates_shared,
              vault_keywords=excluded.vault_keywords, vault_category=excluded.vault_category
        """, (
            mid,
            result.get('summary_english', ''),
            result.get('summary_arabic', ''),
            json.dumps(result.get('key_topics', [])),
            result.get('updates_shared', ''),
            json.dumps(result.get('vault_record', {}).get('keywords_en', [])),
            result.get('vault_record', {}).get('topic_category', ''),
        ))
        c.execute("DELETE FROM meeting_transcript_items WHERE meeting_id=?", (mid,))
        for i, item in enumerate(result.get('transcript', [])):
            c.execute(
                "INSERT INTO meeting_transcript_items (meeting_id, position, timestamp_str, speaker_label, language, text) VALUES (?,?,?,?,?,?)",
                (mid, i, item.get('time', ''), item.get('speaker', ''), item.get('language', 'English'), item.get('text', ''))
            )
        c.execute("DELETE FROM meeting_action_items WHERE meeting_id=?", (mid,))
        for a in result.get('action_items', []):
            c.execute(
                "INSERT INTO meeting_action_items (meeting_id, task, owner, deadline, priority) VALUES (?,?,?,?,?)",
                (mid, a.get('task', ''), a.get('owner', ''), a.get('deadline', ''), a.get('priority', 'medium'))
            )
        c.execute("DELETE FROM meeting_decisions WHERE meeting_id=?", (mid,))
        for d in result.get('decisions_made', []):
            c.execute("INSERT INTO meeting_decisions (meeting_id, decision) VALUES (?,?)", (mid, d))
        c.execute("DELETE FROM meeting_risks WHERE meeting_id=?", (mid,))
        for r in result.get('risks_or_concerns', []):
            c.execute("INSERT INTO meeting_risks (meeting_id, description) VALUES (?,?)", (mid, r))
        c.execute("DELETE FROM meeting_followups WHERE meeting_id=?", (mid,))
        for f in result.get('follow_ups', []):
            c.execute("INSERT INTO meeting_followups (meeting_id, description) VALUES (?,?)", (mid, f))
        title = result.get('meeting_title', '')
        if title:
            c.execute("UPDATE meetings SET title=?, status='complete' WHERE id=?", (title, mid))
        else:
            c.execute("UPDATE meetings SET status='complete' WHERE id=?", (mid,))


def list_meetings() -> list:
    with _conn() as c:
        rows = c.execute("""
            SELECT m.*,
              (SELECT COUNT(*) FROM meeting_action_items WHERE meeting_id=m.id AND status='open') AS open_actions,
              (SELECT COUNT(*) FROM meeting_transcript_items WHERE meeting_id=m.id) AS transcript_lines
            FROM meetings m ORDER BY m.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_meeting(mid: int) -> dict:
    with _conn() as c:
        row = c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        if not row:
            return None
        m = dict(row)
        s = c.execute("SELECT * FROM meeting_summaries WHERE meeting_id=?", (mid,)).fetchone()
        m['summary'] = dict(s) if s else {}
        if m['summary']:
            m['summary']['key_topics']     = json.loads(m['summary'].get('key_topics', '[]') or '[]')
            m['summary']['vault_keywords'] = json.loads(m['summary'].get('vault_keywords', '[]') or '[]')
        m['transcript'] = [dict(r) for r in c.execute(
            "SELECT * FROM meeting_transcript_items WHERE meeting_id=? ORDER BY position", (mid,)
        ).fetchall()]
        m['action_items'] = [dict(r) for r in c.execute(
            "SELECT * FROM meeting_action_items WHERE meeting_id=? ORDER BY id", (mid,)
        ).fetchall()]
        m['decisions'] = [dict(r)['decision'] for r in c.execute(
            "SELECT decision FROM meeting_decisions WHERE meeting_id=?", (mid,)
        ).fetchall()]
        m['risks'] = [dict(r)['description'] for r in c.execute(
            "SELECT description FROM meeting_risks WHERE meeting_id=?", (mid,)
        ).fetchall()]
        m['followups'] = [dict(r) for r in c.execute(
            "SELECT * FROM meeting_followups WHERE meeting_id=?", (mid,)
        ).fetchall()]
        m['participant_names'] = json.loads(m.get('participant_names', '[]') or '[]')
        return m


def delete_meeting(mid: int):
    with _conn() as c:
        c.execute("DELETE FROM meetings WHERE id=?", (mid,))


def update_action_status(action_id: int, status: str):
    with _conn() as c:
        c.execute("UPDATE meeting_action_items SET status=? WHERE id=?", (status, action_id))


def archive_meeting(mid: int):
    with _conn() as c:
        c.execute("UPDATE meetings SET vault_archived=1 WHERE id=?", (mid,))


def meetings_stats() -> dict:
    with _conn() as c:
        total     = c.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
        complete  = c.execute("SELECT COUNT(*) FROM meetings WHERE status='complete'").fetchone()[0]
        archived  = c.execute("SELECT COUNT(*) FROM meetings WHERE vault_archived=1").fetchone()[0]
        open_acts = c.execute("SELECT COUNT(*) FROM meeting_action_items WHERE status='open'").fetchone()[0]
        return {'total': total, 'complete': complete, 'archived': archived, 'open_actions': open_acts}
