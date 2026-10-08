# Working on classification-bench

Use deterministic code for counting, hashing, scoring and scheduling. Use GPT-6.1 Sol with xhigh reasoning for most substantial implementation, integration, debugging and review tasks. Use lower-cost models and lower effort for routine inventories and straightforward work. Escalate to a stronger model only for a concrete unresolved problem and explain why. Set model and effort explicitly for each subagent; report unavailable combinations. Delegate bounded independent work aggressively with explicit file ownership, acceptance criteria and independent review. Prefer deterministic scripts for routine verification. See docs/NEXT_TASK_GOAL.md for the complete active goal.

Keep references out of planning and future inference capsules. The offline evaluator can read them. Do not claim process isolation unless enforced and tested. Preserve missing/invalid outcomes in the full denominator. Keep repeat, retry, replay and prompt condition distinct.

Never launch paid inference, copy credentials, publish datasets or make this repository public without explicit authorization for that action. Default execution is offline; completed smoke approvals do not authorize new provider calls. Do not import the source project's dollar approvals as a standing budget for this project.

Preserve raw evidence and version reference corrections. A changed label triggers a new evaluation, not an overwrite of historical results. Use task-specific rubrics rather than inferring hiring or business policy from the model.

Run python3 -m unittest discover -s tests -v. Commit tested changes and stage exact files. Code review findings are BLOCKING if reachable in normal use and cause corruption, security exposure or feature failure; other confirmed findings are RESIDUAL.
