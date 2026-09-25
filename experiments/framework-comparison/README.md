# Offline framework comparison fixtures

These scripts generate synthetic inputs and saved responses. They do not read references, credentials, or case-study records and make no model calls. Keep generated JSON, framework logs, and installed dependencies outside the repository.

Tested with Inspect AI 0.3.268, promptfoo 0.123.1, Python 3.14.0, and Node 26.4.0. Exact package identities and observed installation size are in [the comparison decision](../../docs/FRAMEWORK_COMPARISON.md). Install the named packages into disposable environments before running. The direct package pins are tested; this repository does not contain a complete transitive lock.

Set `SPIKE_OUT` to a fresh directory outside the repository, for example `SPIKE_OUT=$(mktemp -d /private/tmp/classification-framework-XXXXXX)`, then run:

```sh
python3 experiments/framework-comparison/make_fixtures.py "$SPIKE_OUT"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py paired_P1 --out "$SPIKE_OUT"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py paired_P2 --out "$SPIKE_OUT"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py rate_limit --out "$SPIKE_OUT" --max-retries 1
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py invalid --out "$SPIKE_OUT"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py specialist --out "$SPIKE_OUT"
PROMPTFOO_CONFIG_DIR="$SPIKE_OUT/promptfoo-state" PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_ADAPTIVE_SCHEDULER=1 SPIKE_FIXTURE_DIR="$SPIKE_OUT" node /path/to/promptfoo/node_modules/promptfoo/dist/src/entrypoint.js eval -c "$SPIKE_OUT/promptfooconfig.json" --no-cache --no-progress-bar --no-table --no-write -o "$SPIKE_OUT/promptfoo-results.json"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/inspect_spike.py crash --out "$SPIKE_OUT"
PROMPTFOO_CONFIG_DIR="$SPIKE_OUT/promptfoo-state" PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_ADAPTIVE_SCHEDULER=1 SPIKE_FIXTURE_DIR="$SPIKE_OUT" SPIKE_CRASH=1 node /path/to/promptfoo/node_modules/promptfoo/dist/src/entrypoint.js eval -c "$SPIKE_OUT/promptfoo-crash-config.json" --no-cache --no-progress-bar --no-table --no-write -o "$SPIKE_OUT/promptfoo-crash-results.json"
XDG_DATA_HOME="$SPIKE_OUT/inspect-data" XDG_CACHE_HOME="$SPIKE_OUT/inspect-cache" /path/to/inspect-venv/bin/python experiments/framework-comparison/verify.py "$SPIKE_OUT"
python3 experiments/framework-comparison/test_verify.py
```

The promptfoo command returns exit 100 when the expected invalid JSON and first simulated 429 fail. The two crash commands deliberately exit with code 77 after writing a side audit event. Run them after the ordinary cases and before verification. The framework views alone are not a recovery or billing ledger.
