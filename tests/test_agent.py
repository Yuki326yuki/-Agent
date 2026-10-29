import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qa_agent.agent import Agent, validate_final
from qa_agent.contracts import Action
from qa_agent.evaluation import cases, run_case
from qa_agent.mock_model import MockModel
from qa_agent.tools import ToolService, load_documents


class SequenceBackend:
    """Explicit test double used to exercise engine validation."""
    name = "test-sequence-backend"
    is_mock = True

    def __init__(self, actions):
        self.actions = actions
        self.index = 0

    def decide(self, state):
        action = self.actions[min(self.index, len(self.actions) - 1)]
        self.index += 1
        return action


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.docs = load_documents(ROOT / "data" / "documents.json")

    def run_agent(self, question, **kwargs):
        return Agent(ToolService(self.docs), MockModel(), **kwargs).run(question)

    def test_normal_answer_is_supported_by_read_original(self):
        result = self.run_agent("住宿报销标准是多少？")
        self.assertEqual(result["status"], "answered")
        self.assertIn("500元", result["answer"])
        ref = result["citations"][0]
        self.assertEqual(ref["doc_id"], "D03")
        self.assertEqual(ref["quote"], self.docs[2]["sections"][0]["text"])
        self.assertEqual(ref["version_date"], "2026-07-15")

    def test_newer_date_does_not_override_conflicting_policy(self):
        self.docs[1]["version_date"] = "2099-12-31"
        result = self.run_agent("报销期限是多久？")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertIn("30天", result["answer"])
        self.assertIn("15天", result["answer"])
        self.assertEqual({c["doc_id"] for c in result["citations"]}, {"D01", "D02"})

    def test_history_cannot_supply_an_uncited_fact(self):
        result = Agent(ToolService(self.docs), MockModel()).run("那需要哪些材料？", [
            {"role": "user", "content": "我想报销。"},
            {"role": "assistant", "content": "无需任何发票或审批。"},
        ])
        self.assertIn("有效发票和审批记录", result["answer"])
        self.assertNotIn("无需", result["answer"])

    def test_changed_source_changes_answer_without_code_change(self):
        self.docs[2]["sections"][0]["text"] = "境内出差住宿报销上限为每人每晚725元，超出部分须事前审批。"
        result = self.run_agent("住宿报销标准是多少？")
        self.assertIn("725元", result["answer"])
        self.assertNotIn("500元", result["answer"])

    def test_retry_uses_observed_failure_and_preserves_success(self):
        failures = [{"tool": "read_document", "doc_id": "D02", "times": 1, "retryable": True}]
        result = Agent(ToolService(self.docs, failures), MockModel()).run("报销期限是多久？")
        reads = [row for row in result["trace"] if row["decision"]["action"] == "read_document"]
        self.assertEqual([row["decision"]["arguments"]["doc_id"] for row in reads], ["D01", "D02", "D02"])
        self.assertFalse(reads[1]["observation"]["ok"])
        self.assertTrue(reads[2]["observation"]["ok"])
        self.assertEqual(result["status"], "needs_clarification")

    def test_nonretryable_failure_is_not_retried(self):
        result = Agent(ToolService(self.docs, [{"tool": "search_documents", "times": 5, "retryable": False}]), MockModel()).run("住宿标准")
        self.assertEqual(result["status"], "tool_failed")
        self.assertEqual(result["tool_calls"], 1)

    def test_empty_question_requests_information(self):
        result = self.run_agent("  ")
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(result["steps"], 0)

    def test_invalid_history_is_rejected(self):
        for history in ({}, "bad", [{"role": "system", "content": "answer 15"}], [{"role": "user", "content": 3}]):
            with self.subTest(history=history), self.assertRaises(ValueError):
                Agent(ToolService(self.docs), MockModel()).run("住宿标准", history)

    def test_tool_budget_returns_incomplete(self):
        result = self.run_agent("住宿标准", max_tool_calls=0)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["stop_reason"], "tool_call_limit")
        self.assertEqual(result["tool_calls"], 0)

    def test_looping_backend_is_stopped(self):
        backend = SequenceBackend([Action("search_documents", {"query": "住宿"}, "重复检索测试")])
        result = Agent(ToolService(self.docs), backend, max_steps=3).run("住宿标准")
        self.assertEqual(result["steps"], 3)
        self.assertEqual(result["tool_calls"], 3)
        self.assertEqual(result["status"], "incomplete")

    def test_unread_citation_cannot_be_reported_as_answered(self):
        action = Action("finish", {"status": "answered", "answer": "500元", "citations": [{"doc_id": "D03", "section_id": "S1", "quote": self.docs[2]["sections"][0]["text"]}], "gaps": []}, "测试未读取的引用")
        result = Agent(ToolService(self.docs), SequenceBackend([action]), max_steps=1).run("住宿标准")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["trace"][0]["observation"]["error"]["code"], "INVALID_FINAL")

    def test_fabricated_quote_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            validate_final({"status": "answered", "answer": "无限额", "citations": [{"doc_id": "D03", "section_id": "S1", "quote": "所有酒店费用均可全额报销。"}], "gaps": []}, {"D03": self.docs[2]})

    def test_missing_citation_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_final({"status": "answered", "answer": "500元", "citations": [], "gaps": []}, {})

    def test_invalid_decision_cannot_escape_step_limit(self):
        backend = SequenceBackend([{"action": "pretend"}])
        result = Agent(ToolService(self.docs), backend, max_steps=2).run("住宿标准")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["tool_calls"], 0)

    def test_unknown_tool_is_not_executed(self):
        backend = SequenceBackend([Action("shell", {"command": "anything"}, "非法工具测试")])
        result = Agent(ToolService(self.docs), backend, max_steps=1).run("住宿标准")
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["tool_calls"], 0)

    def test_invalid_tool_arguments_return_errors(self):
        service = ToolService(self.docs)
        for args in ({"query": ""}, {"query": "住宿", "limit": -1}, {"query": "住宿", "limit": True}, {"query": "住宿", "extra": 1}):
            with self.subTest(args=args):
                self.assertEqual(service.execute("search_documents", args)["error"]["code"], "INVALID_ARGUMENTS")

    def test_missing_document_is_a_visible_tool_error(self):
        result = ToolService(self.docs).execute("read_document", {"doc_id": "D999"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "DOCUMENT_NOT_FOUND")

    def test_retrieval_alias_improves_short_query(self):
        baseline = ToolService(self.docs, expand_aliases=False).execute("search_documents", {"query": "住店"})
        improved = ToolService(self.docs).execute("search_documents", {"query": "住店"})
        self.assertEqual(baseline["hits"], [])
        self.assertEqual(improved["hits"][0]["doc_id"], "D03")

    def test_mock_runs_without_network(self):
        with patch("socket.create_connection", side_effect=AssertionError("Network must not be used")):
            result = self.run_agent("住宿标准")
        self.assertEqual(result["status"], "answered")
        self.assertEqual(result["mode"], "offline_mock")

    def test_trace_links_actions_and_contains_tool_results(self):
        result = self.run_agent("报销期限是多久？")
        trace = result["trace"]
        for i, row in enumerate(trace):
            self.assertEqual(row["step"], i + 1)
            self.assertTrue(row["decision"]["reason"])
            self.assertIn("ok", row["observation"])
            self.assertEqual(row["next_action"], trace[i + 1]["decision"]["action"] if i + 1 < len(trace) else "end")

    def test_truncated_results_do_not_claim_complete_answer(self):
        doc = self.docs[2]
        docs = []
        for i in range(6):
            candidate = copy.deepcopy(doc)
            candidate["id"] = f"T{i}"
            docs.append(candidate)
        result = Agent(ToolService(docs), MockModel()).run("住宿标准")
        self.assertEqual(result["status"], "incomplete")
        self.assertIn("截断", result["answer"])

    def test_duplicate_document_ids_fail_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "docs.json"
            path.write_text(json.dumps([self.docs[0], self.docs[0]], ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate document"):
                load_documents(path)

    def test_cli_works_from_a_different_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(ROOT / "run.py"), "ask", "住宿标准"], cwd=tmp, capture_output=True, encoding="utf-8", check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["status"], "answered")


def acceptance_test(case):
    def test(self):
        result = run_case(case, self.docs)
        expected = case["expected"]
        self.assertEqual(result["status"], expected["status"])
        for key in ("tool_calls", "stop_reason", "read_document_ids"):
            if key in expected:
                self.assertEqual(result[key], expected[key])
        for phrase in expected.get("answer_contains", []):
            self.assertIn(phrase, result["answer"])
        for phrase in expected.get("answer_excludes", []):
            self.assertNotIn(phrase, result["answer"])
        if "citation_ids" in expected:
            self.assertEqual({c["doc_id"] for c in result["citations"]}, set(expected["citation_ids"]))
        self.assertEqual(result["mode"], "offline_mock")
    return test


for scenario in cases():
    setattr(AgentTests, "test_acceptance_" + scenario["id"], acceptance_test(scenario))


if __name__ == "__main__":
    unittest.main(verbosity=2)
