"""Atomic offline budget admission and dispatch-intent evidence on one SQLite file."""

import math
import time
import uuid
from pathlib import Path

from .budget import BudgetLedger
from .coordinator import Coordinator, _digest, _text


class ExecutionError(ValueError):
    pass


class ExecutionLedger:
    """Bind a claim, frozen request bytes and reservation before dispatch intent."""

    def __init__(self, path, *, budget_path=None):
        if budget_path is not None and Path(path).resolve(strict=False) != Path(budget_path).resolve(strict=False):
            raise ExecutionError("coordinator and budget must use the same SQLite database path")
        self.coordinator = Coordinator(path)
        self.budget = BudgetLedger(path)
        with self.coordinator._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS execution_requests (
                request_id TEXT PRIMARY KEY REFERENCES requests(request_id),
                attempt_id TEXT NOT NULL UNIQUE,
                scope TEXT NOT NULL REFERENCES scopes(scope),
                manifest_digest TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('enrolled','admitted','completed','reconciled')),
                admission_token TEXT,
                reserve_amount INTEGER,
                bound_source TEXT,
                no_fee_evidence TEXT,
                outcome TEXT,
                evidence_id TEXT,
                response_digest TEXT,
                billing_reason TEXT,
                settlement_id TEXT,
                charge INTEGER,
                zero_charge_evidence TEXT,
                reconciliation_id TEXT,
                reconciliation_outcome TEXT,
                reconciliation_response_digest TEXT
            )""")

    @staticmethod
    def _entry(conn, request_id):
        row = conn.execute("SELECT * FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise ExecutionError(f"request is not enrolled for atomic execution: {request_id}")
        return row

    def enqueue(self, request_id, manifest_digest, input_digest, scope):
        """Enroll an immutable request and explicit budget scope in one transaction."""
        _text(request_id, "request_id")
        _text(scope, "scope")
        _digest(manifest_digest, "manifest_digest")
        _digest(input_digest, "input_digest")
        with self.coordinator._transaction() as conn:
            self.budget._scope(conn, scope)
            row = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
            entry = conn.execute("SELECT * FROM execution_requests WHERE request_id=?", (request_id,)).fetchone()
            if row is not None:
                if (row["manifest_digest"], row["request_artifact_digest"]) != (manifest_digest, input_digest):
                    raise ExecutionError("request identity conflicts with frozen evidence")
                if entry is None:
                    raise ExecutionError("existing legacy request cannot be enrolled")
                if (entry["scope"], entry["manifest_digest"], entry["input_digest"]) != (
                        scope, manifest_digest, input_digest):
                    raise ExecutionError("execution enrollment conflicts with frozen evidence")
                return dict(row)
            attempt_id = str(uuid.uuid4())
            conn.execute("""INSERT INTO requests
                (request_id,manifest_digest,request_artifact_digest,attempt_id,state)
                VALUES (?,?,?,?, 'ready')""", (request_id, manifest_digest, input_digest, attempt_id))
            conn.execute("""INSERT INTO execution_requests
                (request_id,attempt_id,scope,manifest_digest,input_digest,state)
                VALUES (?,?,?,?,?,'enrolled')""",
                (request_id, attempt_id, scope, manifest_digest, input_digest))
            row = self.coordinator._row(conn, request_id)
            self.coordinator._event(conn, row, "enqueued", details="atomic execution enrollment")
            return dict(row)

    def claim(self, worker_id, lease_seconds):
        """Claim only enrolled requests; expired, unstarted claims retain attempt identity."""
        _text(worker_id, "worker_id")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or not math.isfinite(lease_seconds) or lease_seconds <= 0 or lease_seconds > 86400:
            raise ExecutionError("lease_seconds must be positive and at most 86400")
        with self.coordinator._transaction() as conn:
            now = time.time()
            row = conn.execute("""SELECT r.* FROM requests r JOIN execution_requests x
                ON x.request_id=r.request_id WHERE x.state='enrolled' AND
                (r.state='ready' OR (r.state='claimed' AND r.lease_until<=?))
                ORDER BY r.seq LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            token = str(uuid.uuid4())
            conn.execute("""UPDATE requests SET state='claimed',generation=?,token=?,
                worker_id=?,lease_until=? WHERE request_id=?""",
                (row["generation"] + 1, token, worker_id, now + lease_seconds, row["request_id"]))
            claimed = self.coordinator._row(conn, row["request_id"])
            self.coordinator._event(conn, claimed, "claimed", worker_id=worker_id, token=token,
                                    details="reclaimed expired claim" if row["state"] == "claimed" else None)
            return dict(claimed)

    def admit(self, request_id, token, manifest_digest, input_digest, scope, reserve_amount,
              *, bound_source=None, no_fee_evidence=None):
        """Reserve and record the one dispatch intent in the same SQLite commit."""
        _text(request_id, "request_id")
        _text(token, "token")
        _text(scope, "scope")
        _digest(manifest_digest, "manifest_digest")
        _digest(input_digest, "input_digest")
        with self.coordinator._transaction() as conn:
            row = self.coordinator._row(conn, request_id)
            entry = self._entry(conn, request_id)
            if entry["state"] != "enrolled" or row["state"] != "claimed" or row["token"] != token or row["lease_until"] <= time.time():
                raise ExecutionError("claim is stale or dispatch grant was already recorded")
            if (entry["scope"], entry["manifest_digest"], entry["input_digest"], entry["attempt_id"]) != (
                    scope, manifest_digest, input_digest, row["attempt_id"]):
                raise ExecutionError("scope or frozen request evidence does not match enrollment")
            balance = self.budget._reserve_in(conn, scope, row["attempt_id"], reserve_amount,
                                              bound_source=bound_source, no_fee_evidence=no_fee_evidence)
            conn.execute("""UPDATE execution_requests SET state='admitted',admission_token=?,
                reserve_amount=?,bound_source=?,no_fee_evidence=? WHERE request_id=?""",
                (token, reserve_amount, bound_source, no_fee_evidence, request_id))
            conn.execute("UPDATE requests SET state='dispatch_intent',lease_until=NULL WHERE request_id=?",
                         (request_id,))
            self.coordinator._event(conn, row, "dispatch_started", worker_id=row["worker_id"],
                                    token=token, details=f"budget scope {scope}")
            return {"request": dict(self.coordinator._row(conn, request_id)), "budget": balance}

    def complete(self, request_id, token, outcome, evidence_id, *, response_digest=None,
                 settlement_id=None, charge=None, zero_charge_evidence=None, billing_reason=None):
        """Commit terminal observation with full charge or an unresolved hold."""
        _text(request_id, "request_id")
        _text(token, "token")
        _text(evidence_id, "evidence_id")
        if outcome not in ("response_saved", "not_sent", "outcome_unknown"):
            raise ExecutionError("unsupported outcome")
        if outcome == "response_saved":
            _digest(response_digest, "response_digest")
        elif response_digest is not None:
            raise ExecutionError("response_digest requires response_saved")
        if charge is None:
            _text(billing_reason, "billing_reason")
            if settlement_id is not None or zero_charge_evidence is not None:
                raise ExecutionError("missing charge cannot have settlement evidence")
        else:
            _text(settlement_id, "settlement_id")
            if billing_reason is not None:
                raise ExecutionError("billing_reason applies only to missing charge")
        with self.coordinator._transaction() as conn:
            row = self.coordinator._row(conn, request_id)
            entry = self._entry(conn, request_id)
            if entry["admission_token"] != token:
                raise ExecutionError("stale admission token")
            proposed = (outcome, evidence_id, response_digest, billing_reason, settlement_id,
                        charge, zero_charge_evidence)
            recorded = tuple(entry[k] for k in ("outcome", "evidence_id", "response_digest",
                                                "billing_reason", "settlement_id", "charge",
                                                "zero_charge_evidence"))
            if entry["state"] in ("completed", "reconciled"):
                same_completion = proposed == recorded or (
                    charge is None and entry["billing_reason"] is not None and
                    proposed[:4] == recorded[:4] and settlement_id is None and
                    zero_charge_evidence is None)
                if same_completion:
                    return self._with_budget(conn, request_id, entry["scope"])
                raise ExecutionError("conflicting completion evidence")
            if entry["state"] != "admitted" or row["state"] != "dispatch_intent":
                raise ExecutionError("dispatch grant is required before completion")
            if charge is None:
                balance = self.budget._mark_unknown_in(conn, entry["scope"], entry["attempt_id"], billing_reason)
            else:
                balance = self.budget._settle_in(conn, entry["scope"], entry["attempt_id"],
                                                  settlement_id, charge,
                                                  zero_charge_evidence=zero_charge_evidence)
            conn.execute("""UPDATE execution_requests SET state='completed',outcome=?,evidence_id=?,
                response_digest=?,billing_reason=?,settlement_id=?,charge=?,zero_charge_evidence=?
                WHERE request_id=?""", (*proposed, request_id))
            conn.execute("""UPDATE requests SET state=?,outcome=?,evidence_id=?,response_digest=?
                WHERE request_id=?""", (outcome, outcome, evidence_id, response_digest, request_id))
            self.coordinator._event(conn, row, outcome, worker_id=row["worker_id"], token=token,
                                    evidence_id=evidence_id, response_digest=response_digest)
            return {**self._view(conn, request_id), "budget": balance}

    def settle_charge(self, request_id, settlement_id, charge, *, zero_charge_evidence=None):
        """Settle a held missing charge once without changing response evidence."""
        _text(request_id, "request_id")
        _text(settlement_id, "settlement_id")
        with self.coordinator._transaction() as conn:
            entry = self._entry(conn, request_id)
            if entry["state"] not in ("completed", "reconciled"):
                raise ExecutionError("terminal observation is required before charge settlement")
            if entry["settlement_id"] is not None:
                if (entry["settlement_id"], entry["charge"], entry["zero_charge_evidence"]) == (
                        settlement_id, charge, zero_charge_evidence):
                    return self._with_budget(conn, request_id, entry["scope"])
                raise ExecutionError("conflicting charge settlement")
            balance = self.budget._settle_in(conn, entry["scope"], entry["attempt_id"],
                                              settlement_id, charge,
                                              zero_charge_evidence=zero_charge_evidence)
            conn.execute("""UPDATE execution_requests SET settlement_id=?,charge=?,zero_charge_evidence=?
                WHERE request_id=?""", (settlement_id, charge, zero_charge_evidence, request_id))
            row = self.coordinator._row(conn, request_id)
            self.coordinator._event(conn, row, "charge_settled", evidence_id=settlement_id)
            return {**self._view(conn, request_id), "budget": balance}

    def reconcile(self, request_id, reconciliation_id, outcome, *, response_digest=None):
        """Append a response finding after an unknown outcome; never requeue."""
        _text(request_id, "request_id")
        _text(reconciliation_id, "reconciliation_id")
        if outcome not in ("response_saved", "not_sent"):
            raise ExecutionError("unsupported reconciliation outcome")
        if outcome == "response_saved":
            _digest(response_digest, "response_digest")
        elif response_digest is not None:
            raise ExecutionError("response_digest requires response_saved")
        with self.coordinator._transaction() as conn:
            row = self.coordinator._row(conn, request_id)
            entry = self._entry(conn, request_id)
            if entry["state"] == "reconciled":
                if (entry["reconciliation_id"], entry["reconciliation_outcome"],
                        entry["reconciliation_response_digest"]) == (
                        reconciliation_id, outcome, response_digest):
                    return self._view(conn, request_id)
                raise ExecutionError("conflicting reconciliation evidence")
            if entry["state"] != "completed" or row["state"] != "outcome_unknown":
                raise ExecutionError("only an unknown outcome can be reconciled")
            conn.execute("""UPDATE execution_requests SET state='reconciled',reconciliation_id=?,
                reconciliation_outcome=?,reconciliation_response_digest=? WHERE request_id=?""",
                (reconciliation_id, outcome, response_digest, request_id))
            conn.execute("""UPDATE requests SET state='reconciled',reconciliation_id=?,
                reconciliation_outcome=?,reconciliation_response_digest=? WHERE request_id=?""",
                (reconciliation_id, outcome, response_digest, request_id))
            self.coordinator._event(conn, row, "reconciled", evidence_id=reconciliation_id,
                                    response_digest=response_digest, details=outcome)
            return self._view(conn, request_id)

    def _view(self, conn, request_id):
        return {"request": dict(self.coordinator._row(conn, request_id)),
                "execution": dict(self._entry(conn, request_id))}

    def _with_budget(self, conn, request_id, scope):
        return {**self._view(conn, request_id),
                "budget": self.budget._view(self.budget._scope(conn, scope))}

    def get(self, request_id):
        _text(request_id, "request_id")
        with self.coordinator._transaction() as conn:
            return self._view(conn, request_id)
