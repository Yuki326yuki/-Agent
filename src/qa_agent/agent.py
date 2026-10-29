"""Bounded decision → tool → observation loop, independent of the backend."""
import copy
from datetime import datetime, timezone
from typing import Any
from .contracts import Action, DecisionBackend, State, STATUSES, validate_action
from .tools import ToolService


def validate_final(args: dict[str, Any], evidence: dict[str, dict]) -> dict[str, Any]:
    if set(args) != {"status", "answer", "citations", "gaps"}:
        raise ValueError("finish needs status, answer, citations and gaps")
    if args["status"] not in STATUSES:
        raise ValueError("Unknown task status")
    if not isinstance(args["answer"], str) or not args["answer"].strip():
        raise ValueError("answer must be a nonempty string")
    if not isinstance(args["gaps"], list) or not all(isinstance(g, str) for g in args["gaps"]):
        raise ValueError("gaps must be a list of strings")
    if not isinstance(args["citations"], list):
        raise ValueError("citations must be a list")
    if args["status"] == "answered" and not args["citations"]:
        raise ValueError("An answered result needs at least one verified citation")
    verified = []
    for ref in args["citations"]:
        if not isinstance(ref, dict) or set(ref) != {"doc_id", "section_id", "quote"}:
            raise ValueError("Each citation needs only doc_id, section_id and quote")
        if not all(isinstance(v, str) for v in ref.values()):
            raise ValueError("Citation fields must be strings")
        doc = evidence.get(ref["doc_id"])
        if doc is None:
            raise ValueError("Citation refers to a document that was not read")
        section = next((s for s in doc["sections"] if s["id"] == ref["section_id"]), None)
        if section is None or not ref["quote"].strip() or ref["quote"] not in section["text"]:
            raise ValueError("Citation quote does not match the original section")
        if len(ref["quote"].strip()) < min(6, len(section["text"].strip())):
            raise ValueError("Citation quote is too short to provide useful evidence")
        verified.append({**ref, "title": doc["title"], "version_date": doc["version_date"], "scope": doc["scope"]})
    return {"status": args["status"], "answer": args["answer"], "citations": verified, "gaps": args["gaps"]}


class Agent:
    def __init__(self, tools: ToolService, backend: DecisionBackend, max_steps: int = 10, max_tool_calls: int = 8):
        if type(max_steps) is not int or not 1 <= max_steps <= 100:
            raise ValueError("max_steps must be between 1 and 100")
        if type(max_tool_calls) is not int or not 0 <= max_tool_calls <= 100:
            raise ValueError("max_tool_calls must be between 0 and 100")
        self.tools, self.backend = tools, backend
        self.max_steps, self.max_tool_calls = max_steps, max_tool_calls

    def run(self, question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        if not isinstance(question, str) or len(question) > 2000:
            raise ValueError("Question must be a string of at most 2000 characters")
        history = [] if history is None else history
        if not isinstance(history, list) or len(history) > 20:
            raise ValueError("History must contain at most 20 messages")
        for item in history:
            if not isinstance(item, dict) or set(item) != {"role", "content"} or item["role"] not in {"user", "assistant"} or not isinstance(item["content"], str) or len(item["content"]) > 2000:
                raise ValueError("Invalid history message")
        state = State(question.strip(), copy.deepcopy(history))
        trace: list[dict[str, Any]] = []
        tool_calls = 0

        def result(final: dict, stop_reason: str) -> dict:
            for i, row in enumerate(trace):
                row["next_action"] = trace[i + 1]["decision"]["action"] if i + 1 < len(trace) else "end"
            return {
                "schema_version": "1.0", "question": state.question, **final,
                "mode": "offline_mock" if self.backend.is_mock else "real_model",
                "backend": self.backend.name,
                "steps": len(trace), "tool_calls": tool_calls,
                "limits": {"max_steps": self.max_steps, "max_tool_calls": self.max_tool_calls},
                "stop_reason": stop_reason, "read_document_ids": list(state.evidence),
                "created_at": datetime.now(timezone.utc).isoformat(), "trace": trace,
            }

        def incomplete(reason: str) -> dict:
            return result({"status": "incomplete", "answer": "达到执行上限，任务尚未完成。", "citations": [], "gaps": [reason]}, reason)

        if not state.question:
            return result({"status": "needs_clarification", "answer": "请提供要查询的问题。", "citations": [], "gaps": ["缺少问题"]}, "missing_question")
        for step in range(1, self.max_steps + 1):
            try:
                action = self.backend.decide(copy.deepcopy(state))
                validate_action(action)
            except Exception as exc:
                observation = ToolService.error("INVALID_DECISION", f"Backend returned an invalid decision ({type(exc).__name__})")
                row = {"step": step, "decision": {"action": "invalid_decision", "arguments": {}, "reason": "决策格式未通过校验"}, "observation": observation}
                trace.append(row)
                state.observations.append({"action": "invalid_decision", "arguments": {}, "result": observation})
                continue
            row = {"step": step, "decision": {"action": action.name, "arguments": copy.deepcopy(action.arguments), "reason": action.reason}}
            if action.name == "finish":
                try:
                    final = validate_final(action.arguments, state.evidence)
                except (ValueError, TypeError) as exc:
                    observation = ToolService.error("INVALID_FINAL", str(exc))
                else:
                    row["observation"] = {"ok": True, "status": final["status"], "verified_citations": len(final["citations"])}
                    trace.append(row)
                    return result(final, "backend_finished")
            else:
                if tool_calls >= self.max_tool_calls:
                    row["observation"] = ToolService.error("TOOL_CALL_LIMIT", "Tool call budget exhausted")
                    trace.append(row)
                    return incomplete("tool_call_limit")
                tool_calls += 1
                try:
                    observation = self.tools.execute(action.name, action.arguments)
                except Exception as exc:
                    observation = ToolService.error("TOOL_EXCEPTION", f"Tool raised {type(exc).__name__}", retryable=False)
                if action.name == "read_document" and observation.get("ok"):
                    doc = observation["document"]
                    state.evidence[doc["id"]] = copy.deepcopy(doc)
            row["observation"] = observation
            trace.append(row)
            state.observations.append({"action": action.name, "arguments": copy.deepcopy(action.arguments), "result": copy.deepcopy(observation)})
        return incomplete("step_limit")
