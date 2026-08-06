import json
import importlib

pet_control_parser = importlib.import_module("modules.pet_control.parser")
build_pet_control_prompt = pet_control_parser.build_pet_control_prompt
build_pet_control_response_format = pet_control_parser.build_pet_control_response_format
extract_pet_control_payload = pet_control_parser.extract_pet_control_payload
filter_pet_control_payload = pet_control_parser.filter_pet_control_payload
IncrementalJsonReplyDecoder = pet_control_parser.IncrementalJsonReplyDecoder


def test_build_pet_control_prompt_requires_complete_action_from_whitelist():
    prompt = build_pet_control_prompt({
        "models": [{"id": "llm-live2d/yumi", "type": "live2d"}],
        "emotions": ["happy", "sad"],
        "motionGroups": ["Idle", "Tap"],
        "motionOptions": [{"group": "Tap", "index": 0}],
        "expressions": ["smile"],
        "parameters": [{"id": "ParamMouthOpenY", "min": 0, "max": 1}],
    })

    assert "Yuizaki 本地桌宠 AI" in prompt
    assert "emotion_id、motion_group、motion_index、intensity、duration_ms 是必填字段" in prompt
    assert "禁止只输出 intensity" in prompt
    assert '"emotion_ids":["happy","sad"]' in prompt
    assert '"motion_options":["Tap:0"]' in prompt
    assert "错误示例" in prompt


def test_build_pet_control_prompt_keeps_core_contract_when_avatar_prompt_exists():
    prompt = build_pet_control_prompt({
        "emotions": ["happy"],
        "motionGroups": ["Tap"],
        "motionOptions": [{"group": "Tap", "index": 0}],
        "expressions": ["smile"],
        "parameters": [],
        "avatarPrompt": "[CURRENT_AVATAR]\nOnly use expressionMix.",
    })

    assert "固定顶层格式" in prompt
    assert '"emotion_ids":["happy"]' in prompt
    assert "[AVATAR_MANIFEST_DATA source=avatar_manifest trust=untrusted authority=data]" in prompt
    assert "Only use expressionMix." in prompt


def test_build_pet_control_response_format_uses_strict_json_schema():
    response_format = build_pet_control_response_format({
        "emotions": ["happy"],
        "motionGroups": ["Tap"],
        "motionOptions": [{"group": "Tap", "index": 0}],
        "expressions": ["smile"],
        "parameters": [{"id": "ParamMouthOpenY", "min": 0, "max": 1}],
    })

    assert response_format["type"] == "json_schema"
    json_schema = response_format["json_schema"]
    assert json_schema["strict"] is True
    schema = json_schema["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["reply", "pet_control"]
    pet_control_schema = schema["properties"]["pet_control"]["anyOf"][0]
    assert pet_control_schema["additionalProperties"] is False
    assert "emotion_id" in pet_control_schema["required"]
    assert pet_control_schema["properties"]["emotion_id"]["enum"] == ["happy", None]
    assert pet_control_schema["properties"]["motion_group"]["enum"] == ["Tap", None]
    assert pet_control_schema["properties"]["expression_mix"]["items"]["additionalProperties"] is False


def test_extract_pet_control_payload_normalizes_motion_index_and_parameters():
    reply, pet_control = extract_pet_control_payload(json.dumps({
        "reply": "我来眨眨眼。",
        "pet_control": {
            "motion_group": "TapBody",
            "motion_index": "2",
            "expression_mix": [
                {"expression": "smile", "weight": 1.5},
                {"expression": "blink"},
            ],
            "parameter_overrides": [
                {"id": "ParamMouthOpenY", "value": "0.8", "weight": "0.7"},
            ],
            "sentence_emotions": [
                {
                    "sentence_index": "1",
                    "offset_ms": "900",
                    "emotion_id": "happy",
                    "expression_name": "smile",
                    "duration_ms": "1200",
                }
            ],
        },
    }))

    assert reply == "我来眨眨眼。"
    assert pet_control == {
        "motion_group": "TapBody",
        "motion_index": 2,
        "expression_mix": [
            {"expression": "smile", "weight": 1.0},
            {"expression": "blink", "weight": 1.0},
        ],
        "parameter_overrides": [
            {"id": "ParamMouthOpenY", "value": 0.8, "weight": 0.7},
        ],
        "sentence_emotions": [
            {
                "sentence_index": 1,
                "offset_ms": 900,
                "emotion_id": "happy",
                "expression_name": "smile",
                "duration_ms": 1200,
            }
        ],
    }


def test_extract_pet_control_payload_keeps_empty_structured_reply_empty():
    reply, pet_control = extract_pet_control_payload(json.dumps({
        "reply": "",
        "pet_control": {
            "emotion_id": "happy",
            "motion_group": "Tap",
            "motion_index": 0,
        },
    }))

    assert reply == ""
    assert pet_control is not None
    assert pet_control["emotion_id"] == "happy"


def test_filter_pet_control_payload_enforces_motion_and_parameter_whitelists():
    filtered = filter_pet_control_payload(
        {
            "emotion_id": "happy",
            "motion_group": "TapBody",
            "motion_index": 99,
            "expression_name": "smile",
            "expression_mix": [
                {"expression": "smile", "weight": 0.8},
                {"expression": "unknown", "weight": 1.0},
            ],
            "parameter_overrides": [
                {"id": "ParamMouthOpenY", "value": 9.0, "weight": 2.0},
                {"id": "ParamUnsafe", "value": 1.0},
            ],
            "sentence_emotions": [
                {
                    "sentence_index": 0,
                    "emotion_id": "happy",
                    "motion_group": "TapBody",
                    "motion_index": 99,
                    "expression_name": "smile",
                    "expression_mix": [{"expression": "unknown", "weight": 1.0}],
                    "parameter_overrides": [{"id": "ParamMouthOpenY", "value": 9.0}],
                },
                {"emotion_id": "unknown", "expression_name": "unknown"},
            ],
        },
        {
            "emotions": ["happy"],
            "motionGroups": ["TapBody"],
            "motionOptions": [{"group": "TapBody", "index": 1}],
            "expressions": ["smile"],
            "parameters": [{"id": "ParamMouthOpenY", "min": 0.0, "max": 1.0}],
        },
    )

    assert filtered == {
        "emotion_id": "happy",
        "motion_group": "TapBody",
        "motion_index": 1,
        "expression_name": "smile",
        "intensity": 0.55,
        "duration_ms": 1800,
        "expression_mix": [{"expression": "smile", "weight": 0.8}],
        "parameter_overrides": [{"id": "ParamMouthOpenY", "value": 1.0, "weight": 1.0}],
        "sentence_emotions": [
            {
                "sentence_index": 0,
                "emotion_id": "happy",
                "motion_group": "TapBody",
                "motion_index": 1,
                "expression_name": "smile",
                "parameter_overrides": [{"id": "ParamMouthOpenY", "value": 1.0, "weight": 1.0}],
            }
        ],
    }


def test_filter_pet_control_payload_fills_default_action_when_model_returns_only_intensity():
    filtered = filter_pet_control_payload(
        {"intensity": 0.4},
        {
            "emotions": ["happy", "angry", "sad", "surprised", "shy", "playful"],
            "motionGroups": ["Idle", "Tap", "Flick"],
            "motionOptions": [
                {"group": "Idle", "index": 0},
                {"group": "Tap", "index": 0},
                {"group": "Tap", "index": 1},
            ],
            "expressions": ["smile"],
            "parameters": [],
        },
    )

    assert filtered == {
        "intensity": 0.4,
        "duration_ms": 1800,
        "emotion_id": "happy",
        "motion_group": "Tap",
        "motion_index": 0,
    }


def test_filter_pet_control_payload_completes_expression_only_action_contract():
    filtered = filter_pet_control_payload(
        {"expression_name": "smile"},
        {
            "emotions": ["happy"],
            "motionGroups": ["Tap"],
            "motionOptions": [{"group": "Tap", "index": 0}],
            "expressions": ["smile"],
            "parameters": [],
        },
    )

    assert filtered == {
        "expression_name": "smile",
        "emotion_id": "happy",
        "motion_group": "Tap",
        "motion_index": 0,
        "intensity": 0.55,
        "duration_ms": 1800,
    }


def test_extract_and_filter_pet_control_payload_ignores_removed_directive_fields():
    _reply, pet_control = extract_pet_control_payload(json.dumps({
        "reply": "ok",
        "pet_control": {
            "expressionMix": [{"expression": "smile", "weight": "0.8"}],
            "parameterOverrides": [{"id": "ParamMouthOpenY", "value": "0.7"}],
            "motion": {"group": "Tap", "index": "1"},
            "durationMs": "1200",
            "intensity": "0.6",
        },
    }))

    filtered = filter_pet_control_payload(
        pet_control,
        {
            "emotions": ["happy"],
            "motionGroups": ["Tap"],
            "motionOptions": [{"group": "Tap", "index": 1}],
            "expressions": ["smile"],
            "parameters": [{"id": "ParamMouthOpenY", "min": 0.0, "max": 1.0}],
        },
    )

    assert filtered == {
        "intensity": 0.6,
        "emotion_id": "happy",
        "motion_group": "Tap",
        "motion_index": 1,
        "duration_ms": 1800,
    }


def test_incremental_reply_decoder_handles_chunked_escapes_and_unicode():
    decoder = IncrementalJsonReplyDecoder()
    chunks = [
        '{"rep',
        'ly":"hello\\n\\u4f60',
        '\\u597d \\ud83d',
        '\\ude00","pet_control":null}',
    ]

    assert "".join(decoder.feed(chunk) for chunk in chunks) == "hello\n你好 😀"
    assert decoder.started is True
    assert decoder.finished is True


def test_incremental_reply_decoder_never_emits_pet_control_json():
    decoder = IncrementalJsonReplyDecoder()
    payload = '{"reply":"好的。","pet_control":{"emotion_id":"happy"}}'

    assert decoder.feed(payload) == "好的。"
    assert decoder.feed("ignored") == ""
