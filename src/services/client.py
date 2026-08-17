"""
MUMO — dispatching work to a specialist service.

The registry says WHERE a capability lives. This module actually calls it, and
decides what happens when the call does not come back.

DESIGN RULES, EACH EARNED THE HARD WAY
--------------------------------------
* **Never fall back to running heavy work locally.** If the docking specialist
  is unreachable, we report that and stop. Importing Vina/ProLIF into the front
  door to "be helpful" recreates the exact segfault that motivated the split —
  a partial outage would become a total one.
* **Health is cached, not polled per call.** A liveness probe in front of every
  request doubles the latency of the common case to protect against the rare
  one. A short TTL gives the same protection for one probe per interval.
* **A sleeping Space is not a broken Space.** Free-tier Spaces cold-start, so a
  first call can legitimately take a minute. Timeouts are per-capability, and
  the retry exists to ride out a wake-up, not to hammer a dead host.
* **Transport errors retry once; HTTP errors do not.** A dropped connection is
  worth retrying. A 500 means the specialist ran our job and failed at it, and
  sending it again just fails twice — the same distinction `auth_store._run`
  draws for Supabase.
"""

import time

import requests

from . import registry

# Cold starts are real on free Spaces, so these are generous. Docking is long
# by nature; the others should be quick or something is wrong.
TIMEOUTS = {
    "dock": 900,
    "md": 900,
    "report": 600,
    "export": 300,
    "blast": 180,
    "string": 120,
    "phylogeny": 180,
}
DEFAULT_TIMEOUT = 120

_HEALTH_TTL = 60.0          # seconds a health verdict stays trusted
_health = {}                # sid -> (checked_at, ok)


class SpecialistUnavailable(RuntimeError):
    """The specialist could not be reached, or refused to run.

    Carries the capability so the caller can render registry.unavailable()
    without having to remember what it asked for.
    """

    def __init__(self, capability, detail=""):
        self.capability = capability
        self.detail = detail
        super().__init__(f"{capability} specialist unavailable: {detail}".strip())


def health(sid, force=False):
    """Is this specialist up? Cached for _HEALTH_TTL seconds.

    A specialist served locally is always 'up' — there is no network in the way.
    """
    url = registry.endpoint(sid)
    if not url:
        return True

    now = time.time()
    hit = _health.get(sid)
    if hit and not force and (now - hit[0]) < _HEALTH_TTL:
        return hit[1]

    ok = False
    try:
        r = requests.get(f"{url}/health", timeout=10)
        ok = r.status_code == 200
    except requests.RequestException:
        ok = False
    _health[sid] = (now, ok)
    return ok


def invalidate_health(sid=None):
    """Drop cached health so the next call re-probes. Called after a failure,
    so a specialist that just died is not treated as healthy for another TTL."""
    if sid:
        _health.pop(sid, None)
    else:
        _health.clear()


def call(capability, payload, timeout=None):
    """Run `capability` on its specialist.

    Returns the specialist's decoded JSON result.

    Raises SpecialistUnavailable if it is unreachable — deliberately, rather
    than silently running the job here.

    Returns None when the capability is served LOCALLY, which is the caller's
    signal to run it in-process exactly as before. That is what keeps every
    un-migrated capability working untouched.
    """
    sid = registry.owner_of(capability)
    if not sid:
        raise ValueError(f"No specialist owns capability {capability!r}")

    url = registry.endpoint(sid)
    if not url:
        # Local — but still gated, so a capability that is broken IN THIS
        # PROCESS (missing RDKit, absent Vina, repeated crashes) degrades
        # exactly like an unreachable remote one. One failure path, one
        # message, whether or not the split has happened yet.
        from . import resilience
        ok, reason = resilience.available(capability)
        if not ok:
            raise SpecialistUnavailable(capability, reason or "unavailable locally")
        return None                      # caller runs it itself

    if not health(sid):
        raise SpecialistUnavailable(capability, "health check failed")

    t = timeout or TIMEOUTS.get(capability, DEFAULT_TIMEOUT)
    last = ""
    for attempt in (1, 2):
        try:
            r = requests.post(f"{url}/run/{capability}", json=payload, timeout=t)
        except requests.RequestException as e:
            # transport-level: the connection never completed, so the job may
            # not have run at all. Worth one retry — this is also what riding
            # out a cold start looks like.
            last = f"{type(e).__name__}: {e}"
            invalidate_health(sid)
            if attempt == 1:
                time.sleep(2)
                continue
            raise SpecialistUnavailable(capability, last)

        if r.status_code == 200:
            try:
                return r.json()
            except ValueError:
                raise SpecialistUnavailable(
                    capability, "specialist returned a non-JSON body")

        # The specialist answered, so it is alive; it just could not do this
        # job. Retrying would fail identically and cost the user the wait.
        detail = (r.text or "")[:200].replace("\n", " ")
        raise SpecialistUnavailable(capability, f"HTTP {r.status_code}: {detail}")

    raise SpecialistUnavailable(capability, last)


def describe(capability, current_sid="B"):
    """Routing decision as plain text, for logs and for the UI's status line."""
    sid = registry.owner_of(capability)
    if not sid:
        return f"{capability}: no owning specialist"
    spec = registry.specialist(sid)
    where = registry.endpoint(sid) or "in-process"
    note = " (referral)" if sid != current_sid else ""
    return f"{capability} -> {spec['name']} [{where}]{note}"
