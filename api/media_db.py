"""Media Relations database layer."""
import sqlite3, json, os
from datetime import datetime
from pathlib import Path

DB_PATH = str(Path(os.getenv('DATA_DIR', str(Path(__file__).parent.parent / 'data'))) / 'arc.db')


def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_media_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS publications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            type       TEXT DEFAULT 'online',
            region     TEXT,
            language   TEXT DEFAULT 'English',
            tier       INTEGER DEFAULT 2,
            website    TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS journalists (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT NOT NULL,
            email                TEXT,
            phone                TEXT,
            beat                 TEXT,
            language             TEXT DEFAULT 'English',
            region               TEXT,
            social_twitter       TEXT,
            social_linkedin      TEXT,
            relationship_owner   TEXT,
            risk_score           REAL DEFAULT 0,
            risk_label           TEXT DEFAULT 'safe',
            risk_override_label  TEXT,
            risk_override_reason TEXT,
            risk_override_by     TEXT,
            notes                TEXT,
            created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_journalists_risk ON journalists(risk_label);
        CREATE TABLE IF NOT EXISTS journalist_publications (
            journalist_id  INTEGER NOT NULL REFERENCES journalists(id) ON DELETE CASCADE,
            publication_id INTEGER NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
            role           TEXT DEFAULT 'staff',
            PRIMARY KEY (journalist_id, publication_id)
        );
        CREATE TABLE IF NOT EXISTS media_articles (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            title               TEXT NOT NULL,
            url                 TEXT,
            publication_id      INTEGER REFERENCES publications(id),
            journalist_id       INTEGER REFERENCES journalists(id),
            published_at        TEXT,
            content_snippet     TEXT,
            sentiment           TEXT DEFAULT 'neutral',
            sentiment_score     REAL DEFAULT 0.5,
            sentiment_reasoning TEXT,
            topics              TEXT DEFAULT '[]',
            risk_flag           INTEGER DEFAULT 0,
            ingested_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_articles_journalist ON media_articles(journalist_id);
        CREATE INDEX IF NOT EXISTS idx_articles_sentiment  ON media_articles(sentiment);
        CREATE INDEX IF NOT EXISTS idx_articles_risk       ON media_articles(risk_flag);
        CREATE TABLE IF NOT EXISTS article_entities (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id  INTEGER NOT NULL REFERENCES media_articles(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_name TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS journalist_interactions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            journalist_id INTEGER NOT NULL REFERENCES journalists(id) ON DELETE CASCADE,
            type          TEXT NOT NULL DEFAULT 'email',
            date          TEXT,
            notes         TEXT,
            draft_id      INTEGER,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_interactions_journalist ON journalist_interactions(journalist_id);
        CREATE TABLE IF NOT EXISTS media_alerts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT NOT NULL,
            entity_id   INTEGER,
            entity_type TEXT,
            message     TEXT NOT NULL,
            severity    TEXT DEFAULT 'medium',
            status      TEXT DEFAULT 'unread',
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_alerts_status ON media_alerts(status);
        CREATE TRIGGER IF NOT EXISTS journalists_updated
        AFTER UPDATE ON journalists
        BEGIN
            UPDATE journalists SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
        END;
    """)
    conn.commit()
    conn.close()


# ── Publications ──────────────────────────────────────────────────────────────

def list_publications():
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM publications ORDER BY tier, name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_publication(pub_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM publications WHERE id = ?", (pub_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_publication(data: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO publications (name, type, region, language, tier, website)
        VALUES (:name,:type,:region,:language,:tier,:website)
    """, {
        'name': data.get('name', ''),
        'type': data.get('type', 'online'),
        'region': data.get('region', ''),
        'language': data.get('language', 'English'),
        'tier': int(data.get('tier', 2)),
        'website': data.get('website', ''),
    })
    conn.commit()
    pub_id = cur.lastrowid
    conn.close()
    return pub_id


# ── Journalists ───────────────────────────────────────────────────────────────

def list_journalists(search='', risk_label='', region=''):
    conn = _get_conn()
    q = "SELECT * FROM journalists WHERE 1=1"
    args = []
    if search:
        q += " AND (name LIKE ? OR beat LIKE ? OR email LIKE ?)"
        s = f'%{search}%'
        args.extend([s, s, s])
    if risk_label:
        q += " AND COALESCE(risk_override_label, risk_label) = ?"
        args.append(risk_label)
    if region:
        q += " AND region = ?"
        args.append(region)
    q += " ORDER BY name ASC"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_journalist(jid):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM journalists WHERE id = ?", (jid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_journalist(data: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO journalists (name, email, phone, beat, language, region,
            social_twitter, social_linkedin, relationship_owner, notes)
        VALUES (:name,:email,:phone,:beat,:language,:region,
                :social_twitter,:social_linkedin,:relationship_owner,:notes)
    """, {
        'name': data.get('name', ''),
        'email': data.get('email', ''),
        'phone': data.get('phone', ''),
        'beat': data.get('beat', ''),
        'language': data.get('language', 'English'),
        'region': data.get('region', ''),
        'social_twitter': data.get('social_twitter', ''),
        'social_linkedin': data.get('social_linkedin', ''),
        'relationship_owner': data.get('relationship_owner', ''),
        'notes': data.get('notes', ''),
    })
    conn.commit()
    jid = cur.lastrowid
    conn.close()
    return jid


def update_journalist(jid, data: dict):
    allowed = {'name','email','phone','beat','language','region',
               'social_twitter','social_linkedin','relationship_owner','notes',
               'risk_score','risk_label','risk_override_label','risk_override_reason','risk_override_by'}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    fields['id'] = jid
    conn = _get_conn()
    conn.execute(f"UPDATE journalists SET {set_clause} WHERE id = :id", fields)
    conn.commit()
    conn.close()


def delete_journalist(jid):
    conn = _get_conn()
    conn.execute("DELETE FROM journalists WHERE id = ?", (jid,))
    conn.commit()
    conn.close()


def get_journalist_publications(jid):
    conn = _get_conn()
    rows = conn.execute("""
        SELECT p.*, jp.role FROM publications p
        JOIN journalist_publications jp ON jp.publication_id = p.id
        WHERE jp.journalist_id = ?
    """, (jid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def link_journalist_publication(jid, pub_id, role='staff'):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO journalist_publications (journalist_id, publication_id, role) VALUES (?,?,?)",
        (jid, pub_id, role)
    )
    conn.commit()
    conn.close()


# ── Articles ──────────────────────────────────────────────────────────────────

def list_articles(sentiment='', journalist_id=None, publication_id=None, risk_flag=None, limit=50):
    conn = _get_conn()
    q = """
        SELECT a.*, j.name as journalist_name, p.name as publication_name
        FROM media_articles a
        LEFT JOIN journalists j ON j.id = a.journalist_id
        LEFT JOIN publications p ON p.id = a.publication_id
        WHERE 1=1
    """
    args = []
    if sentiment:
        q += " AND a.sentiment = ?"
        args.append(sentiment)
    if journalist_id is not None:
        q += " AND a.journalist_id = ?"
        args.append(journalist_id)
    if publication_id is not None:
        q += " AND a.publication_id = ?"
        args.append(publication_id)
    if risk_flag is not None:
        q += " AND a.risk_flag = ?"
        args.append(1 if risk_flag else 0)
    q += " ORDER BY a.ingested_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['topics'] = json.loads(d.get('topics') or '[]')
        except Exception:
            d['topics'] = []
        result.append(d)
    return result


def get_article(article_id):
    conn = _get_conn()
    row = conn.execute("SELECT * FROM media_articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d['topics'] = json.loads(d.get('topics') or '[]')
    except Exception:
        d['topics'] = []
    return d


def create_article(data: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO media_articles (title, url, publication_id, journalist_id, published_at,
            content_snippet, sentiment, sentiment_score, sentiment_reasoning, topics, risk_flag)
        VALUES (:title,:url,:publication_id,:journalist_id,:published_at,
                :content_snippet,:sentiment,:sentiment_score,:sentiment_reasoning,:topics,:risk_flag)
    """, {
        'title': data.get('title', ''),
        'url': data.get('url', ''),
        'publication_id': data.get('publication_id'),
        'journalist_id': data.get('journalist_id'),
        'published_at': data.get('published_at', ''),
        'content_snippet': data.get('content_snippet', ''),
        'sentiment': data.get('sentiment', 'neutral'),
        'sentiment_score': float(data.get('sentiment_score', 0.5)),
        'sentiment_reasoning': data.get('sentiment_reasoning', ''),
        'topics': json.dumps(data.get('topics', [])),
        'risk_flag': 1 if data.get('risk_flag') else 0,
    })
    conn.commit()
    article_id = cur.lastrowid
    conn.close()
    return article_id


# ── Interactions ──────────────────────────────────────────────────────────────

def log_interaction(data: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO journalist_interactions (journalist_id, type, date, notes, draft_id)
        VALUES (:journalist_id,:type,:date,:notes,:draft_id)
    """, {
        'journalist_id': data['journalist_id'],
        'type': data.get('type', 'email'),
        'date': data.get('date', datetime.now().strftime('%Y-%m-%d')),
        'notes': data.get('notes', ''),
        'draft_id': data.get('draft_id'),
    })
    conn.commit()
    iid = cur.lastrowid
    conn.close()
    return iid


def list_interactions(journalist_id):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM journalist_interactions WHERE journalist_id = ? ORDER BY date DESC, created_at DESC",
        (journalist_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Alerts ────────────────────────────────────────────────────────────────────

def create_alert(data: dict):
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO media_alerts (type, entity_id, entity_type, message, severity, status)
        VALUES (:type,:entity_id,:entity_type,:message,:severity,'unread')
    """, {
        'type': data.get('type', 'negative_article'),
        'entity_id': data.get('entity_id'),
        'entity_type': data.get('entity_type', ''),
        'message': data.get('message', ''),
        'severity': data.get('severity', 'medium'),
    })
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def list_alerts(status='', severity=''):
    conn = _get_conn()
    q = "SELECT * FROM media_alerts WHERE 1=1"
    args = []
    if status:
        q += " AND status = ?"
        args.append(status)
    if severity:
        q += " AND severity = ?"
        args.append(severity)
    q += " ORDER BY created_at DESC LIMIT 100"
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_alert_status(alert_id, status):
    conn = _get_conn()
    conn.execute("UPDATE media_alerts SET status = ? WHERE id = ?", (status, alert_id))
    conn.commit()
    conn.close()


# ── Risk scoring ──────────────────────────────────────────────────────────────

def recalculate_risk(journalist_id):
    conn = _get_conn()
    rows = conn.execute(
        "SELECT sentiment FROM media_articles WHERE journalist_id = ?", (journalist_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return {'score': 0, 'label': 'safe'}
    total = len(rows)
    negative = sum(1 for r in rows if r['sentiment'] == 'negative')
    score = round((negative / total) * 100)
    label = 'safe' if score <= 33 else ('neutral' if score <= 66 else 'threat')
    update_journalist(journalist_id, {'risk_score': score, 'risk_label': label})
    return {'score': score, 'label': label}


# ── Stats ─────────────────────────────────────────────────────────────────────

def media_stats():
    conn = _get_conn()
    j_total  = conn.execute("SELECT COUNT(*) FROM journalists").fetchone()[0]
    j_safe   = conn.execute("SELECT COUNT(*) FROM journalists WHERE COALESCE(risk_override_label,risk_label)='safe'").fetchone()[0]
    j_neutral= conn.execute("SELECT COUNT(*) FROM journalists WHERE COALESCE(risk_override_label,risk_label)='neutral'").fetchone()[0]
    j_threat = conn.execute("SELECT COUNT(*) FROM journalists WHERE COALESCE(risk_override_label,risk_label)='threat'").fetchone()[0]
    a_total  = conn.execute("SELECT COUNT(*) FROM media_articles").fetchone()[0]
    a_pos    = conn.execute("SELECT COUNT(*) FROM media_articles WHERE sentiment='positive'").fetchone()[0]
    a_neg    = conn.execute("SELECT COUNT(*) FROM media_articles WHERE sentiment='negative'").fetchone()[0]
    a_neu    = conn.execute("SELECT COUNT(*) FROM media_articles WHERE sentiment='neutral'").fetchone()[0]
    a_risk   = conn.execute("SELECT COUNT(*) FROM media_articles WHERE risk_flag=1").fetchone()[0]
    alerts_u = conn.execute("SELECT COUNT(*) FROM media_alerts WHERE status='unread'").fetchone()[0]
    conn.close()
    return {
        'journalists': {'total': j_total, 'safe': j_safe, 'neutral': j_neutral, 'threat': j_threat},
        'articles': {'total': a_total, 'positive': a_pos, 'neutral': a_neu, 'negative': a_neg, 'flagged': a_risk},
        'alerts_unread': alerts_u,
    }
