# 企业知识问答 Agent · 第3题

根据本地制度和产品资料回答员工问题，输出原文引用、资料缺口、任务状态和执行记录。

运行模式：离线规则型 Mock。真实模型接入与验证待完成。

## 环境与运行

Python 3.10及以上，使用标准库，无需安装第三方依赖或配置环境变量。已在Windows、Python 3.12.14下验证。

在项目根目录执行：

```bash
python run.py ask "境内出差住宿报销上限是多少？"
python run.py ask "报销期限是多久？"
python run.py evaluate
python scripts/run_tests.py
```

第一条返回住宿标准及D03引用。第二条列出D01的30天和D02的15天，返回`needs_clarification`并请求确认适用制度。

## 运行示例

保存结果与Trace：

```bash
python run.py ask "报销期限是多久？" --output runtime/conflict.json
```

注入两次检索失败：

```bash
python run.py ask "出差住宿标准是什么？" --fail-tool search_documents --fail-count 2
```

复现上下文追问、文档内容替换和执行上限：

```bash
python run.py replay examples/05_context/input.json
python run.py replay examples/09_changed_document/input.json
python run.py ask "出差住宿标准是什么？" --max-steps 2
```

`--history history.json`接收`role/content`消息数组，支持`user`和`assistant`；`--corpus documents.json`指定资料文件，格式见[data/documents.json](data/documents.json)。

业务结果退出码为0，配置或输入错误为2；`evaluate`出现失败用例时退出码为1。

## 验证结果

13组场景、36项自动化测试通过。

- [正常问答](examples/01_normal/output.json)
- [文档冲突及逐步记录](examples/02_conflict/trace.json)
- [工具失败及逐步记录](examples/06_tool_failure/trace.json)
- [场景汇总](examples/evaluation_summary.json)
- [测试汇总](examples/test_summary.json)与[测试日志](examples/test_results.txt)

## 项目结构

```text
run.py                  CLI入口
src/qa_agent/           执行器、工具、Mock决策、评估
data/documents.json     6份合成资料
tests/                  自动化测试
scripts/                测试与检索实验脚本
examples/               输入、预期、实际输出与Trace
docs/                   需求、方案、评估、AI使用与复盘
requirements.txt        依赖说明
.env.example            环境配置说明
SUBMISSION.txt          提交信息
```

文档：[需求](docs/01-requirements.md) · [方案](docs/02-solution.md) · [评估](docs/03-evaluation.md) · [AI使用](docs/04-ai-usage.md) · [复盘](docs/05-retrospective.md)
