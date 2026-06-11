from __future__ import annotations

from dataclasses import asdict
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import pandas as pd

from trex_energy.forecasting import (
    backtest_monthly_planning_profile,
    backtest_site_forecast,
    forecast_md_ensemble_profile,
    forecast_monthly_planning_profile,
    resolve_existing_pv_kwp,
)
from trex_energy.ingestion import ACTIVE_POWER_UNITS, load_site_workbook
from trex_energy.optimization import OptimizationConfig, evaluate_assumption_sensitivity, evaluate_site_scenarios
from trex_energy.profile import build_site_summary, load_workspace_datasets
from trex_energy.reporting import (
    build_decision_explainability,
    build_executive_summary_text,
    build_optimization_explanation,
    dataframe_to_csv_bytes,
)
from trex_energy.tariff import TariffConfig
from trex_energy.validation import validate_intervals
from trex_energy.assistant import build_grounded_assistant_response


ROOT = Path(__file__).resolve().parent


def _load_local_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_local_env(ROOT / ".env")


def _cors_origins() -> list[str]:
    configured = os.getenv("FRONTEND_ORIGINS", "")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return ["http://localhost:3000", "http://127.0.0.1:3000", *origins]


app = FastAPI(title="TREX Local API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_origin_regex=(
        r"^https?://("
        r"localhost|127\.0\.0\.1|0\.0\.0\.0|"
        r"192\.168\.\d{1,3}\.\d{1,3}|"
        r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
        r"172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}"
        r"):\d+$|^https://[a-z0-9-]+\.vercel\.app$"
    ),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BundledAnalysisRequest(BaseModel):
    source_file: str
    months: int = Field(default=1, ge=1, le=3)
    active_power_unit: str = "auto"
    growth_rate_pct: float = 0.0
    ev_load_kw: float = 0.0
    existing_pv_kwp: float | None = Field(default=None, ge=0)
    use_md_risk_envelope: bool = True
    md_rate_rm_per_kw: float = 97.06
    peak_energy_rate_rm_per_kwh: float = 0.455
    offpeak_energy_rate_rm_per_kwh: float = 0.365
    battery_capex_rm_per_kw: float = 1400.0
    battery_capex_rm_per_kwh: float = 900.0
    solar_capex_rm_per_kwp: float = 3200.0


class AssistantRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)


class AssistantResponse(BaseModel):
    answer: str
    sources: list[str]
    mode: str
    suggested_questions: list[str]


def _json_value(value: Any) -> Any:
    if pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    working = frame.head(limit) if limit is not None else frame
    return [{column: _json_value(value) for column, value in row.items()} for row in working.to_dict(orient="records")]


def _site_files() -> list[Path]:
    return sorted(path for path in ROOT.glob("*.xlsx") if not path.name.startswith("~$"))


def _find_bundled_file(source_file: str) -> Path:
    requested_name = Path(source_file).name
    for workbook in _site_files():
        if workbook.name == requested_name:
            return workbook
    raise HTTPException(status_code=404, detail=f"Unknown bundled workbook: {requested_name}")


def _bundled_reference_frames(source_file: str, active_power_unit: str) -> list[pd.DataFrame]:
    requested_name = Path(source_file).name
    references: list[pd.DataFrame] = []
    for workbook in _site_files():
        if workbook.name == requested_name:
            continue
        try:
            reference_frame, _ = load_site_workbook(workbook, active_power_unit=active_power_unit)
        except Exception:
            continue
        if not reference_frame.empty:
            references.append(reference_frame)
    return references


def _forecast_planning_profile(
    frame: pd.DataFrame,
    *,
    months: int,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    existing_pv_kwp: float | None = None,
    reference_frames: list[pd.DataFrame] | None = None,
) -> pd.DataFrame:
    try:
        return forecast_md_ensemble_profile(
            frame,
            months=months,
            reference_frames=reference_frames,
            growth_rate_pct=growth_rate_pct,
            ev_load_kw=ev_load_kw,
            existing_pv_kwp=existing_pv_kwp,
        )
    except Exception:
        pass

    return forecast_monthly_planning_profile(
        frame,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        existing_pv_kwp=existing_pv_kwp,
    )


def _build_analysis_payload(
    frame: pd.DataFrame,
    metadata: object,
    *,
    months: int,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    existing_pv_kwp: float | None = None,
    reference_frames: list[pd.DataFrame] | None = None,
    use_md_risk_envelope: bool = True,
    md_rate_rm_per_kw: float = 97.06,
    peak_energy_rate_rm_per_kwh: float = 0.455,
    offpeak_energy_rate_rm_per_kwh: float = 0.365,
    battery_capex_rm_per_kw: float = 1400.0,
    battery_capex_rm_per_kwh: float = 900.0,
    solar_capex_rm_per_kwp: float = 3200.0,
) -> dict[str, Any]:
    if frame.empty:
        raise HTTPException(status_code=422, detail="Workbook did not contain usable interval data")

    validation = validate_intervals(frame)
    profile = build_site_summary(frame)
    site_id = str(frame["site_id"].iloc[0])
    metadata_existing_pv = getattr(metadata, "existing_pv_kwp", None)
    resolved_existing_pv = resolve_existing_pv_kwp(
        site_id=site_id,
        source_file=getattr(metadata, "source_file", ""),
        has_solar=bool(getattr(metadata, "has_solar", False)),
        user_existing_pv_kwp=existing_pv_kwp,
        metadata_existing_pv_kwp=metadata_existing_pv,
    )
    forecast = _forecast_planning_profile(
        frame,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        existing_pv_kwp=resolved_existing_pv,
        reference_frames=reference_frames,
    )
    tariff = TariffConfig(
        md_rate_rm_per_kw=md_rate_rm_per_kw,
        peak_energy_rate_rm_per_kwh=peak_energy_rate_rm_per_kwh,
        offpeak_energy_rate_rm_per_kwh=offpeak_energy_rate_rm_per_kwh,
    )
    base_solar_kwp = float(resolved_existing_pv) if resolved_existing_pv is not None else 0.0
    optimization_config = OptimizationConfig(
        use_md_risk_envelope=use_md_risk_envelope,
        battery_capex_rm_per_kw=battery_capex_rm_per_kw,
        battery_capex_rm_per_kwh=battery_capex_rm_per_kwh,
        solar_capex_rm_per_kwp=solar_capex_rm_per_kwp,
        savings_period_months=months,
        base_solar_kwp=base_solar_kwp,
        tariff=tariff,
    )
    optimization = evaluate_site_scenarios(forecast, optimization_config)
    sensitivity = evaluate_assumption_sensitivity(forecast, optimization_config)

    try:
        short_backtest = backtest_site_forecast(frame, horizon=48).metrics
    except Exception as exc:  # pragma: no cover - defensive API fallback
        short_backtest = {"error": str(exc)}

    try:
        monthly_backtest = backtest_monthly_planning_profile(frame).metrics
    except Exception as exc:
        monthly_backtest = {"error": str(exc)}

    assumptions = {
        "planning_months": months,
        "growth_rate_pct": growth_rate_pct,
        "ev_load_kw": ev_load_kw,
        "existing_pv_kwp": resolved_existing_pv,
        "md_rate_rm_per_kw": md_rate_rm_per_kw,
        "peak_energy_rate_rm_per_kwh": peak_energy_rate_rm_per_kwh,
        "offpeak_energy_rate_rm_per_kwh": offpeak_energy_rate_rm_per_kwh,
        "battery_capex_rm_per_kw": battery_capex_rm_per_kw,
        "battery_capex_rm_per_kwh": battery_capex_rm_per_kwh,
        "solar_capex_rm_per_kwp": solar_capex_rm_per_kwp,
    }
    validation_payload = asdict(validation)
    explanation = build_optimization_explanation(
        site_id,
        optimization.best_scenario,
        assumptions,
        validation_payload,
        sensitivity,
    )
    explainability = build_decision_explainability(
        forecast,
        optimization.best_scenario,
        assumptions,
        sensitivity,
    )
    return {
        "metadata": asdict(metadata),
        "assumptions": assumptions,
        "validation": validation_payload,
        "profile": {key: _json_value(value) for key, value in profile.items()},
        "load_history": _records(frame),
        "normalized_preview": _records(frame, limit=20),
        "forecast": {
            "metrics": {
                "short_horizon": {key: _json_value(value) for key, value in short_backtest.items()},
                "monthly_planning": {key: _json_value(value) for key, value in monthly_backtest.items()},
            },
            "points": _records(forecast),
            "preview": _records(forecast, limit=48),
        },
        "optimization": {
            "best_scenario": {key: _json_value(value) for key, value in optimization.best_scenario.items()},
            "scenarios": _records(optimization.scenario_summary),
            "schedule_preview": _records(optimization.optimized_schedule, limit=96),
            "sensitivity": _records(sensitivity),
            "explanation": explanation,
            "explainability": explainability,
        },
        "executive_summary": build_executive_summary_text(site_id, optimization.best_scenario),
        "exports": {
            "normalized_csv": dataframe_to_csv_bytes(frame).decode("utf-8"),
            "forecast_csv": dataframe_to_csv_bytes(forecast).decode("utf-8"),
            "scenario_summary_csv": dataframe_to_csv_bytes(optimization.scenario_summary).decode("utf-8"),
        },
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _extract_openai_text(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                text = message["content"].strip()
                if text:
                    return text

    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    for output_item in payload.get("output", []):
        if not isinstance(output_item, dict):
            continue
        for content_item in output_item.get("content", []):
            if isinstance(content_item, dict) and isinstance(content_item.get("text"), str):
                text = content_item["text"].strip()
                if text:
                    return text
    return None


def _assistant_prompt(question: str, context: dict[str, Any], grounded_answer: str) -> str:
    return (
        "Question:\n"
        f"{question}\n\n"
        "Grounded fallback answer:\n"
        f"{grounded_answer}\n\n"
        "Dashboard context JSON:\n"
        f"{json.dumps(context, ensure_ascii=True)[:6000]}"
    )


def _assistant_provider_answer(question: str, context: dict[str, Any], grounded_answer: str) -> tuple[str, str] | None:
    provider = os.getenv("AI_ASSISTANT_PROVIDER", "").lower()
    generic_api_key = os.getenv("AI_ASSISTANT_API_KEY") or os.getenv("ZAI_API_KEY")
    generic_base_url = os.getenv("AI_ASSISTANT_BASE_URL") or os.getenv("ZAI_BASE_URL")
    generic_model = os.getenv("AI_ASSISTANT_MODEL") or os.getenv("ZAI_MODEL")
    system_prompt = (
        "You are PeakLogic's read-only dashboard assistant. Answer only from the provided dashboard context "
        "and the grounded fallback answer. Do not generate judge-facing scripts, pitch scripts, or presentation scripts. "
        "If the data is insufficient, say what is missing. Keep the answer simple and under 120 words. "
        "Use plain text sentences only. Do not use markdown headings, bold markers, bullet markers, or numbered lists."
    )

    if generic_api_key and generic_base_url:
        try:
            response = httpx.post(
                generic_base_url,
                headers={
                    "Authorization": f"Bearer {generic_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": generic_model or "assistant-default",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": _assistant_prompt(question, context, grounded_answer)},
                    ],
                    "temperature": 0.2,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            text = _extract_openai_text(response.json())
        except Exception:
            return None
        return (text, "provider") if text else None

    if provider != "openai":
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    model = os.getenv("OPENAI_ASSISTANT_MODEL", "gpt-4.1")
    try:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": f"{system_prompt}\n\n{_assistant_prompt(question, context, grounded_answer)}",
            },
            timeout=20.0,
        )
        response.raise_for_status()
    except Exception:
        return None
    text = _extract_openai_text(response.json())
    return (text, "openai") if text else None


@app.post("/api/assistant", response_model=AssistantResponse)
def dashboard_assistant(request: AssistantRequest) -> dict[str, Any]:
    grounded = build_grounded_assistant_response(request.question, request.context)
    provider_result = _assistant_provider_answer(request.question, request.context, str(grounded["answer"]))
    if provider_result:
        provider_answer, mode = provider_result
        return {
            **grounded,
            "answer": provider_answer,
            "mode": mode,
        }
    return grounded


@app.get("/api/bundled-sites")
def bundled_sites() -> dict[str, list[dict[str, Any]]]:
    sites: list[dict[str, Any]] = []
    for dataset in load_workspace_datasets(ROOT):
        metadata = dataset["metadata"]
        frame = dataset["frame"]
        validation = dataset["validation"]
        summary = build_site_summary(frame)
        sites.append(
            {
                "site_id": metadata.site_id,
                "source_file": metadata.source_file,
                "has_solar": metadata.has_solar,
                "existing_pv_kwp": metadata.existing_pv_kwp,
                "row_count": validation.row_count,
                "gap_count": validation.gap_count,
                "peak_kw_import": summary["peak_kw_import"],
            }
        )
    return {"sites": sites}


@app.post("/api/analyze/bundled")
def analyze_bundled(request: BundledAnalysisRequest) -> dict[str, Any]:
    if request.active_power_unit not in ACTIVE_POWER_UNITS:
        raise HTTPException(status_code=400, detail="active_power_unit must be auto, kw, or kwh_per_interval")
    workbook = _find_bundled_file(request.source_file)
    frame, metadata = load_site_workbook(workbook, active_power_unit=request.active_power_unit)
    reference_frames = _bundled_reference_frames(request.source_file, request.active_power_unit)
    return _build_analysis_payload(
        frame,
        metadata,
        months=request.months,
        growth_rate_pct=request.growth_rate_pct,
        ev_load_kw=request.ev_load_kw,
        existing_pv_kwp=request.existing_pv_kwp,
        reference_frames=reference_frames,
        use_md_risk_envelope=request.use_md_risk_envelope,
        md_rate_rm_per_kw=request.md_rate_rm_per_kw,
        peak_energy_rate_rm_per_kwh=request.peak_energy_rate_rm_per_kwh,
        offpeak_energy_rate_rm_per_kwh=request.offpeak_energy_rate_rm_per_kwh,
        battery_capex_rm_per_kw=request.battery_capex_rm_per_kw,
        battery_capex_rm_per_kwh=request.battery_capex_rm_per_kwh,
        solar_capex_rm_per_kwp=request.solar_capex_rm_per_kwp,
    )


@app.post("/api/analyze/upload")
async def analyze_upload(
    file: UploadFile = File(...),
    months: int = Form(1),
    active_power_unit: str = Form("auto"),
    growth_rate_pct: float = Form(0.0),
    ev_load_kw: float = Form(0.0),
    existing_pv_kwp: float | None = Form(None),
    use_md_risk_envelope: bool = Form(True),
    md_rate_rm_per_kw: float = Form(97.06),
    peak_energy_rate_rm_per_kwh: float = Form(0.455),
    offpeak_energy_rate_rm_per_kwh: float = Form(0.365),
    battery_capex_rm_per_kw: float = Form(1400.0),
    battery_capex_rm_per_kwh: float = Form(900.0),
    solar_capex_rm_per_kwp: float = Form(3200.0),
) -> dict[str, Any]:
    if months < 1 or months > 3:
        raise HTTPException(status_code=400, detail="months must be between 1 and 3")
    if active_power_unit not in ACTIVE_POWER_UNITS:
        raise HTTPException(status_code=400, detail="active_power_unit must be auto, kw, or kwh_per_interval")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx uploads are supported")

    safe_name = Path(file.filename).name
    with TemporaryDirectory() as directory:
        temp_path = Path(directory) / safe_name
        temp_path.write_bytes(await file.read())
        frame, metadata = load_site_workbook(temp_path, active_power_unit=active_power_unit)

    return _build_analysis_payload(
        frame,
        metadata,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        existing_pv_kwp=existing_pv_kwp,
        use_md_risk_envelope=use_md_risk_envelope,
        md_rate_rm_per_kw=md_rate_rm_per_kw,
        peak_energy_rate_rm_per_kwh=peak_energy_rate_rm_per_kwh,
        offpeak_energy_rate_rm_per_kwh=offpeak_energy_rate_rm_per_kwh,
        battery_capex_rm_per_kw=battery_capex_rm_per_kw,
        battery_capex_rm_per_kwh=battery_capex_rm_per_kwh,
        solar_capex_rm_per_kwp=solar_capex_rm_per_kwp,
    )
