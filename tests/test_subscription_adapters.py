"""Subscription CLI contracts and failures; no inference or credential reads."""

import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import tempfile
import unittest
from unittest.mock import Mock, patch

from classification_bench.adapters import AdapterError, TransportResult
from classification_bench.isolation import IsolationUnavailable
from classification_bench.manifest import canonical_bytes
from classification_bench.subscription_adapters import (
    CLIResult, CODEX_DISABLED, CLAUDE_FLAGS, CODEX_FLAGS, SubscriptionAdapter,
    SubscriptionCLIWorker, clean_environment, command, _redact,
)


def config(kind="codex"):
    return {"id": "account", "model": "gpt-6.1-sol" if kind == "codex" else "claude-sonnet-5",
            "settings": {"adapter": kind, "executable": "/fictional/native-cli",
                         "cli_version": "fixture-cli 1.2.3", "effort": "medium",
                         "extra_usage_disabled": True,
                         "extra_usage_verified_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                         "extra_usage_source": "operator checked account settings; test fixture"}}


def material(adapter):
    return adapter.prepare({"task": {"fields": [
        {"name": "routing", "labels": ["accept", "defer", "abstain"]},
        {"name": "severity", "labels": ["urgent", "routine"]}]}},
        {"request_id": "request-123", "config_id": "account", "prompt_id": "custom",
         "items": [{"id": "input-A", "input": {"narrative": "a quoted customer message"}},
                   {"id": "input-B", "input": {"narrative": "another message"}}]},
        {"id": "custom", "text": "Follow this task-specific rubric."})


def output():
    return {"request_id": "request-123", "predictions": [
        {"id": "input-A", "prediction": {"routing": "defer", "severity": "urgent"}},
        {"id": "input-B", "prediction": {"routing": "accept", "severity": "routine"}}]}


def receipt(adapter, events=None, *, returncode=0, final_text=None, error=None, truncated=False):
    if events is None:
        if adapter.kind == "codex":
            events = [{"type": "thread.started", "thread_id": "fresh-session-1"},
                      {"type": "turn.started"}, {"type": "turn.completed", "usage": {
                          "input_tokens": 30, "cached_input_tokens": 4, "output_tokens": 20}}]
            final_text = json.dumps(output()) if final_text is None else final_text
        else:
            events = [{"type": "system", "subtype": "init", "model": adapter.model,
                       "tools": ["StructuredOutput"], "mcp_servers": [], "skills": [], "plugins": [],
                       "apiKeySource": "none"},
                      {"type": "result", "subtype": "success", "is_error": False,
                       "structured_output": output(), "modelUsage": {adapter.model: {}},
                       "total_cost_usd": 0.034, "duration_ms": 95, "duration_api_ms": 70,
                       "usage": {"input_tokens": 50, "output_tokens": 25}, "num_turns": 1,
                       "session_id": "fresh-session-2"}]
    body = {"schema_version": 1, "adapter": adapter.kind, "requested_model": adapter.model,
            "requested_effort": adapter.effort, "cli_version": adapter.cli_version,
            "preflight": {"authentication": "ChatGPT" if adapter.kind == "codex" else "claude.ai",
                          "isolation": {"reference_read_denied": True},
                          "extra_usage_guard": {"verification": "operator_assertion", "disabled": True}},
            "stdout": "\n".join(json.dumps(e) for e in events), "stderr": "",
            "returncode": returncode, "final_text": final_text}
    return TransportResult(canonical_bytes(body), None, 125, error=error, truncated=truncated)


def parse(adapter, result):
    return adapter.parse(result, expected_request_id="request-123", expected_ids=("input-A", "input-B"),
                         expected_model=adapter.model)


class SubscriptionContractTests(unittest.TestCase):
    def test_generic_rendering_contains_no_reference_or_repository_context(self):
        for kind in ("claude_code", "codex"):
            with self.subTest(kind=kind):
                adapter = SubscriptionAdapter(config(kind))
                prepared = material(adapter)
                body = json.loads(prepared.body)
                self.assertEqual(prepared.reserve_microusd, 1)
                self.assertEqual(adapter.accounting_currency, "REQ")
                self.assertEqual(prepared.expected_ids, ("input-A", "input-B"))
                self.assertIn("narrative", body["messages"][1]["content"])
                self.assertIn("routing", body["output_schema"]["properties"]["predictions"]["items"]["properties"]["prediction"]["properties"])
                self.assertNotIn("reference", body)
                self.assertEqual([m["role"] for m in body["messages"]], ["system", "user"])
                self.assertIn("unknown-subscription-cost", prepared.bound_source)

    def test_reference_metadata_cannot_enter_inference_request(self):
        adapter = SubscriptionAdapter(config())
        request = {"request_id": "r", "config_id": "account", "prompt_id": "p",
                   "items": [{"id": "i", "input": {"text": "input"}, "reference": {"kind": "a"}}]}
        with self.assertRaisesRegex(AdapterError, "only declared inputs"):
            adapter.prepare({"task": {"fields": [{"name": "kind", "labels": ["a", "b"]}]}},
                            request, {"id": "p", "text": "classify"})

    def test_settings_reject_implicit_or_paid_api_controls(self):
        mutations = [{"effort": None}, {"extra_usage_disabled": False},
                     {"executable": "codex"}, {"api_key": "never-used"},
                     {"timeout_seconds": float("inf")}, {"max_output_bytes": True}]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = config()
                value["settings"].update(mutation)
                with self.assertRaises(AdapterError):
                    SubscriptionAdapter(value)

    def test_haiku_no_effort_and_alias_refusal(self):
        value = config("claude_code")
        value["model"] = "claude-haiku-4-5"
        with self.assertRaisesRegex(AdapterError, "not_applicable"):
            SubscriptionAdapter(value)
        value["settings"]["effort"] = "not_applicable"
        adapter = SubscriptionAdapter(value)
        self.assertNotIn("--effort", command(adapter, json.loads(material(adapter).body), Path("/tmp/fresh")))
        value["model"] = "sonnet"
        with self.assertRaisesRegex(AdapterError, "explicit model"):
            SubscriptionAdapter(value)

    def test_clean_environment_retains_account_location_without_api_credentials(self):
        source = {"HOME": "/Users/operator", "USER": "operator", "PATH": "/evil/wrappers",
                  "ANTHROPIC_API_KEY": "not-a-real-key", "OPENAI_API_KEY": "not-a-real-key",
                  "CODEX_HOME": "/private/custom-memory", "CLAUDE_CONFIG_DIR": "/private/custom",
                  "HTTP_PROXY": "http://proxy", "NODE_OPTIONS": "--require hook",
                  "SSL_CERT_FILE": "/private/reference", "LANG": "en_US.UTF-8"}
        for kind in ("codex", "claude_code"):
            env = clean_environment(kind, source)
            self.assertEqual(env["HOME"], source["HOME"])
            self.assertEqual(env["PATH"], "/usr/bin:/bin:/usr/sbin:/sbin")
            self.assertFalse(set(env) & {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_HOME",
                                        "CLAUDE_CONFIG_DIR", "HTTP_PROXY", "NODE_OPTIONS", "SSL_CERT_FILE"})

    def test_commands_enforce_explicit_identity_and_fresh_context(self):
        for kind in ("codex", "claude_code"):
            adapter = SubscriptionAdapter(config(kind))
            cmd = command(adapter, json.loads(material(adapter).body), Path("/private/tmp/fresh"))
            self.assertEqual(cmd[cmd.index("--model") + 1], adapter.model)
            self.assertNotIn("--resume", cmd)
            self.assertNotIn("--continue", cmd)
            self.assertNotIn("--fallback-model", cmd)
            if kind == "claude_code":
                self.assertEqual(cmd[cmd.index("--tools") + 1], "")
                self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
                self.assertIn("--no-session-persistence", cmd)
            else:
                self.assertIn("--ignore-user-config", cmd)
                self.assertIn("--ignore-rules", cmd)
                self.assertIn("--ephemeral", cmd)
                self.assertIn('model_reasoning_effort="medium"', cmd)
                for feature in CODEX_DISABLED:
                    self.assertIn("features." + feature + "=false", cmd)

    def test_preflight_assertion_freshness_blocks_before_worker(self):
        for offset in (-25, 1):
            value = config()
            value["settings"]["extra_usage_verified_at"] = (datetime.now(timezone.utc) +
                timedelta(hours=offset)).isoformat().replace("+00:00", "Z")
            worker = Mock()
            with self.assertRaisesRegex(AdapterError, "last 24 hours"):
                SubscriptionAdapter(value).preflight(worker)
            worker.preflight.assert_not_called()

    def test_dispatch_requires_preflight_and_bound_controls(self):
        adapter = SubscriptionAdapter(config())
        worker = Mock()
        prepared = material(adapter)
        with self.assertRaisesRegex(AdapterError, "preflight"):
            adapter.dispatch(prepared, worker)
        worker.dispatch.assert_not_called()
        worker.preflight.return_value = {"cli_version": adapter.cli_version}
        adapter.preflight(worker)
        worker.dispatch.return_value = receipt(adapter)
        self.assertIs(adapter.dispatch(prepared, worker), worker.dispatch.return_value)
        worker.dispatch.assert_called_once_with(adapter, prepared)

    def test_codex_identity_and_subscription_cost_stay_unknown(self):
        adapter = SubscriptionAdapter(config())
        parsed = parse(adapter, receipt(adapter))
        self.assertEqual(parsed.status, "valid")
        self.assertIsNone(parsed.returned_model)
        self.assertIsNone(parsed.observed_cost_microusd)
        self.assertEqual(parsed.usage["prompt_tokens"], 30)
        self.assertEqual(parsed.usage["completion_tokens"], 20)
        self.assertEqual(parsed.usage["subscription"]["identity_status"], "unavailable")
        self.assertEqual(parsed.usage["subscription"]["cost_status"], "unknown_subscription_cost")

    def test_claude_api_equivalent_is_not_an_invoice(self):
        adapter = SubscriptionAdapter(config("claude_code"))
        parsed = parse(adapter, receipt(adapter))
        self.assertEqual(parsed.status, "valid")
        self.assertEqual(parsed.returned_model, adapter.model)
        self.assertIsNone(parsed.observed_cost_microusd)
        evidence = parsed.usage["subscription"]
        self.assertEqual(evidence["cli_api_equivalent_cost_usd"], 0.034)
        self.assertIsNone(evidence["actual_billed_usd"])
        self.assertIsNone(evidence["subscription_quota_consumed"])
        self.assertEqual(evidence["identity_status"], "cli_observed")

    def test_claude_model_substitution_invalidates_response(self):
        adapter = SubscriptionAdapter(config("claude_code"))
        raw = json.loads(receipt(adapter).raw_bytes)
        events = [json.loads(line) for line in raw["stdout"].splitlines()]
        events[1]["modelUsage"] = {"claude-other-model": {}}
        parsed = parse(adapter, receipt(adapter, events))
        self.assertEqual(parsed.status, "invalid")
        self.assertEqual(parsed.predictions, ())
        self.assertIn("model mismatch", parsed.reason)

    def test_cli_tool_use_fails_closed(self):
        for kind in ("codex", "claude_code"):
            adapter = SubscriptionAdapter(config(kind))
            raw = json.loads(receipt(adapter).raw_bytes)
            events = [json.loads(line) for line in raw["stdout"].splitlines()]
            events.insert(1, ({"type": "item.completed", "item": {"type": "command_execution", "command": "cat labels"}}
                if kind == "codex" else {"type": "assistant", "message": {"content": [
                    {"type": "tool_use", "name": "Read", "input": {"path": "labels"}}]}}))
            parsed = parse(adapter, receipt(adapter, events, final_text=json.dumps(output())))
            self.assertEqual(parsed.status, "invalid")
            self.assertEqual(parsed.predictions, ())
            self.assertIn("isolation violation", parsed.reason)

    def test_claude_context_and_overage_guards(self):
        adapter = SubscriptionAdapter(config("claude_code"))
        for field in ("mcp_servers", "skills", "plugins", "tools"):
            raw = json.loads(receipt(adapter).raw_bytes)
            events = [json.loads(line) for line in raw["stdout"].splitlines()]
            events[0][field] = ["unexpected"]
            parsed = parse(adapter, receipt(adapter, events))
            self.assertIn("isolation violation", parsed.reason)
        raw = json.loads(receipt(adapter).raw_bytes)
        events = [json.loads(line) for line in raw["stdout"].splitlines()]
        events.append({"type": "rate_limit_event", "rate_limit_info": {"isUsingOverage": True}})
        parsed = parse(adapter, receipt(adapter, events))
        self.assertIn("paid extra usage", parsed.reason)
        self.assertTrue(parsed.usage["subscription"]["overage_observed"])

    def test_claude_accepts_only_exact_official_builtin_plugin_identities(self):
        adapter = SubscriptionAdapter(config("claude_code"))
        raw = json.loads(receipt(adapter).raw_bytes)
        events = [json.loads(line) for line in raw["stdout"].splitlines()]
        plugins = [{"name": name, "path": "builtin", "source": name + "@builtin"}
                   for name in ("agents-md", "telemetry")]
        events[0]["plugins"] = plugins
        parsed = parse(adapter, receipt(adapter, events))
        self.assertEqual(parsed.status, "valid")
        self.assertEqual(parsed.usage["subscription"]["observed_plugins"], plugins)
        plugins[0]["path"] = "/Users/operator/plugins/agents-md"
        self.assertIn("isolation violation", parse(adapter, receipt(adapter, events)).reason)

    def test_cache_token_semantics_are_preserved_by_cli_surface(self):
        adapter = SubscriptionAdapter(config("claude_code"))
        raw = json.loads(receipt(adapter).raw_bytes)
        events = [json.loads(line) for line in raw["stdout"].splitlines()]
        events[1]["usage"].update(cache_creation_input_tokens=100, cache_read_input_tokens=25)
        usage = parse(adapter, receipt(adapter, events)).usage
        self.assertEqual(usage["prompt_tokens"], 175)
        self.assertEqual(usage["input_tokens"], 50)
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 25)
        codex = SubscriptionAdapter(config())
        usage = parse(codex, receipt(codex)).usage
        self.assertEqual(usage["prompt_tokens"], 30)
        self.assertEqual(usage["prompt_tokens_details"]["cached_tokens"], 4)

    def test_recognizable_credentials_are_redacted_without_reading_login_files(self):
        raw = b'{"access_token":"jwt-fixture","refresh_token":"refresh-fixture","note":"Bearer token-fixture sk-ant-fakekey"}'
        cleaned, redacted = _redact(raw)
        self.assertTrue(redacted)
        self.assertNotIn(b"jwt-fixture", cleaned)
        self.assertNotIn(b"refresh-fixture", cleaned)
        self.assertNotIn(b"token-fixture", cleaned)
        self.assertNotIn(b"sk-ant-fakekey", cleaned)
        self.assertIsInstance(json.loads(cleaned), dict)

    def test_failed_and_interrupted_attempts_preserve_usage_but_no_predictions(self):
        adapter = SubscriptionAdapter(config())
        for options in ({"returncode": 1}, {"error": "TimeoutExpired"}, {"truncated": True}):
            parsed = parse(adapter, receipt(adapter, **options))
            self.assertEqual(parsed.status, "unknown")
            self.assertEqual(parsed.predictions, ())
            self.assertIsNone(parsed.observed_cost_microusd)
            self.assertEqual(parsed.usage["input_tokens"], 30)

    def test_empty_and_partial_cli_events_keep_interruption_uncertain(self):
        for kind in ("claude_code", "codex"):
            adapter = SubscriptionAdapter(config(kind))
            for stdout in ("", '{"type":"turn.', '{"type":"turn.started"}\n{"type":"item.'):
                for error, truncated in (("TimeoutExpired", False), ("OutputLimitExceeded", True), (None, False)):
                    with self.subTest(kind=kind, stdout=stdout, error=error):
                        raw = json.loads(receipt(adapter).raw_bytes)
                        raw.update(stdout=stdout, returncode=-9, final_text=None)
                        parsed = parse(adapter, TransportResult(canonical_bytes(raw), None, 50,
                                       error=error, truncated=truncated))
                        self.assertEqual(parsed.status, "unknown")
                        self.assertEqual(parsed.predictions, ())
                        self.assertIsNone(parsed.observed_cost_microusd)
                        self.assertEqual(parsed.usage["subscription"]["cost_status"], "unknown_subscription_cost")

    def test_quota_exhaustion_and_event_parse_errors(self):
        adapter = SubscriptionAdapter(config())
        events = [{"type": "error", "message": "Usage limit reached"}, {"type": "turn.failed"}]
        parsed = parse(adapter, receipt(adapter, events))
        self.assertEqual(parsed.status, "invalid")
        self.assertTrue(parsed.usage["subscription"]["quota_exhausted"])
        raw = json.loads(receipt(adapter).raw_bytes)
        raw["stdout"] += "\nmalformed event"
        parsed = parse(adapter, TransportResult(canonical_bytes(raw), None, 12))
        self.assertEqual(parsed.status, "invalid")
        self.assertIn("event JSON", parsed.reason)

    def test_ids_order_duplicates_and_request_binding_are_enforced(self):
        adapter = SubscriptionAdapter(config())
        values = []
        wrong_request = output()
        wrong_request["request_id"] = "another-request"
        values.append(wrong_request)
        reversed_ids = output()
        reversed_ids["predictions"].reverse()
        values.append(reversed_ids)
        duplicate = output()
        duplicate["predictions"][1]["id"] = "input-A"
        values.append(duplicate)
        extra = output()
        extra["explanation"] = "unexpected"
        values.append(extra)
        for value in values:
            self.assertEqual(parse(adapter, receipt(adapter, final_text=json.dumps(value))).status, "invalid")

    def test_saved_receipt_cannot_change_model_effort_or_cli_version(self):
        adapter = SubscriptionAdapter(config())
        for key in ("requested_model", "requested_effort", "cli_version", "adapter"):
            raw = json.loads(receipt(adapter).raw_bytes)
            raw[key] = "changed"
            parsed = parse(adapter, TransportResult(canonical_bytes(raw), None, 12))
            self.assertEqual(parsed.status, "invalid")
            self.assertIn("receipt identity mismatch", parsed.reason)


class SubscriptionWorkerTests(unittest.TestCase):
    def _preflight(self, kind, *, auth=None, version=None, help_text=None):
        adapter = SubscriptionAdapter(config(kind))
        worker = SubscriptionCLIWorker()
        worker.probe = Mock(return_value={"reference_read_denied": True})
        correct_auth = (b'{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"firstParty","email":"private@example.com"}'
                        if kind == "claude_code" else b"Logged in using ChatGPT")
        calls = [CLIResult(version or adapter.cli_version.encode(), b"", 0),
                 CLIResult((help_text if help_text is not None else " ".join(
                     (*CLAUDE_FLAGS, "--effort") if kind == "claude_code" else CODEX_FLAGS)).encode(), b"", 0),
                 CLIResult(auth if auth is not None else correct_auth, b"", 0)]
        worker._launch = Mock(side_effect=calls)
        with patch("pathlib.Path.read_bytes", return_value=b"native-cli-fixture"):
            result = worker.preflight(adapter)
        return result, worker

    def test_preflight_records_only_auth_mode_and_hashes(self):
        for kind in ("codex", "claude_code"):
            result, worker = self._preflight(kind)
            self.assertEqual(result["accounting_currency"], "REQ")
            self.assertIsNone(result["monetary_bound"])
            self.assertEqual(result["extra_usage_guard"]["verification"], "operator_assertion")
            self.assertNotIn("private@example.com", json.dumps(result))
            commands = [call.args[0] for call in worker._launch.call_args_list]
            self.assertEqual(len(commands), 3)
            self.assertFalse(any("--print" in call or ("exec" in call and "--help" not in call) for call in commands))

    def test_auth_rejects_api_key_and_third_party_modes(self):
        for auth in (b'{"loggedIn":true,"authMethod":"api_key","apiProvider":"firstParty"}',
                     b'{"loggedIn":true,"authMethod":"claude.ai","apiProvider":"thirdParty"}'):
            with self.assertRaisesRegex(AdapterError, "paid API auth refused"):
                self._preflight("claude_code", auth=auth)
        with self.assertRaisesRegex(AdapterError, "paid API auth refused"):
            self._preflight("codex", auth=b"Logged in using an API key")

    def test_cli_version_or_controls_drift_fails_preflight(self):
        with self.assertRaisesRegex(AdapterError, "version changed"):
            self._preflight("codex", version=b"different-cli")
        with self.assertRaisesRegex(AdapterError, "required controls"):
            self._preflight("claude_code", help_text="--print --model")

    def test_unsupported_host_fails_before_any_cli_process(self):
        adapter = SubscriptionAdapter(config())
        with patch("platform.system", return_value="Linux"), patch("subprocess.Popen") as launch:
            with self.assertRaises(IsolationUnavailable):
                SubscriptionCLIWorker().probe(adapter)
            launch.assert_not_called()

    def test_worker_dispatch_saves_raw_events_and_final_text_before_parsing(self):
        adapter = SubscriptionAdapter(config())
        adapter._preflight = {"cli_sha256": "hash", "authentication": "ChatGPT"}
        worker = SubscriptionCLIWorker()
        def launch(args, current, cwd, **kwargs):
            (cwd / "response.json").write_text(json.dumps(output()))
            self.assertEqual(json.loads((cwd / "schema.json").read_text())["required"], ["request_id", "predictions"])
            self.assertIn(b"task-specific rubric", kwargs["input_bytes"])
            return CLIResult(b'{"type":"turn.completed","usage":{"input_tokens":5}}', b"cli diagnostic", 0)
        worker._launch = Mock(side_effect=launch)
        with patch("classification_bench.subscription_adapters.digest", return_value="hash"):
            with patch("pathlib.Path.read_bytes", autospec=True, side_effect=lambda path: (
                b"native-cli-fixture" if str(path) == adapter.executable else Path.read_text(path).encode())):
                result = worker.dispatch(adapter, material(adapter))
        saved = json.loads(result.raw_bytes)
        self.assertEqual(saved["stderr"], "cli diagnostic")
        self.assertIn("turn.completed", saved["stdout"])
        self.assertEqual(json.loads(saved["final_text"]), output())
        self.assertIsNone(result.http_status)
        worker._launch.assert_called_once()

    def test_inference_profile_excludes_user_config_and_allows_only_exact_auth_files(self):
        adapter = SubscriptionAdapter(config())
        worker = SubscriptionCLIWorker()
        with tempfile.TemporaryDirectory() as temp, patch.object(worker, "_require_host"), \
                patch("pathlib.Path.resolve", autospec=True, side_effect=lambda path, **kw: path):
            profile = worker._profile(adapter, Path(temp))
            auth_profile = worker._profile(adapter, Path(temp), auth_probe=True)
        home = os.environ["HOME"]
        self.assertNotIn(home + "/.codex/config.toml", profile)
        self.assertIn(home + "/.codex/config.toml", auth_profile)
        self.assertIn('(literal "' + home + '/.codex/auth.json")', profile)
        self.assertNotIn('(subpath "' + home + '/.codex")', profile)

    def test_binary_change_after_preflight_prevents_launch(self):
        adapter = SubscriptionAdapter(config())
        adapter._preflight = {"cli_sha256": "old-hash"}
        worker = SubscriptionCLIWorker()
        worker._launch = Mock()
        with patch("pathlib.Path.read_bytes", return_value=b"changed-cli"):
            with self.assertRaisesRegex(AdapterError, "binary changed"):
                worker.dispatch(adapter, material(adapter))
        worker._launch.assert_not_called()

    @unittest.skipUnless(platform.system() == "Darwin", "macOS OS-profile probe")
    def test_real_os_profile_denies_reference_and_symlink_without_inference(self):
        with tempfile.TemporaryDirectory(prefix="subscription-native-fixture-", dir="/private/tmp") as temp:
            executable = Path(temp) / "native-header-fixture"
            executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"fixture-is-not-executed")
            executable.chmod(0o700)
            value = config()
            value["settings"]["executable"] = str(executable)
            proof = SubscriptionCLIWorker().probe(SubscriptionAdapter(value))
            self.assertTrue(proof["reference_read_denied"])
            self.assertTrue(proof["symlink_read_denied"])
            self.assertTrue(proof["environment_scrubbed"])


if __name__ == "__main__":
    unittest.main()
