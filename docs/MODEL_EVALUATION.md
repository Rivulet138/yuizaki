# 模型评测

项目提供一个不依赖云端凭据、默认不下载模型的离线评测入口，用于锁定模型质量和延迟回归。评测读取已采集的结果，不会在 CI 中调用 ASR、TTS、LLM 或 Embedding 服务。

```powershell
cd python
.\.venv\Scripts\python.exe -m evals
```

```bash
cd python
./.venv/bin/python -m evals
```

| 能力 | 指标 | 默认门槛 |
| --- | --- | --- |
| ASR | WER、CER | WER/CER <= 0.20 |
| TTS | RTF、TTFA | RTF <= 1.0，TTFA <= 500 ms |
| LLM | 工具调用成功率 | >= 0.90 |
| Embedding | Recall@k | >= 0.80 |

默认 fixture 位于 `python/evals/fixtures/smoke.json`，只验证评测管线和指标实现，不代表真实模型质量。

## 自定义数据

```powershell
python -m evals --fixture path/to/evaluation.json --output artifacts/evaluation.json
```

fixture 使用 `schema_version: 1`，必须包含 `metadata.source`、每个能力的
`metadata.models.<suite>.provider/model`，以及非空的 `asr`、`tts`、`llm`、`embedding` 数组：

```json
{
  "schema_version": 1,
  "metadata": {
    "source": "offline-capture-2026-07-20",
    "models": {
      "asr": {"provider": "sherpa-onnx", "model": "sensevoice-small"},
      "tts": {"provider": "genie-tts", "model": "default"},
      "llm": {"provider": "deepseek", "model": "deepseek-chat"},
      "embedding": {"provider": "qwen", "model": "qwen3-embedding"}
    }
  },
  "asr": [{"reference": "你好", "hypothesis": "你好"}],
  "tts": [{"audio_duration_s": 2.0, "elapsed_ms": 250, "first_audio_ms": 120}],
  "llm": [{"expected_tools": ["read_file"], "actual_tools": ["read_file"]}],
  "embedding": [{"relevant_ids": ["m1"], "ranked_ids": ["m1", "m2"], "k": 2}]
}
```

fixture 可以在 `thresholds` 中覆盖默认门槛；命令行 `--thresholds path/to/thresholds.json`
可以进一步覆盖 fixture。失败时退出码为 1，并在报告的 `failures` 中列出指标、实际值、门槛和比较方向。

真实模型适配应在同一 fixture schema 下采集结果后再运行评测，不应把网络调用、凭据或大模型权重提交到测试仓库。

## 指标解释

- WER：有空格文本按词计算；中文无空格文本按字符计算。
- CER：移除空白后按字符计算。
- RTF：推理耗时秒数除以生成音频秒数，越低越好。
- TTFA：从请求开始到首个可播放音频块的毫秒数，越低越好。
- 工具成功率：按调用次数匹配期望工具与实际工具，重复调用不会被一次成功错误地计为全部成功。
- Recall@k：相关记忆出现在前 k 个结果中的比例。

评测代码位于 `python/evals/metrics.py` 和 `python/evals/suite.py`。报告会记录 schema、来源、模型/provider、运行时间、Python 与平台信息。
CI smoke 评测不等同于真实模型质量认证；要建立真实基线，应按同一 schema 采集固定数据集和模型版本，并分别保存报告产物。
