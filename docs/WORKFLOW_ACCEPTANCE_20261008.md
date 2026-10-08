# Workflow acceptance, 8 October 2026

The [frozen workflow](WORKFLOW.md) prepares and runs smoke/full phases for both
fictional examples through the installed CLI. The examples test software
behavior; they make no claims about model quality, subscription quota or paid
provider access.

## Independent installation

An independent worker copied only the package and `pyproject.toml`, built a wheel
with `pip wheel --no-index --no-deps --no-build-isolation`, and installed it into
a fresh virtual environment without system site packages or runtime
dependencies. The build used existing setuptools 80.10.2 and wheel 0.47.0;
it does not prove installation on a machine lacking those build prerequisites.

The installed module resolved inside the new environment's Python 3.14
`site-packages`. Commands ran from an unrelated directory with no `PYTHONPATH`
or source-tree fallback. All installed source hashes matched the final package
copy, including the final report provenance change.

Twenty-eight CLI commands passed across the product and candidate examples:
preparation, preview, smoke/full preflight and execution, status, export, phase
reports and combined reports. Six reports were regenerated and checked after
the final report change. Evidence is retained under
`/private/tmp/classification-clean-install-wlp5npo5/evidence/` in
`operator-acceptance.json`, `final-install-acceptance.json` and
`all-commands.txt`. These temporary logs may be removed by the operating system;
the reproducible commands and fixtures are in [the workflow guide](WORKFLOW.md).

## Private inspection artifacts

Fresh repository-side CLI reproduction is retained under
`private-data/workflow-acceptance-20261008T044900/`. Each example completed the
following work exactly once in its own prepared workflow:

| Phase, per example | Requests | Planned outputs | Valid selected | Invalid |
| --- | ---: | ---: | ---: | ---: |
| Smoke | 4 | 4 | 2 | 2 |
| Full | 24 | 36 | 18 | 18 |

All outputs remain in the denominator. Repeated records are scheduled outputs,
not additional independent cases. Synthetic charges settle at zero; cumulative
paid/request-cap exhaustion is proved separately with offline accounting
fixtures, not inferred from these examples.

| Final report | SHA-256 |
| --- | --- |
| `product/report-final.html` | `2aa930a4a0869272b52c246dccb06842ac7d96b9a83aadd8992992a41e9d444b` |
| `candidate/report-final.html` | `0788665c16a59ebed206ed29f42418d39f97afc0378f7fb84b194ed64ccfcc16` |

Both reports have mode 0600. Each passed syntax checks for 17 JavaScript scripts
and parsing checks for 13 JSON script blocks, including both embedded phase
reports. `inspection-final.json` preserves the exact paths, hashes and counts.
These are source/syntax checks, not rendered acceptance.

## Review and remaining gates

Review reproduced and repaired interrupted aggregate-startup inspection,
blocked-group credential lookup preventing independent progress, portable
evidence links selecting the wrong run, and dollar-token expansion corrupting
restored URLs. Workflow preparation, execution, metadata and report contracts
retain independent verification boundaries. Independent preparation, execution/CLI/scheduler and combined-report reviews
returned **APPROVE** after the confirmed BLOCKING findings were repaired.
The primary agent independently reviewed metadata validation, projection,
exports and rendering without a confirmed finding. The report reviewer added
seven durable DOM regressions and independently reran all ten workflow
execution tests.

The DOM harness opens iframe content in a separate `about:srcdoc` document and
relays its actual frame sender. It explicitly models same-file fragment history
because jsdom compares file-path arrays by identity, and captures download
bytes without native file saving. Those harness accommodations do not establish
real-browser behavior. Full-suite results are recorded in
[implementation status](IMPLEMENTATION_STATUS.md).

No credentials were copied, provider inference dispatched, billing settings
changed, or source-project files modified. The fresh installation gate is
complete for the recorded platform and prerequisites. Current live-route
acceptance, account/provider evidence and exact rendered desktop/mobile,
keyboard and reduced-motion verification remain open. DOM checks do not prove
recruitment-level visual parity. The [existing browser acceptance boundary](BROWSER_ACCEPTANCE_20261001.md)
still applies; no alternate route was used to bypass it.

The repository remains private. Public release follows completion, final
license selection and the history, dataset and redistribution audit described
in [the goal](NEXT_TASK_GOAL.md).
