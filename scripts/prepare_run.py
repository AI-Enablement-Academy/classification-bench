"""Prepare a private smoke or full fictional run without credentials or inference."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path

from classification_bench.benchmark import preview


def budget_units(value):
    try:
        units = Decimal(value) * 1_000_000
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError('budget must be a positive USD amount') from exc
    if not units.is_finite() or units <= 0 or units != units.to_integral_value():
        raise argparse.ArgumentTypeError('budget must be positive with at most six decimal places')
    return int(units)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, help='New private output directory')
    parser.add_argument('--snapshot', required=True, help='Public endpoint snapshot from catalog command')
    parser.add_argument('--budget-usd', type=budget_units, required=True)
    parser.add_argument('--on-budget-exhausted', choices=('pause', 'stop'), default='pause')
    parser.add_argument('--mode', choices=('smoke', 'full'), required=True)
    parser.add_argument('--task', choices=('candidate', 'product'), default='candidate')
    parser.add_argument('--max-output-tokens', type=int, default=512)
    args = parser.parse_args(argv)
    snapshot = json.loads(Path(args.snapshot).read_text())
    target = Path(args.directory).resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    fixture = Path(__file__).resolve().parents[1] / 'examples' / args.task
    for name in ('task.json', 'inputs.json'):
        (target/name).write_bytes((fixture/name).read_bytes())
    experiment = json.loads((fixture/'experiment.json').read_text())
    experiment['configs'] = [{'id':'openrouter-pinned', 'model':snapshot['model_id'], 'settings':{
        'adapter':'openrouter', 'provider':snapshot['provider_tag'],
        'max_output_tokens':args.max_output_tokens, 'temperature':0,
        'endpoint_snapshot':snapshot}}]
    experiment['batch_size'] = 1
    if args.mode == 'smoke':
        experiment['repeats'] = 1
        experiment['prompts'] = experiment['prompts'][:1]
    (target/'experiment.json').write_text(json.dumps(experiment, indent=2)+'\n')
    config = dict(schema_version=1, task=str(target/'task.json'), experiment=str(target/'experiment.json'),
                  inputs=str(target/'inputs.json'), database=str(target/'run.sqlite'),
                  artifacts=str(target/'artifacts'), scope=f'openrouter:{args.mode}',
                  cap=args.budget_usd, currency='USD', scale=1000000,
                  max_concurrency=1, provider_limits={snapshot['provider_tag']:1},
                  authorization_file=str(target/'authorization.json'),
                  on_budget_exhausted=args.on_budget_exhausted)
    path = target/'config.json'
    path.write_text(json.dumps(config, indent=2)+'\n')
    proposal = preview(path)
    (target/'preview.json').write_text(json.dumps(proposal, indent=2)+'\n')
    # Deliberately no authorization file and no key lookup. An operator reviews
    # preview.json and supplies a separate explicit grant only after approval.
    print(json.dumps({'config':str(path), 'preview':str(target/'preview.json'),
                      'request_count':proposal['request_count'], 'cap_micro_usd':config['cap'],
                      'sum_request_bounds_micro_usd':proposal['sum_request_bounds'],
                      'authorization':'pending; no authorization file created', 'model_calls':0}, indent=2))


if __name__ == '__main__':
    main()
