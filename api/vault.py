"""Vault layer — wraps the existing Chroma + Gemini RAG from vault_analyst.py."""
import os, json, time
from pathlib import Path

_OBSIDIAN_PATH      = "/Users/mayed/Obsidian/AlDar/AlDar Vault"
_BUNDLED_PATH       = str(Path(__file__).resolve().parent.parent / 'vault_docs')
DEFAULT_VAULT_PATH  = (
    os.environ.get('VAULT_PATH')
    or (_OBSIDIAN_PATH if os.path.isdir(_OBSIDIAN_PATH) else _BUNDLED_PATH)
)
_data_dir           = Path(os.getenv('DATA_DIR', str(Path(__file__).parent.parent / 'data')))
DEFAULT_VECTOR_PATH = str(_data_dir / 'chroma_db')
EMBEDDING_MODEL     = os.environ.get('EMBEDDING_MODEL', 'models/gemini-embedding-001')
META_PATH           = os.path.join(DEFAULT_VECTOR_PATH, 'db_meta.json')

def _read_meta(vector_path: str) -> dict:
    p = os.path.join(vector_path, 'db_meta.json')
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            pass
    return {}

def _vault_mtime(vault_path: str) -> float:
    latest = 0.0
    for root, _, files in os.walk(vault_path):
        for f in files:
            if f.endswith('.md'):
                try:
                    mtime = os.path.getmtime(os.path.join(root, f))
                    if mtime > latest: latest = mtime
                except OSError:
                    pass
    return latest

def _resolve_vault_path(settings: dict) -> str:
    p = settings.get('vault_path') or DEFAULT_VAULT_PATH
    if not os.path.isdir(p):
        p = _BUNDLED_PATH
    return p

def get_store(settings: dict):
    """Return a loaded (or freshly built) Chroma vector store."""
    vault_path  = _resolve_vault_path(settings)
    vector_path = settings.get('vector_db_path') or DEFAULT_VECTOR_PATH
    api_key     = settings.get('gemini_api_key') or os.getenv('GEMINI_API_KEY', '')
    if api_key:
        os.environ['GOOGLE_API_KEY'] = api_key

    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from langchain_chroma import Chroma

    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL, task_type="retrieval_query"
    )

    meta = _read_meta(vector_path)
    vault_mt = _vault_mtime(vault_path)
    is_fresh = (
        os.path.exists(vector_path)
        and meta.get('embedding_model') == EMBEDDING_MODEL
        and meta.get('vault_mtime', 0) >= vault_mt
    )

    if is_fresh:
        return Chroma(persist_directory=vector_path, embedding_function=embeddings)
    else:
        return _build_store(vault_path, vector_path, api_key)

def _add_with_retry(store, batch, *, max_attempts: int = 6):
    delay = 5.0
    for attempt in range(1, max_attempts + 1):
        try:
            store.add_documents(batch)
            return
        except Exception as e:
            msg = str(e)
            is_rate = ('429' in msg or 'RESOURCE_EXHAUSTED' in msg
                       or 'quota' in msg.lower() or 'rate' in msg.lower())
            if not is_rate or attempt == max_attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 60.0)


def _build_store(vault_path: str, vector_path: str, api_key: str,
                 batch_size: int = 50, batch_pause: float = 0.5):
    import shutil
    from langchain_community.document_loaders import DirectoryLoader, TextLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from langchain_chroma import Chroma
    if api_key:
        os.environ['GOOGLE_API_KEY'] = api_key

    loader = DirectoryLoader(
        vault_path, glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"autodetect_encoding": True},
        silent_errors=True,
    )
    docs = loader.load()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=800, chunk_overlap=100, add_start_index=True,
        separators=["\n## ", "\n### ", "\n#### ", "\n\n", "\n", " "],
    )
    chunks = splitter.split_documents(docs)
    embeddings = GoogleGenerativeAIEmbeddings(
        model=EMBEDDING_MODEL, task_type="retrieval_document"
    )

    # Wipe any prior on-disk store so we don't accumulate stale chunks
    if os.path.isdir(vector_path):
        shutil.rmtree(vector_path, ignore_errors=True)
    os.makedirs(vector_path, exist_ok=True)

    store = Chroma(persist_directory=vector_path, embedding_function=embeddings)
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        _add_with_retry(store, batch)
        if i + batch_size < len(chunks):
            time.sleep(batch_pause)

    meta = {"vault_mtime": _vault_mtime(vault_path), "built_at": time.time(), "embedding_model": EMBEDDING_MODEL, "doc_count": len(docs), "chunk_count": len(chunks)}
    json.dump(meta, open(os.path.join(vector_path, 'db_meta.json'), 'w'))
    return store

def search(query: str, settings: dict, k: int = 6) -> list[dict]:
    """Return top-k relevant chunks as list of dicts with title/excerpt/source."""
    try:
        store = get_store(settings)
        results = store.similarity_search_with_relevance_scores(query, k=k)
        out = []
        for doc, score in results:
            source = os.path.basename(doc.metadata.get('source', 'Unknown'))
            title  = source.replace('.md', '').replace('_', ' ')
            out.append({
                'title':   title,
                'excerpt': doc.page_content[:300],
                'source':  source,
                'score':   round(score, 3),
            })
        return out
    except Exception as e:
        return [{'title': 'Error', 'excerpt': str(e), 'source': '', 'score': 0}]

def get_doc_content(filename: str, settings: dict) -> dict:
    vault_path = _resolve_vault_path(settings)
    for root, _, files in os.walk(vault_path):
        if filename in files:
            path = os.path.join(root, filename)
            content = open(path, encoding='utf-8', errors='replace').read()
            return {'filename': filename, 'title': filename.replace('.md','').replace('_',' '), 'content': content}
    return {'filename': filename, 'title': filename, 'content': 'File not found.'}

def list_docs(settings: dict) -> list[dict]:
    vault_path = _resolve_vault_path(settings)
    docs = []
    for root, _, files in os.walk(vault_path):
        for f in files:
            if f.endswith('.md'):
                path = os.path.join(root, f)
                size = os.path.getsize(path)
                docs.append({
                    'filename': f,
                    'title': f.replace('.md','').replace('_',' '),
                    'size': f"{size//1024}KB" if size > 1024 else f"{size}B"
                })
    return sorted(docs, key=lambda x: x['filename'], reverse=True)

def vault_stats(settings: dict) -> dict:
    vector_path = settings.get('vector_db_path') or DEFAULT_VECTOR_PATH
    meta = _read_meta(vector_path)
    docs = list_docs(settings)
    age = '—'
    if meta.get('built_at'):
        secs = time.time() - meta['built_at']
        if secs < 3600:   age = f"{int(secs//60)}m ago"
        elif secs < 86400: age = f"{int(secs//3600)}h ago"
        else:             age = f"{int(secs//86400)}d ago"
    return {
        'doc_count':       len(docs),
        'chunk_count':     meta.get('chunk_count', '—'),
        'index_age':       age,
        'embedding_model': EMBEDDING_MODEL,
    }
