"""Authenticated, non-blocking UI boundaries for optional private reuse."""
import copy
import threading


def may_view_offer(status, user):
    owner = (user or {}).get('id')
    return bool(owner and owner == status.get('owner_id'))


def cache_fields(client, user):
    from docking_reuse_ui import load_worker_cache_fields, worker_cache_fields
    from docking_release import private_cache_enabled
    if not private_cache_enabled():
        return worker_cache_fields(None)
    owner = (user or {}).get('id')
    if not owner:
        return worker_cache_fields(None)
    try:
        return load_worker_cache_fields(client, owner)
    except Exception:
        return worker_cache_fields(owner, notice='Private cache unavailable; calculating fresh.')


def public_result(result):
    """Keep provenance but not duplicate cache evidence inside chat history/report state."""
    result = dict(result)
    result.pop('cache_entries', None)
    meta = copy.deepcopy(result.get('meta') or {})
    meta.pop('cache_entries', None)
    for target in (meta.get('per_target') or {}).values():
        target.pop('cache_entries', None)
    result['meta'] = meta
    return result


def save_cache_async(client, user, result, on_complete=None):
    """Capture user/client before thread start; never access Streamlit in the worker."""
    from docking_release import private_cache_enabled
    if not private_cache_enabled():
        return None
    owner = (user or {}).get('id')
    if not owner or not result.get('ok') or result.get('partial'):
        return None
    if not (result.get('cache_entries') or (result.get('meta') or {}).get('cache_entries')):
        return None
    from docking_reuse_ui import persist_completed_pairs
    def save():
        try:
            outcome = persist_completed_pairs(client, owner, result)
        except Exception:
            outcome = {'saved_pairs': 0, 'notice': 'Private reuse storage unavailable.'}
        if on_complete:
            on_complete(outcome)
    worker = threading.Thread(target=save, name='mumo-private-cache-save', daemon=True)
    worker.start()
    return worker
