"""Contract tests for the W3 review backend service layer."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from services.review.store import ReviewStore


class ReviewApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

        from api.routes import review

        self.review = review
        self.store = ReviewStore(Path(self.tmp.name))
        review.configure_for_tests(self.store)
        app = FastAPI()
        app.include_router(review.router)
        self.client = TestClient(app)

    def test_rule_batch_job_decision_report_and_qa_contract(self):
        rule = self.client.post(
            "/review/rules",
            json={
                "name": "经济补偿",
                "category": "termination",
                "severity": "high",
                "definition": {
                    "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "经济补偿"}]},
                    "description": "解除协议应说明经济补偿。",
                },
                "source_anchor": self._docx_anchor("source-v1"),
                "llm_fallback": False,
            },
        )
        self.assertEqual(rule.status_code, 201, rule.text)
        rule_item = rule.json()
        self.assertEqual(rule_item["version"], 1)
        self.assertEqual(rule_item["status"], "published")

        listed_rules = self.client.get("/review/rules").json()
        self.assertEqual(listed_rules["total"], 1)
        self.assertEqual(listed_rules["items"][0]["id"], rule_item["id"])
        self.assertEqual(
            self.client.get(f"/review/rule-versions/{rule_item['id']}").json()["definition"]["matcher"],
            rule_item["definition"]["matcher"],
        )

        template = self.client.post(
            "/review/templates",
            json={
                "name": "解除协议基础模板",
                "category": "termination",
                "source_version_id": "source-v1",
                "applicable_document_types": ["termination_agreement"],
                "rule_version_ids": [rule_item["id"]],
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        template_item = self.client.post(
            f"/review/template-versions/{template.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-template"},
        ).json()
        self.assertEqual(template_item["status"], "published")

        batch = self.client.post(
            "/review/batches",
            json={"name": "W3 batch", "document_type": "termination_agreement", "ocr_required": False},
        )
        self.assertEqual(batch.status_code, 201, batch.text)
        batch_id = batch.json()["id"]
        membership = self.client.post(
            f"/review/batches/{batch_id}/documents",
            json={
                "document_id": "doc-1",
                "document_version_id": "ver-1",
                "filename": "termination.docx",
                "status": "ready",
                "ir": {
                    "doc_id": "doc-1",
                    "document_version_id": "ver-1",
                    "source": {"filename": "termination.docx"},
                    "blocks": [
                        {
                            "block_id": "b1",
                            "type": "paragraph",
                            "text": "甲方应支付经济补偿。",
                            "locator": {
                                "kind": "docx",
                                "locator_id": "docx-p-000000",
                                "container_kind": "paragraph",
                                "document_order": 0,
                                "block_id": "b1",
                                "text_range": {"start": 0, "end": 10, "unit": "unicode_code_point"},
                                "precision": "exact",
                            },
                        }
                    ],
                },
            },
        )
        self.assertEqual(membership.status_code, 201, membership.text)
        membership_id = membership.json()["id"]

        job_request = {
            "batch_id": batch_id,
            "document_membership_ids": [membership_id],
            "template_version_id": template_item["id"],
            "rule_selections": [{"rule_version_id": rule_item["id"], "enabled": True, "overrides": {}}],
            "sensitivity": 80,
            "analysis_profile_id": "accurate",
            "marking_mode": "standard",
        }
        job = self.client.post(
            "/review/analysis-jobs",
            headers={"Idempotency-Key": "analysis-1"},
            json=job_request,
        )
        self.assertEqual(job.status_code, 202, job.text)
        job_item = job.json()
        self.assertEqual(job_item["status"], "complete")
        self.assertEqual(job_item["progress"], 100)
        self.assertIn("version_tuple", job_item["snapshot"])

        replay = self.client.post(
            "/review/analysis-jobs",
            headers={"Idempotency-Key": "analysis-1"},
            json=job_request,
        )
        self.assertEqual(replay.status_code, 202)
        self.assertEqual(replay.json()["id"], job_item["id"])

        conflict_request = dict(job_request)
        conflict_request["sensitivity"] = 20
        conflict = self.client.post(
            "/review/analysis-jobs",
            headers={"Idempotency-Key": "analysis-1"},
            json=conflict_request,
        )
        self.assertEqual(conflict.status_code, 409)

        stream = self.client.get(f"/review/analysis-jobs/{job_item['id']}/stream")
        self.assertEqual(stream.status_code, 200)
        self.assertIn("event: issues", stream.text)
        self.assertEqual(stream.text.count("event: complete"), 1)

        findings = self.client.get(f"/review/analysis-jobs/{job_item['id']}/findings").json()
        self.assertEqual(findings["total"], 1)
        finding = findings["items"][0]
        self.assertEqual(finding["quote"], "经济补偿")
        self.assertEqual(finding["decision"], None)

        decision = self.client.put(
            f"/review/findings/{finding['id']}/decision",
            headers={"If-Match": str(job_item["decision_revision"])},
            json={"decision_type": "accepted", "comment": "需要补充条款"},
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        self.assertEqual(decision.json()["decision_type"], "accepted")

        stale = self.client.put(
            f"/review/findings/{finding['id']}/decision",
            headers={"If-Match": "0"},
            json={"decision_type": "dismissed"},
        )
        self.assertEqual(stale.status_code, 409)

        hitl = self.client.post(
            "/review/decisions/start",
            json={"analysis_job_id": job_item["id"], "finding_id": finding["id"], "decision_type": "accepted"},
        )
        self.assertEqual(hitl.status_code, 201, hitl.text)
        resumed = self.client.post(
            f"/review/decisions/{hitl.json()['id']}/resume",
            json={"action": "confirm", "comment": "confirmed"},
        )
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["status"], "completed")

        overall = self.client.put(
            f"/review/analysis-jobs/{job_item['id']}/decision",
            json={"decision_type": "approved", "comment": "同意定稿"},
        )
        self.assertEqual(overall.status_code, 200, overall.text)
        self.assertEqual(overall.json()["decision_type"], "approved")

        export = self.client.post(
            f"/review/analysis-jobs/{job_item['id']}/exports",
            headers={"Idempotency-Key": "export-1"},
            json={"format": "markdown"},
        )
        self.assertEqual(export.status_code, 202, export.text)
        artifact = self.client.get(f"/review/export-artifacts/{export.json()['id']}").json()
        self.assertEqual(artifact["status"], "completed")
        report = self.client.get(f"/review/export-artifacts/{artifact['id']}/download")
        self.assertEqual(report.status_code, 200)
        self.assertIn("版本六元组", report.text)
        self.assertIn(rule_item["id"], report.text)

        audit = self.client.get(f"/review/analysis-jobs/{job_item['id']}/audit-events").json()
        self.assertGreaterEqual(audit["total"], 4)
        self.assertIn("analysis.completed", {item["event_type"] for item in audit["items"]})

        legacy_conversation = self.client.post("/review/conversations", json={"analysis_job_id": job_item["id"]})
        self.assertEqual(legacy_conversation.status_code, 422)
        conversation = self.client.post(
            "/review/conversations",
            json={"analysis_job_id": job_item["id"], "document_membership_id": membership_id},
        )
        self.assertEqual(conversation.status_code, 201, conversation.text)
        self.assertEqual(conversation.json()["document_id"], "doc-1")
        self.assertEqual(conversation.json()["document_version_id"], "ver-1")
        conv_id = conversation.json()["id"]
        answer = self.client.post(
            f"/review/conversations/{conv_id}/stream",
            json={"request_id": "00000000-0000-0000-0000-000000000001", "message": "为什么有风险？", "history": []},
        )
        self.assertEqual(answer.status_code, 200)
        self.assertIn("event: meta", answer.text)
        self.assertEqual(answer.text.count("event: error"), 1)
        self.assertNotIn("event: done", answer.text)
        self.assertEqual(answer.headers["cache-control"], "no-cache")
        self.assertEqual(answer.headers["x-accel-buffering"], "no")
        stop = self.client.post(
            f"/review/conversations/{conv_id}/stop",
            json={"request_id": "00000000-0000-0000-0000-000000000001"},
        )
        self.assertEqual(stop.status_code, 202)
        self.assertEqual(stop.json()["request_id"], "00000000-0000-0000-0000-000000000001")

    def test_analysis_loads_ir_from_document_store_when_membership_ir_empty(self):

        rule = self.client.post(
            "/review/rules",
            json={
                "name": "经济补偿",
                "category": "termination",
                "severity": "high",
                "definition": {
                    "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "经济补偿"}]},
                    "description": "解除协议应说明经济补偿。",
                },
                "source_anchor": self._docx_anchor("source-v1"),
                "llm_fallback": False,
            },
        )
        rule_id = rule.json()["id"]
        template = self.client.post(
            "/review/templates",
            json={
                "name": "基础模板",
                "category": "termination",
                "source_version_id": "source-v1",
                "applicable_document_types": ["termination_agreement"],
                "rule_version_ids": [rule_id],
            },
        )
        template_id = self.client.post(
            f"/review/template-versions/{template.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-template-load-ir"},
        ).json()["id"]

        batch_id = self.client.post(
            "/review/batches",
            json={"name": "load-ir batch", "document_type": "termination_agreement", "ocr_required": False},
        ).json()["id"]

        # Membership intentionally omits the ``ir`` field (frontend addBatchDocument
        # does not send it), so the engine must load IR from document_store.
        membership = self.client.post(
            f"/review/batches/{batch_id}/documents",
            json={
                "document_id": "doc-load-ir",
                "document_version_id": "ver-load-ir",
                "filename": "termination.docx",
                "status": "ready",
            },
        )
        self.assertEqual(membership.status_code, 201, membership.text)
        self.assertIsNone(membership.json().get("ir"))
        membership_id = membership.json()["id"]

        stored_ir = {
            "doc_id": "doc-load-ir",
            "document_version_id": "ver-load-ir",
            "source": {"filename": "termination.docx"},
            "blocks": [
                {
                    "block_id": "b1",
                    "type": "paragraph",
                    "text": "甲方应支付经济补偿。",
                    "locator": {
                        "kind": "docx",
                        "locator_id": "docx-p-000000",
                        "container_kind": "paragraph",
                        "document_order": 0,
                        "block_id": "b1",
                        "text_range": {"start": 0, "end": 10, "unit": "unicode_code_point"},
                        "precision": "exact",
                    },
                }
            ],
        }

        with mock.patch.object(self.review.document_store, "load_ir", return_value=stored_ir):
            job = self.client.post(
                "/review/analysis-jobs",
                json={
                    "batch_id": batch_id,
                    "document_membership_ids": [membership_id],
                    "template_version_id": template_id,
                    "rule_selections": [{"rule_version_id": rule_id, "enabled": True, "overrides": {}}],
                    "sensitivity": 80,
                    "analysis_profile_id": "accurate",
                    "marking_mode": "standard",
                },
            )
        self.assertEqual(job.status_code, 202, job.text)
        job_item = job.json()
        self.assertEqual(job_item["status"], "complete")

        findings = self.client.get(f"/review/analysis-jobs/{job_item['id']}/findings").json()
        self.assertEqual(findings["total"], 1)
        finding = findings["items"][0]
        self.assertEqual(finding["quote"], "经济补偿")
        self.assertEqual(finding["document_id"], "doc-load-ir")
        self.assertEqual(finding["location_label"], "b1")
        evidence = finding.get("evidence_anchor") or {}
        self.assertEqual(evidence.get("kind"), "docx")
        self.assertEqual(evidence.get("quote"), "经济补偿")
        self.assertEqual(evidence.get("locator_id"), "docx-p-000000")
        self.assertEqual(evidence.get("block_id"), "b1")
        self.assertGreater(evidence.get("end", 0), evidence.get("start", 0))

    def test_conversation_reconciles_membership_stuck_queued_when_document_ready(self):
        """批成员状态滞后于文档管线事实（queued）时，创建会话应自愈而不是 409。

        复现：前端在文档解析完成前把成员加入批次（status=queued），随后文档管线
        已到 ready，但成员状态无人更新；问答助手因此一直提示服务不可用。
        """
        rule = self.client.post(
            "/review/rules",
            json={
                "name": "经济补偿",
                "category": "termination",
                "severity": "high",
                "definition": {
                    "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "经济补偿"}]},
                    "description": "解除协议应说明经济补偿。",
                },
                "source_anchor": self._docx_anchor("source-stuck"),
                "llm_fallback": False,
            },
        ).json()["id"]
        template = self.client.post(
            "/review/templates",
            json={
                "name": "基础模板",
                "category": "termination",
                "source_version_id": "source-stuck",
                "applicable_document_types": ["termination_agreement"],
                "rule_version_ids": [rule],
            },
        )
        self.assertEqual(template.status_code, 201, template.text)
        template_id = self.client.post(
            f"/review/template-versions/{template.json()['id']}/publish",
            headers={"Idempotency-Key": "publish-stuck"},
        ).json()["id"]

        batch_id = self.client.post(
            "/review/batches",
            json={"name": "stuck-membership batch", "document_type": "termination_agreement", "ocr_required": False},
        ).json()["id"]

        def add_membership(document_id: str, version_id: str, status: str) -> str:
            membership = self.client.post(
                f"/review/batches/{batch_id}/documents",
                json={
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "filename": "termination.docx",
                    "status": status,
                },
            )
            self.assertEqual(membership.status_code, 201, membership.text)
            return membership.json()["id"]

        ready_membership = add_membership("doc-stuck-ready", "ver-stuck-ready", "queued")
        blocked_membership = add_membership("doc-stuck-blocked", "ver-stuck-blocked", "queued")

        job = self.client.post(
            "/review/analysis-jobs",
            json={
                "batch_id": batch_id,
                "document_membership_ids": [ready_membership, blocked_membership],
                "template_version_id": template_id,
                "rule_selections": [{"rule_version_id": rule, "enabled": True, "overrides": {}}],
                "sensitivity": 80,
                "analysis_profile_id": "accurate",
                "marking_mode": "standard",
            },
        )
        self.assertEqual(job.status_code, 202, job.text)
        job_id = job.json()["id"]

        with mock.patch.object(
            self.review.document_store,
            "load_meta",
            side_effect=lambda doc_id: {"status": "ready", "current_version_id": "ver-1"}
            if doc_id == "doc-stuck-ready"
            else {"status": "parsing"},
        ):
            healed = self.client.post(
                "/review/conversations",
                json={"analysis_job_id": job_id, "document_membership_id": ready_membership},
            )
            self.assertEqual(healed.status_code, 201, healed.text)
            blocked = self.client.post(
                "/review/conversations",
                json={"analysis_job_id": job_id, "document_membership_id": blocked_membership},
            )
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertEqual(blocked.json()["detail"], "document_not_ready")

        batch_after = self.client.get(f"/review/batches/{batch_id}").json()
        by_id = {item["id"]: item["status"] for item in batch_after["documents"]}
        self.assertEqual(by_id[ready_membership], "ready")
        self.assertEqual(by_id[blocked_membership], "queued")

    def test_delete_rule_and_configuration_driven_analysis(self):
        """无用规则可删除；启动分析时优先根据已有配置（规则选择/灵敏度/方案/标记模式）。"""
        rule = self.client.post(
            "/review/rules",
            json={
                "name": "配置规则A",
                "category": "财务",
                "severity": "high",
                "definition": {
                    "description": "检查甲",
                    "suggested_fix": "建议补充甲条款。",
                    "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "经济补偿"}]},
                },
                "source_anchor": self._docx_anchor("source-cfg-a"),
                "llm_fallback": False,
            },
        )
        self.assertEqual(rule.status_code, 201, rule.text)
        rule_item = rule.json()
        junk = self.client.post(
            "/review/rules",
            json={
                "name": "无用规则-待删除",
                "category": "技术",
                "severity": "low",
                "definition": {"description": "无用"},
                "llm_fallback": False,
            },
        ).json()

        removed = self.client.delete(f"/review/rules/{junk['id']}")
        self.assertEqual(removed.status_code, 204)
        self.assertEqual(self.client.get(f"/review/rule-versions/{junk['id']}").status_code, 404)
        self.assertNotIn(junk["id"], {item["id"] for item in self.client.get("/review/rules").json()["items"]})

        batch_id = self.client.post(
            "/review/batches",
            json={"name": "config batch", "document_type": "termination_agreement", "ocr_required": False},
        ).json()["id"]
        membership = self.client.post(
            f"/review/batches/{batch_id}/documents",
            json={
                "document_id": "doc-cfg",
                "document_version_id": "ver-cfg",
                "filename": "termination.docx",
                "status": "ready",
                "ir": {
                    "doc_id": "doc-cfg",
                    "document_version_id": "ver-cfg",
                    "source": {"filename": "termination.docx"},
                    "blocks": [
                        {
                            "block_id": "b1",
                            "type": "paragraph",
                            "text": "甲方应支付经济补偿。",
                            "locator": {
                                "kind": "docx",
                                "locator_id": "docx-p-000000",
                                "container_kind": "paragraph",
                                "document_order": 0,
                                "block_id": "b1",
                                "text_range": {"start": 0, "end": 10, "unit": "unicode_code_point"},
                                "precision": "exact",
                            },
                        }
                    ],
                },
            },
        ).json()

        configuration = self.client.post(
            "/review/configurations",
            json={
                "name": "默认审查配置",
                "rule_selections": [{"rule_version_id": rule_item["id"], "enabled": True, "overrides": {}}],
                "sensitivity": 40,
                "analysis_profile_id": "fast",
                "marking_mode": "high_only",
            },
        )
        self.assertEqual(configuration.status_code, 201, configuration.text)
        config_item = configuration.json()

        job = self.client.post(
            "/review/analysis-jobs",
            json={
                "batch_id": batch_id,
                "document_membership_ids": [membership["id"]],
                "rule_selections": [],
                "sensitivity": 99,
                "analysis_profile_id": "accurate",
                "marking_mode": "standard",
                "configuration_id": config_item["id"],
            },
        )
        self.assertEqual(job.status_code, 202, job.text)
        job_item = job.json()
        self.assertEqual(job_item["status"], "complete")
        # 配置内的取值优先于请求体
        self.assertEqual(job_item["snapshot"]["sensitivity"], 40)
        self.assertEqual(job_item["snapshot"]["analysis_profile_id"], "fast")
        self.assertEqual(job_item["snapshot"]["marking_mode"], "high_only")
        self.assertEqual(job_item["snapshot"]["rule_version_ids"], [rule_item["id"]])
        self.assertEqual(job_item["snapshot"]["configuration"]["id"], config_item["id"])

        findings = self.client.get(f"/review/analysis-jobs/{job_item['id']}/findings").json()
        self.assertEqual(findings["total"], 1)
        self.assertEqual(findings["items"][0]["suggestion"], "建议补充甲条款。")

        # 配置引用已删除规则 → 409 且指明失效规则
        stale_config = self.client.post(
            "/review/configurations",
            json={
                "name": "含失效规则的配置",
                "rule_selections": [{"rule_version_id": junk["id"], "enabled": True, "overrides": {}}],
                "sensitivity": 50,
                "analysis_profile_id": "accurate",
                "marking_mode": "standard",
            },
        ).json()
        blocked = self.client.post(
            "/review/analysis-jobs",
            json={
                "batch_id": batch_id,
                "document_membership_ids": [membership["id"]],
                "rule_selections": [],
                "sensitivity": 50,
                "analysis_profile_id": "accurate",
                "marking_mode": "standard",
                "configuration_id": stale_config["id"],
            },
        )
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "invalid_configuration_rules")
        self.assertEqual(blocked.json()["detail"]["rule_version_ids"], [junk["id"]])

    def test_rule_update_creates_new_version_and_lists_latest_only(self):
        """修改规则产生不可变新版本；列表只返回每个逻辑规则的最新版本。"""
        rule = self.client.post(
            "/review/rules",
            json={
                "name": "可编辑规则",
                "category": "财务",
                "severity": "medium",
                "definition": {
                    "description": "旧描述",
                    "matcher": {"text_pattern": [{"kind": "keyword", "pattern": "投标保证金"}]},
                },
                "llm_fallback": False,
            },
        ).json()
        self.assertEqual(rule["version"], 1)

        updated = self.client.put(
            f"/review/rules/{rule['id']}",
            json={
                "name": "可编辑规则（改）",
                "category": "合规",
                "severity": "high",
                "definition": {"description": "新描述"},
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        new_version = updated.json()
        self.assertEqual(new_version["rule_id"], rule["rule_id"])
        self.assertEqual(new_version["version"], 2)
        self.assertEqual(new_version["name"], "可编辑规则（改）")
        self.assertEqual(new_version["severity"], "high")
        # 定义合并：新描述 + 保留原 matcher（不可变部分的延续）
        self.assertEqual(new_version["definition"]["description"], "新描述")
        self.assertEqual(
            new_version["definition"]["matcher"]["text_pattern"][0]["pattern"], "投标保证金"
        )
        # 旧版本保持不可变
        old = self.client.get(f"/review/rule-versions/{rule['id']}").json()
        self.assertEqual(old["version"], 1)
        self.assertEqual(old["definition"]["description"], "旧描述")

        # 列表只返回最新版本
        listed = self.client.get("/review/rules").json()
        matching = [item for item in listed["items"] if item["rule_id"] == rule["rule_id"]]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["version"], 2)

    def test_store_startup_drift_scan_recovers_running_jobs_and_quarantines_corrupt_json(self):
        store = ReviewStore(Path(self.tmp.name) / "drift")
        batch = store.create_batch({"name": "drift", "document_type": "termination_agreement"})
        job = store.create_analysis_job(
            {
                "batch_id": batch["id"],
                "snapshot": {"id": "snap", "version_tuple": {}},
                "documents": [],
                "events": [],
                "idempotency": {},
            }
        )
        store.update_analysis_job(job["id"], {"status": "running"})
        (store.root / "rules" / "corrupt.json").write_text("{", encoding="utf-8")

        report = store.startup_drift_scan()
        recovered = store.get_analysis_job(job["id"])

        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(report["requeued_jobs"], [job["id"]])
        self.assertEqual(report["quarantined_files"], ["rules/corrupt.json"])

    def _docx_anchor(self, version_id: str) -> dict:
        return {
            "kind": "docx",
            "document_id": "source-doc",
            "document_version_id": version_id,
            "precision": "exact",
            "quote": "source",
            "quote_sha256": "0" * 64,
            "validation_status": "valid",
            "container_kind": "paragraph",
            "locator_id": "docx-p-000000",
            "document_order": 0,
            "start": 0,
            "end": 6,
            "block_id": "b1",
        }


if __name__ == "__main__":
    unittest.main()
