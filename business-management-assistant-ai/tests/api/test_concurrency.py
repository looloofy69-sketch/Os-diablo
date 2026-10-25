"""Races the design claims to handle. Uses a file database (SQLite WAL) or TEST_DATABASE_URL (PostgreSQL)."""

import os
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.domain.models import ActionProposal, ApprovalDecision, GoalCreate
from app.errors import Conflict
from app.main import create_app
from app.security import Principal, Role
from app.services import approvals, records
from app.services.audit import verify_database_chain
from app.services.context import Ctx
from app.services.context import Ctx
from tests.api.conftest import make_settings

THREADS = 8


def database_url(tmp_path):
    return os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'race.db'}"


def ctx(name="root", role=Role.admin):
    return Ctx(Principal(name, role))


def run_all(fn, count=THREADS):
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(lambda i: fn(i), range(count)))


def test_exactly_one_reviewer_wins_a_decision_race(tmp_path):
    settings = make_settings(database_url=database_url(tmp_path))
    with TestClient(create_app(settings)) as client:
        engine, registry = client.app.state.engine, client.app.state.connectors
        with Session(engine, expire_on_commit=False) as s:
            item, _, _ = approvals.propose(s, ActionProposal(action_type="message.send", target="a@b.io", reason="r"), ctx("ops", Role.operator), client.app.state.policy, settings)

        def decide(i):
            with Session(engine, expire_on_commit=False) as s:
                try:
                    return approvals.decide(s, item.id, ApprovalDecision(decision="approved"), ctx(f"admin{i}"), settings, registry).reviewed_by
                except Conflict:
                    return None

        winners = [w for w in run_all(decide) if w]
        assert len(winners) == 1
        with Session(engine) as s:
            assert s.get(type(item), item.id).reviewed_by == winners[0]
            assert verify_database_chain(s).ok


def test_concurrent_execute_runs_the_connector_once(tmp_path):
    settings = make_settings(database_url=database_url(tmp_path))
    with TestClient(create_app(settings)) as client:
        engine, registry = client.app.state.engine, client.app.state.connectors
        with Session(engine, expire_on_commit=False) as s:
            item, _, _ = approvals.propose(s, ActionProposal(action_type="message.send", target="a@b.io", reason="r"), ctx("ops", Role.operator), client.app.state.policy, settings)
            approvals.decide(s, item.id, ApprovalDecision(decision="approved"), ctx("root"), settings, registry)

        def execute(i):
            with Session(engine, expire_on_commit=False) as s:
                try:
                    return approvals.execute(s, item.id, ctx(f"admin{i}"), registry).status
                except Conflict:
                    return "conflict"

        outcomes = run_all(execute)
        assert "executed" in outcomes
        with Session(engine) as s:
            events = [e for e in client.get("/api/audit", params={"target": item.id, "event_type": "action.executing"}).json()]
            assert len(events) == 1  # only one thread won the claim
            assert verify_database_chain(s).ok


def test_audit_chain_stays_linear_under_concurrent_writers(tmp_path):
    settings = make_settings(database_url=database_url(tmp_path))
    with TestClient(create_app(settings)) as client:
        engine = client.app.state.engine

        def create(i):
            with Session(engine, expire_on_commit=False) as s:
                return records.create_goal(s, GoalCreate(title=f"goal {i}"), ctx(f"writer{i}")).id

        ids = run_all(create, count=THREADS)
        assert len(set(ids)) == THREADS
        with Session(engine) as s:
            result = verify_database_chain(s)
            assert result.ok and result.checked >= THREADS
