"""Review API request and response models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PageResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    page: int = 1
    page_size: int = 50


class CreateRuleRequest(BaseModel):
    name: str
    category: str = "general"
    severity: Literal["low", "medium", "high"] = "medium"
    definition: dict[str, Any] = Field(default_factory=dict)
    source_anchor: dict[str, Any] | None = None
    configurable_fields: list[str] = Field(default_factory=list)
    llm_fallback: bool = False


class CreateBatchRequest(BaseModel):
    name: str
    document_type: str = "unknown"
    ocr_required: bool = False


class UpdateBatchRequest(BaseModel):
    name: str | None = None
    document_type: str | None = None
    ocr_required: bool | None = None


class AddBatchDocumentRequest(BaseModel):
    document_id: str
    document_version_id: str
    filename: str | None = None
    status: str = "ready"
    ir: dict[str, Any] | None = None


class RuleSelection(BaseModel):
    rule_version_id: str
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


class CreateTemplateVersionRequest(BaseModel):
    template_id: str | None = None
    name: str
    category: str = "general"
    description: str = ""
    source_version_id: str
    applicable_document_types: list[str]
    rule_version_ids: list[str] = Field(default_factory=list)


class ConfigurationWrite(BaseModel):
    name: str
    rule_selections: list[RuleSelection] = Field(default_factory=list)
    sensitivity: int = Field(50, ge=0, le=100)
    analysis_profile_id: Literal["accurate", "fast"] = "accurate"
    marking_mode: Literal["standard", "high_only"] = "standard"


class StartAnalysisRequest(BaseModel):
    batch_id: str
    document_membership_ids: list[str]
    template_version_id: str | None = None
    rule_selections: list[RuleSelection]
    sensitivity: int = Field(50, ge=0, le=100)
    analysis_profile_id: Literal["accurate", "fast"] = "accurate"
    marking_mode: Literal["standard", "high_only"] = "standard"
    configuration_id: str | None = None


class RetryAnalysisRequest(BaseModel):
    document_job_ids: list[str] = Field(default_factory=list)


class FindingDecisionWrite(BaseModel):
    decision_type: Literal["open", "accepted", "dismissed", "resolved"]
    comment: str | None = None


class OverallDecisionWrite(BaseModel):
    decision_type: Literal["approved", "rejected"]
    comment: str | None = None


class CreateConversationRequest(BaseModel):
    analysis_job_id: str
    document_membership_id: str


class ReviewStreamRequest(BaseModel):
    request_id: str
    message: str
    finding_id: str | None = None
    history: list[dict[str, Any]] = Field(default_factory=list)


class StopRequest(BaseModel):
    request_id: str


class CreateExportRequest(BaseModel):
    format: Literal["markdown", "docx"] = "markdown"


class StartDecisionRequest(BaseModel):
    analysis_job_id: str
    finding_id: str | None = None
    decision_type: str
    comment: str | None = None


class ResumeDecisionRequest(BaseModel):
    action: Literal["confirm", "cancel"]
    comment: str | None = None

