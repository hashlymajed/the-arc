"""AI layer for media intelligence — Gemini sentiment analysis and crisis intelligence."""
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


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError("No JSON in model response")


async def analyze_article(title: str, snippet: str, settings: dict) -> dict:
    key = _get_key(settings)
    client = genai.Client(api_key=key)
    model = _model(settings)

    prompt = (
        "You are a media intelligence analyst for Aldar Properties (UAE real estate developer).\n"
        "Analyse the article for sentiment toward Aldar and the UAE real estate sector.\n\n"
        f"Title: {title}\n\nContent:\n{snippet[:2000]}\n\n"
        "Return ONLY valid JSON (no markdown):\n"
        '{"sentiment":"positive|neutral|negative","sentiment_score":0.75,'
        '"topics":["topic1","topic2","topic3"],'
        '"risk_flag":false,'
        '"reasoning":"One sentence explaining the sentiment."}'
    )

    loop = asyncio.get_event_loop()

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=512, temperature=0.1),
        )
        return resp.text.strip()

    try:
        raw = await loop.run_in_executor(None, _call)
        result = _parse_json(raw)
    except Exception:
        return {'sentiment': 'neutral', 'sentiment_score': 0.5,
                'topics': [], 'risk_flag': False, 'reasoning': ''}

    return {
        'sentiment':       result.get('sentiment', 'neutral'),
        'sentiment_score': float(result.get('sentiment_score', 0.5)),
        'topics':          result.get('topics', [])[:5],
        'risk_flag':       bool(result.get('risk_flag', False)),
        'reasoning':       result.get('reasoning', ''),
    }


COMPANY_BACKGROUND = (
    "Aldar Properties is the UAE's leading real estate developer, headquartered in Abu Dhabi. "
    "It is publicly listed on the Abu Dhabi Securities Exchange (ADX). "
    "Brand promise: 'from property to people' — community-focused, premium, aspirational. "
    "Key stakeholders: government/sovereign funds (major shareholders), retail investors, "
    "off-plan buyers, international buyers, media, regulators, and the general public. "
    "Reputation pillars: reliability, quality, sustainability, innovation, community trust."
)

CRISIS_ROLES = [
    ("PR Crisis Lead",             "Specialist in rapid-response communications and narrative control"),
    ("Corporate Legal Advisor",    "Focused on liability exposure, disclosure obligations, and legal risk"),
    ("Investor Relations Executive","Manages ADX-listed shareholder expectations and market confidence"),
    ("Political Communications Strategist", "Attuned to government relations, regulatory optics, and UAE stakeholder dynamics"),
    ("CEO Communications Advisor", "Guards executive reputation and long-term brand equity"),
]


async def crisis_analysis(alert_message: str, alert_type: str, severity: str, settings: dict) -> dict:
    key = _get_key(settings)
    client = genai.Client(api_key=key)
    model = _model(settings)

    roles_block = "\n".join(
        f"- {role}: {desc}" for role, desc in CRISIS_ROLES
    )

    prompt = (
        "You are a multi-disciplinary crisis intelligence system for Aldar Properties (UAE real estate developer).\n\n"
        f"## Company Background\n{COMPANY_BACKGROUND}\n\n"
        f"## Alert\nType: {alert_type.replace('_',' ').title()}\nSeverity: {severity.upper()}\nMessage: {alert_message}\n\n"
        "## Your Task\n"
        "Simulate an internal crisis council debate between these five perspectives:\n"
        f"{roles_block}\n\n"
        "Each advisor assesses: risks, recommended response posture, strategic concerns, predicted media behaviour.\n\n"
        "Then synthesise a unified final strategy.\n\n"
        "Return ONLY valid JSON (no markdown fences) with this exact structure:\n"
        '{"risk_level":"critical|high|medium|low",'
        '"risk_summary":"One precise sentence.",'
        '"debate":['
        '{"role":"PR Crisis Lead","risk_assessment":"2-3 sentences.","response_posture":"1-2 sentences.","strategic_concerns":"2-3 sentences.","media_prediction":"1-2 sentences."},'
        '{"role":"Corporate Legal Advisor","risk_assessment":"...","response_posture":"...","strategic_concerns":"...","media_prediction":"..."},'
        '{"role":"Investor Relations Executive","risk_assessment":"...","response_posture":"...","strategic_concerns":"...","media_prediction":"..."},'
        '{"role":"Political Communications Strategist","risk_assessment":"...","response_posture":"...","strategic_concerns":"...","media_prediction":"..."},'
        '{"role":"CEO Communications Advisor","risk_assessment":"...","response_posture":"...","strategic_concerns":"...","media_prediction":"..."}'
        '],'
        '"strategy":{'
        '"overall_risk":"2-3 sentences of integrated risk assessment.",'
        '"posture":"proactive_engage|acknowledge_monitor|hold_and_watch|no_comment",'
        '"respond_publicly":true,'
        '"positioning_guidance":"3-5 sentences of specific messaging guidance.",'
        '"escalation_triggers":["trigger 1","trigger 2","trigger 3"],'
        '"media_engagement":"2-3 sentences on how to handle press enquiries.",'
        '"executive_comms":"2-3 sentences on executive visibility and spokesperson strategy.",'
        '"reputation_protection":"2-3 sentences on long-term brand protection measures."'
        '}}'
    )

    loop = asyncio.get_event_loop()

    def _call():
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(max_output_tokens=4096, temperature=0.3),
        )
        return resp.text.strip()

    try:
        raw = await loop.run_in_executor(None, _call)
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        result = json.loads(m.group(0)) if m else {}
    except Exception as e:
        return {'error': str(e)}

    return {
        'risk_level':   result.get('risk_level', 'medium'),
        'risk_summary': result.get('risk_summary', ''),
        'debate':       result.get('debate', []),
        'strategy':     result.get('strategy', {}),
    }
