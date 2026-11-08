from modules.tts.synthesizer import StreamingSentenceBuffer


def test_streaming_buffer_releases_finished_sentences_before_llm_done() -> None:
    buffer = StreamingSentenceBuffer(max_chars=4096)

    assert buffer.feed("第一句还没") == []
    assert buffer.feed("说完。第二句尚未完成") == ["第一句还没说完。"]
    assert buffer.flush() == ["第二句尚未完成"]


def test_streaming_buffer_does_not_split_normal_sentence_for_tts() -> None:
    text = "这是一个较长的句子，交给翻译后再由 Genie 自行进行语音切分。"
    buffer = StreamingSentenceBuffer(max_chars=4096)

    assert buffer.feed(text) == [text]
    assert buffer.flush() == []
