"""Media Relations API routes."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/media", tags=["media"])


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_media_stats():
    from api.media_db import media_stats, init_media_db
    init_media_db()
    return media_stats()


# ── Publications ──────────────────────────────────────────────────────────────

@router.get("/publications")
async def list_publications_route():
    from api.media_db import list_publications, init_media_db
    init_media_db()
    return list_publications()


@router.post("/publications")
async def create_publication_route(request: Request):
    from api.media_db import create_publication, init_media_db
    init_media_db()
    data = await request.json()
    if not data.get('name'):
        return JSONResponse({'error': 'name required'}, status_code=400)
    pub_id = create_publication(data)
    return {'id': pub_id, 'ok': True}


# ── Journalists ───────────────────────────────────────────────────────────────

@router.get("/journalists")
async def list_journalists_route(search: str = '', risk_label: str = '', region: str = ''):
    from api.media_db import list_journalists, init_media_db
    init_media_db()
    return list_journalists(search=search, risk_label=risk_label, region=region)


@router.get("/journalists/{jid}")
async def get_journalist_route(jid: int):
    from api.media_db import (get_journalist, get_journalist_publications,
                               list_articles, list_interactions, init_media_db)
    init_media_db()
    j = get_journalist(jid)
    if not j:
        raise HTTPException(404)
    j['publications']  = get_journalist_publications(jid)
    j['articles']      = list_articles(journalist_id=jid, limit=20)
    j['interactions']  = list_interactions(jid)
    return j


@router.post("/journalists")
async def create_journalist_route(request: Request):
    from api.media_db import create_journalist, init_media_db
    init_media_db()
    data = await request.json()
    if not data.get('name'):
        return JSONResponse({'error': 'name required'}, status_code=400)
    jid = create_journalist(data)
    return {'id': jid, 'ok': True}


@router.put("/journalists/{jid}")
async def update_journalist_route(jid: int, request: Request):
    from api.media_db import get_journalist, update_journalist, init_media_db
    init_media_db()
    if not get_journalist(jid):
        raise HTTPException(404)
    data = await request.json()
    update_journalist(jid, data)
    return {'ok': True}


@router.delete("/journalists/{jid}")
async def delete_journalist_route(jid: int):
    from api.media_db import get_journalist, delete_journalist, init_media_db
    init_media_db()
    if not get_journalist(jid):
        raise HTTPException(404)
    delete_journalist(jid)
    return {'ok': True}


@router.post("/journalists/{jid}/risk-override")
async def risk_override_route(jid: int, request: Request):
    from api.media_db import get_journalist, update_journalist, init_media_db
    init_media_db()
    if not get_journalist(jid):
        raise HTTPException(404)
    data = await request.json()
    label = data.get('label', '')
    if label not in ('safe', 'neutral', 'threat', ''):
        return JSONResponse({'error': 'invalid label'}, status_code=400)
    update_journalist(jid, {
        'risk_override_label':  label or None,
        'risk_override_reason': data.get('reason', ''),
        'risk_override_by':     data.get('override_by', 'admin'),
    })
    return {'ok': True}


@router.post("/journalists/{jid}/interactions")
async def log_interaction_route(jid: int, request: Request):
    from api.media_db import get_journalist, log_interaction, init_media_db
    init_media_db()
    if not get_journalist(jid):
        raise HTTPException(404)
    data = await request.json()
    data['journalist_id'] = jid
    iid = log_interaction(data)
    return {'id': iid, 'ok': True}


# ── Articles ──────────────────────────────────────────────────────────────────

@router.get("/articles")
async def list_articles_route(
    sentiment: str = '',
    journalist_id: Optional[int] = None,
    publication_id: Optional[int] = None,
    risk_flag: str = '',
    limit: int = 50,
):
    from api.media_db import list_articles, init_media_db
    init_media_db()
    rf = True if risk_flag == '1' else (False if risk_flag == '0' else None)
    return list_articles(
        sentiment=sentiment,
        journalist_id=journalist_id,
        publication_id=publication_id,
        risk_flag=rf,
        limit=min(limit, 100),
    )


@router.post("/articles")
async def ingest_article_route(request: Request):
    from api.media_db import create_article, recalculate_risk, create_alert, get_journalist, init_media_db
    from api.media_ai import analyze_article
    from api.db import get_settings
    init_media_db()
    data = await request.json()
    if not data.get('title'):
        return JSONResponse({'error': 'title required'}, status_code=400)

    settings = get_settings()
    ai_result = {'sentiment': 'neutral', 'sentiment_score': 0.5,
                 'topics': [], 'risk_flag': False, 'reasoning': ''}
    try:
        ai_result = await analyze_article(
            data['title'], data.get('content_snippet', ''), settings
        )
    except Exception:
        pass

    article_id = create_article({
        'title':               data['title'],
        'url':                 data.get('url', ''),
        'publication_id':      data.get('publication_id'),
        'journalist_id':       data.get('journalist_id'),
        'published_at':        data.get('published_at', ''),
        'content_snippet':     data.get('content_snippet', ''),
        'sentiment':           ai_result['sentiment'],
        'sentiment_score':     ai_result['sentiment_score'],
        'sentiment_reasoning': ai_result['reasoning'],
        'topics':              ai_result['topics'],
        'risk_flag':           ai_result['risk_flag'],
    })

    if data.get('journalist_id'):
        recalculate_risk(data['journalist_id'])

    if ai_result['sentiment'] == 'negative' or ai_result['risk_flag']:
        journalist_name = ''
        if data.get('journalist_id'):
            j = get_journalist(data['journalist_id'])
            journalist_name = j['name'] if j else ''
        severity = 'high' if ai_result['risk_flag'] else 'medium'
        create_alert({
            'type':        'negative_article',
            'entity_id':   article_id,
            'entity_type': 'article',
            'message':     f"{'Flagged' if ai_result['risk_flag'] else 'Negative'} article: {data['title']}"
                           + (f" — by {journalist_name}" if journalist_name else ""),
            'severity':    severity,
        })

    return {'id': article_id, 'ok': True, 'analysis': ai_result}


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts_route(status: str = '', severity: str = ''):
    from api.media_db import list_alerts, init_media_db
    init_media_db()
    return list_alerts(status=status, severity=severity)


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert_route(alert_id: int):
    from api.media_db import update_alert_status, init_media_db
    init_media_db()
    update_alert_status(alert_id, 'resolved')
    return {'ok': True}


@router.post("/alerts/{alert_id}/reopen")
async def reopen_alert_route(alert_id: int):
    from api.media_db import update_alert_status, init_media_db
    init_media_db()
    update_alert_status(alert_id, 'unread')
    return {'ok': True}


@router.post("/alerts/{alert_id}/crisis-analysis")
async def crisis_analysis_route(alert_id: int):
    from api.media_db import list_alerts, init_media_db
    from api.media_ai import crisis_analysis
    from api.db import get_settings
    init_media_db()
    alerts = list_alerts()
    alert = next((a for a in alerts if a['id'] == alert_id), None)
    if not alert:
        raise HTTPException(404)
    settings = get_settings()
    try:
        result = await crisis_analysis(
            alert_message=alert['message'],
            alert_type=alert.get('type', ''),
            severity=alert.get('severity', 'medium'),
            settings=settings,
        )
        return result
    except Exception as e:
        return JSONResponse({'error': str(e)}, status_code=500)
