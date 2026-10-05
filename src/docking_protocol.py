"""Validated, request-wide docking settings; independent of narrative tier."""

MODES = {'Medium': 8, 'Standard': 16, 'High': 32}


def resolve_protocol(mode=None):
    mode = 'Standard' if mode is None else str(mode).strip().title()
    if mode not in MODES:
        raise ValueError('Unknown docking mode; choose Medium, Standard or High.')
    return {'docking_mode': mode, 'exhaustiveness': MODES[mode],
            'replicas': 3, 'seed': 42, 'replica_seeds': [42, 43, 44]}


def request_for_mode(convo, mode):
    request = dict(convo or {})
    request['docking_mode'] = resolve_protocol(mode)['docking_mode']
    return request
