"""Run one saved-response Inspect fixture; never imports references or calls a model."""
import argparse
import json
import os
from pathlib import Path
from typing import Any
from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, GenerateConfig, ModelAPI, ModelCall, ModelOutput, modelapi
from inspect_ai.solver import generate
from inspect_ai.tool import ToolChoice, ToolInfo

parser = argparse.ArgumentParser()
parser.add_argument('case')
parser.add_argument('--out', required=True)
parser.add_argument('--max-retries', type=int, default=0)
args = parser.parse_args()
out = Path(args.out).resolve()
requests = json.loads((out / 'requests.json').read_text())
responses = json.loads((out / 'responses.json').read_text())
if args.case not in requests:
    parser.error('unknown case')

class Simulated429(Exception):
    pass

class FixtureAPI(ModelAPI):
    def should_retry(self, ex: Exception) -> bool:
        return isinstance(ex, Simulated429)

    async def generate(self, input: list[ChatMessage], tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig) -> Any:
        prompt = input[-1].text
        expected = requests[args.case]
        if prompt != expected['prompt'] or tools:
            raise AssertionError('request fidelity failure')
        audit = out / 'inspect-attempts.jsonl'
        ordinal = sum(1 for line in audit.read_text().splitlines() if json.loads(line)['case_id'] == args.case) + 1 if audit.exists() else 1
        event = {'case_id': args.case, 'ordinal': ordinal, 'prompt_hex': prompt.encode().hex(), 'request_identity': expected['identity_sha256'], 'temperature': config.temperature, 'max_tokens': config.max_tokens, 'max_retries': config.max_retries}
        with audit.open('a') as file:
            file.write(json.dumps(event) + '\n')
            file.flush()
            os.fsync(file.fileno())
        if args.case == 'crash':
            os._exit(77)
        if args.case == 'rate_limit' and ordinal == 1:
            raise Simulated429('simulated 429')
        raw = responses[args.case].get('raw')
        native = responses[args.case].get('native')
        content = raw if raw is not None else json.dumps(native, separators=(',', ':'))
        output = ModelOutput.from_content(model=responses[args.case]['reported_model'], content=content)
        return output, ModelCall.create(request={'messages': [{'role': m.role, 'content': m.text} for m in input], 'controls': expected['controls']}, response={'raw': raw, 'native': native, 'reported_model': responses[args.case]['reported_model']})

@modelapi(name='savedfixture')
def savedfixture():
    return FixtureAPI

log = eval(Task(dataset=[Sample(input=requests[args.case]['prompt'], id=args.case)], solver=generate(), name='saved_fixture'), model='savedfixture/offline', temperature=0, max_tokens=256, max_retries=args.max_retries, display='none', log_dir=str(out / 'inspect-logs'), log_model_api=True)[0]
print(json.dumps({'case': args.case, 'status': log.status, 'sample_error': bool(log.samples and log.samples[0].error), 'completion': log.samples[0].output.completion if log.samples else None, 'log': str(log.location)}))
