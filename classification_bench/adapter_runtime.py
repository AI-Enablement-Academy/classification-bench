"""Trusted adapter runtime registry and provider-specific execution boundaries.

Only code registered by the application can dispatch. Matrix scheduling depends
on this contract, rather than on an individual provider's HTTP details.
"""

from dataclasses import dataclass, replace
import os
from pathlib import Path

from .adapters import AdapterError, OpenRouterAdapter
from .evidence import put_artifact, read_artifact
from .manifest import digest


def _module_digest(value):
    module = __import__(type(value).__module__, fromlist=["x"])
    return digest(Path(module.__file__).read_bytes())


@dataclass(frozen=True)
class Supplement:
    parsed: object
    identity_status: str
    generation: dict | None = None
    generation_response_sha256: str | None = None


class RuntimeRegistry:
    def __init__(self):
        self._runtimes = {}

    def register(self, name, runtime):
        if not isinstance(name, str) or not name or name in self._runtimes:
            raise ValueError("runtime name must be unique and nonempty")
        for method in ("create_adapter", "credential", "source_digests", "preflight", "dispatch", "parse",
                       "supplement", "recovery_identity_status", "zero_charge_evidence"):
            if not callable(getattr(runtime, method, None)):
                raise ValueError(f"runtime lacks {method}")
        if type(getattr(runtime, "offline", None)) is not bool:
            raise ValueError("runtime must declare offline status")
        self._runtimes[name] = runtime

    def get(self, name):
        return self._runtimes.get(name)

    def unregister(self, name):
        del self._runtimes[name]


registry = RuntimeRegistry()


class OfflineRuntime:
    """Adapter supplied by trusted application code; no network credentials."""

    offline = True

    def __init__(self, adapter_factory, *, identity_status="synthetic",
                 zero_charge_source="synthetic:zero-fee"):
        self.adapter_factory = adapter_factory
        self.identity_status = identity_status
        self.zero_charge_source = zero_charge_source

    def create_adapter(self, config):
        return self.adapter_factory(config)

    def credential(self, supplied):
        return None

    def source_digests(self, adapter):
        return {"adapter_source_sha256": _module_digest(adapter),
                "runtime_source_sha256": _module_digest(self),
                "transport_source_sha256": None}

    def preflight(self, adapter, prepared, worker):
        return prepared.bound_source

    def dispatch(self, adapter, prepared, api_key, worker):
        return adapter.dispatch(prepared)

    def parse(self, adapter, result, *, expected_request_id, expected_ids, expected_model):
        return adapter.parse(result, expected_request_id=expected_request_id,
                             expected_ids=expected_ids, expected_model=expected_model)

    def supplement(self, adapter, parsed, api_key, worker, artifact_root, config):
        return Supplement(parsed, self.identity_status)

    def recovery_identity_status(self):
        return self.identity_status

    def zero_charge_evidence(self, observation):
        return self.zero_charge_source


class OpenRouterRuntime:
    offline = False

    def create_adapter(self, config):
        return OpenRouterAdapter(config)

    def credential(self, supplied):
        value = supplied or os.environ.get("OPENROUTER_API_KEY")
        if not value:
            raise ValueError("OPENROUTER_API_KEY is required before live admission")
        return value

    def source_digests(self, adapter):
        from . import network_isolation
        return {"adapter_source_sha256": _module_digest(adapter),
                "runtime_source_sha256": _module_digest(self),
                "transport_source_sha256": digest(Path(network_isolation.__file__).read_bytes())}

    def preflight(self, adapter, prepared, worker):
        from .network_isolation import NetworkSandboxedPythonWorker
        (worker or NetworkSandboxedPythonWorker()).probe()
        catalog = adapter.verify_live_snapshot()
        source = f"{prepared.bound_source}:catalog:{catalog['catalog_sha256']}"
        if "identity_response_sha256" in catalog:
            source += f":identity:{catalog['identity_response_sha256']}"
        return source

    def dispatch(self, adapter, prepared, api_key, worker):
        from .network_isolation import isolated_dispatch
        return isolated_dispatch(adapter, prepared, api_key, worker=worker)

    def parse(self, adapter, result, *, expected_request_id, expected_ids, expected_model):
        return adapter.parse(result, expected_request_id=expected_request_id,
                             expected_ids=expected_ids, expected_model=expected_model)

    def recovery_identity_status(self):
        return "unverified:recovery"

    def supplement(self, adapter, parsed, api_key, worker, artifact_root, config):
        if not parsed.response_id:
            return Supplement(parsed, "unverified")
        generation = None
        generation_ref = None
        identity_status = "unverified"
        try:
            from .network_isolation import isolated_lookup_generation
            result = isolated_lookup_generation(adapter, parsed.response_id, api_key,
                                                worker=worker)
            if result.raw_bytes:
                generation_ref = put_artifact(artifact_root, result.raw_bytes, "application/json")
                read_artifact(artifact_root, generation_ref)
            generation = adapter.parse_generation(result,
                                                  expected_response_id=parsed.response_id,
                                                  expected_model=config["model"])
            identity_status = "observed"
            if (parsed.observed_cost_microusd is not None and
                    generation["observed_cost_microusd"] is not None and
                    parsed.observed_cost_microusd != generation["observed_cost_microusd"]):
                parsed = replace(parsed, status="invalid", predictions=(),
                                 observed_cost_microusd=None,
                                 reason="conflicting provider charge evidence")
            elif parsed.observed_cost_microusd is None:
                parsed = replace(parsed,
                                 observed_cost_microusd=generation["observed_cost_microusd"])
        except Exception as exc:
            if isinstance(exc, AdapterError) and "identity mismatch" in str(exc):
                parsed = replace(parsed, status="invalid", predictions=(),
                                 reason="provider generation identity mismatch")
                identity_status = "identity_error"
            else:
                identity_status = f"unverified:{type(exc).__name__}"
        return Supplement(parsed, identity_status, generation,
                          generation_ref.sha256 if generation_ref else None)

    def zero_charge_evidence(self, observation):
        generation_sha = observation.get("generation_response_sha256")
        if generation_sha and (observation.get("generation") or {}).get(
                "observed_cost_microusd") == 0:
            return f"openrouter:generation:{generation_sha}"
        usage = observation["parsed"].get("usage") or {}
        if usage.get("cost") is not None:
            return f"openrouter:usage:{observation['response_sha256']}"
        return None


registry.register("openrouter", OpenRouterRuntime())


class DecisionRuntime:
    """Native typed-choice call with provider-specific credential and billing gate."""

    offline = False

    def __init__(self, kind):
        from .decision_adapters import CONTRACTS
        self.kind = kind
        self.contract = CONTRACTS[kind]

    def create_adapter(self, config):
        from .decision_adapters import DecisionAdapter
        if config.get("settings", {}).get("adapter") != self.kind:
            raise AdapterError("native adapter kind mismatch")
        return DecisionAdapter(config)

    def credential(self, supplied):
        if supplied is not None:
            raise ValueError("native decision credentials must come from their provider-specific environment variable")
        name = self.contract["credential"]
        value = os.environ.get(name)
        if not value:
            raise ValueError(f"{name} is required before live admission")
        return value

    def source_digests(self, adapter):
        from . import adapters, decision_adapters, decision_network, isolation, network_isolation
        def composite(*modules):
            return digest(b"".join(len(raw).to_bytes(8, "big") + raw for raw in
                           (Path(module.__file__).read_bytes() for module in modules)))
        return {"adapter_source_sha256": composite(adapters, decision_adapters),
                "runtime_source_sha256": _module_digest(self),
                "transport_source_sha256": composite(isolation, network_isolation,
                                                     decision_network)}

    def preflight(self, adapter, prepared, worker):
        from .decision_network import DecisionNetworkWorker
        (worker or DecisionNetworkWorker()).probe_endpoint(adapter.endpoint)
        attestation = adapter.verify_live_snapshot()
        return f"{prepared.bound_source}:source:{attestation['billing_response_sha256']}"

    def dispatch(self, adapter, prepared, api_key, worker):
        from .decision_network import isolated_decision_dispatch
        return isolated_decision_dispatch(adapter, prepared, api_key, worker=worker)

    def parse(self, adapter, result, *, expected_request_id, expected_ids, expected_model):
        return adapter.parse(result, expected_request_id=expected_request_id,
                             expected_ids=expected_ids, expected_model=expected_model)

    def supplement(self, adapter, parsed, api_key, worker, artifact_root, config):
        return Supplement(parsed, "model-echoed;provider-unverified")

    def recovery_identity_status(self):
        return "unverified:recovery"

    def zero_charge_evidence(self, observation):
        return None


for _decision_kind in ("liquid_decide", "solar_decide", "qwen_decision"):
    registry.register(_decision_kind, DecisionRuntime(_decision_kind))
