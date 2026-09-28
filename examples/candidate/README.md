# Fictional candidate feedback fixture

These three texts and labels were authored for software verification. They are not real candidate records or independently human-adjudicated benchmark references. The four field names and vocabularies follow the existing [offline import contract](../../docs/CASE_IMPORT_VERIFICATION.md).

The prompt states a small fixture-specific rubric. It is not a hiring policy and does not evaluate a person's suitability. Labels remain in a separate file and are opened only for offline scoring and the private report. The synthetic adapter deliberately returns first labels or invalid output; its score says nothing about model quality.

Run from the repository root:

```sh
python3 -m scripts.offline_demo --task candidate --directory /tmp/classification-candidate-demo
```

Choose a new output directory. `examples/product` supplies a second fictional task using the same runner without changing its code.
