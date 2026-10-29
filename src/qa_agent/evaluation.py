"""Generate actual inputs, results and traces by running the offline program."""
import copy
import json
import platform
from datetime import datetime, timezone
from pathlib import Path
from .agent import Agent
from .mock_model import MockModel
from .tools import ToolService, load_documents


def cases() -> list[dict]:
    return [
        {"id": "01_normal", "question": "境内出差住宿报销上限是多少？", "expected": {"status": "answered", "answer_contains": ["500元"], "citation_ids": ["D03"]}},
        {"id": "02_conflict", "question": "报销期限是多久？", "expected": {"status": "needs_clarification", "answer_contains": ["30天", "15天", "确认"], "citation_ids": ["D01", "D02"]}},
        {"id": "03_outside", "question": "公司2027年的全球销售额目标是多少？", "expected": {"status": "insufficient_evidence", "citation_ids": []}},
        {"id": "04_paraphrase", "question": "出差住酒店，一晚最多能报多少费用？", "expected": {"status": "answered", "answer_contains": ["500元"], "citation_ids": ["D03"]}},
        {"id": "05_context", "question": "那需要准备什么材料？", "history": [{"role": "user", "content": "我想了解费用报销。"}, {"role": "assistant", "content": "请问你想了解哪个方面？"}], "expected": {"status": "answered", "answer_contains": ["有效发票", "审批记录"], "citation_ids": ["D01"]}},
        {"id": "06_tool_failure", "question": "出差住宿标准是什么？", "failures": [{"tool": "search_documents", "times": 2, "retryable": True}], "expected": {"status": "tool_failed", "tool_calls": 2, "citation_ids": []}},
        {"id": "07_retry_recovery", "question": "出差住宿标准是什么？", "failures": [{"tool": "read_document", "doc_id": "D03", "times": 1, "retryable": True}], "expected": {"status": "answered", "answer_contains": ["500元"], "has_tool_error": True}},
        {"id": "08_missing_context", "question": "那需要什么材料？", "expected": {"status": "needs_clarification", "tool_calls": 0}},
        {"id": "09_changed_document", "question": "境内出差住宿报销上限是多少？", "corpus_variant": "lodging_650", "expected": {"status": "answered", "answer_contains": ["650元"], "answer_excludes": ["500元"], "citation_ids": ["D03"]}},
        {"id": "10_step_limit", "question": "出差住宿标准是什么？", "max_steps": 2, "expected": {"status": "incomplete", "stop_reason": "step_limit", "read_document_ids": ["D03"]}},
        {"id": "11_partial_read_failure", "question": "报销期限是多久？", "failures": [{"tool": "read_document", "doc_id": "D02", "times": 2, "retryable": True}], "expected": {"status": "tool_failed", "read_document_ids": ["D01"], "citation_ids": ["D01"]}},
        {"id": "12_single_policy", "question": "报销期限是多久？", "corpus_variant": "only_D01", "expected": {"status": "answered", "answer_contains": ["30天"], "answer_excludes": ["15天"], "citation_ids": ["D01"]}},
        {"id": "13_empty_corpus", "question": "出差住宿标准是什么？", "corpus_variant": "empty", "expected": {"status": "insufficient_evidence", "tool_calls": 2}},
    ]


def variant_documents(documents: list[dict], variant: str | None) -> list[dict]:
    docs = copy.deepcopy(documents)
    if variant == "empty":
        return []
    if variant == "only_D01":
        return [d for d in docs if d["id"] == "D01"]
    if variant == "lodging_650":
        for doc in docs:
            if doc["id"] == "D03":
                doc["sections"][0]["text"] = doc["sections"][0]["text"].replace("500元", "650元")
                doc["version_date"] = "2026-10-01"
    elif variant is not None:
        raise ValueError("Unknown corpus variant")
    return docs


def run_case(case: dict, documents: list[dict]) -> dict:
    tools = ToolService(variant_documents(documents, case.get("corpus_variant")), case.get("failures"))
    return Agent(tools, MockModel(), case.get("max_steps", 10), case.get("max_tool_calls", 8)).run(case["question"], case.get("history"))


def check_expected(result: dict, expected: dict) -> list[str]:
    failures = []
    for key in ("status", "tool_calls", "stop_reason", "read_document_ids"):
        if key in expected and result[key] != expected[key]:
            failures.append(f"{key}: expected {expected[key]!r}, got {result[key]!r}")
    for value in expected.get("answer_contains", []):
        if value not in result["answer"]:
            failures.append("Missing answer text: " + value)
    for value in expected.get("answer_excludes", []):
        if value in result["answer"]:
            failures.append("Unexpected answer text: " + value)
    if "citation_ids" in expected and sorted({c["doc_id"] for c in result["citations"]}) != sorted(expected["citation_ids"]):
        failures.append("Citation document ids differ")
    if expected.get("has_tool_error") and not any(not row["observation"].get("ok") for row in result["trace"]):
        failures.append("Expected an observed tool failure")
    if result["mode"] != "offline_mock":
        failures.append("Offline run is not labelled as Mock")
    return failures


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def evaluate(corpus: Path, output_dir: Path) -> dict:
    documents = load_documents(corpus)
    rows = []
    for case in cases():
        result = run_case(case, documents)
        errors = check_expected(result, case["expected"])
        case_dir = output_dir / case["id"]
        write_json(case_dir / "input.json", {k: v for k, v in case.items() if k not in {"id", "expected"}})
        write_json(case_dir / "expected.json", case["expected"])
        write_json(case_dir / "output.json", {k: v for k, v in result.items() if k != "trace"})
        write_json(case_dir / "trace.json", result["trace"])
        rows.append({"case": case["id"], "passed": not errors, "status": result["status"], "steps": result["steps"], "tool_calls": result["tool_calls"], "errors": errors})
    summary = {"mode": "offline_mock", "real_model_verified": False, "python_version": platform.python_version(),
               "created_at": datetime.now(timezone.utc).isoformat(), "passed": sum(row["passed"] for row in rows), "total": len(rows), "cases": rows}
    write_json(output_dir / "evaluation_summary.json", summary)
    return summary
