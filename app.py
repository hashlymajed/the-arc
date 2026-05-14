"""The Arc — Aldar AI Strategic Communications Platform"""
import os, sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR   = Path(__file__).parent
TEMPLATES  = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="The Arc", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

from api.auth_routes import router as auth_router
app.include_router(auth_router)

from api.media_routes import router as media_router
app.include_router(media_router)

from api.meetings_routes import router as meetings_router
app.include_router(meetings_router)

from api.meltwater_routes import router as meltwater_router
app.include_router(meltwater_router)

_PUBLIC = ("/login", "/api/auth/login", "/static")

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _PUBLIC):
        return await call_next(request)
    uid = request.session.get('user_id')
    if not uid:
        return RedirectResponse("/login", status_code=302)
    request.state.user = {
        'id':   uid,
        'name': request.session.get('user_name', ''),
        'role': request.session.get('user_role', 'user'),
    }
    return await call_next(request)

# SessionMiddleware must be added AFTER auth_guard so it wraps it (outermost runs first).
# add_middleware uses insert(0,...) — later adds become outer.
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SECRET_KEY', 'arc-dev-secret-2026'))

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get('user_id'):
        return RedirectResponse("/", status_code=302)
    return TEMPLATES.TemplateResponse(request, "login.html", {})

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

# Lazy imports — only load heavy libs when first needed
def get_db():
    from api.db import init_db, get_conn
    init_db()
    return get_conn

def _settings():
    from api.db import init_db, get_settings
    init_db()
    return get_settings()

def _today():
    return datetime.now().strftime("%d %B %Y")

# ─── Page routes ──────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from api.db import init_db, list_drafts, get_settings
    init_db()
    s = get_settings()

    # news preview from existing SQLite
    news_db = s.get('news_db_path') or str(BASE_DIR / "data" / "news_articles.db")
    recent_news = []
    try:
        conn = sqlite3.connect(news_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title, date_string FROM articles ORDER BY scraped_at DESC LIMIT 8").fetchall()
        recent_news = [dict(r) for r in rows]
        conn.close()
    except Exception:
        pass

    all_drafts = list_drafts(limit=20)
    recent = [dict(d, updated_at=d['updated_at'][:16] if d['updated_at'] else '—') for d in all_drafts[:6]]
    queue  = [dict(d, updated_at=d['updated_at'][:16] if d['updated_at'] else '—', reviewer='—')
              for d in all_drafts if d['status'] in ('review', 'approved')][:6]

    stats = {
        'drafts':       sum(1 for d in all_drafts if d['status'] == 'draft'),
        'pending':      sum(1 for d in all_drafts if d['status'] in ('review',)),
        'published':    sum(1 for d in all_drafts if d['status'] == 'published'),
        'vault_docs':   _count_vault_docs(s),
        'news_articles': len(recent_news) or _count_news(s),
    }

    return TEMPLATES.TemplateResponse(request, "dashboard.html", {
        "active": "home",
        "today": _today(), "stats": stats,
        "recent_drafts": recent, "queue_items": queue,
        "recent_news": recent_news,
        "draft_count": stats['drafts'] or None,
        "pending_count": stats['pending'] or None,
    })

@app.get("/draft", response_class=HTMLResponse)
async def draft_list(request: Request):
    from api.db import init_db, list_drafts
    init_db()
    drafts = list_drafts(limit=100)
    return TEMPLATES.TemplateResponse(request, "draft.html", {
        "active": "draft",
        "draft": {}, "draft_count": None, "pending_count": None,
    })

@app.get("/draft/new", response_class=HTMLResponse)
async def draft_new(request: Request, channel: str = "Press Release", vault_context: str = ""):
    from api.db import init_db
    init_db()
    return TEMPLATES.TemplateResponse(request, "draft.html", {
        "active": "draft",
        "draft": {"channel": channel, "vault_context": vault_context},
        "draft_count": None, "pending_count": None,
    })

@app.get("/draft/{draft_id}", response_class=HTMLResponse)
async def draft_edit(request: Request, draft_id: int):
    from api.db import init_db, get_draft
    init_db()
    draft = get_draft(draft_id) or {}
    return TEMPLATES.TemplateResponse(request, "draft.html", {
        "active": "draft",
        "draft": draft, "draft_count": None, "pending_count": None,
    })

@app.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    from api.db import init_db, list_drafts, drafts_by_status
    init_db()
    by_status = drafts_by_status()
    all_items = []
    for items in by_status.values():
        all_items.extend(items)
    all_items.sort(key=lambda x: x.get('updated_at',''), reverse=True)
    return TEMPLATES.TemplateResponse(request, "queue.html", {
        "active": "queue",
        "items_by_status": by_status,
        "all_items": [dict(d, updated_at=d['updated_at'][:16] if d['updated_at'] else '—') for d in all_items],
        "draft_count": None, "pending_count": len(by_status.get('review', [])) or None,
    })

@app.get("/vault", response_class=HTMLResponse)
async def vault_page(request: Request, q: str = ""):
    from api.vault import list_docs, vault_stats
    s = _settings()
    try:
        docs   = list_docs(s)
        vstats = vault_stats(s)
    except Exception:
        docs   = []
        vstats = {'doc_count': 0, 'chunk_count': 0, 'index_age': '—', 'embedding_model': '—'}
    return TEMPLATES.TemplateResponse(request, "vault.html", {
        "active": "vault",
        "documents": docs, "draft_count": None, "pending_count": None,
        **vstats,
    })

@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request):
    s = _settings()
    news_db = s.get('news_db_path') or str(BASE_DIR / "data" / "news_articles.db")
    articles, year_list, total = [], [], 0
    try:
        conn = sqlite3.connect(news_db)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, title, url, date_string FROM articles ORDER BY date_string DESC").fetchall()
        for r in rows:
            d = dict(r)
            year = (d.get('date_string') or '')[:4]
            d['year'] = year
            articles.append(d)
        year_list = sorted(set(a['year'] for a in articles if a['year']), reverse=True)
        total = len(articles)
        conn.close()
    except Exception:
        pass
    years = f"{year_list[-1]}–{year_list[0]}" if len(year_list) > 1 else (year_list[0] if year_list else '2024–2025')
    return TEMPLATES.TemplateResponse(request, "news.html", {
        "active": "news",
        "articles": articles, "year_list": year_list,
        "total": total, "years": years,
        "draft_count": None, "pending_count": None,
    })

@app.get("/intelligence", response_class=HTMLResponse)
async def intelligence_page(request: Request):
    return TEMPLATES.TemplateResponse(request, "intelligence.html", {
        "active": "intelligence",
        "draft_count": None, "pending_count": None,
    })

@app.post("/api/intelligence/analyze")
async def api_intelligence_analyze(request: Request):
    from api import ai
    from api.vault import list_docs, get_doc_content
    data = await request.json()
    s = _settings()
    try:
        docs_meta = list_docs(s)
        vault_docs = []
        for d in docs_meta[:60]:  # cap at 60 to keep within token limits
            content = get_doc_content(d['filename'], s)
            vault_docs.append({'filename': d['filename'], 'content': content.get('content', '')})
        if not vault_docs:
            return JSONResponse({'error': 'No vault documents found. Check vault path in Settings.'}, status_code=400)
        result = await ai.analyze(
            vault_docs,
            s,
            spokespeople=data.get('spokespeople', ''),
            pillars=data.get('pillars', ''),
        )
        return result
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/intelligence/translate")
async def api_intelligence_translate(request: Request):
    from api import ai
    data = await request.json()
    s = _settings()
    try:
        return await ai.translate(data['content'], data.get('target', 'Arabic (MSA)'), data.get('tone', 'Premium & Confident'), s)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    s = _settings()
    return TEMPLATES.TemplateResponse(request, "settings.html", {
        "active": "settings",
        "settings": s, "draft_count": None, "pending_count": None,
    })

@app.get("/media", response_class=HTMLResponse)
async def media_page(request: Request):
    from api.media_db import init_media_db
    init_media_db()
    return TEMPLATES.TemplateResponse(request, "media.html", {
        "active": "media", "draft_count": None, "pending_count": None,
    })

@app.get("/media/journalist/{jid}", response_class=HTMLResponse)
async def media_journalist_page(request: Request, jid: int):
    from api.media_db import init_media_db
    init_media_db()
    return TEMPLATES.TemplateResponse(request, "media_journalist.html", {
        "active": "media", "jid": jid, "draft_count": None, "pending_count": None,
    })

@app.get("/media/monitor", response_class=HTMLResponse)
async def media_monitor_page(request: Request):
    from api.media_db import init_media_db
    init_media_db()
    return TEMPLATES.TemplateResponse(request, "media_monitor.html", {
        "active": "media", "draft_count": None, "pending_count": None,
    })

@app.get("/media/alerts", response_class=HTMLResponse)
async def media_alerts_page(request: Request):
    from api.media_db import init_media_db
    init_media_db()
    return TEMPLATES.TemplateResponse(request, "media_alerts.html", {
        "active": "media", "draft_count": None, "pending_count": None,
    })

@app.get("/meetings", response_class=HTMLResponse)
async def meetings_page(request: Request):
    from api.meetings_db import init_meetings_db
    init_meetings_db()
    return TEMPLATES.TemplateResponse(request, "meetings.html", {
        "active": "meetings", "draft_count": None, "pending_count": None,
    })

@app.get("/meetings/{mid}", response_class=HTMLResponse)
async def meeting_detail_page(request: Request, mid: int):
    from api.meetings_db import init_meetings_db
    init_meetings_db()
    return TEMPLATES.TemplateResponse(request, "meeting_detail.html", {
        "active": "meetings", "mid": mid, "draft_count": None, "pending_count": None,
    })

@app.get("/meltwater", response_class=HTMLResponse)
async def meltwater_page(request: Request):
    from api.meltwater_db import init_meltwater_db
    init_meltwater_db()
    return TEMPLATES.TemplateResponse(request, "meltwater.html", {
        "active": "meltwater", "draft_count": None, "pending_count": None,
    })


@app.get("/archive", response_class=HTMLResponse)
async def archive_page(request: Request):
    from api.db import init_db, list_drafts
    init_db()
    published = list_drafts(status='published')
    return TEMPLATES.TemplateResponse(request, "queue.html", {
        "active": "archive",
        "items_by_status": {'draft':[],'review':[],'approved':[],'published': published},
        "all_items": published, "draft_count": None, "pending_count": None,
    })

# ─── API routes ───────────────────────────────────────────────────────────────

@app.get("/api/stats")
async def api_stats():
    from api.db import init_db, list_drafts
    from api.vault import vault_stats
    init_db()
    s = _settings()
    all_d = list_drafts(limit=500)
    vstats = vault_stats(s)
    return {
        'drafts':        sum(1 for d in all_d if d['status'] == 'draft'),
        'pending':       sum(1 for d in all_d if d['status'] == 'review'),
        'published':     sum(1 for d in all_d if d['status'] == 'published'),
        'vault_docs':    vstats['doc_count'],
        'news_articles': _count_news(s),
    }

@app.get("/api/draft/{draft_id}")
async def api_get_draft(draft_id: int):
    from api.db import init_db, get_draft
    init_db()
    d = get_draft(draft_id)
    if not d: raise HTTPException(404)
    return d

@app.post("/api/draft/generate")
async def api_generate(request: Request):
    from api import ai
    from api.vault import search as vault_search
    data = await request.json()
    s = _settings()
    vault_ctx = ''
    intel = []
    if data.get('brief'):
        results = vault_search(data['brief'], s, k=5)
        vault_ctx = "\n\n".join(f"[{r['source']}]\n{r['excerpt']}" for r in results)
        intel = results
    try:
        result = await ai.generate(data, s, vault_ctx)
        result['intel'] = intel
        return result
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/draft/refine")
async def api_refine(request: Request):
    from api import ai
    data = await request.json()
    s = _settings()
    try:
        return await ai.refine(data['content'], data['action'], data.get('channel',''), s)
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)

@app.post("/api/draft/save")
async def api_save_draft(request: Request):
    from api.db import init_db, create_draft, update_draft, log_activity
    init_db()
    data = await request.json()
    author = data.get('author', 'system')
    draft_id = data.get('id')
    if draft_id:
        update_draft(int(draft_id), data)
        log_activity(int(draft_id), author, 'edited')
        return {'id': int(draft_id), 'ok': True}
    else:
        new_id = create_draft({
            'title':         data.get('title', 'Untitled Draft'),
            'channel':       data.get('channel', 'Press Release'),
            'audience':      data.get('audience', ''),
            'tone':          data.get('tone', ''),
            'brief':         data.get('brief', ''),
            'vault_context': data.get('vault_context', ''),
            'content':       data.get('content', ''),
            'author':        author,
        })
        log_activity(new_id, author, 'created')
        return {'id': new_id, 'ok': True}

@app.post("/api/draft/submit")
async def api_submit_draft(request: Request):
    from api.db import init_db, update_draft, log_activity
    init_db()
    data = await request.json()
    if not data.get('id'): return JSONResponse({'error': 'No id'}, status_code=400)
    draft_id = int(data['id'])
    update_draft(draft_id, {'status': 'review'})
    log_activity(draft_id, data.get('author', 'system'), 'submitted_for_review')
    return {'ok': True}

@app.post("/api/draft/status")
async def api_update_status(request: Request):
    from api.db import init_db, update_draft, log_activity
    init_db()
    data = await request.json()
    draft_id = int(data['id'])
    update_draft(draft_id, {'status': data['status'], 'review_notes': data.get('review_notes', '')})
    log_activity(draft_id, data.get('author', 'system'), data['status'], data.get('review_notes', ''))
    return {'ok': True}

@app.get("/api/draft/{draft_id}/activity")
async def api_get_draft_activity(draft_id: int):
    from api.db import init_db, get_draft, get_draft_activity
    init_db()
    if not get_draft(draft_id):
        raise HTTPException(404)
    return get_draft_activity(draft_id)

@app.get("/api/tags")
async def api_list_tags():
    from api.db import init_db, list_tags
    init_db()
    return list_tags()


@app.post("/api/tags")
async def api_create_tag(request: Request):
    from api.db import init_db, create_tag
    init_db()
    data = await request.json()
    if not data.get("name"):
        return JSONResponse({"error": "name required"}, status_code=400)
    tag_id = create_tag(data["name"], data.get("color", "#6B7280"))
    return {"id": tag_id, "ok": True}


@app.delete("/api/tags/{tag_id}")
async def api_delete_tag(tag_id: int):
    from api.db import init_db, delete_tag
    init_db()
    delete_tag(tag_id)
    return {"ok": True}


@app.get("/api/draft/{draft_id}/tags")
async def api_get_draft_tags(draft_id: int):
    from api.db import init_db, get_draft, get_draft_tags
    init_db()
    if not get_draft(draft_id):
        raise HTTPException(404)
    return get_draft_tags(draft_id)


@app.post("/api/draft/{draft_id}/tags/{tag_id}")
async def api_add_draft_tag(draft_id: int, tag_id: int):
    from api.db import init_db, get_draft, add_draft_tag
    init_db()
    if not get_draft(draft_id):
        raise HTTPException(404)
    add_draft_tag(draft_id, tag_id)
    return {"ok": True}


@app.delete("/api/draft/{draft_id}/tags/{tag_id}")
async def api_remove_draft_tag(draft_id: int, tag_id: int):
    from api.db import init_db, remove_draft_tag
    init_db()
    remove_draft_tag(draft_id, tag_id)
    return {"ok": True}


@app.get("/api/vault/debug")
async def api_vault_debug():
    from api import vault
    s = _settings()
    resolved = vault._resolve_vault_path(s)
    info = {
        'cwd': os.getcwd(),
        'vault_py_file': vault.__file__,
        'env_VAULT_PATH': os.environ.get('VAULT_PATH'),
        'settings_vault_path': s.get('vault_path'),
        'DEFAULT_VAULT_PATH': vault.DEFAULT_VAULT_PATH,
        '_BUNDLED_PATH': vault._BUNDLED_PATH,
        'resolved_vault_path': resolved,
        'resolved_exists': os.path.isdir(resolved),
        'bundled_exists': os.path.isdir(vault._BUNDLED_PATH),
        'app_listing': sorted(os.listdir('/app'))[:30] if os.path.isdir('/app') else None,
    }
    if os.path.isdir(resolved):
        try:
            info['resolved_listing'] = sorted(os.listdir(resolved))[:30]
            md_count = sum(1 for r,_,fs in os.walk(resolved) for f in fs if f.endswith('.md'))
            info['md_count'] = md_count
        except Exception as e:
            info['error'] = str(e)
    return info


@app.get("/api/vault/search")
async def api_vault_search(q: str):
    from api.vault import search as vault_search
    s = _settings()
    return {'results': vault_search(q, s)}

@app.get("/api/vault/doc")
async def api_vault_doc(f: str):
    from api.vault import get_doc_content
    s = _settings()
    return get_doc_content(f, s)

@app.post("/api/vault/rebuild")
async def api_vault_rebuild():
    from api import vault
    s = _settings()
    try:
        vault._build_store(
            vault._resolve_vault_path(s),
            s.get('vector_db_path') or vault.DEFAULT_VECTOR_PATH,
            s.get('gemini_api_key') or os.getenv('GEMINI_API_KEY','')
        )
        return {'ok': True, 'message': 'Index rebuilt successfully'}
    except Exception as e:
        msg = str(e)
        if '429' in msg or 'RESOURCE_EXHAUSTED' in msg or 'quota' in msg.lower():
            msg = ("Gemini embedding quota hit. The free tier for gemini-embedding-001 "
                   "is ~5 requests/minute. Wait a few minutes and try again, or enable "
                   "billing in Google AI Studio for higher limits.")
        return JSONResponse({'ok': False, 'message': msg}, status_code=500)

@app.get("/api/news/{article_id}")
async def api_get_news(article_id: int):
    s = _settings()
    news_db = s.get('news_db_path') or str(BASE_DIR / "data" / "news_articles.db")
    try:
        conn = sqlite3.connect(news_db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        conn.close()
        if row: return dict(row)
    except Exception:
        pass
    raise HTTPException(404)

@app.post("/api/news/scrape")
async def api_scrape_news():
    import subprocess, sys
    scraper = str(BASE_DIR / "scripts" / "scraper.py")
    if not os.path.exists(scraper):
        return JSONResponse({'message': 'Scraper script not found.'}, status_code=404)
    news_db = str(BASE_DIR / "data" / "news_articles.db")
    try:
        subprocess.Popen([sys.executable, scraper], cwd=str(BASE_DIR / "scripts"), env={**os.environ, 'NEWS_DB': news_db})
        return {'message': 'Scraper started in background — new articles will appear on refresh'}
    except Exception as e:
        return JSONResponse({'message': f'Scraper could not start: {e}'}, status_code=500)

@app.get("/api/settings")
async def api_get_settings():
    return _settings()

@app.post("/api/settings")
async def api_save_settings(request: Request):
    from api.db import init_db, save_settings
    init_db()
    data = await request.json()
    save_settings(data)
    return {'ok': True}

@app.post("/api/settings/test")
async def api_test_connection(request: Request):
    from api import ai
    data = await request.json()
    return await ai.test_connection(data.get('gemini_api_key',''))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _count_vault_docs(settings: dict) -> int:
    from api.vault import list_docs
    try: return len(list_docs(settings))
    except Exception: return 0

def _count_news(settings: dict) -> int:
    news_db = settings.get('news_db_path') or str(BASE_DIR / "data" / "news_articles.db")
    try:
        conn = sqlite3.connect(news_db)
        count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
