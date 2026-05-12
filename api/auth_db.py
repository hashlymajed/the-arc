"""User authentication database."""
import hashlib, os, sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv('DATA_DIR', str(Path(__file__).parent.parent / 'data'))) / 'arc.db'

def _conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def _hash(username: str, password: str) -> str:
    return hashlib.sha256(f"{username.lower()}:{password}:arc-salt-2026".encode()).hexdigest()

def init_auth_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT NOT NULL,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role          TEXT DEFAULT 'user',
            created_at    TEXT DEFAULT (datetime('now'))
        );
        """)
    _seed_users()

def _seed_users():
    users = [
        ('Mayed',    'mayed',    'Arc!Mayed26',    'admin'),
        ('Aindreas', 'aindreas', 'Arc!Aindreas26', 'user'),
        ('Obaid',    'obaid',    'Arc!Obaid26',    'user'),
    ]
    with _conn() as c:
        for name, username, password, role in users:
            if not c.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone():
                c.execute(
                    "INSERT INTO users (name, username, password_hash, role) VALUES (?,?,?,?)",
                    (name, username, _hash(username, password), role)
                )

def verify_user(username: str, password: str):
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM users WHERE username=? AND password_hash=?",
            (username.lower().strip(), _hash(username.lower().strip(), password))
        ).fetchone()
        return dict(row) if row else None

def get_user(user_id: int):
    with _conn() as c:
        row = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def list_users() -> list:
    with _conn() as c:
        rows = c.execute(
            "SELECT id, name, username, role, created_at FROM users ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

def change_password(user_id: int, username: str, new_password: str):
    with _conn() as c:
        c.execute(
            "UPDATE users SET password_hash=? WHERE id=?",
            (_hash(username, new_password), user_id)
        )
