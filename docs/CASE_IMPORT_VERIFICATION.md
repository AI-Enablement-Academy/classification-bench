# Offline case import verification

The generic planner and evaluator reproduced the validity and field scores of one completed 60-record native OpenJev fixed-choice run. It read the source project's existing development inputs, provisional references, reconciled predictions and evaluation by explicit path and file-byte SHA-256. It made no model calls and stored no candidate text or predictions in this repository.

The saved [source evaluation](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/results/openjev-local-fixed-2026-09-23/evaluation.json) reports 60 records, 60 valid outputs, no missing or failed IDs, and 57/60 sentiment, 59/60 follow-up, 56/60 serious-concern and 58/60 testimonial decisions correct. The generic evaluator returned those same counts and the same per-label TP, FP and FN counts. It found 52/60 records with all four fields correct. The source evaluation does **not** contain an all-four total. The verifier derives 52 independently from the pinned [reconciled predictions](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/results/openjev-local-fixed-2026-09-23/development-reconciled.jsonl) and [provisional references](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/data/pilot/proposed_labels.jsonl), then compares that count with the generic evaluator. There is no saved source all-four number to assert equality against.

| Source file | File-byte SHA-256 |
| --- | --- |
| [Development inputs](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/data/pilot/inputs.jsonl) | `bd79e602f45f6aff78796ebdca4f2d0b1585c48665b6b8a9af1fe0b5e52d2b9e` |
| [Provisional references](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/data/pilot/proposed_labels.jsonl) | `440fa16759473b6d4ff52fe7e7296e5f2dfca0a58f5df26f20aef0daafed1464` |
| [Reconciled predictions](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/results/openjev-local-fixed-2026-09-23/development-reconciled.jsonl) | `60ff59a5933fd9a926f921eafe5209cedfa0f13b05d3422f8a6bfb8a2962b396` |
| [Saved evaluation](https://github.com/adambkovacs/candidate-experience-benchmark/blob/2cf643df4faf3b2dc5d6445601b79ccd323e90bb/results/openjev-local-fixed-2026-09-23/evaluation.json) | `2ee246baf0596be99274f8a85be4f37b97851138fdfd7f976e0b59f82bc4e186` |

From the `classification-bench` repository root, with the source checkout at the path shown below:

```sh
SOURCE=/Users/adamkovacs/Documents/codebuild/recruitment-feedback-demo
python3 -m scripts.verify_case_import \
  --inputs "$SOURCE/data/pilot/inputs.jsonl" \
  --inputs-sha256 bd79e602f45f6aff78796ebdca4f2d0b1585c48665b6b8a9af1fe0b5e52d2b9e \
  --references "$SOURCE/data/pilot/proposed_labels.jsonl" \
  --references-sha256 440fa16759473b6d4ff52fe7e7296e5f2dfca0a58f5df26f20aef0daafed1464 \
  --responses "$SOURCE/results/openjev-local-fixed-2026-09-23/development-reconciled.jsonl" \
  --responses-sha256 60ff59a5933fd9a926f921eafe5209cedfa0f13b05d3422f8a6bfb8a2962b396 \
  --evaluation "$SOURCE/results/openjev-local-fixed-2026-09-23/evaluation.json" \
  --evaluation-sha256 2ee246baf0596be99274f8a85be4f37b97851138fdfd7f976e0b59f82bc4e186
```

The command prints aggregate counts and hashes only. Add `--out /tmp/case-import-verification.json` to save a new report outside the repository; the file must not already exist. A hash mismatch or invalid source structure exits with code 2. A scoring mismatch exits with code 1.

This is an offline replay of saved predictions. The generic plan's prompt text is an import marker, not the native Jev request, and its content-derived request IDs are not historical execution IDs. The source method used native choice questions; the generic core only consumes its already selected categorical labels. The verifier does not reproduce native probability handling, runtime identity, pair checks, the serious-concern audit or model execution. References remain AI-reviewed provisional development labels. No repeatability or live-adapter claim follows from this check.
