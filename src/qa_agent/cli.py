import argparse
import json
import sys
from pathlib import Path
from .agent import Agent
from .evaluation import evaluate, run_case, write_json
from .mock_model import MockModel
from .tools import ToolService, load_documents

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="企业知识问答 Agent：离线 Mock 版")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="运行一个问答任务")
    ask.add_argument("question")
    ask.add_argument("--history", type=Path, help="含 role/content 的 JSON 消息数组")
    ask.add_argument("--corpus", type=Path, default=ROOT / "data" / "documents.json")
    ask.add_argument("--max-steps", type=int, default=10)
    ask.add_argument("--max-tool-calls", type=int, default=8)
    ask.add_argument("--fail-tool", choices=["search_documents", "read_document"])
    ask.add_argument("--fail-count", type=int, default=1)
    ask.add_argument("--fail-doc-id")
    ask.add_argument("--non-retryable", action="store_true")
    ask.add_argument("--output", type=Path)
    test = sub.add_parser("evaluate", help="实际执行13组场景并生成输入、输出与Trace")
    test.add_argument("--corpus", type=Path, default=ROOT / "data" / "documents.json")
    test.add_argument("--output-dir", type=Path, default=ROOT / "examples")
    replay = sub.add_parser("replay", help="从 examples 中的 input.json 重新运行用例")
    replay.add_argument("input", type=Path)
    replay.add_argument("--corpus", type=Path, default=ROOT / "data" / "documents.json")
    replay.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "evaluate":
            result = evaluate(args.corpus, args.output_dir)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["passed"] == result["total"] else 1
        documents = load_documents(args.corpus)
        if args.command == "replay":
            result = run_case(json.loads(args.input.read_text(encoding="utf-8")), documents)
        else:
            if args.fail_count < 1:
                raise ValueError("fail-count must be positive")
            history = json.loads(args.history.read_text(encoding="utf-8")) if args.history else []
            failures = [{"tool": args.fail_tool, "times": args.fail_count, "doc_id": args.fail_doc_id, "retryable": not args.non_retryable}] if args.fail_tool else []
            result = Agent(ToolService(documents, failures), MockModel(), args.max_steps, args.max_tool_calls).run(args.question, history)
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        # A business outcome such as needs_clarification is a successful CLI run.
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"error": str(exc), "mode": "offline_mock"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
