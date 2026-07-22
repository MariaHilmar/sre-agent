from sre_agent.memory import IncidentStore
from sre_agent.models import Incident


def test_record_and_recall_similar():
    store = IncidentStore(":memory:")
    store.record(Incident(service="sj-scraping", status="down", summary="503", root_cause="pool"))
    store.record(Incident(service="sj-fast-api", status="degraded", summary="db down"))
    store.record(Incident(service="sj-scraping", status="down", summary="timeout"))

    similar = store.similar("sj-scraping")
    assert len(similar) == 2
    assert all(i.service == "sj-scraping" for i in similar)

    recent = store.recent()
    assert len(recent) == 3
    assert recent[0].id is not None
    store.close()


def test_similar_empty_for_unknown_service():
    store = IncidentStore(":memory:")
    assert store.similar("inexistente") == []
    store.close()
