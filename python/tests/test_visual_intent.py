from modules.agent.pipeline import (
    classify_visual_context_request,
    visual_context_requested,
)
from modules.agent.visual_intent import query_matches_partial


def test_explicit_visual_requests_are_accepted_without_confirmation() -> None:
    chinese = classify_visual_context_request("请描述一下当前屏幕上有什么")
    english = classify_visual_context_request("what is currently on my screen?")

    assert chinese.requested is True
    assert chinese.confirmation_required is False
    assert english.requested is True
    assert english.confirmation_required is False
    assert visual_context_requested("看看这个") is False


def test_ambiguous_deictic_requests_remain_non_capturing() -> None:
    decision = classify_visual_context_request("你看到这个了吗")

    assert decision.requested is False
    assert decision.confirmation_required is True
    assert decision.reason.startswith("ambiguous_deictic_request:")


def test_partial_query_matching_is_normalized_and_bounded() -> None:
    assert query_matches_partial("  look at this  ", "Look at this screen") is True
    assert query_matches_partial("screen", "open a screen") is False
    assert query_matches_partial("", "screen") is False
