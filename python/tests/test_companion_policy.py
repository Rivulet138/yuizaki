from modules.system.companion_policy import (
    apply_behavior_modifiers,
    build_base_behavior_event,
)


def test_proactive_message_uses_one_social_prefix_when_many_signals_overlap():
    event = build_base_behavior_event(mood='warm', tick_count=4, warm_interval=4, gentle_interval=3)
    assert event is not None

    result = apply_behavior_modifiers(
        event,
        trace_layers=['profile'],
        recall_count=1,
        recent_kinds=['trust_shift', 'comfort_event'],
        relationship_summary={'relationship_stage': 'close', 'milestone_salience': 'high'},
        temperament='playful',
        attachment_style='attached',
        support_style='cheerful',
    )

    assert result is not None
    message = str(result['message'])
    prefixes = (
        '我记得你的偏好，', '最近我们之间更有默契了，', '我们已经很熟悉了，',
        '我记得我们之间那些重要时刻，', '我会更贴近地陪着你，', '我会更积极一点帮你推进，',
    )
    assert sum(message.startswith(prefix) for prefix in prefixes) == 1
    assert message.count('，') <= 2


def test_proactive_message_keeps_task_style_when_no_social_prefix_was_selected():
    event = build_base_behavior_event(mood='curious', tick_count=2, warm_interval=4, gentle_interval=3)
    assert event is not None
    result = apply_behavior_modifiers(
        event,
        trace_layers=[],
        recall_count=0,
        recent_kinds=[],
        relationship_summary={},
        temperament='reserved',
        attachment_style=None,
        support_style=None,
    )
    assert result is not None
    assert result['message'] == '你最近好像有些事情在推进，我可以帮你整理。'
    assert result['motion_group'] == 'Idle'
