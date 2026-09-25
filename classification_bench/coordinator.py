"""Single-host, offline SQLite coordination for logical classification requests.

This module records dispatch *intent*, not permission to spend or call a provider.
It deliberately has no adapter and is not transactionally coupled to BudgetLedger.
"""

import math
import os
import re
import sqlite3
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class CoordinatorError(ValueError):
    """Invalid evidence, unsafe storage, or an illegal state transition."""


def _text(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise CoordinatorError(f"{name} must be a nonempty trimmed string")


def _digest(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise CoordinatorError(f"{name} must be a lowercase SHA-256 hex digest")


def _private_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise CoordinatorError(f"database or SQLite sidecar is not a private regular file: {path}")
    return True


def _prepare_database(path):
    try:
        handle = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        try:
            os.fchmod(handle, 0o600)
            os.fsync(handle)
        finally:
            os.close(handle)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    if not _private_file(path):
        raise CoordinatorError(f"database is missing: {path}")
    for suffix in ("-journal", "-wal", "-shm"):
        _private_file(Path(str(path) + suffix))


class Coordinator:
    """A short-transaction request ledger. One object may be opened per process."""

    def __init__(self, path):
        self.path = Path(path)
        _prepare_database(self.path)
        with self._transaction() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS requests (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                manifest_digest TEXT NOT NULL,
                request_artifact_digest TEXT NOT NULL,
                attempt_id TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL CHECK(state IN
                    ('ready','claimed','dispatch_intent','response_saved',
                     'not_sent','outcome_unknown','reconciled')),
                generation INTEGER NOT NULL DEFAULT 0,
                token TEXT,
                worker_id TEXT,
                lease_until REAL,
                outcome TEXT,
                evidence_id TEXT,
                response_digest TEXT,
                reconciliation_id TEXT,
                reconciliation_outcome TEXT,
                reconciliation_response_digest TEXT
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL REFERENCES requests(request_id),
                attempt_id TEXT NOT NULL,
                generation INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                recorded_at REAL NOT NULL,
                worker_id TEXT,
                token TEXT,
                evidence_id TEXT,
                response_digest TEXT,
                details TEXT
            )""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN
                SELECT RAISE(ABORT, 'events are immutable'); END""")
            conn.execute("""CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN
                SELECT RAISE(ABORT, 'events are immutable'); END""")

    def _connect(self):
        _prepare_database(self.path)
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @staticmethod
    def _event(conn, row, kind, *, worker_id=None, token=None, evidence_id=None,
               response_digest=None, details=None):
        conn.execute("""INSERT INTO events
            (request_id,attempt_id,generation,event_type,recorded_at,worker_id,
             token,evidence_id,response_digest,details) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row["request_id"], row["attempt_id"], row["generation"], kind,
             time.time(), worker_id, token, evidence_id, response_digest, details))

    @staticmethod
    def _row(conn, request_id):
        row = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
        if row is None:
            raise CoordinatorError(f"unknown request: {request_id}")
        return row

    @staticmethod
    def _view(row):
        return dict(row)

    def enqueue(self, request_id, manifest_digest, request_artifact_digest):
        """Register immutable request identity; an identical replay is a no-op."""
        _text(request_id, "request_id")
        _digest(manifest_digest, "manifest_digest")
        _digest(request_artifact_digest, "request_artifact_digest")
        with self._transaction() as conn:
            old = conn.execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
            if old is not None:
                if (old["manifest_digest"], old["request_artifact_digest"]) != (
                        manifest_digest, request_artifact_digest):
                    raise CoordinatorError("request identity already exists with different evidence")
                return self._view(old)
            attempt_id = str(uuid.uuid4())
            conn.execute("""INSERT INTO requests
                (request_id,manifest_digest,request_artifact_digest,attempt_id,state)
                VALUES (?,?,?,?, 'ready')""",
                (request_id, manifest_digest, request_artifact_digest, attempt_id))
            row = self._row(conn, request_id)
            self._event(conn, row, "enqueued")
            return self._view(row)

    def claim(self, worker_id, lease_seconds):
        """Claim one ready or expired, never-dispatched request with a fresh fence."""
        _text(worker_id, "worker_id")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or (
                not math.isfinite(lease_seconds) or lease_seconds <= 0):
            raise CoordinatorError("lease_seconds must be finite and positive")
        with self._transaction() as conn:
            now = time.time()
            row = conn.execute("""SELECT * FROM requests
                WHERE state='ready' OR (state='claimed' AND lease_until<=?)
                ORDER BY seq LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            generation = row["generation"] + 1
            token = str(uuid.uuid4())
            conn.execute("""UPDATE requests SET state='claimed', generation=?, token=?,
                worker_id=?, lease_until=? WHERE request_id=?""",
                (generation, token, worker_id, now + lease_seconds, row["request_id"]))
            claimed = self._row(conn, row["request_id"])
            self._event(conn, claimed, "claimed", worker_id=worker_id, token=token,
                        details="reclaimed expired claim" if row["state"] == "claimed" else None)
            return self._view(claimed)

    def record_dispatch_intent(self, request_id, token):
        """Commit the one-shot intent before any external call; no live permit is issued."""
        _text(request_id, "request_id")
        _text(token, "token")
        with self._transaction() as conn:
            row = self._row(conn, request_id)
            if row["state"] != "claimed" or row["token"] != token or row["lease_until"] <= time.time():
                raise CoordinatorError("claim is stale or dispatch intent was already recorded")
            conn.execute("UPDATE requests SET state='dispatch_intent', lease_until=NULL WHERE request_id=?",
                         (request_id,))
            self._event(conn, row, "dispatch_started", worker_id=row["worker_id"], token=token)
            return self._view(self._row(conn, request_id))

    def complete(self, request_id, token, outcome, evidence_id, *, response_digest=None):
        """Record one terminal observation. Duplicate identical evidence is idempotent."""
        _text(request_id, "request_id")
        _text(token, "token")
        _text(evidence_id, "evidence_id")
        if outcome not in ("response_saved", "not_sent", "outcome_unknown"):
            raise CoordinatorError("unsupported outcome")
        if outcome == "response_saved":
            _digest(response_digest, "response_digest")
        elif response_digest is not None:
            raise CoordinatorError("response_digest requires response_saved")
        with self._transaction() as conn:
            row = self._row(conn, request_id)
            if row["token"] != token:
                raise CoordinatorError("stale claim token")
            if row["state"] in ("response_saved", "not_sent", "outcome_unknown", "reconciled"):
                if (row["outcome"], row["evidence_id"], row["response_digest"]) == (
                        outcome, evidence_id, response_digest):
                    return self._view(row)
                raise CoordinatorError("conflicting completion evidence")
            if row["state"] != "dispatch_intent":
                raise CoordinatorError("dispatch intent must be recorded first")
            conn.execute("""UPDATE requests SET state=?, outcome=?, evidence_id=?,
                response_digest=? WHERE request_id=?""",
                (outcome, outcome, evidence_id, response_digest, request_id))
            self._event(conn, row, outcome, worker_id=row["worker_id"], token=token,
                        evidence_id=evidence_id, response_digest=response_digest)
            return self._view(self._row(conn, request_id))

    def reconcile(self, request_id, reconciliation_id, outcome, *, response_digest=None):
        """Append a finding that resolves an unknown; never requeue the request."""
        _text(request_id, "request_id")
        _text(reconciliation_id, "reconciliation_id")
        if outcome not in ("response_saved", "not_sent"):
            raise CoordinatorError("reconciliation outcome must be response_saved or not_sent")
        if outcome == "response_saved":
            _digest(response_digest, "response_digest")
        elif response_digest is not None:
            raise CoordinatorError("response_digest requires response_saved")
        with self._transaction() as conn:
            row = self._row(conn, request_id)
            if row["state"] == "reconciled":
                if (row["reconciliation_id"], row["reconciliation_outcome"],
                        row["reconciliation_response_digest"]) == (
                        reconciliation_id, outcome, response_digest):
                    return self._view(row)
                raise CoordinatorError("conflicting reconciliation evidence")
            if row["state"] != "outcome_unknown":
                raise CoordinatorError("only an unknown outcome can be reconciled")
            conn.execute("""UPDATE requests SET state='reconciled', reconciliation_id=?,
                reconciliation_outcome=?, reconciliation_response_digest=?
                WHERE request_id=?""", (reconciliation_id, outcome, response_digest, request_id))
            self._event(conn, row, "reconciled", evidence_id=reconciliation_id,
                        response_digest=response_digest, details=outcome)
            return self._view(self._row(conn, request_id))

    def get(self, request_id):
        _text(request_id, "request_id")
        with self._transaction() as conn:
            return self._view(self._row(conn, request_id))

    def events(self, request_id):
        _text(request_id, "request_id")
        with self._transaction() as conn:
            self._row(conn, request_id)
            return [dict(row) for row in conn.execute(
                "SELECT * FROM events WHERE request_id=? ORDER BY event_id", (request_id,))]
