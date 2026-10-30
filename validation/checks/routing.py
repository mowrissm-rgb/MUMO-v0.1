"""Routing and outage check: dispatch accuracy and the specialist split.

Protocol: validation/PROTOCOL.md, section "Routing and outage". Tests the
deterministic modules only (no LLM parser, no Streamlit UI).
"""
import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

SERVICE_ENV = ('MUMO_SPACE_DOCKING', 'MUMO_SPACE_SEQUENCE', 'MUMO_SPACE_CHEM', 'MUMO_SPACE_REPORT')


class FakeSpecialist:
    """A tiny specialist service: /health returns 200; /run/<cap> behaves per `mode`."""

    def __init__(self, port=0, mode='ok'):
        owner = self
        self.mode = mode

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body, ctype='application/json'):
                data = body.encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, json.dumps({'ok': True}))

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                self.rfile.read(length)
                if owner.mode == 'err500':
                    self._send(500, 'internal error')
                elif owner.mode == 'nonjson':
                    self._send(200, 'this is not json', 'text/plain')
                else:
                    self._send(200, json.dumps({'ok': True, 'capability': self.path}))

        self.server = HTTPServer(('127.0.0.1', port), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f'http://127.0.0.1:{self.port}'

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


def wiring_audit(src_root):
    """Descriptive: where the app (outside services/) references the remote-specialist path."""
    hits = {'client.call': [], 'MUMO_SPACE': [], 'registry.referral': [], 'resilience': []}
    for path in Path(src_root).rglob('*.py'):
        rel = path.relative_to(src_root).as_posix()
        if rel.startswith('services/'):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        for key in hits:
            if key in text or (key == 'registry.referral' and 'referral(' in text):
                hits[key].append(rel)
    return hits


def run(manifest, ctx):
    from validation.harness import ROOT
    import dispatch
    from agent_catalog import agent_for
    from services import client, registry, resilience

    items = []

    # ── Part R ──
    req_ok = req_total = 0
    non_ok = non_total = 0
    multi_ok = multi_total = 0
    by_cat, failures = {}, []
    for i, case in enumerate(manifest['routing_cases']):
        got = dispatch.requested_actions(case['text'])
        ok = got == case['expect']
        cat = case['category']
        by_cat.setdefault(cat, [0, 0])
        by_cat[cat][1] += 1
        by_cat[cat][0] += ok
        if cat in ('plain', 'explicit', 'multi'):
            req_total += 1
            req_ok += ok
        if cat == 'multi':
            multi_total += 1
            multi_ok += ok
        if cat in ('question', 'trap'):
            non_total += 1
            non_ok += ok
        if not ok:
            failures.append({'text': case['text'], 'expected': case['expect'], 'got': got, 'category': cat})
        items.append({'item': f'R:{i:02d} {case["text"][:50]}', 'status': 'PASS' if ok else 'FAIL',
                      'details': {'category': cat, 'expected': case['expect'], 'got': got}})

    ready_ok = 0
    for case in manifest['readiness_cases']:
        got = dispatch.is_ready(case['action'], case['convo'])
        ok = got == case['ready']
        ready_ok += ok
        items.append({'item': f'R4:{case["name"]}', 'status': 'PASS' if ok else 'FAIL',
                      'details': {'expected': case['ready'], 'got': got}})

    unsup_ok = 0
    for case in manifest['unsupported_cases']:
        message = dispatch.unsupported_request(case['text'])
        ok = bool(message) == case['flag']
        unsup_ok += ok
        items.append({'item': f'R5:{case["text"][:50]}', 'status': 'PASS' if ok else 'FAIL',
                      'details': {'expected_flagged': case['flag'], 'flagged': bool(message),
                                  'message_start': message[:60]}})

    # ── Part O ──
    saved_env = {k: os.environ.get(k) for k in SERVICE_ENV + ('MUMO_XTB', 'MUMO_MD_PYTHON')}
    for k in SERVICE_ENV:
        os.environ.pop(k, None)
    os.environ['MUMO_XTB'] = str(ROOT / 'bin' / 'xtb-6.7.1pre' / 'xtb-6.7.1' / 'bin' / 'xtb.exe')
    os.environ['MUMO_MD_PYTHON'] = str(ROOT / 'bin' / 'mdenv' / 'python.exe')
    resilience.reset()
    client.invalidate_health()

    # O1
    o1 = []
    for action, name in manifest['agent_names'].items():
        owned = registry.owner_of(action) is not None
        named = agent_for(action) == name
        o1.append(owned and named)
        items.append({'item': f'O1:{action}', 'status': 'PASS' if (owned and named) else 'FAIL',
                      'details': {'owner': registry.owner_of(action), 'agent_for': agent_for(action),
                                  'expected_name': name}})

    # O2
    o2 = []
    for cap in sorted(registry.OWNER):
        try:
            out = client.call(cap, {})
            ok, detail = out is None, repr(out)
        except Exception as exc:
            ok, detail = False, f'{type(exc).__name__}: {exc}'
        o2.append(ok)
        items.append({'item': f'O2:{cap}', 'status': 'PASS' if ok else 'FAIL', 'details': {'result': detail}})

    # O3
    os.environ['MUMO_SPACE_DOCKING'] = manifest['dead_endpoint']
    client.invalidate_health()
    resilience.reset()
    o3_down, o3_up = [], []
    for cap in ('dock', 'ramachandran', 'md', 'structure'):
        try:
            client.call(cap, {})
            ok, detail = False, 'returned without raising'
        except client.SpecialistUnavailable as exc:
            ok, detail = True, str(exc)[:80]
        except Exception as exc:
            ok, detail = False, f'{type(exc).__name__}: {exc}'
        if cap != 'structure':          # protocol: capabilities with a resilience requirement
            o3_down.append(ok)
        items.append({'item': f'O3:down:{cap}', 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})
    for cap in sorted(registry.OWNER):
        if registry.owner_of(cap) == 'A':
            continue
        try:
            ok = client.call(cap, {}) is None
            detail = 'served locally' if ok else 'not served locally'
        except Exception as exc:
            ok, detail = False, f'{type(exc).__name__}: {exc}'
        o3_up.append(ok)
        items.append({'item': f'O3:up:{cap}', 'status': 'PASS' if ok else 'FAIL', 'details': {'outcome': detail}})
    msg = registry.unavailable('dock')
    o3_msg = 'Pose' in msg and 'dock' in msg and 'No result' in msg
    items.append({'item': 'O3:message', 'status': 'PASS' if o3_msg else 'FAIL', 'details': {'message': msg}})
    o3 = all(o3_down) and all(o3_up) and o3_msg
    os.environ.pop('MUMO_SPACE_DOCKING', None)
    client.invalidate_health()

    # O4
    o4, o4_fail = [], []
    for cap in sorted(registry.OWNER):
        owner = registry.owner_of(cap)
        for sid in registry.SPECIALISTS:
            text = registry.referral(cap, sid)
            if owner == sid:
                ok = text == ''
            else:
                name = agent_for(cap) or registry.specialist(owner)['name']
                ok = name in text and 'I can still run this' in text
            o4.append(ok)
            if not ok:
                o4_fail.append(f'{cap} from {sid}: {text[:80]!r}')
    items.append({'item': 'O4:referral', 'status': 'PASS' if all(o4) else 'FAIL',
                  'details': {'pairs': len(o4), 'failures': o4_fail[:6]}})

    # O5
    saved_cooldown = resilience.COOLDOWN
    resilience.COOLDOWN = manifest['breaker_cooldown_seconds']
    resilience.reset()
    o5 = {}
    resilience.record_failure('string', 'x')
    o5['one_failure_keeps_it_up'] = resilience.available('string')[0]
    resilience.record_failure('string', 'x')
    o5['two_failures_open_it'] = (not resilience.available('string')[0]
                                  and 'temporarily unavailable' in resilience.message('string'))
    o5['other_capability_unaffected'] = resilience.available('blast')[0]
    time.sleep(manifest['breaker_cooldown_seconds'] + 0.15)
    o5['recovers_after_cooldown'] = resilience.available('string')[0]
    resilience.reset()
    resilience.record_failure('string', 'x')
    resilience.record_success('string')
    resilience.record_failure('string', 'x')
    o5['success_clears_count'] = resilience.available('string')[0]
    resilience.COOLDOWN = saved_cooldown
    resilience.reset()
    items.append({'item': 'O5:breaker', 'status': 'PASS' if all(o5.values()) else 'FAIL', 'details': o5})

    # O6
    cap = manifest['fake_specialist_cap']
    sid = registry.owner_of(cap)
    env_name = registry.specialist(sid)['env']
    o6 = {}
    server = FakeSpecialist(mode='ok')
    port = server.port
    os.environ[env_name] = server.url
    try:
        client.invalidate_health()
        try:
            o6['healthy_returns_json'] = client.call(cap, {}) == {'ok': True, 'capability': f'/run/{cap}'}
        except Exception as exc:
            o6['healthy_returns_json'] = False
            o6['healthy_error'] = f'{type(exc).__name__}: {exc}'
        server.mode = 'err500'
        try:
            client.call(cap, {})
            o6['http_500_raises'] = False
        except client.SpecialistUnavailable as exc:
            o6['http_500_raises'] = 'HTTP 500' in str(exc)
        server.mode = 'nonjson'
        try:
            client.call(cap, {})
            o6['non_json_raises'] = False
        except client.SpecialistUnavailable as exc:
            o6['non_json_raises'] = 'non-JSON' in str(exc)
        server.stop()
        client.invalidate_health()
        try:
            client.call(cap, {})
            o6['server_down_raises'] = False
        except client.SpecialistUnavailable:
            o6['server_down_raises'] = not client.health(sid, force=True)
        server = FakeSpecialist(port=port, mode='ok')
        client.invalidate_health()
        o6['recovers'] = bool(client.health(sid, force=True)) and client.call(cap, {}) is not None
    finally:
        try:
            server.stop()
        except Exception:
            pass
        os.environ.pop(env_name, None)
        client.invalidate_health()
    o6_checks = [o6.get(k) for k in ('healthy_returns_json', 'http_500_raises', 'non_json_raises',
                                     'server_down_raises', 'recovers')]
    items.append({'item': 'O6:fake_specialist', 'status': 'PASS' if all(o6_checks) else 'FAIL', 'details': o6})

    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    audit = wiring_audit(ROOT / 'src')
    r1 = req_ok / req_total
    r2 = (non_total - non_ok) / non_total
    criteria = [
        {'id': 'R1', 'description': f"exact-match accuracy on request cases >= {manifest['request_min_accuracy']}",
         'passed': r1 >= manifest['request_min_accuracy'], 'value': f'{req_ok}/{req_total} = {r1:.3f}'},
        {'id': 'R2', 'description': f"false-trigger rate on non-requests <= {manifest['false_trigger_max_rate']}",
         'passed': r2 <= manifest['false_trigger_max_rate'], 'value': f'{non_total - non_ok}/{non_total} = {r2:.3f}'},
        {'id': 'R3', 'description': f"multi-step order correct in >= {manifest['multi_min_correct']} of {multi_total}",
         'passed': multi_ok >= manifest['multi_min_correct'], 'value': f'{multi_ok}/{multi_total}'},
        {'id': 'R4', 'description': 'readiness rules (6 of 6)',
         'passed': ready_ok == len(manifest['readiness_cases']), 'value': f"{ready_ok}/{len(manifest['readiness_cases'])}"},
        {'id': 'R5', 'description': f"out-of-scope detection >= {manifest['unsupported_min_correct']} of {len(manifest['unsupported_cases'])}",
         'passed': unsup_ok >= manifest['unsupported_min_correct'], 'value': f"{unsup_ok}/{len(manifest['unsupported_cases'])}"},
        {'id': 'O1', 'description': 'every routed action has an owner and the documented workflow name (7 of 7)',
         'passed': len(o1) == 7 and all(o1), 'value': f'{sum(o1)}/{len(o1)}'},
        {'id': 'O2', 'description': 'all capabilities served locally when nothing is remote (13 of 13)',
         'passed': len(o2) == len(registry.OWNER) and all(o2), 'value': f'{sum(o2)}/{len(o2)}'},
        {'id': 'O3', 'description': 'one specialist down: its capabilities raise, the rest keep serving, message names it',
         'passed': o3, 'value': f'down {sum(o3_down)}/{len(o3_down)}, up {sum(o3_up)}/{len(o3_up)}, message {o3_msg}'},
        {'id': 'O4', 'description': 'referral rules hold for every capability and specialist pair (100%)',
         'passed': all(o4), 'value': f'{sum(o4)}/{len(o4)} pairs'},
        {'id': 'O5', 'description': 'circuit breaker behaves as specified (5 of 5)',
         'passed': all(o5.values()), 'value': f'{sum(o5.values())}/{len(o5)}'},
        {'id': 'O6', 'description': 'remote specialist behaviour on a fake server (5 of 5)',
         'passed': all(o6_checks), 'value': f'{sum(bool(x) for x in o6_checks)}/5'},
    ]
    extras = {'by_category': {k: f'{v[0]}/{v[1]}' for k, v in by_cat.items()}, 'routing_failures': failures,
              'wiring_audit_references_outside_services': audit,
              'not_tested': ['LLM intent parser', 'Streamlit chat UI', 'a real crashed container']}
    return items, criteria, extras
