# classification-bench

A reusable benchmark core for categorical classification tasks: define the task, compare prompts and model configurations, and measure both agreement and repeatability.

**Current release: offline foundation.** It creates deterministic request plans and scores saved predictions. It does not call models yet. The included three-pass example is a synthetic software fixture, not evidence of model performance or nondeterminism.

## Why a separate project

The [Candidate Experience Feedback Benchmark](https://github.com/adambkovacs/candidate-experience-benchmark) tested four decisions about candidate-written reviews. Its results exposed reusable needs: strict output validation, visible missing answers, versioned references, exact request identities, cost accounting, and repeatability measurements. This repository separates those capabilities from one recruitment dataset.

Each task defines its own inputs, label vocabulary and rubric. Possible task packages include:

| Task | Inputs | Example decisions |
| --- | --- | --- |
| Candidate testimonials | Candidate-written feedback | Sentiment, follow-up, serious concern, testimonial potential |
| Interviewer feedback | Interview evidence and competency rubric | Evidence present, competency category, clarification needed |
| Ideal customer profile | Company description and explicit ICP criteria | Segment, criterion match, missing evidence |
| Candidate/job-description alignment | Candidate evidence and job requirements | Requirement supported, contradicted, or unknown |

Employment-related examples evaluate evidence against a declared rubric; a benchmark score does not establish suitability for autonomous hiring decisions. Task authors must define and review the reference criteria. No real candidate data is bundled.

## Run the offline example

Python 3.10 or later is sufficient. Runtime code uses the standard library and needs no API key.

```sh
python3 -m classification_bench plan   --task examples/task.json   --experiment examples/experiment.json   --inputs examples/inputs.json   --out /tmp/classification-plan.json

python3 -m classification_bench evaluate   --task examples/task.json   --plan /tmp/classification-plan.json   --labels examples/labels.json   --predictions examples/predictions.json   --out /tmp/classification-results.json

python3 -m unittest discover -s tests -v
```

Choose fresh output paths. Existing files are never overwritten.

The example has three fictional product descriptions, two categorical fields and three supplied replay passes. It intentionally contains one label change and one invalid prediction. The evaluator accounts for all nine planned positions and returns exact-match rates of 1, 2/3 and 2/3. This tests the analysis pipeline; no LLM was run.

## Supported now

- Custom named string inputs and any number of categorical output fields, each with a declared vocabulary.
- A configuration × prompt × repeat matrix, with fixed ordered batch membership.
- Content-derived request IDs that change with inputs, prompt bytes, model settings or repeat number.
- Strict predictions: extra fields, missing fields and unknown labels are invalid outcomes.
- Full-denominator exact agreement, per-label precision/recall/F1, confusion counts and macro-F1.
- Per-pass scores and their mean/range, plus per-field and whole-response flip rates between repeat pairs.
- Explicit IDs and denominators for comparable, changed and excluded repeat positions.
- Offline reference scoring, with SHA-256 bindings for task, plan, labels and predictions.
- A Python artifact-store API for raw bytes and immutable parser projections, with verified source bindings and concurrent publication.

Reference labels are a separate file, opened only by `evaluate`. Plans contain the allowed output vocabulary, which is part of the task, but no answer key. This is a data-interface boundary, not an operating-system sandbox.

## Reading the metrics

Missing and invalid predictions earn no exact-match credit and remain in the scheduled denominator. Per-label recall treats them as missed true labels. Precision uses valid predicted labels; invalid outputs do not invent a predicted class. Macro-F1 averages over every declared label, including unsupported classes whose F1 is defined as zero. Inspect support counts alongside that metric.

Flip rates compare only positions with valid predictions in both passes and report excluded IDs. A rate of zero over no comparable positions is meaningless, so the output uses null. Three passes are a useful diagnostic, not a precise estimate of population variability. Repeated answers to three inputs are still three distinct inputs, not nine independent cases.

Changing prompts, models, providers, batch membership, sampling policy or reference versions creates a different comparison. Recovery attempts and cached replay do not count as fresh model repetitions.

## Next implementation stages

Live model execution, budgets, resume, an attempt-event ledger and a report website are **not implemented** in v0.1. The offline artifact-store primitives are available through the Python API; they are not yet connected to a runner. The [architecture](docs/ARCHITECTURE.md) and [delivery plan](docs/ROADMAP.md) describe how to add them while retaining the current benchmark's evidence.

The core accepts categorical fields. Multi-label sets, numerical scores, rankings, multimodal inputs and free-text rationale scoring need separate contracts; they are not silently treated as categorical tasks.

[Source project and reuse decisions](docs/PROVENANCE.md) · [Task and result formats](docs/FORMATS.md)
