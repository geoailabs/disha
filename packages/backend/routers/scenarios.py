"""
routers/scenarios.py — HTTP endpoints that let the Scenario Builder panel
call backend scenario tools directly without going through the chat WebSocket.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from mcp_servers.scenario_server import ScenarioServer

router = APIRouter()
_server = ScenarioServer()


class AnalyzeRequest(BaseModel):
    bbox: dict[str, float]
    metric_toggles: dict[str, bool] | None = None
    workspace: str | None = None
    layers: list[dict[str, Any]] | None = None


class GenerateRequest(BaseModel):
    context: str
    scenario_types: list[str] | None = None
    focus_area: str = "mixed"
    baseline_metrics: dict[str, Any] | None = None
    hyperparameters: dict[str, Any] | None = None


class CompareRequest(BaseModel):
    scenarios: list[dict[str, Any]]
    criteria: list[str] | None = None
    baseline_metrics: dict[str, Any] | None = None


class BuildReportRequest(BaseModel):
    context: str
    bbox: dict[str, float] | None = None
    focus_area: str = "mixed"
    scenarios: list[dict[str, Any]]
    criteria: list[str] | None = None
    baseline_metrics: dict[str, Any] | None = None
    workspace: str | None = None


@router.post("/analyze")
async def analyze_area(body: AnalyzeRequest):
    """Fetch real geospatial metrics for a bounding box, prioritizing local layers."""
    args: dict[str, Any] = {"bbox": body.bbox}
    if body.metric_toggles:
        args["metric_toggles"] = body.metric_toggles
    if body.workspace:
        args["workspace"] = body.workspace
    if body.layers:
        args["layers"] = body.layers
    result = await _server.execute("analyze_area_for_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/generate")
async def generate_scenarios(body: GenerateRequest):
    """Generate structured planning scenarios for a study area."""
    args: dict[str, Any] = {
        "context": body.context,
        "focus_area": body.focus_area,
    }
    if body.scenario_types:
        args["scenario_types"] = body.scenario_types
    if body.baseline_metrics:
        args["baseline_metrics"] = body.baseline_metrics
    if body.hyperparameters:
        args["hyperparameters"] = body.hyperparameters
    result = await _server.execute("generate_planning_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/compare")
async def compare_scenarios(body: CompareRequest):
    """Compare scenarios using real baseline data or LLM-estimated scores."""
    args = {"scenarios": body.scenarios}
    if body.criteria:
        args["criteria"] = body.criteria
    if body.baseline_metrics:
        args["baseline_metrics"] = body.baseline_metrics
    result = await _server.execute("compare_scenarios", args)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/build-report")
async def build_scenario_report(body: BuildReportRequest):
    """Build and persist the approved scenario draft as the final report."""
    if len([s for s in body.scenarios if str(s.get("name") or "").strip()]) < 2:
        raise HTTPException(status_code=400, detail="At least two scenarios are required.")

    args: dict[str, Any] = {
        "context": body.context,
        "focus_area": body.focus_area,
        "scenario_overrides": body.scenarios,
    }
    if body.bbox:
        args["bbox"] = body.bbox
    if body.criteria:
        args["criteria"] = body.criteria
    if body.baseline_metrics:
        args["baseline_metrics"] = body.baseline_metrics

    # The server reuses the approved scenario descriptions and reruns the
    # comparison so edited inputs are reflected in the scores and recommendation.
    result = await _server.execute("create_scenario_report", args)
    if result.get("status") != "success":
        raise HTTPException(status_code=400, detail=result.get("error", "Report generation failed"))

    from tools.artifact_store import save_artifact
    artifact = save_artifact(
        title=result.get("report_title", f"Planning Scenario Report — {body.context}"),
        artifact_type="report",
        format="markdown",
        content=result.get("report_markdown", ""),
        workspace=body.workspace,
    )
    return {**result, "artifact": artifact}


from fastapi import Query

@router.post("/save-artifact")
async def save_scenario_artifact(body: dict, workspace: str | None = Query(None)):
    """Save a generated scenario report as a markdown artifact."""
    from tools.artifact_store import save_artifact
    title = body.get("title", "Planning Scenario Report")
    content = body.get("markdown", "")
    if not content:
        raise HTTPException(status_code=400, detail="markdown content is required")
    result = save_artifact(
        title=title,
        artifact_type="report",
        format="markdown",
        content=content,
        workspace=workspace,
    )
    return result
