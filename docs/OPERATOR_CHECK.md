# Second-operator reproduction check

This check requires an independent operator to run the documented workflow and inspect the report. The user explicitly selected subagents for this check. Record agent reproduction as agent reproduction; distinguish it from human inspection and browser rendering. Automated unit tests alone do not replace the workflow check. This check makes no model calls and needs no API key or spending authorization.

## Run from the private checkout

Use a fresh directory name for each invocation; existing output paths are not overwritten. Confirm the checkout commit with `git rev-parse HEAD`, then run:

```sh
python3 -m scripts.offline_demo --task candidate --directory /tmp/classification-operator-candidate
python3 -m scripts.offline_demo --task product --directory /tmp/classification-operator-product
python3 -m classification_bench status --config /tmp/classification-operator-candidate/config.json
python3 -m classification_bench run --config /tmp/classification-operator-candidate/config.json
python3 -m classification_bench recover --config /tmp/classification-operator-candidate/config.json
```

Each fictional demo should finish 24 synthetic requests and retain all 36 planned positions. The second candidate `run` should add no requests; recovery should have no unresolved work. Neither command reads a provider key. The synthetic report demonstrates software behavior, not model performance. Definitions and expected fixture behavior are in [RUNNER.md](RUNNER.md) and [the candidate fixture](../examples/candidate/README.md).

## Inspect the local reports

Open `/tmp/classification-operator-candidate/report.html` and `/tmp/classification-operator-product/report.html` in your browser. Check that tables and charts are readable; task/model/provider/effort/prompt/repeat/route filters work; supporting case details are accessible; and empty measurements do not appear as measured zero. Verify that missing and invalid outputs remain in the displayed denominator and are distinguished from valid disagreements.

The implementing agent's browser tool rejected local-file navigation. A permitted browser inspection is needed for rendered layout and interaction evidence; static HTML inspection cannot establish those results. Do not publish the reports or upload private inputs to bypass that restriction.

Optionally inspect the already saved live report at `private-data/smoke-20260928/offline-evaluation/report-parser-correction.html` in this machine's checkout. It must identify itself as an offline parser correction over two suffix responses, retain the invalid outcomes, and disclose the original unknown attempt and hold outside that report. The private archive is not tracked; its absence from another checkout is expected. Do not execute archived live grants, resume the original live run, or treat this check as permission for more inference.

## Return the result

Record the commit, Python/OS/browser versions, whether both demos and the restart/recovery checks succeeded, whether the report filters and case details worked, and any exact error or visual defect. Report an unsuccessful or unperformed check honestly. Successful independent reproduction can close the operator workflow gate; rendered report inspection remains a separate gate. The unresolved model-identity comparison and any further live checks remain separate, as recorded in [LIVE_SMOKE_RESULT.md](LIVE_SMOKE_RESULT.md).

Latest result: [independent subagent check](OPERATOR_CHECK_RESULT.md). Workflow and static report inspection passed; browser rendering remains unverified.
