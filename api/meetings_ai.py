"""AI layer for meeting intelligence — bilingual MoM generation via Gemini."""
import asyncio, json, os, re
from google import genai
from google.genai import types


def _get_key(settings: dict) -> str:
    key = settings.get('gemini_api_key') or os.getenv('GEMINI_API_KEY', '')
    if not key:
        raise ValueError("No Gemini API key configured. Add it in Settings.")
    return key


def _model(settings: dict) -> str:
    return settings.get('llm_model', 'gemini-2.5-flash')


SYSTEM_PROMPT = (
    "You are a bilingual Arabic-English Meeting Intelligence and Minutes of Meeting (MoM) system "
    "for Aldar Properties (UAE leading real estate developer).\n\n"
    "## Instructions\n"
    "1. Identify unique speakers — assign labels: Person 1, Person 2, Person 3, etc.\n"
    "2. Maintain speaker consistency — the same voice keeps the same label throughout.\n"
    "3. Detect spoken language per sentence: English | Arabic | Mixed.\n"
    "4. Preserve the original language in the transcript exactly as spoken.\n"
    "5. For Arabic: transcribe accurately in Arabic script; preserve professional/business terminology.\n"
    "6. For mixed dialogue: preserve natural code-switching.\n"
    "7. Extract tasks, deadlines, owners, decisions, risks, follow-ups, approvals, escalations.\n"
    "8. Generate bilingual executive summaries (English + formal Arabic MSA).\n"
    "9. Do NOT hallucinate participants, decisions, or facts not present in the input.\n"
    "   If anything is unclear, flag it explicitly in the relevant field.\n\n"
    "Return ONLY valid JSON (no markdown fences) with this exact structure:\n"
    '{"meeting_title":"Concise professional title",'
    '"summary_english":"2-5 paragraph executive summary in English.",'
    '"summary_arabic":"ملخص تنفيذي احترافي باللغة العربية.",'
    '"participants":["Person 1","Person 2"],'
    '"transcript":['
    '{"time":"00:01:22","speaker":"Person 1","language":"English","text":"Transcript text"},'
    '{"time":"00:02:10","speaker":"Person 2","language":"Arabic","text":"النص العربي"}'
    '],'
    '"key_topics":["Topic 1","Topic 2"],'
    '"decisions_made":["Decision 1","Decision 2"],'
    '"action_items":['
    '{"task":"Task description","owner":"Person 1","deadline":"2026-05-20","priority":"high"}'
    '],'
    '"updates_shared":"Summary of operational or strategic updates shared.",'
    '"risks_or_concerns":["Risk 1","Risk 2"],'
    '"follow_ups":["Follow-up 1","Follow-up 2"],'
    '"vault_record":{'
    '"keywords_en":["keyword1","keyword2"],'
    '"keywords_ar":["كلمة1","كلمة2"],'
    '"topic_category":"Category name",'
    '"participant_mapping":{"Person 1":"Real name if known","Person 2":"Real name if known"}'
    '}}'
)


async def generate_mom(transcript: str, context: str, participant_list: str, settings: dict) -> dict:
    key    = _get_key(settings)
    client = genai.Client(api_key=key)
    model  = _model(settings)

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"## Meeting Context\n{context or 'No additional context provided.'}\n\n"
        f"## Known Participants\n{participant_list or 'Not specified — label speakers as Person 1, Person 2, etc.'}\n\n"
        f"## Meeting Transcript / Notes\n{transcript[:8000]}"
    )

    loop = asyncio.get_event_loop()

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=8192, temperature=0.2),
        )
        return resp.text.strip()

    try:
        raw = await loop.run_in_executor(None, _call)
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(m.group(0)) if m else {}
    except Exception as e:
        raise ValueError(f"AI analysis failed: {e}")

    return {
        'meeting_title':     result.get('meeting_title', 'Untitled Meeting'),
        'summary_english':   result.get('summary_english', ''),
        'summary_arabic':    result.get('summary_arabic', ''),
        'participants':      result.get('participants', []),
        'transcript':        result.get('transcript', []),
        'key_topics':        result.get('key_topics', []),
        'decisions_made':    result.get('decisions_made', []),
        'action_items':      result.get('action_items', []),
        'updates_shared':    result.get('updates_shared', ''),
        'risks_or_concerns': result.get('risks_or_concerns', []),
        'follow_ups':        result.get('follow_ups', []),
        'vault_record':      result.get('vault_record', {}),
    }
