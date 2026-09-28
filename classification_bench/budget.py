"""Offline, per-scope SQLite money reservations; no provider or dispatch integration.

Amounts are integer monetary subunits. A scope must be explicitly created with
its authorization source. Bound evidence and zero-charge evidence are recorded,
but this module cannot authenticate provider pricing or user authorization.
"""

import os
import re
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path


class BudgetError(ValueError):
    pass


def _text(value, name):
    if not isinstance(value, str) or not value or value != value.strip():
        raise BudgetError(f"{name} must be a nonempty trimmed string")


def _money(value, name, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise BudgetError(f"{name} must be a {'positive' if positive else 'nonnegative'} integer")


def _private_file(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise BudgetError(f"database or SQLite sidecar is not a private regular file: {path}")
    return True


def _prepare_database(path):
    """Create a new database exclusively at 0600; never change an existing file."""
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
    _validate_database_files(path)


def _validate_database_files(path):
    if not _private_file(path):
        raise BudgetError(f"database is missing: {path}")
    for suffix in ("-journal", "-wal", "-shm"):
        _private_file(Path(str(path) + suffix))


class BudgetLedger:
    """One SQLite database; each operation uses a short IMMEDIATE transaction."""

    def __init__(self, path):
        self.path = Path(path)
        _prepare_database(self.path)
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scopes (
                    scope TEXT PRIMARY KEY, cap INTEGER NOT NULL CHECK(cap > 0),
                    currency TEXT NOT NULL, scale INTEGER NOT NULL CHECK(scale > 0),
                    authorization_source TEXT NOT NULL,
                    known INTEGER NOT NULL DEFAULT 0 CHECK(known >= 0),
                    active INTEGER NOT NULL DEFAULT 0 CHECK(active >= 0),
                    holds INTEGER NOT NULL DEFAULT 0 CHECK(holds >= 0),
                    frozen INTEGER NOT NULL DEFAULT 0 CHECK(frozen IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    scope TEXT NOT NULL REFERENCES scopes(scope),
                    attempt_id TEXT NOT NULL, reserved INTEGER NOT NULL CHECK(reserved >= 0),
                    bound_source TEXT, no_fee_evidence TEXT,
                    state TEXT NOT NULL CHECK(state IN ('active','held','settled')),
                    settlement_id TEXT, charge INTEGER CHECK(charge >= 0),
                    zero_charge_evidence TEXT, unknown_reason TEXT,
                    PRIMARY KEY (scope, attempt_id), UNIQUE (scope, settlement_id)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scope TEXT NOT NULL REFERENCES scopes(scope),
                    attempt_id TEXT, event_type TEXT NOT NULL,
                    known_delta INTEGER NOT NULL, active_delta INTEGER NOT NULL,
                    holds_delta INTEGER NOT NULL,
                    known_after INTEGER NOT NULL, active_after INTEGER NOT NULL,
                    holds_after INTEGER NOT NULL, frozen_after INTEGER NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events
                BEGIN SELECT RAISE(ABORT, 'audit events are immutable'); END;
                CREATE TABLE IF NOT EXISTS cap_events (
                    event_id INTEGER PRIMARY KEY REFERENCES audit_events(event_id),
                    scope TEXT NOT NULL REFERENCES scopes(scope),
                    amendment_id TEXT,
                    expected_cap INTEGER NOT NULL CHECK(expected_cap > 0),
                    new_cap INTEGER NOT NULL CHECK(new_cap > 0),
                    authorization_source TEXT NOT NULL,
                    UNIQUE(scope, amendment_id)
                );
                CREATE TRIGGER IF NOT EXISTS cap_events_no_update BEFORE UPDATE ON cap_events
                BEGIN SELECT RAISE(ABORT, 'cap events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS cap_events_no_delete BEFORE DELETE ON cap_events
                BEGIN SELECT RAISE(ABORT, 'cap events are immutable'); END;
            """)
        finally:
            conn.close()
        # Backfill the initial cap for databases created before cap amendments
        # existed. Existing audit balance events and the initial authorization
        # terms remain untouched.
        with self._transaction() as conn:
            for row in conn.execute("""SELECT * FROM scopes WHERE scope NOT IN
                                      (SELECT scope FROM cap_events)""").fetchall():
                creation = conn.execute("""SELECT event_id FROM audit_events
                                           WHERE scope=? AND event_type='scope_created'
                                           ORDER BY event_id LIMIT 1""", (row["scope"],)).fetchone()
                if creation is None:
                    raise BudgetError("missing scope creation audit event")
                conn.execute("""INSERT INTO cap_events
                             (event_id,scope,amendment_id,expected_cap,new_cap,authorization_source)
                             VALUES (?,?,NULL,?,?,?)""",
                             (creation["event_id"], row["scope"], row["cap"], row["cap"],
                              row["authorization_source"]))

    def _connect(self):
        _validate_database_files(self.path)
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=15000")
        return conn

    @contextmanager
    def _transaction(self):
        conn = self._connect()
        began = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            began = True
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if began and conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def _scope(self, conn, scope):
        row = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        if row is None:
            raise BudgetError(f"unknown authorization scope: {scope}")
        self._verify_scope(conn, row)
        return row

    @staticmethod
    def _last_event(conn, scope):
        return conn.execute(
            "SELECT * FROM audit_events WHERE scope=? ORDER BY event_id DESC LIMIT 1", (scope,)
        ).fetchone()

    def _verify_scope(self, conn, row):
        scope = row["scope"]
        totals = conn.execute("""
            SELECT COALESCE(SUM(CASE WHEN state='settled' THEN charge ELSE 0 END),0) known,
                   COALESCE(SUM(CASE WHEN state='active' THEN reserved ELSE 0 END),0) active,
                   COALESCE(SUM(CASE WHEN state='held' THEN reserved ELSE 0 END),0) holds
            FROM attempts WHERE scope=?
        """, (scope,)).fetchone()
        last = self._last_event(conn, scope)
        if last is None or any(row[key] != totals[key] or row[key] != last[f"{key}_after"]
                               for key in ("known", "active", "holds")) or row["frozen"] != last["frozen_after"]:
            raise BudgetError("ledger balances disagree with attempts or audit trail")
        self._verify_cap_chain(conn, row)

    @staticmethod
    def _verify_cap_chain(conn, row):
        events = conn.execute("""SELECT c.*, a.event_type, a.scope AS audit_scope,
                              a.known_delta, a.active_delta, a.holds_delta
                              FROM cap_events c JOIN audit_events a ON a.event_id=c.event_id
                              WHERE c.scope=? ORDER BY c.event_id""", (row["scope"],)).fetchall()
        audit_ids = [x["event_id"] for x in conn.execute("""SELECT event_id FROM audit_events
                       WHERE scope=? AND event_type IN ('scope_created','cap_increased')
                       ORDER BY event_id""", (row["scope"],)).fetchall()]
        if not events or [x["event_id"] for x in events] != audit_ids:
            raise BudgetError("cap amendment audit chain mismatch")
        original = events[0]
        if (original["event_type"] != "scope_created" or original["amendment_id"] is not None or
                original["expected_cap"] != original["new_cap"] or
                original["authorization_source"] != row["authorization_source"]):
            raise BudgetError("initial cap authorization mismatch")
        cap = original["new_cap"]
        for index, event in enumerate(events):
            if (event["audit_scope"] != row["scope"] or
                    (event["known_delta"], event["active_delta"], event["holds_delta"]) != (0, 0, 0)):
                raise BudgetError("cap amendment audit event mismatch")
            if index == 0:
                continue
            if (event["event_type"] != "cap_increased" or not event["amendment_id"] or
                    not event["authorization_source"] or event["expected_cap"] != cap or
                    event["new_cap"] <= cap):
                raise BudgetError("invalid cap amendment chain")
            cap = event["new_cap"]
        if row["cap"] != cap:
            raise BudgetError("scope cap disagrees with amendment chain")
        return original["new_cap"]

    @staticmethod
    def _view(row):
        total = row["known"] + row["active"] + row["holds"]
        return {"scope": row["scope"], "cap": row["cap"], "currency": row["currency"],
                "scale": row["scale"], "authorization_source": row["authorization_source"],
                "known_charges": row["known"], "active_reservations": row["active"],
                "unknown_holds": row["holds"], "remaining": row["cap"] - total,
                "over_cap": total > row["cap"], "frozen": bool(row["frozen"])}

    def _audit(self, conn, scope, attempt_id, kind, before, after):
        cursor = conn.execute("""
            INSERT INTO audit_events
            (scope,attempt_id,event_type,known_delta,active_delta,holds_delta,
             known_after,active_after,holds_after,frozen_after)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (scope, attempt_id, kind,
              after["known"] - before["known"], after["active"] - before["active"],
              after["holds"] - before["holds"], after["known"], after["active"],
              after["holds"], after["frozen"]))
        return cursor.lastrowid

    @staticmethod
    def _reject_execution_owned(conn, attempt_id):
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_requests'").fetchone()
        if exists and conn.execute("SELECT 1 FROM execution_requests WHERE attempt_id=?",
                                   (attempt_id,)).fetchone():
            raise BudgetError("execution-owned attempt requires atomic ExecutionLedger API")

    def create_scope(self, scope, cap, currency, scale, authorization_source):
        """Register an explicit cap and source; a conflicting redefinition fails."""
        _text(scope, "scope")
        _money(cap, "cap", positive=True)
        _money(scale, "scale", positive=True)
        _text(authorization_source, "authorization_source")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise BudgetError("currency must be a three-letter uppercase code")
        with self._transaction() as conn:
            old = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            if old is not None:
                self._verify_scope(conn, old)
                original_cap = self._verify_cap_chain(conn, old)
                if (original_cap, old["currency"], old["scale"], old["authorization_source"]) != (
                        cap, currency, scale, authorization_source):
                    raise BudgetError("authorization scope already exists with different terms")
                return self._view(old)
            conn.execute("""INSERT INTO scopes(scope,cap,currency,scale,authorization_source)
                         VALUES (?,?,?,?,?)""", (scope, cap, currency, scale, authorization_source))
            row = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            event_id = self._audit(conn, scope, None, "scope_created", row, row)
            conn.execute("""INSERT INTO cap_events
                         (event_id,scope,amendment_id,expected_cap,new_cap,authorization_source)
                         VALUES (?,?,NULL,?,?,?)""", (event_id, scope, cap, cap, authorization_source))
            return self._view(row)

    def increase_cap(self, scope, amendment_id, expected_cap, new_cap, authorization_source):
        """Apply one expressly authorized, conditional increase to a scope cap."""
        _text(scope, "scope")
        _text(amendment_id, "amendment_id")
        _money(expected_cap, "expected_cap", positive=True)
        _money(new_cap, "new_cap", positive=True)
        _text(authorization_source, "authorization_source")
        if new_cap <= expected_cap:
            raise BudgetError("new cap must exceed expected cap")
        with self._transaction() as conn:
            before = self._scope(conn, scope)
            existing = conn.execute("SELECT * FROM cap_events WHERE scope=? AND amendment_id=?",
                                    (scope, amendment_id)).fetchone()
            if existing is not None:
                if (existing["expected_cap"], existing["new_cap"], existing["authorization_source"]) != (
                        expected_cap, new_cap, authorization_source):
                    raise BudgetError("conflicting cap amendment identity")
                return self._view(before)
            if before["cap"] != expected_cap:
                raise BudgetError("scope cap changed since expected value")
            conn.execute("UPDATE scopes SET cap=? WHERE scope=?", (new_cap, scope))
            after = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            event_id = self._audit(conn, scope, None, "cap_increased", before, after)
            conn.execute("""INSERT INTO cap_events
                         (event_id,scope,amendment_id,expected_cap,new_cap,authorization_source)
                         VALUES (?,?,?,?,?,?)""",
                         (event_id, scope, amendment_id, expected_cap, new_cap,
                          authorization_source))
            self._verify_scope(conn, after)
            return self._view(after)

    def balances(self, scope):
        _text(scope, "scope")
        with self._transaction() as conn:
            return self._view(self._scope(conn, scope))

    def reserve(self, scope, attempt_id, amount, *, bound_source=None, no_fee_evidence=None):
        """Reserve once per attempt; amount zero requires explicit no-fee evidence."""
        _text(scope, "scope")
        _text(attempt_id, "attempt_id")
        _money(amount, "amount")
        if amount:
            _text(bound_source, "bound_source")
            if no_fee_evidence is not None:
                raise BudgetError("no_fee_evidence applies only to zero reservations")
        else:
            _text(no_fee_evidence, "no_fee_evidence")
            if bound_source is not None:
                raise BudgetError("bound_source applies only to positive reservations")
        with self._transaction() as conn:
            self._reject_execution_owned(conn, attempt_id)
            return self._reserve_in(conn, scope, attempt_id, amount,
                                    bound_source=bound_source, no_fee_evidence=no_fee_evidence)

    def _reserve_in(self, conn, scope, attempt_id, amount, *, bound_source=None,
                    no_fee_evidence=None):
            """Reserve on a caller-owned IMMEDIATE transaction after public validation."""
            _text(scope, "scope")
            _text(attempt_id, "attempt_id")
            _money(amount, "amount")
            if amount:
                _text(bound_source, "bound_source")
                if no_fee_evidence is not None:
                    raise BudgetError("no_fee_evidence applies only to zero reservations")
            else:
                _text(no_fee_evidence, "no_fee_evidence")
                if bound_source is not None:
                    raise BudgetError("bound_source applies only to positive reservations")
            before = self._scope(conn, scope)
            if conn.execute("SELECT 1 FROM attempts WHERE scope=? AND attempt_id=?",
                            (scope, attempt_id)).fetchone():
                raise BudgetError("attempt already reserved")
            if before["frozen"]:
                raise BudgetError("scope is frozen after an above-bound charge")
            if before["known"] + before["active"] + before["holds"] + amount > before["cap"]:
                raise BudgetError("reservation would exceed authorization cap")
            conn.execute("""INSERT INTO attempts
                         (scope,attempt_id,reserved,bound_source,no_fee_evidence,state)
                         VALUES (?,?,?,?,?,'active')""",
                         (scope, attempt_id, amount, bound_source, no_fee_evidence))
            conn.execute("UPDATE scopes SET active=active+? WHERE scope=?", (amount, scope))
            after = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            self._audit(conn, scope, attempt_id, "reserved", before, after)
            self._verify_scope(conn, after)
            return self._view(after)

    def mark_unknown(self, scope, attempt_id, reason):
        """Transfer an active reservation into an unresolved charge hold."""
        _text(scope, "scope")
        _text(attempt_id, "attempt_id")
        _text(reason, "reason")
        with self._transaction() as conn:
            self._reject_execution_owned(conn, attempt_id)
            return self._mark_unknown_in(conn, scope, attempt_id, reason)

    def _mark_unknown_in(self, conn, scope, attempt_id, reason):
            _text(scope, "scope")
            _text(attempt_id, "attempt_id")
            _text(reason, "reason")
            before = self._scope(conn, scope)
            attempt = conn.execute("SELECT * FROM attempts WHERE scope=? AND attempt_id=?",
                                   (scope, attempt_id)).fetchone()
            if attempt is None or attempt["state"] != "active":
                raise BudgetError("only an active attempt can become unknown")
            amount = attempt["reserved"]
            conn.execute("""UPDATE attempts SET state='held',unknown_reason=?
                         WHERE scope=? AND attempt_id=?""", (reason, scope, attempt_id))
            conn.execute("""UPDATE scopes SET active=active-?,holds=holds+?
                         WHERE scope=?""", (amount, amount, scope))
            after = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            self._audit(conn, scope, attempt_id, "outcome_unknown", before, after)
            self._verify_scope(conn, after)
            return self._view(after)

    def settle(self, scope, attempt_id, settlement_id, charge, *, zero_charge_evidence=None):
        """Settle active or held attempt once; record the full observed charge."""
        _text(scope, "scope")
        _text(attempt_id, "attempt_id")
        _text(settlement_id, "settlement_id")
        _money(charge, "charge")
        if charge == 0:
            _text(zero_charge_evidence, "zero_charge_evidence")
        elif zero_charge_evidence is not None:
            raise BudgetError("zero_charge_evidence applies only to zero charges")
        with self._transaction() as conn:
            self._reject_execution_owned(conn, attempt_id)
            return self._settle_in(conn, scope, attempt_id, settlement_id, charge,
                                   zero_charge_evidence=zero_charge_evidence)

    def _settle_in(self, conn, scope, attempt_id, settlement_id, charge, *, zero_charge_evidence=None):
            _text(scope, "scope")
            _text(attempt_id, "attempt_id")
            _text(settlement_id, "settlement_id")
            _money(charge, "charge")
            if charge == 0:
                _text(zero_charge_evidence, "zero_charge_evidence")
            elif zero_charge_evidence is not None:
                raise BudgetError("zero_charge_evidence applies only to zero charges")
            before = self._scope(conn, scope)
            attempt = conn.execute("SELECT * FROM attempts WHERE scope=? AND attempt_id=?",
                                   (scope, attempt_id)).fetchone()
            if attempt is None:
                raise BudgetError("attempt was never reserved")
            if attempt["state"] == "settled":
                if (attempt["settlement_id"], attempt["charge"], attempt["zero_charge_evidence"]) == (
                        settlement_id, charge, zero_charge_evidence):
                    return self._view(before)
                raise BudgetError("conflicting settlement for attempt")
            if conn.execute("SELECT 1 FROM attempts WHERE scope=? AND settlement_id=?",
                            (scope, settlement_id)).fetchone():
                raise BudgetError("settlement identity already used by another attempt")
            source_col = "active" if attempt["state"] == "active" else "holds"
            reserved = attempt["reserved"]
            overbound = charge > reserved
            conn.execute("""UPDATE attempts SET state='settled',settlement_id=?,charge=?,
                         zero_charge_evidence=? WHERE scope=? AND attempt_id=?""",
                         (settlement_id, charge, zero_charge_evidence, scope, attempt_id))
            conn.execute(f"""UPDATE scopes SET {source_col}={source_col}-?,known=known+?,
                         frozen=CASE WHEN ? THEN 1 ELSE frozen END WHERE scope=?""",
                         (reserved, charge, int(overbound), scope))
            after = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
            self._audit(conn, scope, attempt_id, "settled_above_bound" if overbound else "settled", before, after)
            self._verify_scope(conn, after)
            return self._view(after)

    def verify(self, scope):
        """Replay audit deltas and compare them with current attempts and balances."""
        _text(scope, "scope")
        with self._transaction() as conn:
            row = self._scope(conn, scope)
            known = active = holds = frozen = 0
            events = conn.execute("SELECT * FROM audit_events WHERE scope=? ORDER BY event_id",
                                  (scope,)).fetchall()
            if not events or events[0]["event_type"] != "scope_created":
                raise BudgetError("missing scope creation audit event")
            for event in events:
                known += event["known_delta"]
                active += event["active_delta"]
                holds += event["holds_delta"]
                if (known, active, holds) != (event["known_after"], event["active_after"], event["holds_after"]):
                    raise BudgetError("audit delta chain mismatch")
                if min(known, active, holds) < 0 or event["frozen_after"] not in (0, 1) or event["frozen_after"] < frozen:
                    raise BudgetError("invalid audit balance or frozen transition")
                frozen = event["frozen_after"]
            if (known, active, holds, frozen) != (row["known"], row["active"], row["holds"], row["frozen"]):
                raise BudgetError("audit final balance mismatch")
            return {**self._view(row), "audit_events": len(events)}
