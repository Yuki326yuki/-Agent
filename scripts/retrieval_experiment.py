"""Compare retrieval with and without query alias expansion."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qa_agent.tools import ToolService, load_documents

docs = load_documents(ROOT / "data" / "documents.json")
queries = [("住店", "D03"), ("宾馆", "D03"), ("报账期限", "D01"), ("无线网", "D06")]
rows = []
for query, expected in queries:
    before = ToolService(docs, expand_aliases=False).execute("search_documents", {"query": query})["hits"]
    after = ToolService(docs).execute("search_documents", {"query": query})["hits"]
    rows.append({"query": query, "expected_doc_id": expected,
                 "baseline_ids": [x["doc_id"] for x in before], "expanded_ids": [x["doc_id"] for x in after],
                 "baseline_hit_at_5": expected in [x["doc_id"] for x in before], "expanded_hit_at_5": expected in [x["doc_id"] for x in after]})
output = {"scope": "4条中文改写查询的检索对照实验", "total": len(rows),
          "baseline_hits": sum(r["baseline_hit_at_5"] for r in rows), "expanded_hits": sum(r["expanded_hit_at_5"] for r in rows), "queries": rows}
target = ROOT / "examples" / "retrieval_experiment.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(output, ensure_ascii=True, indent=2))
