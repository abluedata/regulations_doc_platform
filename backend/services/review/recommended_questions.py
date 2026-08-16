"""Grounded recommended-question generation with deterministic fallback."""
from __future__ import annotations
import hashlib, json
from typing import Any, Mapping

def _valid_ref(ref: str, document_version_id: str, refs: set[str]) -> bool:
    return ref in refs or ref.startswith(f"{document_version_id}:")

def generate_recommended_questions(document: Mapping[str, Any], findings: list[Mapping[str, Any]] | None = None, *, model_output: Any = None, document_version_id: str | None = None) -> list[dict[str, Any]]:
    doc_id = document_version_id or str(document.get("document_version_id") or document.get("id") or "")
    refs = {str(x) for x in (document.get("source_refs") or document.get("sections") or [])}
    candidates = model_output if isinstance(model_output, list) else []
    out=[]; seen=set()
    for item in candidates:
        if not isinstance(item, Mapping): continue
        q=str(item.get("question") or "").strip(); source=[str(r) for r in (item.get("source_refs") or [])]
        if not q or q.lower() in seen or any(not _valid_ref(r,doc_id,refs) for r in source): continue
        seen.add(q.lower()); out.append({"question":q,"rationale":str(item.get("rationale") or ""),"source_refs":source,"rank":len(out)+1})
    for finding in findings or []:
        if len(out)>=3: break
        category=str(finding.get("category") or finding.get("rule_name") or "风险"); q=f"文档中的{category}问题应如何整改，依据是什么？"
        if q.lower() not in seen: out.append({"question":q,"rationale":"基于审查发现生成","source_refs":[],"rank":len(out)+1}); seen.add(q.lower())
    title=str(document.get("title") or document.get("filename") or "该文档")
    for q in (f"{title}中最需要优先关注的合规风险是什么？", "文档中的关键义务和例外条款有哪些？", "哪些条款建议结合业务场景进一步确认？"):
        if len(out)>=3: break
        if q.lower() not in seen: out.append({"question":q,"rationale":"确定性文档模板","source_refs":[],"rank":len(out)+1}); seen.add(q.lower())
    return out[:5]

def prompt_hash(document: Mapping[str, Any], findings: list[Mapping[str, Any]] | None = None) -> str:
    return hashlib.sha256(json.dumps({"document":document,"findings":findings or []},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
