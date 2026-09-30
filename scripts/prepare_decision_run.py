"""Prepare a native categorical decision experiment; never authorize or dispatch."""
import argparse
import json
from pathlib import Path

from classification_bench.benchmark import preview
from scripts.prepare_run import budget_units

MODELS = {
    'liquid_decide': ('d1:free', 'liquid'),
    'solar_decide': ('solar-decide', 'upstage'),
    'qwen_decision': ('decision-model-preview', 'qwen'),
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--adapter', required=True, choices=MODELS)
    parser.add_argument('--billing-snapshot', required=True,
                        help='Reviewed provider billing evidence; no inferred default price')
    parser.add_argument('--task', choices=('product', 'candidate'), default='product')
    parser.add_argument('--mode', choices=('smoke', 'full'), required=True)
    parser.add_argument('--budget-usd', type=budget_units, required=True)
    parser.add_argument('--on-budget-exhausted', choices=('pause', 'stop'), default='pause')
    parser.add_argument('--workspace-id')
    parser.add_argument('--region', choices=('cn-beijing', 'ap-southeast-1'))
    args = parser.parse_args(argv)
    if args.adapter == 'qwen_decision':
        if not args.workspace_id or not args.region:
            parser.error('Qwen requires --workspace-id and --region')
    elif args.workspace_id or args.region:
        parser.error('Workspace and region apply only to Qwen')
    billing = json.loads(Path(args.billing_snapshot).read_text())
    model, provider = MODELS[args.adapter]
    settings = {'adapter': args.adapter, 'billing_snapshot': billing}
    if args.adapter == 'qwen_decision':
        settings.update(workspace_id=args.workspace_id, region=args.region)
    target = Path(args.directory).resolve()
    target.mkdir(mode=0o700, parents=True, exist_ok=False)
    fixture = Path(__file__).resolve().parents[1] / 'examples' / args.task
    for name in ('task.json', 'inputs.json'):
        (target / name).write_bytes((fixture / name).read_bytes())
    experiment = json.loads((fixture / 'experiment.json').read_text())
    experiment['configs'] = [{'id': args.adapter, 'model': model, 'settings': settings}]
    experiment['batch_size'] = 1
    if args.mode == 'smoke':
        experiment['repeats'] = 1
        experiment['prompts'] = experiment['prompts'][:1]
    (target / 'experiment.json').write_text(json.dumps(experiment, indent=2)+'\n')
    config = dict(schema_version=1, task=str(target/'task.json'),
                  experiment=str(target/'experiment.json'), inputs=str(target/'inputs.json'),
                  database=str(target/'run.sqlite'), artifacts=str(target/'artifacts'),
                  scope=f'{args.adapter}:{args.mode}', cap=args.budget_usd,
                  currency='USD', scale=1000000, max_concurrency=1,
                  provider_limits={provider: 1}, authorization_file=str(target/'authorization.json'),
                  on_budget_exhausted=args.on_budget_exhausted)
    path = target/'config.json'
    path.write_text(json.dumps(config, indent=2)+'\n')
    proposal = preview(path)
    (target/'preview.json').write_text(json.dumps(proposal, indent=2)+'\n')
    for item in target.iterdir():
        if item.is_file():
            item.chmod(0o600)
    print(json.dumps({'config':str(path), 'preview':str(target/'preview.json'),
                      'request_count':proposal['request_count'],
                      'cap_micro_usd':config['cap'],
                      'sum_request_bounds_micro_usd':proposal['sum_request_bounds'],
                      'authorization':'pending; no authorization file created',
                      'model_calls':0}, indent=2))


if __name__ == '__main__':
    main()
