"""Authenticated UI/server adapter; never construct a privileged client in workers."""
import base64
import gzip
import json
import zlib

from docking_memory import eligible_entry

MAX_RAW_BYTES = 16 * 1024 * 1024
MAX_PACKED_BYTES = 4 * 1024 * 1024
TABLE = 'private_docking_cache'
NOTICE = 'Private cache unavailable or at its limit; calculate fresh. Finished results remain available.'


def encode_entry(entry, max_raw_bytes=MAX_RAW_BYTES):
    if not eligible_entry(entry, entry.get('owner_id'), entry.get('key')):
        raise ValueError('Incomplete private cache evidence')
    raw = json.dumps(entry, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > max_raw_bytes:
        raise ValueError('Cache evidence exceeds raw storage limit')
    packed = base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')
    if len(packed) > MAX_PACKED_BYTES:
        raise ValueError('Cache evidence exceeds compressed storage limit')
    return packed


def decode_entry(packed, owner_id, key, max_raw_bytes=MAX_RAW_BYTES):
    try:
        if not isinstance(packed, str) or len(packed) > MAX_PACKED_BYTES:
            return None
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        raw = inflater.decompress(base64.b64decode(packed, validate=True), max_raw_bytes + 1)
        if len(raw) > max_raw_bytes or not inflater.eof or inflater.unused_data:
            return None
        entry = json.loads(raw)
        return entry if eligible_entry(entry, owner_id, key) else None
    except (ValueError, TypeError, zlib.error, UnicodeError):
        return None


class PrivateCacheStore:
    """Supply auth_store's existing user-authenticated client and verified user id.

    RLS remains the actual authorization boundary. Do not pass standalone_client,
    service-role clients, tokens or this object through job specifications.
    """
    def __init__(self, authenticated_client, owner_id):
        self.client = authenticated_client
        self.owner_id = owner_id
        self.notice = None

    def _authenticated(self):
        try:
            response = self.client.auth.get_user()
            user = response.user
            if not user or user.id != self.owner_id or getattr(user, 'is_anonymous', False):
                self.notice = NOTICE
                return False
            return True
        except Exception:
            self.notice = NOTICE
            return False

    def candidates(self, keys=None):
        if not self.owner_id:
            return []
        if not self._authenticated():
            return []
        try:
            query = self.client.table(TABLE).select('pair_key').eq('owner_id', self.owner_id)
            if keys is not None:
                keys = list(dict.fromkeys(k for k in keys if k))
                if not keys:
                    return []
                query = query.in_('pair_key', keys[:64])
            rows = query.limit(64).execute().data or []
            entries = []
            raw_budget = 64 * 1024 * 1024
            packed_budget = 16 * 1024 * 1024
            for row in rows:
                # Fetch one bounded row at a time, not 64 potentially 4 MiB payloads at once.
                if packed_budget < MAX_PACKED_BYTES or raw_budget <= 0:
                    self.notice = NOTICE
                    break
                evidence_rows = self.client.table(TABLE).select('pair_key,evidence').eq(
                    'owner_id', self.owner_id).eq('pair_key', row['pair_key']).limit(1).execute().data or []
                if not evidence_rows:
                    continue
                evidence_row = evidence_rows[0]
                packed_budget -= len(evidence_row['evidence'])
                if packed_budget < 0 or raw_budget <= 0:
                    self.notice = NOTICE
                    break
                entry = decode_entry(evidence_row['evidence'], self.owner_id, row['pair_key'],
                                     max_raw_bytes=min(MAX_RAW_BYTES, raw_budget))
                if entry is not None:
                    raw_budget -= len(json.dumps(entry).encode())
                    entries.append(entry)
            return entries
        except Exception:
            self.notice = NOTICE
            return []

    def save(self, entry):
        if not isinstance(entry, dict) or not eligible_entry(entry, self.owner_id, entry.get('key')):
            return False
        if not self._authenticated():
            return False
        try:
            payload = {'owner_id': self.owner_id, 'pair_key': entry['key'],
                       'source_run_id': entry['source_run_id'], 'created_at': entry['created_at'],
                       'evidence': encode_entry(entry)}
            # Keep the first executed provenance for this exact pair immutable.
            response = self.client.table(TABLE).upsert(payload,
                on_conflict='owner_id,pair_key', ignore_duplicates=True).execute()
            if not response.data:
                self.notice = NOTICE
                return False
            return True
        except Exception:
            self.notice = NOTICE
            return False
