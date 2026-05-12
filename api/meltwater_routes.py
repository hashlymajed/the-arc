"""Meltwater integration API routes."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/meltwater", tags=["meltwater"])


def _key(settings: dict) -> str:
    key = settings.get("meltwater_api_key", "")
    if not key:
        raise ValueError("No Meltwater API key configured. Add it in Settings.")
    return key


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/status")
async def meltwater_status():
    from api.meltwater_db import init_meltwater_db, sync_stats
    from api.db import get_settings
    init_meltwater_db()
    s = get_settings()
    has_key = bool(s.get("meltwater_api_key", "").strip())
    stats = sync_stats()
    return {"configured": has_key, **stats}


@router.post("/test")
async def test_meltwater(request: Request):
    from api.meltwater import test_connection
    data = await request.json()
    key  = data.get("api_key", "")
    if not key:
        return JSONResponse({"ok": False, "error": "API key required"}, status_code=400)
    return await test_connection(key)


# ── Searches ──────────────────────────────────────────────────────────────────

@router.get("/searches")
async def list_mw_searches():
    from api.meltwater import list_searches
    from api.meltwater_db import init_meltwater_db, list_search_configs
    from api.db import get_settings
    init_meltwater_db()
    s = get_settings()
    try:
        key      = _key(s)
        searches = await list_searches(key)
        configs  = {c['search_id']: c for c in list_search_configs()}
        for sr in searches:
            sid = sr.get("id") or sr.get("search_id", "")
            sr["auto_sync"]   = bool(configs.get(sid, {}).get("auto_sync", False))
            sr["last_synced"] = configs.get(sid, {}).get("last_synced")
        return searches
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/searches/{search_id}/watch")
async def toggle_watch(search_id: str, request: Request):
    from api.meltwater_db import init_meltwater_db, upsert_search_config
    init_meltwater_db()
    data = await request.json()
    upsert_search_config(search_id, data.get("name", ""), data.get("auto_sync", True))
    return {"ok": True}


# ── Article Sync ──────────────────────────────────────────────────────────────

@router.post("/sync/articles")
async def sync_articles(request: Request):
    from api.meltwater import fetch_documents
    from api.meltwater_db import init_meltwater_db, log_sync, update_last_synced
    from api.media_db import (create_article, create_publication, list_publications,
                               recalculate_risk, create_alert, list_journalists, init_media_db)
    from api.db import get_settings
    init_meltwater_db()
    init_media_db()
    data = await request.json()

    s         = get_settings()
    key       = _key(s)
    search_id = data.get("search_id", "")
    days_back = min(int(data.get("days_back", 7)), 90)

    if not search_id:
        return JSONResponse({"error": "search_id required"}, status_code=400)

    try:
        docs = await fetch_documents(key, search_id, days_back=days_back)
    except Exception as e:
        log_sync("articles", search_id, 0, "error", str(e))
        return JSONResponse({"error": str(e)}, status_code=500)

    pub_cache  = {p["name"]: p["id"] for p in list_publications()}
    jour_cache = {j["name"]: j["id"] for j in list_journalists()}
    count = 0

    for doc in docs:
        pub_id  = None
        jour_id = None

        if doc["source_name"]:
            if doc["source_name"] not in pub_cache:
                pid = create_publication({"name": doc["source_name"], "type": "online", "tier": 2})
                pub_cache[doc["source_name"]] = pid
            pub_id = pub_cache[doc["source_name"]]

        if doc["author_name"]:
            if doc["author_name"] not in jour_cache:
                from api.media_db import create_journalist
                jid = create_journalist({"name": doc["author_name"], "notes": "Auto-imported from Meltwater"})
                jour_cache[doc["author_name"]] = jid
            jour_id = jour_cache[doc["author_name"]]

        try:
            aid = create_article({
                "title":               doc["title"],
                "url":                 doc["url"],
                "publication_id":      pub_id,
                "journalist_id":       jour_id,
                "published_at":        doc["published_at"],
                "content_snippet":     doc["content_snippet"],
                "sentiment":           doc["sentiment"],
                "sentiment_score":     doc["sentiment_score"],
                "sentiment_reasoning": f"Meltwater analysis · reach {doc.get('reach', 0):,}",
                "topics":              doc["topics"],
                "risk_flag":           doc["sentiment"] == "negative" and doc["sentiment_score"] < 0.3,
            })
            if jour_id:
                recalculate_risk(jour_id)
            if doc["sentiment"] == "negative":
                create_alert({
                    "type":        "negative_article",
                    "entity_id":   aid,
                    "entity_type": "article",
                    "message":     f"Negative article via Meltwater: {doc['title']}" + (f" — by {doc['author_name']}" if doc['author_name'] else ""),
                    "severity":    "high" if doc["sentiment_score"] < 0.3 else "medium",
                })
            count += 1
        except Exception:
            pass

    update_last_synced(search_id)
    log_sync("articles", search_id, count)
    return {"ok": True, "synced": count}


# ── Journalist Import ─────────────────────────────────────────────────────────

@router.post("/sync/journalists")
async def sync_journalists(request: Request):
    from api.meltwater import fetch_journalist_contacts
    from api.meltwater_db import init_meltwater_db, log_sync
    from api.media_db import create_journalist, list_journalists, list_publications, create_publication, init_media_db
    from api.db import get_settings
    init_meltwater_db()
    init_media_db()
    data = await request.json()

    s     = get_settings()
    key   = _key(s)
    query = data.get("query", "")
    limit = min(int(data.get("limit", 50)), 200)

    try:
        contacts = await fetch_journalist_contacts(key, query, limit)
    except PermissionError as e:
        return JSONResponse({"error": str(e)}, status_code=403)
    except Exception as e:
        log_sync("journalists", query, 0, "error", str(e))
        return JSONResponse({"error": str(e)}, status_code=500)

    existing_names = {j["name"] for j in list_journalists()}
    pub_cache      = {p["name"]: p["id"] for p in list_publications()}
    count = 0

    for c in contacts:
        if c["name"] in existing_names:
            continue
        try:
            jid = create_journalist({k: v for k, v in c.items() if k != "publication_names"})
            existing_names.add(c["name"])
            for pub_name in c.get("publication_names", []):
                if pub_name not in pub_cache:
                    pid = create_publication({"name": pub_name, "type": "online", "tier": 2})
                    pub_cache[pub_name] = pid
                from api.media_db import link_journalist_publication
                try:
                    link_journalist_publication(jid, pub_cache[pub_name], "staff")
                except Exception:
                    pass
            count += 1
        except Exception:
            pass

    log_sync("journalists", query, count)
    return {"ok": True, "imported": count, "skipped": len(contacts) - count}


# ── Mention Alerts Sync ───────────────────────────────────────────────────────

@router.post("/sync/mentions")
async def sync_mentions(request: Request):
    from api.meltwater import fetch_mentions
    from api.meltwater_db import init_meltwater_db, log_sync
    from api.media_db import create_alert, init_media_db
    from api.db import get_settings
    init_meltwater_db()
    init_media_db()
    data = await request.json()

    s         = get_settings()
    key       = _key(s)
    keyword   = data.get("keyword", s.get("org_name", "Aldar"))
    days_back = int(data.get("days_back", 1))

    try:
        mentions = await fetch_mentions(key, keyword, days_back)
    except Exception as e:
        log_sync("mentions", keyword, 0, "error", str(e))
        return JSONResponse({"error": str(e)}, status_code=500)

    count = 0
    for m in mentions:
        if m["sentiment"] == "negative":
            try:
                create_alert({
                    "type":        "negative_article",
                    "entity_id":   0,
                    "entity_type": "mention",
                    "message":     f"[Meltwater mention] {m['title']}",
                    "severity":    "medium",
                })
                count += 1
            except Exception:
                pass

    log_sync("mentions", keyword, count)
    return {"ok": True, "mentions": len(mentions), "alerts_created": count}


# ── Sync Log ──────────────────────────────────────────────────────────────────

@router.get("/sync/log")
async def get_sync_log():
    from api.meltwater_db import init_meltwater_db, get_sync_log
    init_meltwater_db()
    return get_sync_log(30)
