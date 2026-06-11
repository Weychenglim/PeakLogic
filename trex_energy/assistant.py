from __future__ import annotations

from typing import Any


SUGGESTED_QUESTIONS = [
    "What is happening in this site?",
    "Why did the optimizer choose this option?",
    "Why not the cheaper option?",
    "What should we verify before approving?",
]


def _nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _format_rm(value: Any) -> str:
    try:
        return f"RM {float(value):,.0f}"
    except (TypeError, ValueError):
        return "the modeled savings"


def _format_kw(value: Any) -> str:
    try:
        return f"{float(value):,.0f} kW"
    except (TypeError, ValueError):
        return "the modeled demand"


def _scenario_evidence_items(context: dict[str, Any]) -> list[dict[str, str]]:
    items = _nested(context, "optimization", "scenario_evidence", "items", default=[])
    return [item for item in items if isinstance(item, dict)]


def _scenario_evidence_summary(context: dict[str, Any]) -> str:
    summary = _nested(context, "optimization", "scenario_evidence", "summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return "The optimizer ranked the tested scenarios by recurring savings, demand exposure, investment, and payback efficiency."


def _scenario_sensitivity(context: dict[str, Any]) -> list[str]:
    notes = _nested(context, "optimization", "scenario_evidence", "sensitivity", default=[])
    return [note for note in notes if isinstance(note, str) and note.strip()]


def _answer_option_tradeoff(question: str, context: dict[str, Any]) -> tuple[str, list[str]]:
    evidence = _scenario_evidence_items(context)
    cheaper = next((item for item in evidence if "cheaper" in str(item.get("label", "")).lower()), None)
    larger = next((item for item in evidence if "larger" in str(item.get("label", "")).lower()), None)
    lines = [_scenario_evidence_summary(context)]
    lower_question = question.lower()

    if "cheaper" in lower_question and cheaper:
        lines.append(f"Against the cheaper option: {cheaper['detail']}")
    elif "larger" in lower_question and larger:
        lines.append(str(larger["detail"]))
    else:
        if cheaper:
            lines.append(str(cheaper["detail"]))
        if larger:
            lines.append(str(larger["detail"]))

    if not any(line != lines[0] for line in lines):
        best = _nested(context, "optimization", "best_scenario", default={})
        lines.append(
            "The selected scenario is the current best-ranked option using "
            f"{_format_rm(best.get('annual_savings_rm'))}/yr savings, "
            f"{_format_rm(best.get('capex_rm'))} CAPEX, and "
            f"{best.get('payback_months', 'the modeled')} month payback as decision signals."
        )

    return " ".join(lines), ["Options Considered", "Explainable AI"]


def _answer_solar_battery(context: dict[str, Any]) -> tuple[str, list[str]]:
    dispatch = next(
        (
            item
            for item in _scenario_evidence_items(context)
            if "dispatch" in str(item.get("label", "")).lower()
        ),
        None,
    )
    if dispatch:
        return str(dispatch["detail"]), ["Explainable AI", "Load Shape After Optimization"]
    return (
        "The model treats storage and PV as different jobs: storage is controllable during peak-risk intervals, while PV reduces daytime grid import when generation overlaps load.",
        ["Optimization", "Options Considered"],
    )


def _answer_approval_checks(context: dict[str, Any]) -> tuple[str, list[str]]:
    notes = _scenario_sensitivity(context)
    validation = _nested(context, "validation", default={})
    gaps = validation.get("gap_count", 0) if isinstance(validation, dict) else 0
    missing = validation.get("missing_value_count", 0) if isinstance(validation, dict) else 0
    lines = [
        "Before approval, confirm the tariff and CAPEX assumptions, then check whether the interval data is clean enough for a final recommendation.",
        f"Current data quality shows {gaps} gaps and {missing} missing values.",
    ]
    lines.extend(notes[:2])
    return " ".join(lines), ["Decision Checklist", "Assumptions", "Data checks"]


def _answer_site_overview(context: dict[str, Any]) -> tuple[str, list[str]]:
    site_id = context.get("site_id") or "this site"
    profile = _nested(context, "profile", default={})
    best = _nested(context, "optimization", "best_scenario", default={})
    peak_text = _format_kw(profile.get("peak_kw_import")) if isinstance(profile, dict) else "the observed site peak"
    avg_text = _format_kw(profile.get("avg_kw_import")) if isinstance(profile, dict) else "the average load"
    savings_text = _format_rm(best.get("annual_savings_rm")) if isinstance(best, dict) else "the modeled savings"
    return (
        f"{site_id} has an observed peak of {peak_text} against an average load near {avg_text}. "
        f"The current optimization result is mainly a demand-charge and investment tradeoff, with {savings_text}/yr modeled annual savings under the active assumptions.",
        ["Site Profile", "Optimization"],
    )


def build_grounded_assistant_response(question: str, context: dict[str, Any]) -> dict[str, Any]:
    lower_question = question.lower()
    if any(term in lower_question for term in ["script", "presentation", "judge-facing", "judge facing"]):
        answer = (
            "This assistant is scoped to explain the dashboard analysis, not to generate judge-facing scripts. "
            "Ask about the current site, the optimizer decision, option tradeoffs, or approval checks."
        )
        sources = ["Assistant scope"]
    elif any(term in lower_question for term in ["cheaper", "larger", "option", "optimizer", "choose", "chosen", "recommend"]):
        answer, sources = _answer_option_tradeoff(question, context)
    elif "solar alone" in lower_question or ("battery" in lower_question and "solar" in lower_question):
        answer, sources = _answer_solar_battery(context)
    elif any(term in lower_question for term in ["verify", "approval", "approve", "check", "assumption", "risk"]):
        answer, sources = _answer_approval_checks(context)
    else:
        answer, sources = _answer_site_overview(context)

    return {
        "answer": answer,
        "sources": sources,
        "mode": "grounded",
        "suggested_questions": SUGGESTED_QUESTIONS,
    }
