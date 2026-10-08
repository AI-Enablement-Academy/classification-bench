"""Offline, per-scope SQLite money reservations; no provider or dispatch integration.

Amounts are integer monetary subunits. A scope must be explicitly created with
its authorization source. Bound evidence and zero-charge evidence are recorded,
but this module cannot authenticate provider pricing or user authorization.
"""

import os
import re
import sqlite3
import stat
import uuid
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
                CREATE TABLE IF NOT EXISTS aggregate_authority (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                    database_id TEXT NOT NULL, canonical_path TEXT NOT NULL,
                    device INTEGER NOT NULL, inode INTEGER NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS aggregate_authority_no_update BEFORE UPDATE ON aggregate_authority
                BEGIN SELECT RAISE(ABORT, 'aggregate authority is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS aggregate_authority_no_delete BEFORE DELETE ON aggregate_authority
                BEGIN SELECT RAISE(ABORT, 'aggregate authority is immutable'); END;
                CREATE TABLE IF NOT EXISTS aggregate_scopes (
                    scope TEXT PRIMARY KEY REFERENCES scopes(scope)
                );
                CREATE TRIGGER IF NOT EXISTS aggregate_scopes_no_update BEFORE UPDATE ON aggregate_scopes
                BEGIN SELECT RAISE(ABORT, 'aggregate scope identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS aggregate_scopes_no_delete BEFORE DELETE ON aggregate_scopes
                BEGIN SELECT RAISE(ABORT, 'aggregate scope identity is immutable'); END;
                CREATE TABLE IF NOT EXISTS aggregate_allocations (
                    allocation_id TEXT PRIMARY KEY,
                    parent_scope TEXT NOT NULL REFERENCES aggregate_scopes(scope),
                    child_scope TEXT NOT NULL UNIQUE REFERENCES scopes(scope),
                    run_sha256 TEXT NOT NULL UNIQUE,
                    phase TEXT CHECK(phase IN ('smoke','full')),
                    initial_cap INTEGER NOT NULL CHECK(initial_cap > 0),
                    allocated_cap INTEGER NOT NULL CHECK(allocated_cap >= initial_cap),
                    authorization_source TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS aggregate_allocations_binding_no_update BEFORE UPDATE ON aggregate_allocations
                WHEN NEW.allocation_id IS NOT OLD.allocation_id OR NEW.parent_scope IS NOT OLD.parent_scope
                  OR NEW.child_scope IS NOT OLD.child_scope OR NEW.run_sha256 IS NOT OLD.run_sha256
                  OR NEW.phase IS NOT OLD.phase OR NEW.initial_cap IS NOT OLD.initial_cap
                  OR NEW.authorization_source IS NOT OLD.authorization_source
                BEGIN SELECT RAISE(ABORT, 'allocation identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS aggregate_allocations_no_delete BEFORE DELETE ON aggregate_allocations
                BEGIN SELECT RAISE(ABORT, 'allocations are retained'); END;
                CREATE TABLE IF NOT EXISTS aggregate_allocation_events (
                    event_id INTEGER PRIMARY KEY REFERENCES cap_events(event_id),
                    allocation_id TEXT NOT NULL REFERENCES aggregate_allocations(allocation_id),
                    expected_cap INTEGER NOT NULL, new_cap INTEGER NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS aggregate_allocation_events_no_update BEFORE UPDATE ON aggregate_allocation_events
                BEGIN SELECT RAISE(ABORT, 'allocation events are immutable'); END;
                CREATE TRIGGER IF NOT EXISTS aggregate_allocation_events_no_delete BEFORE DELETE ON aggregate_allocation_events
                BEGIN SELECT RAISE(ABORT, 'allocation events are immutable'); END;
                CREATE TABLE IF NOT EXISTS aggregate_freezes (
                    parent_scope TEXT PRIMARY KEY REFERENCES aggregate_scopes(scope),
                    child_scope TEXT NOT NULL REFERENCES aggregate_allocations(child_scope),
                    attempt_id TEXT NOT NULL, settlement_id TEXT NOT NULL,
                    reserved INTEGER NOT NULL, charge INTEGER NOT NULL,
                    child_event_id INTEGER NOT NULL REFERENCES audit_events(event_id),
                    parent_event_id INTEGER NOT NULL REFERENCES audit_events(event_id)
                );
                CREATE TRIGGER IF NOT EXISTS aggregate_freezes_no_update BEFORE UPDATE ON aggregate_freezes
                BEGIN SELECT RAISE(ABORT, 'aggregate freeze evidence is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS aggregate_freezes_no_delete BEFORE DELETE ON aggregate_freezes
                BEGIN SELECT RAISE(ABORT, 'aggregate freeze evidence is immutable'); END;
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
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA busy_timeout=15000")
            self._check_authority(conn)
        except BaseException:
            conn.close()
            raise
        return conn

    def _check_authority(self, conn):
        """Copied aggregate databases cannot become additional authorities."""
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='aggregate_authority'").fetchone():
            return
        authority = conn.execute("SELECT * FROM aggregate_authority WHERE singleton=1").fetchone()
        if authority is None:
            return
        info = self.path.stat()
        if (authority["canonical_path"], authority["device"], authority["inode"]) != (
                str(self.path.resolve()), info.st_dev, info.st_ino):
            raise BudgetError("aggregate authority database identity does not match this file")

    def _bind_authority(self, conn):
        self._check_authority(conn)
        if conn.execute("SELECT 1 FROM aggregate_authority WHERE singleton=1").fetchone() is None:
            info = self.path.stat()
            conn.execute("INSERT INTO aggregate_authority VALUES(1,?,?,?,?)",
                         (str(uuid.uuid4()), str(self.path.resolve()), info.st_dev, info.st_ino))

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
        self._check_authority(conn)
        row = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        if row is None:
            raise BudgetError(f"unknown authorization scope: {scope}")
        self._verify_scope(conn, row)
        allocation = self._allocation(conn, scope)
        if allocation is not None:
            self._verify_allocation(conn, allocation, row)
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
            row = self._create_scope_in(conn, scope, cap, currency, scale, authorization_source)
            return self._balance_view_in(conn, row)

    def _create_scope_in(self, conn, scope, cap, currency, scale, authorization_source):
        old = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        if old is not None:
            self._scope(conn, scope)
            original_cap = self._verify_cap_chain(conn, old)
            if (original_cap, old["currency"], old["scale"], old["authorization_source"]) != (
                    cap, currency, scale, authorization_source):
                raise BudgetError("authorization scope already exists with different terms")
            return old
        conn.execute("""INSERT INTO scopes(scope,cap,currency,scale,authorization_source)
                     VALUES (?,?,?,?,?)""", (scope, cap, currency, scale, authorization_source))
        row = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        event_id = self._audit(conn, scope, None, "scope_created", row, row)
        conn.execute("""INSERT INTO cap_events
                     (event_id,scope,amendment_id,expected_cap,new_cap,authorization_source)
                     VALUES (?,?,NULL,?,?,?)""", (event_id, scope, cap, cap, authorization_source))
        return row

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
            if self._allocation(conn, scope) is not None:
                raise BudgetError("managed child cap requires increase_allocation")
            after, _ = self._increase_cap_in(conn, scope, amendment_id, expected_cap,
                                              new_cap, authorization_source)
            return self._balance_view_in(conn, after)

    def _increase_cap_in(self, conn, scope, amendment_id, expected_cap, new_cap, authorization_source):
        before = self._scope(conn, scope)
        existing = conn.execute("SELECT * FROM cap_events WHERE scope=? AND amendment_id=?",
                                (scope, amendment_id)).fetchone()
        if existing is not None:
            if (existing["expected_cap"], existing["new_cap"], existing["authorization_source"]) != (
                    expected_cap, new_cap, authorization_source):
                raise BudgetError("conflicting cap amendment identity")
            return before, existing["event_id"]
        if before["cap"] != expected_cap:
            raise BudgetError("scope cap changed since expected value")
        conn.execute("UPDATE scopes SET cap=? WHERE scope=?", (new_cap, scope))
        after = conn.execute("SELECT * FROM scopes WHERE scope=?", (scope,)).fetchone()
        event_id = self._audit(conn, scope, None, "cap_increased", before, after)
        conn.execute("""INSERT INTO cap_events
                     (event_id,scope,amendment_id,expected_cap,new_cap,authorization_source)
                     VALUES (?,?,?,?,?,?)""",
                     (event_id, scope, amendment_id, expected_cap, new_cap, authorization_source))
        self._verify_scope(conn, after)
        return after, event_id

    def balances(self, scope):
        _text(scope, "scope")
        with self._transaction() as conn:
            return self._balance_view_in(conn, self._scope(conn, scope))

    @staticmethod
    def _allocation(conn, child_scope):
        return conn.execute("SELECT * FROM aggregate_allocations WHERE child_scope=?",
                            (child_scope,)).fetchone()

    @staticmethod
    def _execution_block_in(conn, scope):
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_admission_blocks'").fetchone():
            return None
        row = conn.execute("SELECT * FROM execution_admission_blocks WHERE scope=?", (scope,)).fetchone()
        return dict(row) if row is not None else None

    def _verify_allocation(self, conn, allocation, child):
        parent = conn.execute("SELECT s.* FROM scopes s JOIN aggregate_scopes a ON a.scope=s.scope WHERE s.scope=?",
                              (allocation["parent_scope"],)).fetchone()
        if parent is None or (parent["currency"], parent["scale"]) != (child["currency"], child["scale"]):
            raise BudgetError("allocation accounting units disagree with parent")
        self._verify_scope(conn, parent)
        events = conn.execute("""SELECT a.*, c.scope, c.amendment_id, c.authorization_source,
                              c.expected_cap AS child_expected, c.new_cap AS child_new
                              FROM aggregate_allocation_events a JOIN cap_events c ON c.event_id=a.event_id
                              WHERE a.allocation_id=? ORDER BY a.event_id""",
                              (allocation["allocation_id"],)).fetchall()
        cap_ids = [row[0] for row in conn.execute("SELECT event_id FROM cap_events WHERE scope=? ORDER BY event_id",
                                                 (child["scope"],)).fetchall()]
        if not events or [event["event_id"] for event in events] != cap_ids:
            raise BudgetError("allocation cap audit chain mismatch")
        cap = allocation["initial_cap"]
        for index, event in enumerate(events):
            if (event["scope"] != child["scope"] or event["expected_cap"] != cap or
                    (event["expected_cap"], event["new_cap"]) != (event["child_expected"], event["child_new"])):
                raise BudgetError("allocation cap audit chain mismatch")
            if index == 0 and (event["new_cap"] != cap or event["amendment_id"] is not None or
                              event["authorization_source"] != allocation["authorization_source"]):
                raise BudgetError("initial allocation audit mismatch")
            if index and event["new_cap"] <= cap:
                raise BudgetError("allocation cap audit must increase monotonically")
            cap = event["new_cap"]
        if cap != allocation["allocated_cap"] or cap != child["cap"]:
            raise BudgetError("allocation projection disagrees with cap audit")

    def _aggregate_parent_in(self, conn, parent_scope):
        if not conn.execute("SELECT 1 FROM aggregate_scopes WHERE scope=?", (parent_scope,)).fetchone():
            raise BudgetError("scope is not an aggregate parent")
        parent = self._scope(conn, parent_scope)
        if any(parent[key] for key in ("known", "active", "holds")):
            raise BudgetError("aggregate parent cannot own direct attempts")
        allocations = conn.execute("SELECT * FROM aggregate_allocations WHERE parent_scope=? ORDER BY child_scope",
                                   (parent_scope,)).fetchall()
        children = [self._scope(conn, allocation["child_scope"]) for allocation in allocations]
        if sum(allocation["allocated_cap"] for allocation in allocations) > parent["cap"]:
            raise BudgetError("allocated child caps exceed aggregate cap")
        freeze = conn.execute("SELECT * FROM aggregate_freezes WHERE parent_scope=?", (parent_scope,)).fetchone()
        if bool(parent["frozen"]) != (freeze is not None) or any(child["frozen"] for child in children) and not parent["frozen"]:
            raise BudgetError("aggregate freeze disagrees with child/audit evidence")
        if freeze is not None:
            attempt = conn.execute("SELECT * FROM attempts WHERE scope=? AND attempt_id=?",
                                   (freeze["child_scope"], freeze["attempt_id"])).fetchone()
            child_event = conn.execute("SELECT * FROM audit_events WHERE event_id=?", (freeze["child_event_id"],)).fetchone()
            parent_event = conn.execute("SELECT * FROM audit_events WHERE event_id=?", (freeze["parent_event_id"],)).fetchone()
            binding = self._allocation(conn, freeze["child_scope"])
            if (attempt is None or binding is None or binding["parent_scope"] != parent_scope or
                    attempt["state"] != "settled" or
                    (attempt["settlement_id"], attempt["reserved"], attempt["charge"]) !=
                    (freeze["settlement_id"], freeze["reserved"], freeze["charge"]) or
                    freeze["charge"] <= freeze["reserved"] or child_event is None or parent_event is None or
                    (child_event["scope"], child_event["attempt_id"], child_event["event_type"]) !=
                    (freeze["child_scope"], freeze["attempt_id"], "settled_above_bound") or
                    (parent_event["scope"], parent_event["event_type"], parent_event["frozen_after"]) !=
                    (parent_scope, "child_settled_above_bound", 1)):
                raise BudgetError("aggregate freeze evidence mismatch")
        return parent, allocations, children, freeze

    def _leaf_view_in(self, conn, row):
        result = self._view(row)
        allocation = self._allocation(conn, row["scope"])
        if allocation is not None:
            parent = self._scope(conn, allocation["parent_scope"])
            parent_block = self._execution_block_in(conn, allocation["parent_scope"])
            result.update(allocation=dict(allocation), scope_frozen=result["frozen"],
                          scope_remaining=result["remaining"], aggregate_frozen=bool(parent["frozen"]),
                          aggregate_admission_block=parent_block)
            result["frozen"] = result["scope_frozen"] or result["aggregate_frozen"] or parent_block is not None
            if result["frozen"]:
                result["remaining"] = min(0, result["remaining"])
        return result

    def _aggregate_view_in(self, conn, parent_scope):
        parent, allocations, children, freeze = self._aggregate_parent_in(conn, parent_scope)
        result = self._view(parent)
        totals = {key: sum(child[key] for child in children) for key in ("known", "active", "holds")}
        allocated = sum(allocation["allocated_cap"] for allocation in allocations)
        exposure = sum(max(allocation["allocated_cap"], child["known"] + child["active"] + child["holds"])
                       for allocation, child in zip(allocations, children))
        parent_block = self._execution_block_in(conn, parent_scope)
        result.update(known_charges=totals["known"], active_reservations=totals["active"],
                      unknown_holds=totals["holds"], allocated_cap=allocated,
                      accounted_exposure=exposure, unallocated=parent["cap"] - allocated,
                      remaining=parent["cap"] - exposure, over_cap=exposure > parent["cap"],
                      children=[self._leaf_view_in(conn, child) for child in children],
                      freeze=dict(freeze) if freeze is not None else None,
                      scope_frozen=bool(parent["frozen"]), scope_remaining=parent["cap"] - exposure,
                      admission_block=parent_block, frozen=bool(parent["frozen"]) or parent_block is not None,
                      authority_database_id=conn.execute("SELECT database_id FROM aggregate_authority WHERE singleton=1").fetchone()[0])
        if result["frozen"]:
            result["remaining"] = min(0, result["remaining"])
        return result

    def _balance_view_in(self, conn, row):
        if conn.execute("SELECT 1 FROM aggregate_scopes WHERE scope=?", (row["scope"],)).fetchone():
            return self._aggregate_view_in(conn, row["scope"])
        return self._leaf_view_in(conn, row)

    def create_aggregate(self, scope, cap, currency, scale, authorization_source):
        """Declare a parent cap; old independent scopes are never adopted implicitly."""
        _text(scope, "scope")
        _money(cap, "cap", positive=True)
        _money(scale, "scale", positive=True)
        _text(authorization_source, "authorization_source")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise BudgetError("currency must be a three-letter uppercase code")
        with self._transaction() as conn:
            existing = conn.execute("SELECT 1 FROM scopes WHERE scope=?", (scope,)).fetchone()
            if existing and not conn.execute("SELECT 1 FROM aggregate_scopes WHERE scope=?", (scope,)).fetchone():
                raise BudgetError("existing scope cannot become an aggregate parent")
            self._bind_authority(conn)
            self._create_scope_in(conn, scope, cap, currency, scale, authorization_source)
            conn.execute("INSERT OR IGNORE INTO aggregate_scopes(scope) VALUES(?)", (scope,))
            return self._aggregate_view_in(conn, scope)

    def allocate_child(self, parent_scope, child_scope, allocation_id, cap, run_sha256,
                       authorization_source, *, phase=None, currency=None, scale=None):
        """Reserve the whole child cap atomically and bind one frozen child run."""
        for value, name in ((parent_scope, "parent_scope"), (child_scope, "child_scope"),
                            (allocation_id, "allocation_id"), (authorization_source, "authorization_source")):
            _text(value, name)
        _money(cap, "cap", positive=True)
        if not isinstance(run_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", run_sha256):
            raise BudgetError("run_sha256 must be a lowercase SHA-256 digest")
        if phase is not None and phase not in ("smoke", "full"):
            raise BudgetError("phase must be smoke, full or unavailable")
        with self._transaction() as conn:
            parent, allocations, _, _ = self._aggregate_parent_in(conn, parent_scope)
            if ((currency is not None and currency != parent["currency"]) or
                    (scale is not None and (type(scale) is not int or scale != parent["scale"]))):
                raise BudgetError("child accounting units must match aggregate parent")
            existing = self._allocation(conn, child_scope)
            if existing is not None:
                if (existing["parent_scope"], existing["allocation_id"], existing["initial_cap"],
                    existing["run_sha256"], existing["authorization_source"], existing["phase"]) != (
                        parent_scope, allocation_id, cap, run_sha256, authorization_source, phase):
                    raise BudgetError("managed child allocation already exists with different terms")
                return self._leaf_view_in(conn, self._scope(conn, child_scope))
            if conn.execute("SELECT 1 FROM aggregate_allocations WHERE allocation_id=?", (allocation_id,)).fetchone():
                raise BudgetError("allocation identity already belongs to another child")
            if conn.execute("SELECT 1 FROM aggregate_allocations WHERE run_sha256=?", (run_sha256,)).fetchone():
                raise BudgetError("run identity already belongs to another child")
            if conn.execute("SELECT 1 FROM scopes WHERE scope=?", (child_scope,)).fetchone():
                raise BudgetError("existing scope cannot be attached as a managed child")
            self._require_aggregate_admission_in(conn, parent)
            if sum(allocation["allocated_cap"] for allocation in allocations) + cap > parent["cap"]:
                raise BudgetError("allocation would exceed aggregate cap")
            child = self._create_scope_in(conn, child_scope, cap, parent["currency"], parent["scale"], authorization_source)
            conn.execute("INSERT INTO aggregate_allocations VALUES(?,?,?,?,?,?,?,?)",
                         (allocation_id, parent_scope, child_scope, run_sha256, phase, cap, cap, authorization_source))
            event_id = conn.execute("SELECT event_id FROM cap_events WHERE scope=? ORDER BY event_id LIMIT 1",
                                    (child_scope,)).fetchone()[0]
            conn.execute("INSERT INTO aggregate_allocation_events VALUES(?,?,?,?)", (event_id, allocation_id, cap, cap))
            return self._leaf_view_in(conn, self._scope(conn, child["scope"]))

    def increase_allocation(self, child_scope, amendment_id, expected_cap, new_cap, authorization_source):
        """Increase managed child cap and allocated parent exposure in one commit."""
        for value, name in ((child_scope, "child_scope"), (amendment_id, "amendment_id"),
                            (authorization_source, "authorization_source")):
            _text(value, name)
        _money(expected_cap, "expected_cap", positive=True)
        _money(new_cap, "new_cap", positive=True)
        if new_cap <= expected_cap:
            raise BudgetError("new cap must exceed expected cap")
        with self._transaction() as conn:
            allocation = self._allocation(conn, child_scope)
            if allocation is None:
                raise BudgetError("scope is not a managed child")
            parent, allocations, _, _ = self._aggregate_parent_in(conn, allocation["parent_scope"])
            old_event = conn.execute("SELECT * FROM cap_events WHERE scope=? AND amendment_id=?",
                                     (child_scope, amendment_id)).fetchone()
            if old_event is not None:
                if (old_event["expected_cap"], old_event["new_cap"], old_event["authorization_source"]) != (
                        expected_cap, new_cap, authorization_source):
                    raise BudgetError("conflicting cap amendment identity")
                return self._leaf_view_in(conn, self._scope(conn, child_scope))
            if allocation["allocated_cap"] != expected_cap:
                raise BudgetError("scope cap changed since expected value")
            self._require_aggregate_admission_in(conn, parent)
            if sum(item["allocated_cap"] for item in allocations) + new_cap - expected_cap > parent["cap"]:
                raise BudgetError("allocation increase would exceed aggregate cap")
            child, event_id = self._increase_cap_in(conn, child_scope, amendment_id,
                                                    expected_cap, new_cap, authorization_source)
            conn.execute("UPDATE aggregate_allocations SET allocated_cap=? WHERE child_scope=?", (new_cap, child_scope))
            conn.execute("INSERT INTO aggregate_allocation_events VALUES(?,?,?,?)",
                         (event_id, allocation["allocation_id"], expected_cap, new_cap))
            return self._leaf_view_in(conn, self._scope(conn, child["scope"]))

    def allocation_for(self, child_scope):
        _text(child_scope, "child_scope")
        with self._transaction() as conn:
            allocation = self._allocation(conn, child_scope)
            if allocation is not None:
                self._aggregate_parent_in(conn, allocation["parent_scope"])
            return dict(allocation) if allocation is not None else None

    def aggregate_balances(self, parent_scope):
        _text(parent_scope, "parent_scope")
        with self._transaction() as conn:
            return self._aggregate_view_in(conn, parent_scope)

    def verify_aggregate(self, parent_scope):
        _text(parent_scope, "parent_scope")
        with self._transaction() as conn:
            result = self._aggregate_view_in(conn, parent_scope)
            scopes = [parent_scope] + [child["scope"] for child in result["children"]]
            result["audit_events"] = sum(self._verify_audit_in(conn, self._scope(conn, scope)) for scope in scopes)
            result["allocation_events"] = conn.execute("""SELECT COUNT(*) FROM aggregate_allocation_events e
                JOIN aggregate_allocations a ON a.allocation_id=e.allocation_id WHERE a.parent_scope=?""",
                (parent_scope,)).fetchone()[0]
            return result

    def _check_aggregate_reservation_in(self, conn, scope):
        if conn.execute("SELECT 1 FROM aggregate_scopes WHERE scope=?", (scope,)).fetchone():
            raise BudgetError("aggregate parent cannot reserve attempts; use a managed child")
        allocation = self._allocation(conn, scope)
        if allocation is not None:
            parent, _, _, _ = self._aggregate_parent_in(conn, allocation["parent_scope"])
            self._require_aggregate_admission_in(conn, parent)

    def _require_aggregate_admission_in(self, conn, parent):
        if parent["frozen"]:
            raise BudgetError("aggregate parent is frozen after an above-bound child charge")
        block = self._execution_block_in(conn, parent["scope"])
        if block is not None:
            raise BudgetError(f"aggregate parent admission blocked: {block['reason']} (evidence {block['evidence_id']})")

    def _freeze_aggregate_in(self, conn, scope, attempt_id, settlement_id, reserved, charge, child_event_id):
        allocation = self._allocation(conn, scope)
        if allocation is None:
            return
        parent_scope = allocation["parent_scope"]
        parent = self._scope(conn, parent_scope)
        if parent["frozen"]:
            return
        conn.execute("UPDATE scopes SET frozen=1 WHERE scope=?", (parent_scope,))
        after = conn.execute("SELECT * FROM scopes WHERE scope=?", (parent_scope,)).fetchone()
        parent_event_id = self._audit(conn, parent_scope, attempt_id, "child_settled_above_bound", parent, after)
        conn.execute("INSERT INTO aggregate_freezes VALUES(?,?,?,?,?,?,?,?)",
                     (parent_scope, scope, attempt_id, settlement_id, reserved, charge, child_event_id, parent_event_id))

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
            self._check_aggregate_reservation_in(conn, scope)
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
            return self._leaf_view_in(conn, after)

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
            return self._leaf_view_in(conn, after)

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
            allocation = self._allocation(conn, scope)
            if allocation is not None:
                self._aggregate_parent_in(conn, allocation["parent_scope"])
            attempt = conn.execute("SELECT * FROM attempts WHERE scope=? AND attempt_id=?",
                                   (scope, attempt_id)).fetchone()
            if attempt is None:
                raise BudgetError("attempt was never reserved")
            if attempt["state"] == "settled":
                if (attempt["settlement_id"], attempt["charge"], attempt["zero_charge_evidence"]) == (
                        settlement_id, charge, zero_charge_evidence):
                    return self._leaf_view_in(conn, before)
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
            event_id = self._audit(conn, scope, attempt_id, "settled_above_bound" if overbound else "settled", before, after)
            if overbound:
                self._freeze_aggregate_in(conn, scope, attempt_id, settlement_id, reserved, charge, event_id)
            self._verify_scope(conn, after)
            return self._leaf_view_in(conn, after)

    def verify(self, scope):
        """Replay audit deltas and compare them with current attempts and balances."""
        _text(scope, "scope")
        with self._transaction() as conn:
            row = self._scope(conn, scope)
            return {**self._balance_view_in(conn, row), "audit_events": self._verify_audit_in(conn, row)}

    @staticmethod
    def _verify_audit_in(conn, row):
        known = active = holds = frozen = 0
        events = conn.execute("SELECT * FROM audit_events WHERE scope=? ORDER BY event_id", (row["scope"],)).fetchall()
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
        return len(events)
