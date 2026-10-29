"""Offline rule-based decision backend."""
import re
from .contracts import Action, State


QUERIES = {
    "expense.deadline": "报销 期限", "expense.materials": "报销 材料 发票",
    "travel.lodging": "出差 住宿 限额", "it.support": "电脑 故障 工单",
    "product.captions": "产品 中文 字幕 编辑", "access.wifi": "访客 wifi 网络",
}


def detect_topic(question: str, history: list[dict[str, str]]) -> str | None:
    context = " ".join(item["content"] for item in history if item["role"] == "user")
    followup = any(word in question for word in ("那", "这个", "上述", "它"))
    text = question + (" " + context if followup else "")
    if any(word in text for word in ("报销", "报账", "报帐")) and any(word in question for word in ("材料", "凭证", "发票", "单据")):
        return "expense.materials"
    if any(word in text for word in ("住宿", "酒店", "宾馆", "旅店", "夜宿", "住店")):
        return "travel.lodging"
    if any(word in text for word in ("报销", "报账", "报帐")) and any(word in text for word in ("期限", "多久", "几天", "截止", "时间")):
        return "expense.deadline"
    if any(word in text for word in ("电脑", "笔记本", "设备")):
        return "it.support"
    if "字幕" in text and not any(word in question for word in ("日文", "日语", "韩文", "英文")):
        return "product.captions"
    if any(word in text.lower() for word in ("wifi", "无线网", "访客网络")):
        return "access.wifi"
    return None


def citation(doc: dict, section: dict) -> dict:
    return {"doc_id": doc["id"], "section_id": section["id"], "quote": section["text"]}


def finish(status: str, answer: str, reason: str, citations: list | None = None, gaps: list | None = None) -> Action:
    return Action("finish", {"status": status, "answer": answer, "citations": citations or [], "gaps": gaps or []}, reason)


class MockModel:
    name = "offline-rule-mock-v1"
    is_mock = True

    def decide(self, state: State) -> Action:
        topic = detect_topic(state.question, state.history)
        if topic is None and any(x in state.question for x in ("那", "这个", "上述", "它")):
            return finish("needs_clarification", "请说明你指的是哪项制度或产品功能。", "缺少可以确定问题对象的上下文", gaps=["需要明确问题对象"])
        observations = state.observations
        if observations and not observations[-1]["result"].get("ok"):
            last = observations[-1]
            error = last["result"]["error"]
            matching_errors = sum(o["action"] == last["action"] and o["arguments"] == last["arguments"] and not o["result"].get("ok") for o in observations)
            if last["action"] in {"search_documents", "read_document"} and error.get("retryable") and matching_errors < 2:
                return Action(last["action"], last["arguments"], "工具报告可重试错误，保留已有资料并再试一次")
            refs = [citation(doc, s) for doc in state.evidence.values() for s in doc["sections"] if s["topic"] == topic]
            return finish("tool_failed", "工具失败，暂时无法完成核对；已成功读取的资料已保留。", "必要工具调用失败，保留已有证据并结束", refs, [error["code"] + ": " + error["message"]])
        searches = [o["result"] for o in observations if o["action"] == "search_documents" and o["result"].get("ok")]
        if not searches:
            return Action("search_documents", {"query": state.question, "limit": 5}, "先检索与当前问题相关的制度或产品资料")
        latest = searches[-1]
        hits = [h for h in latest["hits"] if topic and topic in h["topics"]]
        if not hits:
            if topic and len(searches) < 2 and latest["query"] != QUERIES[topic]:
                return Action("search_documents", {"query": QUERIES[topic], "limit": 5}, "当前结果不足，换用制度关键词补充检索")
            return finish("insufficient_evidence", "现有资料不足以回答这个问题，请补充相关制度或产品说明。", "检索结果未覆盖该问题，返回资料缺口", gaps=["缺少与问题相符的原文证据"])
        for hit in hits:
            if hit["doc_id"] not in state.evidence:
                return Action("read_document", {"doc_id": hit["doc_id"]}, "读取相关文档原文，并核对是否存在不同规定")
        if latest["total_matches"] > len(latest["hits"]) and latest.get("hits"):
            return finish("incomplete", "检索结果被截断，尚未核对全部可能相关的资料。", "候选文档超过本次检索返回数量", gaps=["需要扩大检索范围或增加分页工具"])
        refs = []
        texts = []
        for hit in hits:
            doc = state.evidence[hit["doc_id"]]
            for section in doc["sections"]:
                if section["topic"] == topic:
                    refs.append(citation(doc, section))
                    texts.append(section["text"])
        normalized = {re.sub(r"\s+|[，。；,.;]", "", t) for t in texts}
        if len(normalized) > 1:
            lines = [f"{c['doc_id']}：{c['quote']}" for c in refs]
            return finish("needs_clarification", "资料存在冲突：\n" + "\n".join(lines) + "\n请确认适用制度或优先级后再执行。", "相同主题有不同规定，版本日期本身不表示优先级", refs, ["未给出冲突文档的适用范围或优先关系"])
        return finish("answered", texts[0], "已读取相关原文，当前检索范围内没有发现不同规定", refs)
