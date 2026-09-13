"""Evidence records for executed calculations; verification is not experimental validation."""
import hashlib
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
import json


def validate_box(center, size):
    if len(center) != 3 or len(size) != 3:
        raise ValueError('Docking box requires three coordinates and dimensions.')
    if not all(math.isfinite(float(v)) for v in list(center) + list(size)):
        raise ValueError('Docking box contains nonfinite values.')
    if not all(float(v) > 0 for v in size):
        raise ValueError('Docking box dimensions must be positive.')


def validate_docking_result(result):
    score = float(result['best_score'])
    modes = result['modes']
    if not math.isfinite(score) or not modes or result.get('n', 0) < 1:
        raise ValueError('Docking result lacks finite scores or completed replicas.')
    if not all(math.isfinite(float(value)) for _, value in modes):
        raise ValueError('Docking mode contains a nonfinite score.')
    if abs(float(modes[0][1]) - score) > 0.001:
        raise ValueError('Selected docking score disagrees with its mode table.')
    pose = Path(result['out_pdbqt']).read_text()
    atoms = [line for line in pose.splitlines() if line.startswith(('ATOM  ', 'HETATM'))]
    if not atoms or not all(math.isfinite(float(line[a:b])) for line in atoms
                            for a,b in ((30,38),(38,46),(46,54))):
        raise ValueError('Docking output has no valid finite atom coordinates.')


def capture_artifacts(artifacts):
    captured = {}
    for name, descriptor in artifacts.items():
        path = descriptor['path'] if isinstance(descriptor, dict) else descriptor
        raw = Path(path).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if isinstance(descriptor, dict) and descriptor.get('sha256') not in (None, digest):
            raise ValueError(f'Artifact changed after analysis: {name}')
        captured[name] = {'filename': Path(path).name, 'sha256': digest,
                          'text': raw.decode('utf-8')}
    return captured


def verify_artifacts(artifacts):
    return all(hashlib.sha256(v['text'].encode('utf-8')).hexdigest() == v['sha256']
               for v in artifacts.values())


def run_record(workflow, inputs, settings, steps, artifacts=None):
    statuses = [step.get('status', 'unavailable') for step in steps.values()]
    good = {'verified', 'qualified'}
    status = ('verified' if statuses and all(s == 'verified' for s in statuses)
              else 'qualified' if statuses and all(s in good for s in statuses)
              else 'partial' if any(s in good for s in statuses) else 'failed')
    return {'schema_version': 1, 'run_id': str(uuid.uuid4()),
            'created_at': datetime.now(timezone.utc).isoformat(),
            'workflow': workflow, 'result_kind': 'prediction', 'status': status,
            'inputs': inputs, 'settings': settings, 'steps': steps,
            'artifacts': {k: {field: value for field, value in v.items() if field != 'text'}
                          for k, v in (artifacts or {}).items()},
            'verification_scope': 'Recorded execution, schema and artifact checks; not experimental validation.'}


def evidence_json(result):
    """Portable evidence without rendered images or nonstandard JSON numbers."""
    def normalize(value):
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()
                    if not isinstance(v, bytes) and k not in ('svg_2d', 'png', 'html')}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if hasattr(value, 'to_dict'):
            return normalize(value.to_dict(orient='records'))
        if hasattr(value, 'item'):
            return normalize(value.item())
        return value
    return json.dumps(normalize(result), indent=2, allow_nan=False, default=str).encode('utf-8')
