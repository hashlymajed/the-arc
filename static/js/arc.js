'use strict';

// ── Nav counts ──────────────────────────────────────────────────────────────
async function loadNavCounts() {
  try {
    const r = await fetch('/api/stats');
    if (!r.ok) return;
    const s = await r.json();
    const v = document.getElementById('nav-vault-count');
    const a = document.getElementById('nav-article-count');
    if (v) v.textContent = s.vault_docs ?? '—';
    if (a) a.textContent = s.news_articles ?? '—';
  } catch { /* silent */ }
}

// ── Global search ────────────────────────────────────────────────────────────
const globalSearch = document.getElementById('globalSearch');
if (globalSearch) {
  let searchTimer;
  globalSearch.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      clearTimeout(searchTimer);
      const q = globalSearch.value.trim();
      if (q) window.location.href = '/vault?q=' + encodeURIComponent(q);
    }
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadNavCounts();
});
