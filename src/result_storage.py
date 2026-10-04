"""Lossless transport/storage encoding; scientific payloads stay unchanged."""
import base64
import gzip
import io
import json


def write_compressed(stream, payload):
    from verification import json_safe
    with gzip.GzipFile(fileobj=stream, mode='wb', compresslevel=3, mtime=0) as compressed:
        with io.TextIOWrapper(compressed, encoding='utf-8') as text:
            json.dump(json_safe(payload), text, allow_nan=False)


def pack(payload):
    stream = io.BytesIO()
    write_compressed(stream, payload)
    return {'encoding': 'mumo-json-gzip-v1',
            'payload': base64.b64encode(stream.getvalue()).decode('ascii')}


def unpack(stored):
    if isinstance(stored, dict) and stored.get('encoding') == 'mumo-json-gzip-v1':
        with gzip.GzipFile(fileobj=io.BytesIO(base64.b64decode(stored['payload'], validate=True))) as stream:
            return json.load(io.TextIOWrapper(stream, encoding='utf-8'))
    return stored  # existing uncompressed histories remain readable
