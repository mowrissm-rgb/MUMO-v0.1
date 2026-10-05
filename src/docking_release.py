"""Release switch: enable only after real database isolation and quota checks."""
import os


def private_cache_enabled():
    # Owner: MUMO maintainer. Review by 19 October 2026; no automatic enablement.
    return os.environ.get('MUMO_PRIVATE_CACHE_ENABLED', '0') == '1'
