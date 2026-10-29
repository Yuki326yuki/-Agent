# 验证结果

环境：Windows、Python 3.12.14；运行模式：`offline_mock`。

```bash
python run.py evaluate
python scripts/run_tests.py
python scripts/retrieval_experiment.py
```

## 场景结果

每个示例目录包含`input.json`、`expected.json`、`output.json`和`trace.json`。

| 场景 | 预期与实际结果 | 记录 |
|---|---|---|
| 明确答案 | 引用D03的500元标准，answered | [01_normal](../examples/01_normal/output.json) |
| 文档冲突 | 引用30天与15天，请求确认，needs_clarification | [02_conflict](../examples/02_conflict/trace.json) |
| 资料外问题 | 返回资料缺口，insufficient_evidence | [03_outside](../examples/03_outside/output.json) |
| 改写问题 | 酒店表达匹配住宿标准，answered | [04_paraphrase](../examples/04_paraphrase/output.json) |
| 上下文追问 | 返回报销材料及D01引用，answered | [05_context](../examples/05_context/trace.json) |
| 工具失败 | 重试仍失败后结束，tool_failed | [06_tool_failure](../examples/06_tool_failure/trace.json) |
| 一次失败恢复 | 重试读取成功，answered | [07_retry_recovery](../examples/07_retry_recovery/trace.json) |
| 缺少问题对象 | 请求补充对象，needs_clarification | [08_missing_context](../examples/08_missing_context/output.json) |
| 文档替换 | 原文改为650元后答案同步改变，answered | [09_changed_document](../examples/09_changed_document/output.json) |
| 步数上限 | 两轮后停止，incomplete | [10_step_limit](../examples/10_step_limit/output.json) |
| 部分读取后失败 | 保留D01并报告D02读取失败，tool_failed | [11_partial_read_failure](../examples/11_partial_read_failure/trace.json) |
| 单份制度 | 依据D01回答30天，answered | [12_single_policy](../examples/12_single_policy/output.json) |
| 空资料库 | 补查后返回资料不足，insufficient_evidence | [13_empty_corpus](../examples/13_empty_corpus/trace.json) |

13/13组场景符合预期，36/36项自动化测试通过。汇总见[evaluation_summary.json](../examples/evaluation_summary.json)和[test_summary.json](../examples/test_summary.json)，详细日志见[test_results.txt](../examples/test_results.txt)。

自动化测试还覆盖引用原文校验、非法工具与参数、无效决策、调用上限、已读证据保留、检索截断和历史信息使用。

## 检索改进

使用“住店”“宾馆”“报账期限”“无线网”4条查询比较同义词归一化前后的结果，目标文档的Hit@5从1/4提升至4/4。完整结果见[retrieval_experiment.json](../examples/retrieval_experiment.json)。

## 当前限制

Mock覆盖资料库中的有限主题；关键词检索依赖词面与同义词表；冲突判断基于同主题原文差异，尚未区分等价改写和不同适用范围。

待完成：真实模型接入，并对同一批用例运行验证。
