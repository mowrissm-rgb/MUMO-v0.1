"""Bounded retries for public read-only lookups; TLS checks remain enabled."""
import time
import requests


def get(url, **kwargs):
    kwargs.setdefault('timeout', 30)
    for attempt in range(3):
        try:
            response = requests.get(url, **kwargs)
        except requests.exceptions.SSLError:
            # Retrying does not repair an invalid certificate.
            raise
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
        else:
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                return response
            response.close()
        time.sleep(0.5 * (2 ** attempt))
