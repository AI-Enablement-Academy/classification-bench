"""Append-only operator account assertions, separate from frozen experiments.

This ledger checks local bindings, evidence bytes and assertion age. It does
not inspect an account, authenticate an operator, or verify provider billing.
Admission enforcement is supplied through the caller's existing transaction.
"""

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sqlite3
from types import SimpleNamespace

from .budget import BudgetError, BudgetLedger, _private_file, _validate_database_files
from .evidence import ArtifactRef, EvidenceError, put_artifact, read_artifact
from .manifest import canonical_bytes, digest


class SubscriptionAssertionError(ValueError):
    pass


ASSERTION_KEYS = {"extra_usage_disabled", "verified_at", "source"}
RENEWAL_KEYS = {"schema_version", "renewal_id", "run_sha256", "scope", "config_id",
                "configuration_sha256", "adapter", "expected_revision", "extra_usage_disabled",
                "verified_at", "source", "account_check_sha256"}
MAX_ACCOUNT_CHECK_BYTES = 1_000_000
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _now():
    return datetime.now(timezone.utc)


def _text(value, name):
    if (not isinstance(value, str) or not value or value != value.strip() or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SubscriptionAssertionError(f"{name} must be a nonempty trimmed string without controls")


def _sha(value, name):
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise SubscriptionAssertionError(f"{name} must be a lowercase SHA-256 digest")


def _checked_time(value):
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise SubscriptionAssertionError("verified_at must be a UTC ISO8601 timestamp ending in Z")
    try:
        checked = datetime.fromisoformat(value[:-1] + "+00:00")
        checked + timedelta(days=1)
        return checked
    except (ValueError, OverflowError) as exc:
        raise SubscriptionAssertionError("invalid account assertion timestamp") from exc


def _assertion(value):
    if not isinstance(value, dict) or set(value) != ASSERTION_KEYS:
        raise SubscriptionAssertionError("initial assertion must use exact v1 assertion fields")
    if value["extra_usage_disabled"] is not True:
        raise SubscriptionAssertionError("paid extra usage disabled assertion must be true")
    _text(value["source"], "source")
    return _checked_time(value["verified_at"])


def _key(key):
    if not isinstance(key, (tuple, list)) or len(key) != 3:
        raise SubscriptionAssertionError("guard key must be (scope, run_sha256, config_id)")
    scope, run_sha256, config_id = key
    _text(scope, "scope")
    _sha(run_sha256, "run_sha256")
    _text(config_id, "config_id")
    return scope, run_sha256, config_id


def _table_exists(conn, table):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


class SubscriptionAssertionLedger:
    """Use the execution database and private content-addressed evidence store."""

    def __init__(self, execution, artifact_root):
        self.execution = execution
        self.artifact_root = Path(artifact_root)
        with execution.coordinator._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS subscription_assertion_revisions (
                scope TEXT NOT NULL REFERENCES scopes(scope), run_sha256 TEXT NOT NULL,
                config_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK(revision>=0),
                configuration_sha256 TEXT NOT NULL, adapter TEXT NOT NULL,
                renewal_id TEXT, assertion_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
                PRIMARY KEY(scope,run_sha256,config_id,revision),
                UNIQUE(scope,run_sha256,config_id,renewal_id))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS subscription_guard_admissions (
                request_id TEXT PRIMARY KEY REFERENCES execution_requests(request_id),
                admission_token TEXT NOT NULL, scope TEXT NOT NULL, run_sha256 TEXT NOT NULL,
                config_id TEXT NOT NULL, revision INTEGER NOT NULL,
                assertion_id TEXT NOT NULL REFERENCES subscription_assertion_revisions(assertion_id),
                checked_at TEXT NOT NULL,
                FOREIGN KEY(scope,run_sha256,config_id,revision)
                    REFERENCES subscription_assertion_revisions(scope,run_sha256,config_id,revision))""")
            for table in ("subscription_assertion_revisions", "subscription_guard_admissions"):
                for operation in ("UPDATE", "DELETE"):
                    conn.execute(f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                        BEFORE {operation} ON {table} BEGIN
                        SELECT RAISE(ABORT,'subscription assertion history is immutable'); END""")

    @classmethod
    def read_current(cls, database, artifact_root, key):
        """Read existing assertion state without constructors or migrations.

        An absent database, assertion table or key returns None. Unsafe storage,
        inconsistent bindings and unverifiable history fail closed. The reader
        uses a SQLite read transaction so concurrent renewals cannot mix rows.
        """
        key = _key(key)
        path = Path(database).absolute()
        try:
            path.lstat()
        except FileNotFoundError:
            return None
        connection = None
        try:
            _validate_database_files(path)
            connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True,
                                         timeout=15, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            if not _table_exists(connection, "subscription_assertion_revisions"):
                return None
            if connection.execute("""SELECT 1 FROM subscription_assertion_revisions
                    WHERE scope=? AND run_sha256=? AND config_id=?""", key).fetchone() is None:
                return None
            # Reuse the budget's read validators without initializing a database,
            # creating migration tables, or manufacturing new authorization.
            budget_reader = BudgetLedger.__new__(BudgetLedger)
            budget_reader.path = path
            reader = cls.__new__(cls)
            reader.execution = SimpleNamespace(budget=budget_reader)
            reader.artifact_root = Path(artifact_root)
            return reader._history_in(connection, key)[-1]
        except (BudgetError, sqlite3.Error) as exc:
            raise SubscriptionAssertionError("existing subscription assertion state cannot be read safely") from exc
        finally:
            if connection is not None:
                connection.close()

    def _binding_in(self, conn, key):
        scope, run_sha256, _ = _key(key)
        try:
            budget = self.execution.budget._scope(conn, scope)
        except BudgetError as exc:
            raise SubscriptionAssertionError("subscription assertion scope does not exist") from exc
        if (budget["currency"], budget["scale"]) != ("REQ", 1):
            raise SubscriptionAssertionError("subscription assertions require a REQ scope at scale 1")
        if _table_exists(conn, "benchmark_managed_runs"):
            row = conn.execute("SELECT scope FROM benchmark_managed_runs WHERE run_sha256=?", (run_sha256,)).fetchone()
            if row is not None:
                if row["scope"] != scope:
                    raise SubscriptionAssertionError("subscription assertion run/scope binding mismatch")
                return
        if _table_exists(conn, "benchmark_binding"):
            row = conn.execute("SELECT run_sha256 FROM benchmark_binding WHERE singleton=1").fetchone()
            if row is not None and row["run_sha256"] == run_sha256:
                return
        raise SubscriptionAssertionError("subscription assertion requires the existing exact benchmark run binding")

    def _load_record(self, row):
        try:
            record = json.loads(row["payload"])
            identity = record.pop("assertion_id")
            if identity != row["assertion_id"] or digest(canonical_bytes(record)) != identity:
                raise SubscriptionAssertionError("subscription assertion record digest mismatch")
            record["assertion_id"] = identity
            if any(record[key] != row[key] for key in
                   ("scope", "run_sha256", "config_id", "revision", "configuration_sha256", "adapter", "renewal_id")):
                raise SubscriptionAssertionError("subscription assertion record binding mismatch")
            reference = record["account_check_ref"]
            if reference is not None:
                if not _private_file(self.artifact_root / reference["path"]):
                    raise SubscriptionAssertionError("private account check evidence is missing")
                read_artifact(self.artifact_root, ArtifactRef(**reference))
            return record
        except (KeyError, TypeError, ValueError, EvidenceError, BudgetError) as exc:
            if isinstance(exc, SubscriptionAssertionError):
                raise
            raise SubscriptionAssertionError("subscription assertion evidence cannot be verified") from exc

    def _history_in(self, conn, key):
        self._binding_in(conn, key)
        rows = conn.execute("""SELECT * FROM subscription_assertion_revisions
            WHERE scope=? AND run_sha256=? AND config_id=? ORDER BY revision""", _key(key)).fetchall()
        if not rows:
            raise SubscriptionAssertionError("initial subscription assertion is not bound")
        records = [self._load_record(row) for row in rows]
        for revision, record in enumerate(records):
            previous = records[revision - 1]["assertion_id"] if revision else None
            if record["revision"] != revision or record["previous_assertion_id"] != previous:
                raise SubscriptionAssertionError("subscription assertion revision chain mismatch")
        return records

    @staticmethod
    def _insert_in(conn, record):
        record["assertion_id"] = digest(canonical_bytes(record))
        conn.execute("""INSERT INTO subscription_assertion_revisions
            (scope,run_sha256,config_id,revision,configuration_sha256,adapter,renewal_id,assertion_id,payload)
            VALUES(?,?,?,?,?,?,?,?,?)""", tuple(record[key] for key in
            ("scope", "run_sha256", "config_id", "revision", "configuration_sha256", "adapter", "renewal_id", "assertion_id"))
            + (canonical_bytes(record).decode("utf-8"),))
        return record

    def bind_initial(self, scope, run_sha256, config_id, configuration_sha256, adapter, assertion):
        """Retain original assertion terms, including expired historical checks."""
        key = _key((scope, run_sha256, config_id))
        _sha(configuration_sha256, "configuration_sha256")
        if adapter not in ("codex", "claude_code"):
            raise SubscriptionAssertionError("subscription assertion requires codex or claude_code")
        checked = _assertion(assertion)
        with self.execution.coordinator._transaction() as conn:
            self._binding_in(conn, key)
            existing = conn.execute("""SELECT * FROM subscription_assertion_revisions
                WHERE scope=? AND run_sha256=? AND config_id=? AND revision=0""", key).fetchone()
            if existing is not None:
                original = self._load_record(existing)
                if (original["configuration_sha256"] != configuration_sha256 or original["adapter"] != adapter or
                        original["initial_assertion_sha256"] != digest(canonical_bytes(assertion))):
                    raise SubscriptionAssertionError("initial subscription assertion or configuration changed")
                return original
            if checked > _now():
                raise SubscriptionAssertionError("initial account assertion is in the future")
            return self._insert_in(conn, {
                "schema_version": 1, "scope": scope, "run_sha256": run_sha256, "config_id": config_id,
                "configuration_sha256": configuration_sha256, "adapter": adapter, "revision": 0,
                "renewal_id": None, "previous_assertion_id": None,
                "initial_assertion_sha256": digest(canonical_bytes(assertion)), "authorization_sha256": None,
                **assertion, "expires_at": (checked + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "account_check_ref": None, "origin": "frozen_initial_assertion",
                "verification": "operator_assertion", "verification_limit": "not independently verified; no remote billing check",
                "recorded_at": _now().isoformat().replace("+00:00", "Z")})

    def renew(self, authorization, account_check_bytes, *, media_type="application/json"):
        """Append one run-bound fresh check; identical retry preserves its record."""
        if (not isinstance(authorization, dict) or set(authorization) != RENEWAL_KEYS or
                type(authorization.get("schema_version")) is not int or authorization["schema_version"] != 1):
            raise SubscriptionAssertionError("renewal authorization must use exact v1 fields")
        key = _key(tuple(authorization[name] for name in ("scope", "run_sha256", "config_id")))
        _text(authorization["renewal_id"], "renewal_id")
        _sha(authorization["configuration_sha256"], "configuration_sha256")
        _sha(authorization["account_check_sha256"], "account_check_sha256")
        if type(authorization["expected_revision"]) is not int or authorization["expected_revision"] < 0:
            raise SubscriptionAssertionError("expected_revision must be a nonnegative integer")
        checked = _assertion({name: authorization[name] for name in ASSERTION_KEYS})
        if (not isinstance(account_check_bytes, bytes) or not 1 <= len(account_check_bytes) <= MAX_ACCOUNT_CHECK_BYTES or
                digest(account_check_bytes) != authorization["account_check_sha256"]):
            raise SubscriptionAssertionError("account check evidence bytes do not match the bounded declared SHA-256")
        if not isinstance(media_type, str) or not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", media_type):
            raise SubscriptionAssertionError("invalid account check evidence media type")
        authorization_sha = digest(canonical_bytes(authorization))
        with self.execution.coordinator._transaction() as conn:
            history = self._history_in(conn, key)
            existing = next((row for row in history if row["renewal_id"] == authorization["renewal_id"]), None)
            if existing is not None:
                if (existing["authorization_sha256"] != authorization_sha or
                        existing["account_check_ref"]["media_type"] != media_type):
                    raise SubscriptionAssertionError("conflicting renewal ID reuse")
                return existing
            current = history[-1]
            if (authorization["configuration_sha256"], authorization["adapter"]) != (
                    current["configuration_sha256"], current["adapter"]):
                raise SubscriptionAssertionError("renewal configuration or adapter binding changed")
            if authorization["expected_revision"] != current["revision"]:
                raise SubscriptionAssertionError("stale subscription assertion revision")
            self._fresh(authorization)
            if checked <= _checked_time(current["verified_at"]):
                raise SubscriptionAssertionError("renewal requires a newer actual account check")
            try:
                reference = put_artifact(self.artifact_root, account_check_bytes, media_type)
                read_artifact(self.artifact_root, reference)
            except EvidenceError as exc:
                raise SubscriptionAssertionError("account check evidence could not be preserved") from exc
            return self._insert_in(conn, {
                "schema_version": 1, "scope": key[0], "run_sha256": key[1], "config_id": key[2],
                "configuration_sha256": current["configuration_sha256"], "adapter": current["adapter"],
                "revision": current["revision"] + 1, "renewal_id": authorization["renewal_id"],
                "previous_assertion_id": current["assertion_id"],
                "initial_assertion_sha256": current["initial_assertion_sha256"], "authorization_sha256": authorization_sha,
                **{name: authorization[name] for name in ASSERTION_KEYS},
                "expires_at": (checked + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                "account_check_ref": asdict(reference), "origin": "operator_supplied_renewal",
                "verification": "operator_assertion", "verification_limit": "not independently verified; no remote billing check",
                "recorded_at": _now().isoformat().replace("+00:00", "Z")})

    @staticmethod
    def _fresh(record):
        checked = _assertion({name: record[name] for name in ASSERTION_KEYS})
        age = (_now() - checked).total_seconds()
        if age < 0:
            raise SubscriptionAssertionError("account assertion is in the future")
        if age > 86400:
            raise SubscriptionAssertionError("account assertion expired; supply a fresh actual account check")

    def current(self, scope, run_sha256, config_id):
        """Read the latest immutable record; freshness is enforced at admission."""
        with self.execution.coordinator._transaction() as conn:
            return self._history_in(conn, (scope, run_sha256, config_id))[-1]

    def history(self, key):
        """Verify the full revision chain and each supplied evidence artifact."""
        with self.execution.coordinator._transaction() as conn:
            return self._history_in(conn, key)

    def require_fresh_in(self, conn, key, expected_revision=None, *, request_id=None, admission_token=None):
        """Check inside the existing admission transaction; optionally bind audit.

        Invoke before capacity reservation and dispatch intent. A rollback by the
        caller rolls back the guard admission audit too. This method does not
        open another transaction, reserve capacity or change execution state.
        """
        if not conn.in_transaction:
            raise SubscriptionAssertionError("guard admission requires the caller's active transaction")
        key = _key(key)
        current = self._history_in(conn, key)[-1]
        block = self.execution._admission_block_in(conn, key[0])
        if block is not None:
            raise SubscriptionAssertionError(f"admission blocked for scope {key[0]}: {block['reason']}")
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision != current["revision"]):
            raise SubscriptionAssertionError("subscription assertion revision changed after preflight")
        self._fresh(current)
        if (request_id is None) != (admission_token is None):
            raise SubscriptionAssertionError("guard audit requires both storage request_id and admission_token")
        if request_id is not None:
            _text(request_id, "request_id")
            _text(admission_token, "admission_token")
            row = conn.execute("""SELECT r.state,r.token,r.lease_until,x.scope,x.state AS execution_state
                FROM requests r JOIN execution_requests x ON x.request_id=r.request_id WHERE r.request_id=?""",
                (request_id,)).fetchone()
            if (row is None or row["scope"] != key[0] or row["state"] != "claimed" or
                    row["execution_state"] != "enrolled" or row["token"] != admission_token or
                    row["lease_until"] <= _now().timestamp()):
                raise SubscriptionAssertionError("guard admission claim or scope is stale or unknown")
            terms = (request_id, admission_token, *key, current["revision"], current["assertion_id"])
            existing = conn.execute("SELECT * FROM subscription_guard_admissions WHERE request_id=?", (request_id,)).fetchone()
            if existing is not None:
                if tuple(existing[name] for name in ("request_id", "admission_token", "scope", "run_sha256", "config_id", "revision", "assertion_id")) != terms:
                    raise SubscriptionAssertionError("conflicting guard admission evidence")
            else:
                conn.execute("""INSERT INTO subscription_guard_admissions
                    (request_id,admission_token,scope,run_sha256,config_id,revision,assertion_id,checked_at)
                    VALUES(?,?,?,?,?,?,?,?)""", terms + (_now().isoformat().replace("+00:00", "Z"),))
        return current
