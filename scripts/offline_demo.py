"""Reproduce a complete fictional benchmark and private report without model calls."""
import argparse
import json
import os
from pathlib import Path

from classification_bench.benchmark import preview, run, export_predictions, export_operations
from classification_bench.core import build_plan
from classification_bench.report import generate_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, help='New private output directory')
    parser.add_argument('--task', choices=('candidate', 'product'), default='candidate')
    args = parser.parse_args()
    target = Path(args.directory).resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    examples = Path(__file__).resolve().parents[1] / 'examples' / args.task
    config = dict(schema_version=1, task=str(examples/'task.json'), experiment=str(examples/'experiment.json'),
                  inputs=str(examples/'inputs.json'), database=str(target/'run.sqlite'),
                  artifacts=str(target/'artifacts'), scope='synthetic:demo', cap=1000,
                  currency='SYN', scale=1, max_concurrency=2,
                  provider_limits={'synthetic': 2}, authorization_file=None,
                  on_budget_exhausted='pause')
    config_path = target/'config.json'
    config_path.write_text(json.dumps(config, indent=2)+'\n')
    planned = preview(config_path)
    (target/'preview.json').write_text(json.dumps(planned, indent=2)+'\n')
    status = run(config_path)
    predictions = export_predictions(config_path)
    operations = export_operations(config_path)
    read = lambda name: json.loads((examples/name).read_text())
    task = read('task.json')
    plan = build_plan(task, read('experiment.json'), read('inputs.json'))
    html = generate_report(task, plan, read('labels.json'), predictions, operations)
    descriptor = os.open(target/'report.html', os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(html)
    print(json.dumps({'execution': status, 'report': str(target/'report.html'),
                      'config': str(config_path), 'live_model_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
