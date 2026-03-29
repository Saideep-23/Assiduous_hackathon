"""Pydantic models for API responses."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class IngestResponse(BaseModel):
    status: str
    metrics_ingested: int
    warnings_count: int
    chunks_embedded: int
    message: Optional[str] = None


class ProvenanceNumber(BaseModel):
    key: str
    label: str
    payload: dict[str, Any]


class ModelRunResponse(BaseModel):
    scenarios: list[dict[str, Any]]
    sensitisation: dict[str, Any]
    assumptions: list[dict[str, Any]]
    fcf_bridge_tree: dict[str, Any]
    wacc: dict[str, Any]
    consistency_checks: dict[str, Any]
    error: Optional[dict[str, Any]] = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class AgentFinalEvent(BaseModel):
    memo: str
    validation: dict[str, Any]
    provenance: dict[str, Any]
    run_id: str
