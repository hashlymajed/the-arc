"""Auth routes — login / logout / me."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

@router.post("/api/auth/login")
async def api_login(request: Request):
    from api.auth_db import init_auth_db, verify_user
    init_auth_db()
    data = await request.json()
    user = verify_user(data.get('username', ''), data.get('password', ''))
    if not user:
        return JSONResponse({'error': 'Invalid username or password'}, status_code=401)
    request.session['user_id']   = user['id']
    request.session['user_name'] = user['name']
    request.session['user_role'] = user['role']
    return {'ok': True, 'name': user['name'], 'role': user['role']}

@router.post("/api/auth/logout")
async def api_logout(request: Request):
    request.session.clear()
    return {'ok': True}

@router.get("/api/auth/me")
async def api_me(request: Request):
    uid = request.session.get('user_id')
    if not uid:
        return JSONResponse({'authenticated': False}, status_code=401)
    return {
        'authenticated': True,
        'id':   uid,
        'name': request.session.get('user_name'),
        'role': request.session.get('user_role'),
    }
