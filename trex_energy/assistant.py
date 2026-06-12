from __future__ import annotations

from typing import Any


SUGGESTED_QUESTIONS = [
    "What is happening in this site?",
    "What should I do next?",
    "Why did the optimizer choose this option?",
    "Why not the cheaper option?",
    "What should we verify before approving?",
]

ASSISTANT_ACTIONS = {
    "site_profile": {
        "label": "Check site profile",
        "target_tab": "profile",
        "reason": "Review observed load, solar metadata, and data quality.",
    },
    "peak_windows": {
        "label": "Check peak windows",
        "target_tab": "forecast",
        "reason": "Review forecast risk windows and operational response guidance.",
    },
    "compare_options": {
        "label": "Compare options",
        "target_tab": "optimization",
        "reason": "Review the scenario table and Explainable AI evidence.",
    },
    "review_assumptions": {
        "label": "Review assumptions",
        "target_tab": "optimization",
        "reason": "Tariff and CAPEX inputs can change which scenario ranks first.",
    },
    "read_summary": {
        "label": "Read summary",
        "target_tab": "summary",
        "reason": "Review the current executive-level result summary.",
    },
    "check_settings": {
        "label": "Check settings",
        "target_tab": "settings",
        "reason": "Review API, frontend, and deployment status.",
    },
}


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


def _top_risk_windows(context: dict[str, Any]) -> list[dict[str, Any]]:
    windows = _nested(context, "forecast", "top_risk_windows", default=[])
    return [window for window in windows if isinstance(window, dict)]


def _is_high_risk_event_question(question: str) -> bool:
    lower_question = question.lower()
    high_risk_terms = [
        "high risk",
        "highest risk",
        "most risk",
        "top risk",
        "peak risk",
        "peak-risk",
        "risk window",
        "risk event",
        "risk interval",
        "charge-risk",
        "demand spike",
        "peak window",
    ]
    return any(term in lower_question for term in high_risk_terms)


def _is_next_step_question(question: str) -> bool:
    lower_question = question.lower()
    next_step_terms = [
        "what should i do",
        "what should we do",
        "what do i do",
        "what do we do",
        "what next",
        "next step",
        "next action",
        "step by step",
        "step-by-step",
        "guide me",
        "action plan",
        "how to proceed",
        "where should i start",
    ]
    return any(term in lower_question for term in next_step_terms)


def _answer_high_risk_events(context: dict[str, Any]) -> tuple[str, list[str]]:
    windows = _top_risk_windows(context)
    if not windows:
        return (
            "The assistant context does not include ranked forecast risk windows yet. Open Forecast & Risk to review the interval-level peak-risk chart and top-window list.",
            ["Forecast & Risk"],
        )

    top = windows[0]
    day = top.get("day", "the forecast day")
    time_window = top.get("time_window") or top.get("timeWindow") or "the highlighted window"
    level = str(top.get("level", "risk")).lower()
    label = top.get("label") or "peak-risk window"
    action = top.get("action") or "monitor the MD threshold"
    answer = (
        f"The highest-risk event is {day}, {time_window}: {label} at {_format_kw(top.get('peak_kw') or top.get('peakLoad'))}, marked {level}. "
        f"The practical response is to {str(action).lower()} during that window."
    )
    if len(windows) > 1:
        next_windows = []
        for window in windows[1:3]:
            next_day = window.get("day", "another forecast day")
            next_time = window.get("time_window") or window.get("timeWindow") or "the highlighted window"
            next_load = _format_kw(window.get("peak_kw") or window.get("peakLoad"))
            next_windows.append(f"{next_day}, {next_time} at {next_load}")
        answer += f" The next highest windows are {'; '.join(next_windows)}."
    return answer, ["Forecast & Risk", "Top Risk Windows"]


def _answer_next_steps(context: dict[str, Any]) -> tuple[str, list[str]]:
    best = _nested(context, "optimization", "best_scenario", default={})
    validation = _nested(context, "validation", default={})
    windows = _top_risk_windows(context)
    top_window = windows[0] if windows else {}
    md_after = _format_kw(best.get("md_after")) if isinstance(best, dict) else "the optimized MD"
    annual_savings = _format_rm(best.get("annual_savings_rm")) if isinstance(best, dict) else "the annual savings"
    battery_kw = best.get("battery_kw") if isinstance(best, dict) else None
    battery_kwh = best.get("battery_kwh") if isinstance(best, dict) else None
    solar_kwp = best.get("solar_kwp") if isinstance(best, dict) else None
    gaps = validation.get("gap_count", 0) if isinstance(validation, dict) else 0
    missing = validation.get("missing_value_count", 0) if isinstance(validation, dict) else 0
    top_day = top_window.get("day")
    top_time = top_window.get("time_window") or top_window.get("timeWindow")
    top_peak = _format_kw(top_window.get("peak_kw") or top_window.get("peakLoad")) if top_window else "the top forecast peak"
    asset_text = (
        f"{_format_kw(battery_kw)} / {float(battery_kwh):,.0f} kWh battery and {float(solar_kwp):,.0f} kWp PV"
        if battery_kw is not None and battery_kwh is not None and solar_kwp is not None
        else "the selected battery and PV sizes"
    )
    window_text = (
        f"{top_day}, {top_time} at {top_peak}"
        if top_day and top_time
        else "the top Forecast & Risk window"
    )
    return (
        f"1. Start in Forecast & Risk and inspect {window_text}; this is the event the plan must control. "
        f"2. Open Options Considered and confirm the selected {asset_text} is acceptable for {md_after} optimized MD and {annual_savings}/yr savings. "
        f"3. Before approval, re-check MD tariff, battery CAPEX, and solar CAPEX because those inputs can change the ranking. "
        f"4. Review data quality: this analysis shows {gaps} gaps and {missing} missing values, so confirm the gaps do not hide a larger peak before procurement."
    ), ["Forecast & Risk", "Options Considered", "Decision Checklist"]


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


def _suggest_actions(question: str, sources: list[str]) -> list[dict[str, str]]:
    lower_question = question.lower()
    lower_sources = " ".join(sources).lower()
    action_ids: list[str] = []

    def add(action_id: str) -> None:
        if action_id not in action_ids:
            action_ids.append(action_id)

    if _is_high_risk_event_question(question):
        add("peak_windows")
    if _is_next_step_question(question):
        add("peak_windows")
        add("compare_options")
        add("review_assumptions")
    if any(term in lower_question for term in ["cheaper", "larger", "option", "optimizer", "choose", "chosen", "recommend"]):
        add("compare_options")
        add("review_assumptions")
    if any(term in lower_question for term in ["verify", "approval", "approve", "check", "assumption"]):
        add("review_assumptions")
        add("site_profile")
    if any(term in lower_question for term in ["peak", "forecast", "window"]):
        add("peak_windows")
    if any(term in lower_question for term in ["site", "happening", "load", "solar"]):
        add("site_profile")
    if "settings" in lower_question or "api" in lower_question:
        add("check_settings")

    if "optimization" in lower_sources or "options considered" in lower_sources or "explainable ai" in lower_sources:
        add("compare_options")
    if "site profile" in lower_sources or "data checks" in lower_sources:
        add("site_profile")
    if "forecast" in lower_sources:
        add("peak_windows")
    if not action_ids:
        add("site_profile")
        add("compare_options")

    return [ASSISTANT_ACTIONS[action_id] for action_id in action_ids[:3]]


def build_grounded_assistant_response(question: str, context: dict[str, Any]) -> dict[str, Any]:
    lower_question = question.lower()
    if any(term in lower_question for term in ["script", "presentation", "judge-facing", "judge facing"]):
        answer = (
            "This assistant is scoped to explain the dashboard analysis, not to generate judge-facing scripts. "
            "Ask about the current site, the optimizer decision, option tradeoffs, or approval checks."
        )
        sources = ["Assistant scope"]
    elif _is_high_risk_event_question(question):
        answer, sources = _answer_high_risk_events(context)
    elif _is_next_step_question(question):
        answer, sources = _answer_next_steps(context)
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
        "suggested_actions": _suggest_actions(question, sources),
    }
