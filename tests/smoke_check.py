import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
subprocess.run(['python', 'workflow.py'], cwd=ROOT, check=True)
summary = json.loads((ROOT / 'outputs' / 'run_summary.json').read_text())
assert summary['representative_runs'] == 5
assert summary['average_cost_per_run_usd'] > 0
for name in ['base','renewal_risk','support_spike','quality_batch','segment_decline']:
    path = ROOT / 'outputs' / f'run_{name}.json'
    assert path.exists(), path
    data = json.loads(path.read_text())
    assert data['evaluation']['passed'] is True
    assert len(data['token_usage']) >= 8
print('smoke check passed')
