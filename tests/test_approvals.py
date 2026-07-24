from sre_agent.approvals import ActionStore
from sre_agent.models import Action, ActionStatus


def _store() -> ActionStore:
    return ActionStore(":memory:")


def test_propose_appears_as_pending():
    store = _store()
    a = store.propose(Action(service="sj-fast-api", kind="rollback", description="reverter #142"))
    assert a.id is not None
    assert a.status is ActionStatus.PENDING

    pending = store.pending()
    assert len(pending) == 1
    assert pending[0].service == "sj-fast-api"
    store.close()


def test_approve_removes_from_pending():
    store = _store()
    a = store.propose(Action(service="svc", kind="restart", description="reiniciar"))
    decided = store.approve(a.id)

    assert decided.status is ActionStatus.APPROVED
    assert decided.decided_at is not None
    assert store.pending() == []
    store.close()


def test_reject_sets_status_and_clears_pending():
    store = _store()
    a = store.propose(Action(service="svc", kind="rollback", description="x"))
    decided = store.reject(a.id)

    assert decided.status is ActionStatus.REJECTED
    assert store.pending() == []
    store.close()


def test_cannot_decide_twice():
    store = _store()
    a = store.propose(Action(service="svc", kind="rollback", description="x"))
    store.approve(a.id)
    # segunda decisão não deve valer (já não está pendente)
    assert store.reject(a.id) is None
    store.close()


def test_decide_unknown_action_returns_none():
    store = _store()
    assert store.approve(999) is None
    store.close()
