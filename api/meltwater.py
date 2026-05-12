"""Meltwater API client — article sync, journalist import, mention alerts."""
import asyncio, requests
from datetime import datetime, timedelta

BASE_URL = "https://api.meltwater.com"


def _headers(api_key: str) -> dict:
    return {
        "Authorization": f"user-key {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _get(api_key: str, path: str, params: dict = None) -> dict:
    r = requests.get(BASE_URL + path, headers=_headers(api_key), params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def _post(api_key: str, path: str, body: dict = None) -> dict:
    r = requests.post(BASE_URL + path, headers=_headers(api_key), json=body or {}, timeout=30)
    r.raise_for_status()
    return r.json()


async def _run(fn, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn, *args)


# ── Connection ─────────────────────────────────────────────────────────────────

async def test_connection(api_key: str) -> dict:
    def _call():
        r = requests.get(
            BASE_URL + "/v2/searches",
            headers=_headers(api_key), timeout=10
        )
        return r.status_code, r.text
    try:
        status, text = await _run(_call)
        if status == 200:
            return {"ok": True}
        return {"ok": False, "error": f"HTTP {status} — {text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Searches ──────────────────────────────────────────────────────────────────

async def list_searches(api_key: str) -> list:
    def _call():
        return _get(api_key, "/v2/searches")
    data = await _run(_call)
    return data.get("searches", data if isinstance(data, list) else [])


# ── Documents / Articles ──────────────────────────────────────────────────────

def _map_document(doc: dict) -> dict:
    source = doc.get("source") or {}
    author = doc.get("author") or {}
    if isinstance(author, str):
        author = {"name": author}
    return {
        "title":            doc.get("title", ""),
        "url":              doc.get("url", ""),
        "published_at":     (doc.get("published_at") or "")[:10],
        "content_snippet":  doc.get("summary") or doc.get("body", "")[:1000],
        "sentiment":        doc.get("sentiment", "neutral"),
        "sentiment_score":  float(doc.get("sentiment_score") or 0.5),
        "topics":           doc.get("keywords", [])[:5],
        "risk_flag":        False,
        "source_name":      source.get("name", ""),
        "author_name":      author.get("name", ""),
        "language":         doc.get("language", "en"),
        "reach":            doc.get("reach", 0),
        "meltwater_id":     doc.get("id", ""),
    }


async def fetch_documents(
    api_key: str,
    search_id: str,
    days_back: int = 7,
    document_type: str = "editorial",
    page_size: int = 50,
) -> list:
    to_date   = datetime.utcnow()
    from_date = to_date - timedelta(days=days_back)

    def _call():
        params = {
            "from":          from_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to":            to_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "document_type": document_type,
            "page_size":     page_size,
        }
        results, token = [], None
        while True:
            if token:
                params["page_token"] = token
            data = _get(api_key, f"/v2/searches/{search_id}/documents", params)
            docs = data.get("documents", [])
            results.extend(docs)
            token = data.get("next_page_token")
            if not token or len(results) >= 200:
                break
        return results

    raw = await _run(_call)
    return [_map_document(d) for d in raw]


# ── Journalist Contacts ────────────────────────────────────────────────────────

def _map_contact(c: dict) -> dict:
    outlets = c.get("outlets") or c.get("publications") or []
    social  = c.get("social") or {}
    return {
        "name":             c.get("name", ""),
        "email":            c.get("email", ""),
        "beat":             c.get("beat") or c.get("topics", [""])[0] if c.get("topics") else "",
        "region":           c.get("country") or c.get("region", ""),
        "social_twitter":   social.get("twitter") or c.get("twitter", ""),
        "social_linkedin":  social.get("linkedin") or c.get("linkedin", ""),
        "notes":            f"Imported from Meltwater on {datetime.utcnow().strftime('%Y-%m-%d')}",
        "publication_names": [o.get("name", o) if isinstance(o, dict) else o for o in outlets[:3]],
    }


async def fetch_journalist_contacts(
    api_key: str, query: str, limit: int = 50
) -> list:
    def _call():
        return _get(api_key, "/v1/contacts", {"q": query, "limit": limit})
    try:
        data = await _run(_call)
        contacts = data.get("contacts") or data.get("results") or []
        return [_map_contact(c) for c in contacts]
    except requests.HTTPError as e:
        if e.response.status_code == 403:
            raise PermissionError(
                "Contacts API requires the Meltwater Contacts add-on. "
                "Contact your Meltwater account manager to enable it."
            )
        raise


# ── Mention Alerts ────────────────────────────────────────────────────────────

async def fetch_mentions(
    api_key: str, keyword: str, days_back: int = 1
) -> list:
    to_date   = datetime.utcnow()
    from_date = to_date - timedelta(days=days_back)

    def _call():
        params = {
            "q":    keyword,
            "from": from_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to":   to_date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        return _get(api_key, "/v2/searches/one-time/documents", params)

    try:
        data = await _run(_call)
        return [_map_document(d) for d in data.get("documents", [])]
    except Exception:
        return []
