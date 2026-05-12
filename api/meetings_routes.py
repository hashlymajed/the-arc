"""Meeting Intelligence API routes."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


@router.get("/stats")
async def get_meetings_stats():
    from api.meetings_db import meetings_stats, init_meetings_db
    init_meetings_db()
    return meetings_stats()


@router.get("")
async def list_meetings_route():
    from api.meetings_db import list_meetings, init_meetings_db
    init_meetings_db()
    return list_meetings()


@router.post("")
async def create_meeting_route(request: Request):
    from api.meetings_db import create_meeting, save_meeting_results, update_meeting_status, init_meetings_db
    from api.meetings_ai import generate_mom
    from api.db import get_settings
    init_meetings_db()
    data = await request.json()

    transcript = data.get('transcript', '').strip()
    if not transcript:
        return JSONResponse({'error': 'transcript is required'}, status_code=400)

    title = data.get('title') or 'Processing…'
    mid = create_meeting({
        'title':            title,
        'meeting_date':     data.get('meeting_date', ''),
        'context':          data.get('context', ''),
        'participant_names': data.get('participant_names', []),
        'status':           'processing',
    })

    settings = get_settings()
    try:
        result = await generate_mom(
            transcript=transcript,
            context=data.get('context', ''),
            participant_list=data.get('participant_names_text', ''),
            settings=settings,
        )
        save_meeting_results(mid, result)
        return {'id': mid, 'ok': True, 'title': result.get('meeting_title', title)}
    except Exception as e:
        update_meeting_status(mid, 'failed')
        return JSONResponse({'error': str(e), 'id': mid}, status_code=500)


@router.get("/{mid}")
async def get_meeting_route(mid: int):
    from api.meetings_db import get_meeting, init_meetings_db
    init_meetings_db()
    m = get_meeting(mid)
    if not m:
        raise HTTPException(404)
    return m


@router.delete("/{mid}")
async def delete_meeting_route(mid: int):
    from api.meetings_db import get_meeting, delete_meeting, init_meetings_db
    init_meetings_db()
    if not get_meeting(mid):
        raise HTTPException(404)
    delete_meeting(mid)
    return {'ok': True}


@router.post("/{mid}/archive")
async def archive_meeting_route(mid: int):
    from api.meetings_db import get_meeting, archive_meeting, init_meetings_db
    init_meetings_db()
    if not get_meeting(mid):
        raise HTTPException(404)
    archive_meeting(mid)
    return {'ok': True}


@router.put("/actions/{action_id}/status")
async def update_action_status_route(action_id: int, request: Request):
    from api.meetings_db import update_action_status, init_meetings_db
    init_meetings_db()
    data = await request.json()
    status = data.get('status', 'open')
    if status not in ('open', 'done'):
        return JSONResponse({'error': 'invalid status'}, status_code=400)
    update_action_status(action_id, status)
    return {'ok': True}
