"""AI generation layer — google-genai SDK (new)."""
import os, json, re, asyncio, concurrent.futures
import datetime

from google import genai
from google.genai import types


def _client(api_key: str) -> genai.Client:
    return genai.Client(api_key=api_key)

def _get_key(settings: dict) -> str:
    key = settings.get('gemini_api_key') or os.getenv('GEMINI_API_KEY', '')
    if not key:
        raise ValueError("No Gemini API key configured. Add it in Settings.")
    return key

def _model_name(settings: dict) -> str:
    return settings.get('llm_model', 'gemini-2.5-flash')

def _brand_voice(settings: dict) -> str:
    return settings.get('brand_voice',
        "Tone: confident, premium, human, relatable. Never use aggressive sales language. "
        "Emphasise community, lifestyle, and long-term value. "
        "The brand promise is 'from property to people'.")


CHANNEL_GUIDANCE = {
    "Press Release": (
        "Format: headline, dateline (Abu Dhabi, UAE), lead paragraph (who/what/when/where/why), "
        "2-3 body paragraphs with quotes, boilerplate. AP style. ~400-600 words."
    ),
    "LinkedIn": (
        "Professional thought-leadership. Hook first line, 3-5 short paragraphs, "
        "end with a question or call to reflection. No hashtag spam. ~200-300 words."
    ),
    "Internal Memo": (
        "Clear subject line, direct opening, bullet key points, action items at end. "
        "Warm but professional. ~200-400 words."
    ),
    "IR Update": (
        "Structured: headline metric, performance narrative, strategic context, outlook. "
        "Precise, data-forward, no hype. ~300-500 words."
    ),
    "Arabic Version": (
        "Translate and culturally adapt to Arabic. Use Modern Standard Arabic (MSA) with "
        "a warm Gulf register. Right-to-left. Preserve all key facts and figures."
    ),
    "Crisis Statement": (
        "Holding statement format: acknowledge, commit to transparency, state next steps. "
        "Calm, measured, empathetic. ~100-200 words max. No speculation."
    ),
    "Community Engagement": (
        "Warm, inclusive, conversational. Focus on people and place, not product. ~150-250 words."
    ),
    "Social (Twitter/X)": (
        "280 characters max per tweet. If a thread, max 5 tweets. Punchy, clear."
    ),
    "Email Newsletter": (
        "Subject line + preview text first. Personal opener, 2-3 story blocks, "
        "clear CTA at end. Scannable. ~300-500 words."
    ),
    "Website Copy": (
        "SEO-aware, benefit-led headings, short sentences. "
        "Hero → value props → social proof → CTA structure. ~200-400 words."
    ),
}


def _call(client: genai.Client, model: str, prompt: str,
          max_tokens: int = 8192, temperature: float = 0.4) -> str:
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        ),
    )
    return response.text.strip()


def _parse_json(raw: str) -> dict | list:
    raw = raw.strip()
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    m = re.search(r'[\[{].*[\]}]', raw, re.DOTALL)
    if m:
        candidate = m.group(0)
    else:
        # Truncated response with no closing bracket — take from first opener to end
        start = next((i for i, c in enumerate(raw) if c in '{['), -1)
        if start < 0:
            raise ValueError("No JSON found in model response")
        candidate = raw[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return json.loads(_repair_json(candidate))


def _repair_json(s: str) -> str:
    # Strip trailing commas before } or ]
    s = re.sub(r',(\s*[}\]])', r'\1', s)
    # Walk the string honoring strings/escapes, tracking bracket depth,
    # and truncate to the last balanced close. Then close any still-open
    # brackets so truncated Gemini output still parses.
    stack: list[str] = []
    in_str = False
    esc = False
    last_balanced = -1
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in '{[':
            stack.append('}' if ch == '{' else ']')
        elif ch in '}]':
            if stack and stack[-1] == ch:
                stack.pop()
                if not stack:
                    last_balanced = i
    if not stack and last_balanced >= 0:
        return s[:last_balanced + 1]
    # Truncated: cut at last safe boundary, drop trailing partial token, close stack
    cut = s
    if in_str:
        # Drop the unterminated string entirely
        last_quote = cut.rfind('"')
        if last_quote >= 0:
            cut = cut[:last_quote]
    # Trim partial trailing token (e.g. ': "abc' or ', "key')
    cut = re.sub(r'[,:]\s*"[^"]*$', '', cut)
    cut = re.sub(r'[,:]\s*[^}\],\s]*$', '', cut)
    cut = cut.rstrip().rstrip(',')
    return cut + ''.join(reversed(stack))


# ── Draft generation ──────────────────────────────────────────────

def _draft_prompt(data: dict, settings: dict, vault_context: str = '') -> str:
    channel      = data.get('channel', 'Press Release')
    channel_guide = CHANNEL_GUIDANCE.get(channel, '')
    brand_voice  = _brand_voice(settings)
    org          = settings.get('org_name', 'Aldar Properties')

    vault_section = ''
    if vault_context:
        vault_section = f"\n\n## Relevant vault context:\n{vault_context[:3000]}"
    elif data.get('vault_context'):
        vault_section = f"\n\n## Provided context:\n{data['vault_context'][:3000]}"

    existing_section = ''
    if data.get('existing'):
        existing_section = f"\n\n## Existing draft to improve:\n{data['existing']}"

    return (
        f"You are the senior communications writer for {org}, a leading UAE real estate developer.\n\n"
        f"## Brand voice:\n{brand_voice}\n\n"
        f"## Channel: {channel}\n{channel_guide}\n\n"
        f"## Audience: {data.get('audience', 'General')}\n"
        f"## Tone: {data.get('tone', 'Premium & Confident')}\n\n"
        f"## Brief / key messages:\n{data.get('brief', '')}"
        f"{vault_section}{existing_section}\n\n"
        f"Write the {channel} now. Output ONLY the finished copy — "
        "no meta-commentary, no 'Here is your draft:', no markdown code fences."
    )


async def generate(data: dict, settings: dict, vault_context: str = '') -> dict:
    key    = _get_key(settings)
    client = _client(key)
    model  = _model_name(settings)
    prompt = _draft_prompt(data, settings, vault_context)
    loop   = asyncio.get_event_loop()
    text   = await loop.run_in_executor(
        None, lambda: _call(client, model, prompt,
                            int(settings.get('max_tokens', 8192)),
                            float(settings.get('temperature', 0.4)))
    )
    return {'content': text}


# ── Refine ────────────────────────────────────────────────────────

def _refine_prompt(content: str, action: str, channel: str, settings: dict) -> str:
    brand_voice = _brand_voice(settings)
    instructions = {
        'shorten':         "Shorten by ~30% while keeping all key messages. Do not cut quotes.",
        'expand':          "Expand by ~40%, adding relevant context, detail, and stronger narrative arc.",
        'arabic':          "Translate to Arabic (MSA with warm Gulf register). Preserve all facts exactly.",
        'add_quote':       "Add one attributed executive quote that sounds natural and on-brand.",
        'add_boilerplate': (
            "Append the standard Aldar boilerplate at the end:\n\n"
            + settings.get('boilerplate', 'About Aldar Properties…')
        ),
        'check_voice': (
            "Evaluate this content against the brand voice guidelines. "
            "Return a short report: overall score /10, what works, what to improve, 3 specific edits. "
            "Do NOT rewrite — only analyse.\n\nBrand voice: " + brand_voice
        ),
    }
    instruction = instructions.get(action, 'Improve this content.')

    if action == 'check_voice':
        return f"Content to review:\n\n{content}\n\n---\n{instruction}"

    return (
        f"You are a senior communications editor for Aldar Properties.\n\n"
        f"Brand voice: {brand_voice}\nChannel: {channel}\n\n"
        f"Task: {instruction}\n\nOriginal content:\n{content}\n\n"
        "Output ONLY the revised content — no commentary."
    )


async def refine(content: str, action: str, channel: str, settings: dict) -> dict:
    key    = _get_key(settings)
    client = _client(key)
    model  = _model_name(settings)
    prompt = _refine_prompt(content, action, channel, settings)
    loop   = asyncio.get_event_loop()
    text   = await loop.run_in_executor(
        None, lambda: _call(client, model, prompt, 4096, 0.3)
    )
    return {'content': text}


# ── Intelligence analysis ─────────────────────────────────────────

async def analyze(vault_docs: list[dict], settings: dict,
                  spokespeople: str = '', pillars: str = '') -> dict:
    key    = _get_key(settings)
    client = _client(key)
    model  = _model_name(settings)
    sp     = spokespeople or 'auto-detect from content'
    pl     = pillars or 'Sustainability, Innovation, Community, Growth, Excellence'

    def call(prompt: str, tokens: int = 8192) -> str:
        return _call(client, model, prompt, tokens, 0.1)

    # Step 1 — per-file summaries
    file_summaries: list[dict] = []
    for i in range(0, len(vault_docs), 2):
        batch = vault_docs[i:i + 2]
        batch_text = '\n\n---\n\n'.join(
            f"FILE {j+1}: {f['filename']}\n{f['content'][:1500]}"
            for j, f in enumerate(batch)
        )
        try:
            raw = call(
                f"Analyse these {len(batch)} vault notes for a real estate communications team.\n\n"
                f"{batch_text}\n\n"
                "Respond with ONLY a JSON array (no markdown), one object per file:\n"
                '[{"filename":"exact filename","mainTopic":"one sentence","keywords":["kw1","kw2","kw3"],'
                '"category":"single category","sentiment":"positive|neutral|negative|analytical",'
                '"spokespeople":["name1"],"topics":["topic1","topic2"],"isTemplate":false}]'
            )
            parsed = _parse_json(raw)
            if isinstance(parsed, list):
                file_summaries.extend(f for f in parsed if not f.get('isTemplate'))
        except Exception:
            pass

    slim = json.dumps([{
        'fn': f.get('filename', ''),
        't':  (f.get('mainTopic') or '')[:80],
        'k':  (f.get('keywords') or [])[:3],
        'c':  f.get('category', ''),
        's':  (f.get('spokespeople') or [])[:2],
    } for f in file_summaries])[:4000]

    # Step 2 — 3 parallel synthesis calls
    async def _async_call(prompt, tokens=8192):
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return await loop.run_in_executor(pool, lambda: call(prompt, tokens))

    prompt_a = (
        f"You are a strategic communications analyst for AlDar, a UAE real estate developer.\n"
        f"File summaries: {slim}\nSpokespeople: {sp}\nBrand pillars: {pl}\n\n"
        "Return ONLY valid JSON (no markdown, text fields under 100 words each):\n"
        '{"themes":[{"name":"...","description":"2 sentences","keywords":["k1","k2","k3"],"files":["f1"],"count":0}],'
        '"gaps":[{"topic":"...","severity":"high|mid|low","reason":"1 sentence","recommendation":"1 sentence"}],'
        '"themesSynthesis":"2 paragraph synthesis","gapsSynthesis":"1 paragraph",'
        f'"totalFiles":{len(file_summaries)},"dominantCategory":"..."}}'
    )

    prompt_b = (
        f"You are a strategic communications analyst for AlDar.\n"
        f"File summaries: {slim}\nBrand pillars: {pl}\n\n"
        "Return ONLY valid JSON (no markdown, text fields under 80 words each):\n"
        '{"consistency":{"pillars":[{"name":"...","score":85,"description":"1 sentence","files":["f1"]}],'
        '"overallScore":0,"synthesis":"1 paragraph"},'
        '"lens":[{"audience":"Investors","coverageScore":70,"strengths":"1 sentence","gaps":"1 sentence","topFiles":["f1"],"recommendation":"1 sentence"},'
        '{"audience":"Media","coverageScore":0,"strengths":"...","gaps":"...","topFiles":[],"recommendation":"..."},'
        '{"audience":"Government","coverageScore":0,"strengths":"...","gaps":"...","topFiles":[],"recommendation":"..."},'
        '{"audience":"Community","coverageScore":0,"strengths":"...","gaps":"...","topFiles":[],"recommendation":"..."},'
        '{"audience":"Tenants","coverageScore":0,"strengths":"...","gaps":"...","topFiles":[],"recommendation":"..."}],'
        '"arcs":[{"topic":"...","trajectory":"building|plateauing|fading|emerging","description":"2 sentences","files":["f1"],"recommendation":"1 sentence"}]}'
    )

    prompt_c = (
        f"You are a strategic communications analyst for AlDar.\n"
        f"File summaries: {slim}\nSpokespeople: {sp}\nBrand pillars: {pl}\n\n"
        "Return ONLY valid JSON (no markdown, text fields under 80 words each):\n"
        '{"spokespeople":[{"name":"...","role":"...","mentions":0,"topics":["t1","t2"],'
        '"tone":"authoritative","consistency":"high|medium|low","representativeQuote":"short phrase","recommendation":"1 sentence"}],'
        '"spSynthesis":"1 paragraph",'
        '"briefing":{"executiveSummary":"2-3 sentences","topThemes":"2-3 sentences",'
        '"emergingNarratives":"2-3 sentences","gaps":"2-3 sentences","spokespeople":"2-3 sentences",'
        '"recommendedActions":"3 actions as numbered list","outlook":"1-2 sentences"}}'
    )

    r1, r2, r3 = await asyncio.gather(
        _async_call(prompt_a),
        _async_call(prompt_b),
        _async_call(prompt_c),
    )

    def _safe_parse(raw: str) -> dict:
        try:
            out = _parse_json(raw)
            return out if isinstance(out, dict) else {}
        except Exception:
            return {}

    d1, d2, d3 = _safe_parse(r1), _safe_parse(r2), _safe_parse(r3)

    return {
        'themes':           d1.get('themes', []),
        'themesSynthesis':  d1.get('themesSynthesis', ''),
        'gaps':             d1.get('gaps', []),
        'gapsSynthesis':    d1.get('gapsSynthesis', ''),
        'totalFiles':       d1.get('totalFiles', len(file_summaries)),
        'dominantCategory': d1.get('dominantCategory', ''),
        'consistency':      d2.get('consistency', {}),
        'lens':             d2.get('lens', []),
        'arcs':             d2.get('arcs', []),
        'spokespeople':     d3.get('spokespeople', []),
        'spSynthesis':      d3.get('spSynthesis', ''),
        'briefing':         d3.get('briefing', {}),
        'fileSummaries':    file_summaries,
        'generatedAt':      datetime.datetime.now().isoformat(),
    }


# ── Translate ─────────────────────────────────────────────────────

async def translate(content: str, target: str, tone: str, settings: dict) -> dict:
    key    = _get_key(settings)
    client = _client(key)
    model  = _model_name(settings)
    org    = settings.get('org_name', 'Aldar Properties')

    prompt = (
        f"You are a senior communications translator for {org}.\n"
        f"Brand voice: {_brand_voice(settings)}\n"
        f"Target language/channel: {target}\nTone: {tone}\n\n"
        "Translate and culturally adapt the following content. Preserve all facts and figures exactly.\n"
        f"Output ONLY the translated/adapted content — no commentary.\n\nContent:\n{content}"
    )
    loop = asyncio.get_event_loop()
    text = await loop.run_in_executor(
        None, lambda: _call(client, model, prompt, 4096, 0.3)
    )
    return {'content': text}


# ── Connection test ───────────────────────────────────────────────

async def test_connection(api_key: str) -> dict:
    try:
        client = _client(api_key)
        resp   = client.models.generate_content(
            model='gemini-2.5-flash',
            contents='Reply with just: OK',
            config=types.GenerateContentConfig(max_output_tokens=10),
        )
        return {'ok': True, 'model': 'gemini-2.5-flash', 'response': resp.text.strip()}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
