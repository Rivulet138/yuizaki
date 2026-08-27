from modules.memory.relation_projection import build_relation_projection
from modules.memory.vector_store import Document


def test_relation_projection_rebuilds_explicit_edges_and_time_bounded_event_adjacency():
    documents = [
        Document(
            id="answer",
            text="answer",
            metadata={"source_ids": ["evidence"], "source_id": "conversation", "occurred_at": "2026-08-26T10:00:00Z"},
        ),
        Document(
            id="evidence",
            text="evidence",
            metadata={"source_id": "conversation", "occurred_at": "2026-08-26T11:00:00Z"},
        ),
        Document(
            id="late-event",
            text="late",
            metadata={"source_id": "conversation", "occurred_at": "2026-08-28T12:00:00Z"},
        ),
    ]

    projection = build_relation_projection(documents, event_window_seconds=24 * 60 * 60)
    answer_edges = projection.neighbors("answer")
    assert {(edge.target_id, edge.relation, edge.evidence_type) for edge in answer_edges} == {
        ("evidence", "source", "source"),
        ("evidence", "event_adjacent", "source_id"),
    }
    assert {(edge.target_id, edge.relation) for edge in projection.neighbors("evidence")} == {
        ("answer", "event_adjacent"),
    }
    assert projection.neighbors("late-event") == []


def test_relation_projection_is_rebuilt_from_current_authority_snapshot():
    first = Document(id="first", text="first", metadata={"source_ids": ["second"]})
    second = Document(id="second", text="second", metadata={})
    initial = build_relation_projection([first, second])
    rebuilt = build_relation_projection([Document(id="first", text="first", metadata={}), second])

    assert [edge.target_id for edge in initial.neighbors("first")] == ["second"]
    assert rebuilt.neighbors("first") == []
