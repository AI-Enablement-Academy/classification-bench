# Public synthetic report preview

The preview builder invents every task, input, reference label, prediction and
failed-request observation in its own code. It does not read `examples/`,
`private-data/`, provider receipts, environment credentials or account settings.
No provider adapter runs. Product and candidate examples exercise report
behavior; they provide no evidence about real model quality, cost or speed.

The main `AI-Enablement-Academy/classification-bench` repository stays private.
The read-only GitHub check on 8 October 2026 found organization plan `free`,
`has_pages: false`, and no configured Pages site. GitHub Free supports Pages
from public repositories; publishing from a private organization repository
requires an eligible paid plan. See [GitHub's Pages availability](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).
The credentials have repository administration permission, so the observed
limitation is plan entitlement rather than a missing repository role.

The intended publishing destination is a separate public repository containing
only the audited static output. A read-only lookup of
`AI-Enablement-Academy/classification-bench-preview` returned 404 on 8 October;
this means no repository was accessible by that name, not that the name is
reserved. Repository creation and deployment must use the user's explicit
publication authorization. The builder itself creates no repository, commits,
account changes or deployment.

## Published inspection site

The [fictional preview](https://ai-enablement-academy.github.io/classification-bench-preview/)
is hosted from a separate [static preview repository](https://github.com/AI-Enablement-Academy/classification-bench-preview).
It contains only the 19 audited output files below. The harness source
repository remains private. The private publication record retains exact commit,
manifest and served-file hashes; HTTP delivery is verified separately from
rendered acceptance.

To inspect it:

1. Open the preview index and choose **product complete**, then the corresponding
   candidate report. Check the findings, charts and readable case details.
2. Exercise filters, comparisons, case search, presentation navigation and
   browser Back/Forward. Confirm the displayed scope follows each selection.
3. Open the partial, unlabeled, invalid, all-missing and failed variants. Unknown
   results must stay unknown, and missing/invalid positions must remain counted.
4. Open a workflow report and switch smoke/full. The phases must retain their
   separate counts and scores. Test sensitivity without changing the baseline.
5. Check a narrow window, keyboard focus, reduced motion, print preview and an
   explicit fictional download. Use [the detailed checklist](REPORT_UX_CHECK.md)
   to record browser/version, viewport, report name and SHA-256 from the public
   manifest, with concrete passes or defects.

These checks cover the fictional public preview only. Private/live report
acceptance still requires observations bound to those exact files.

## Build and audit

From this private checkout, choose a new output directory. Existing destinations
are rejected rather than overwritten.

```sh
python3 -m scripts.build_public_preview --directory /private/tmp/classification-preview-publish-20261008-v1
python3 -m unittest tests.test_public_preview -v
python3 -m unittest discover -s tests -v
python3 -m scripts.build_public_preview --audit /private/tmp/classification-preview-publish-20261008-v1
```

The build is deterministic for the same source files and Python runtime. Its
Python guards deny socket connection and subprocess calls during generation;
they are test guards, not OS process isolation. The tests additionally reject
reads of existing examples and private data, provide an environment credential
canary, block adapter execution, and verify the guards with attempted calls.

The exact publish allowlist has 19 ordinary files in one directory:

- `.nojekyll`, `index.html`, `manifest.json`
- `product-complete.html`, `product-invalid.html`, `product-partial.html`,
  `product-unlabeled.html`, `product-all-missing.html`, `product-failed.html`,
  `product-sensitivity.html`, `product-workflow.html`
- `candidate-complete.html`, `candidate-invalid.html`, `candidate-partial.html`,
  `candidate-unlabeled.html`, `candidate-all-missing.html`, `candidate-failed.html`,
  `candidate-sensitivity.html`, `candidate-workflow.html`

The destination repository must contain these files only. Do not copy the
checkout, its `.git` history, the builder, tests, documentation, examples or any
saved evidence. Keep Git metadata outside the audited directory: ordinary
`git init` would add `.git` and correctly fail the exact-file audit. One
supported preparation uses a new external bare Git directory with the publish
directory as its explicit work tree:

```sh
git init --bare --initial-branch=main /private/tmp/classification-preview-git-20261008-v1
git --git-dir=/private/tmp/classification-preview-git-20261008-v1 --work-tree=/private/tmp/classification-preview-publish-20261008-v1 add -- .nojekyll index.html manifest.json product-complete.html product-invalid.html product-partial.html product-unlabeled.html product-all-missing.html product-failed.html product-sensitivity.html product-workflow.html candidate-complete.html candidate-invalid.html candidate-partial.html candidate-unlabeled.html candidate-all-missing.html candidate-failed.html candidate-sensitivity.html candidate-workflow.html
python3 -m scripts.build_public_preview --audit /private/tmp/classification-preview-publish-20261008-v1
```

Before committing or uploading, verify that the Git index contains exactly
these 19 paths and that every staged blob matches the audited file bytes,
including the manifest. Re-run the directory audit immediately before that
verification. A Pages branch-source deployment should serve only this root
directory; `.nojekyll` prevents a Jekyll transformation. The main repository's
visibility and history do not change. See [GitHub's publishing-source guide](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site).

## What the audit checks

The audit rejects unexpected files, directories, symbolic links, hard links,
changed report bytes, private path patterns, credential patterns, forbidden
metadata keys, non-allowlisted navigation, and resource loads. It parses every
JSON script, inspects both embedded workflow phase documents, decompresses
every embedded download, and verifies the declared compressed and uncompressed
SHA-256 hashes and byte lengths. Tests demonstrate rejection after an outer
manifest has been updated to match a leaking nested document or download.

Every report carries a public synthetic notice. Each ordinary data-state
report has 36 planned outputs: three invented cases across two configurations,
two prompts and three repeats. Complete has 36 valid outputs. Invalid, partial,
unlabeled and sensitivity have 35 valid and one invalid output. All-missing and
failed retain 36 missing outputs; failed has 24 invented failed request records.
Partial supplies references for one case. Unlabeled has no references and keeps
accuracy unavailable. Sensitivity presents an illustrative alternate reference
without changing the baseline.

Each workflow embeds a smoke phase with four planned outputs and a full phase
with 36. Each phase has one invalid output; their accuracy stays separate.
Missing costs, tokens and timing remain unavailable. Repeats and phase overlap
do not create independent cases.

Download choices are `sanitized` and `fictional`. Both contain newly invented
demo data. The fictional choice includes those invented inputs and labels; it
is not an export of private benchmark data. Preview projections omit
implementation source path maps while retaining their identity and provenance
digests. Their `preview_projection` field explicitly identifies this digest-only
projection, so it must not be mistaken for an unchanged canonical evidence
export. Download byte hashes are recomputed after this projection.

`manifest.json` records filenames, exact report hashes, fixture digests and
counts. It contains no local source paths, account settings or timestamps.
The manifest excludes its own hash to avoid a circular digest; the audit
command returns the exact manifest SHA-256 separately.

## Inspection boundary

Publication gives the user an inspection URL. A successful HTTP fetch and a
byte-for-byte match prove delivery of the audited static files, not rendered
appearance, keyboard focus, history behavior, print layout or native saving.
`rendered_acceptance` stays `pending` in the manifest.

The [recorded browser restriction](BROWSER_ACCEPTANCE_20261001.md) remains in
force. The agent must not navigate the hosted report or use another browser,
localhost, raw CDP or an indirect rendering route to bypass it. The user can
inspect these public fictional reports and record the file/hash, browser
version, viewport, reduced-motion setting and concrete results from
[the current checklist](REPORT_UX_CHECK.md). Acceptance of this transformed
fictional preview does not accept an existing private or live-evidence report.
