"""Local retrieval and reading tools. No network or model dependencies."""
import copy
import json
import re
from pathlib import Path
from typing import Any


ALIASES = {
    "住酒店": "住宿", "住宾馆": "住宿", "酒店": "住宿", "宾馆": "住宿",
    "旅店": "住宿", "住店": "住宿", "夜宿": "住宿", "报账": "报销",
    "报帐": "报销", "几天": "期限", "多久": "期限", "截止": "期限",
    "上限": "限额", "最多": "限额", "封顶": "限额", "凭证": "材料",
    "单据": "材料", "坏了": "故障", "无线网": "wifi",
}
STOP_TERMS = {"什么", "多少", "怎么", "如何", "一下", "公司", "员工", "需要", "可以", "请问", "是否", "问题"}


def terms(text: str, expand: bool = True) -> set[str]:
    text = text.lower()
    if expand:
        for old, new in ALIASES.items():
            text = text.replace(old, new)
    found = set(re.findall(r"[a-z0-9]+", text))
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        found.update(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return found - STOP_TERMS


def load_documents(path: Path) -> list[dict[str, Any]]:
    docs = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(docs, list):
        raise ValueError("Corpus must be a JSON array")
    ids: set[str] = set()
    for doc in docs:
        if not isinstance(doc, dict) or not isinstance(doc.get("id"), str):
            raise ValueError("Each document needs a string id")
        if doc["id"] in ids:
            raise ValueError("Duplicate document id: " + doc["id"])
        ids.add(doc["id"])
        for key in ("title", "version_date", "scope"):
            if not isinstance(doc.get(key), str) or not doc[key]:
                raise ValueError(f"Document {doc['id']} needs {key}")
        if not isinstance(doc.get("keywords"), list) or not all(isinstance(x, str) for x in doc["keywords"]):
            raise ValueError("keywords must be an array of strings")
        if not isinstance(doc.get("sections"), list) or not doc["sections"]:
            raise ValueError("Each document needs sections")
        section_ids: set[str] = set()
        for section in doc["sections"]:
            if not isinstance(section, dict) or any(not isinstance(section.get(k), str) or not section[k] for k in ("id", "topic", "text")):
                raise ValueError("Section id, topic and text must be nonempty strings")
            if section["id"] in section_ids:
                raise ValueError("Duplicate section id")
            section_ids.add(section["id"])
    return docs


class ToolService:
    def __init__(self, documents: list[dict[str, Any]], failures: list[dict[str, Any]] | None = None, expand_aliases: bool = True):
        self.documents = {d["id"]: copy.deepcopy(d) for d in documents}
        self.failures = copy.deepcopy(failures or [])
        self.expand_aliases = expand_aliases

    @staticmethod
    def error(code: str, message: str, retryable: bool = False) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message, "retryable": retryable}}

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_documents":
            if set(arguments) - {"query", "limit"} or not isinstance(arguments.get("query"), str) or not 1 <= len(arguments["query"].strip()) <= 500:
                return self.error("INVALID_ARGUMENTS", "search_documents requires a query of 1–500 characters")
            limit = arguments.get("limit", 5)
            if type(limit) is not int or not 1 <= limit <= 10:
                return self.error("INVALID_ARGUMENTS", "limit must be an integer between 1 and 10")
        elif name == "read_document":
            if set(arguments) != {"doc_id"} or not isinstance(arguments.get("doc_id"), str):
                return self.error("INVALID_ARGUMENTS", "read_document requires only doc_id")
        else:
            return self.error("UNKNOWN_TOOL", "Only search_documents and read_document are available")
        for rule in self.failures:
            if rule.get("tool") == name and rule.get("times", 0) > 0 and (not rule.get("doc_id") or rule["doc_id"] == arguments.get("doc_id")):
                rule["times"] -= 1
                return self.error("TOOL_UNAVAILABLE", "Injected local tool failure", bool(rule.get("retryable", True)))
        if name == "read_document":
            doc = self.documents.get(arguments["doc_id"])
            if doc is None:
                return self.error("DOCUMENT_NOT_FOUND", "Document does not exist")
            return {"ok": True, "document": copy.deepcopy(doc)}
        query_terms = terms(arguments["query"], self.expand_aliases)
        hits = []
        for doc in self.documents.values():
            title_terms = terms(doc["title"] + " " + " ".join(doc["keywords"]), self.expand_aliases)
            body = " ".join(s["text"] for s in doc["sections"])
            body_terms = terms(body, self.expand_aliases)
            score = 3 * len(query_terms & title_terms) + len(query_terms & body_terms)
            if score:
                hits.append({"doc_id": doc["id"], "title": doc["title"], "version_date": doc["version_date"],
                             "scope": doc["scope"], "topics": list(dict.fromkeys(s["topic"] for s in doc["sections"])),
                             "snippet": body[:65], "score": score})
        hits.sort(key=lambda hit: (-hit["score"], hit["doc_id"]))
        return {"ok": True, "query": arguments["query"], "hits": hits[:arguments.get("limit", 5)], "total_matches": len(hits)}
