"""Small UI/server contracts. No Streamlit, LLM calls, credentials or live migrations."""
import copy
import json

from docking_cache_store import PrivateCacheStore, MAX_RAW_BYTES
from docking_memory import eligible_entry

MAX_CANDIDATES = 64
MAX_BATCH_BYTES = 64 * 1024 * 1024


def worker_cache_fields(owner_id, candidates=(), notice=None):
    """Use a server-verified owner, never a field produced by the conversation model."""
    selected, used = [], 0
    if owner_id:
        for entry in candidates or []:
            if len(selected) >= MAX_CANDIDATES:
                break
            if not isinstance(entry, dict) or not eligible_entry(entry, owner_id, entry.get('key')):
                continue
            raw_size = len(json.dumps(entry, allow_nan=False).encode())
            if raw_size > MAX_RAW_BYTES or used + raw_size > MAX_BATCH_BYTES:
                notice = 'Private cache candidate limit reached; unmatched pairs require fresh calculation.'
                continue
            selected.append(copy.deepcopy(entry)); used += raw_size
    return {'owner_id': owner_id, 'cache_candidates': selected, 'cache_notice': notice}


def load_worker_cache_fields(authenticated_client, owner_id):
    store = PrivateCacheStore(authenticated_client, owner_id)
    entries = store.candidates()
    return worker_cache_fields(owner_id, entries, store.notice)


def foreground_cache_context(fields):
    """Pass alongside reuse_decision callback; if hits exist no callback means no execution."""
    return {'owner_id': fields.get('owner_id'), 'candidates': fields.get('cache_candidates') or [],
            'notice': fields.get('cache_notice')}


def persist_completed_pairs(authenticated_client, owner_id, result):
    """Call after displaying result, preferably on the existing asynchronous user-session path."""
    store = PrivateCacheStore(authenticated_client, owner_id)
    saved = 0
    entries = result.get('cache_entries') or []  # Foreground result, excluded from report metadata.
    for entry in entries:
        saved += bool(store.save(entry))
    return {'saved_pairs': saved, 'notice': store.notice}
