from __future__ import annotations

from typing import Iterable

import pandas as pd

from .optimization import OptimizationResult


def dataframe_to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")


def build_site_comparison_summary(
    site_results: Iterable[tuple[pd.DataFrame, pd.DataFrame, OptimizationResult]],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for frame, forecast, optimization in site_results:
        ordered = frame.sort_values("interval_end").reset_index(drop=True)
        best = optimization.best_scenario
        rows.append(
            {
                "site_id": str(ordered["site_id"].iloc[0]),
                "has_solar": bool(ordered["has_solar"].iloc[0]),
                "baseline_md_kw": float(best["md_before"]),
                "optimized_md_kw": float(best["md_after"]),
                "md_reduction_kw": float(best["md_before"] - best["md_after"]),
                "peak_reduction_pct": float(best["peak_reduction_pct"]),
                "baseline_forecast_peak_kw": float(forecast["forecast_kw_import"].max()),
                "savings_rm": float(best["savings_rm"]),
                "best_scenario_id": str(best["scenario_id"]),
                "battery_kw": float(best["battery_kw"]),
                "battery_kwh": float(best["battery_kwh"]),
                "solar_kwp": float(best["solar_kwp"]),
            }
        )
    return pd.DataFrame(rows).sort_values(["savings_rm", "md_reduction_kw"], ascending=[False, False]).reset_index(drop=True)


def build_executive_summary_text(site_id: str, best_scenario: dict[str, object]) -> str:
    annual_savings = float(best_scenario.get("annual_savings_rm", best_scenario["savings_rm"]))
    period_savings = float(best_scenario["savings_rm"])
    period_months = int(best_scenario.get("savings_period_months", 1) or 1)
    md_before = float(best_scenario["md_before"])
    md_after = float(best_scenario["md_after"])
    battery_kw = float(best_scenario["battery_kw"])
    battery_kwh = float(best_scenario["battery_kwh"])
    solar_kwp = float(best_scenario["solar_kwp"])
    return (
        f"{site_id} can reduce forecast maximum demand from {md_before:.1f} kW to {md_after:.1f} kW, "
        f"with annualized savings of RM {annual_savings:.2f} from RM {period_savings:.2f} over the "
        f"{period_months}-month planning period. "
        f"Current best baseline scenario uses battery {battery_kw:.0f} kW / {battery_kwh:.0f} kWh "
        f"and solar {solar_kwp:.0f} kWp."
    )


def _planning_basis_label(risk_basis: object) -> str:
    if str(risk_basis) == "p95":
        return "Conservative peak-demand planning"
    if str(risk_basis) == "p90":
        return "Balanced peak-demand planning"
    return "Expected-demand planning"


def build_optimization_explanation(
    site_id: str,
    best_scenario: dict[str, object],
    assumptions: dict[str, object],
    validation: dict[str, object],
    sensitivity: pd.DataFrame,
) -> dict[str, object]:
    md_before = float(best_scenario["md_before"])
    md_after = float(best_scenario["md_after"])
    bill_before = float(best_scenario["bill_before_rm"])
    bill_after = float(best_scenario["bill_after_rm"])
    savings = float(best_scenario["savings_rm"])
    monthly_savings = float(best_scenario.get("monthly_savings_rm", savings))
    annual_savings = float(best_scenario.get("annual_savings_rm", monthly_savings * 12.0))
    capex = float(best_scenario.get("capex_rm", 0.0))
    period_months = int(best_scenario.get("savings_period_months", assumptions.get("planning_months", 1)) or 1)
    battery_kw = float(best_scenario["battery_kw"])
    battery_kwh = float(best_scenario["battery_kwh"])
    solar_kwp = float(best_scenario["solar_kwp"])
    payback_months = best_scenario.get("payback_months")
    basis_label = _planning_basis_label(best_scenario.get("risk_basis", "expected"))

    payback_text = f"{float(payback_months) / 12:.1f} years" if payback_months is not None else "not available"
    sensitivity_text = (
        "The active-analysis sensitivity varies MD rate, battery CAPEX, and solar CAPEX by 10%. "
        "Growth rate, EV load, and planning months are full-analysis inputs and update when Apply is run."
    )

    flags: list[dict[str, str]] = []
    row_count = int(validation.get("row_count", 0) or 0)
    gap_count = int(validation.get("gap_count", 0) or 0)
    missing_count = int(validation.get("missing_value_count", 0) or 0)
    planning_months = int(assumptions.get("planning_months", 1) or 1)

    flags.append(
        {
            "level": "ok" if row_count >= planning_months * 30 * 24 else "watch",
            "label": "History depth",
            "message": f"{row_count:,} normalized intervals support the active {planning_months}-month planning run.",
        }
    )
    flags.append(
        {
            "level": "ok" if gap_count == 0 else "watch",
            "label": "Interval gaps",
            "message": "No interval gaps were detected." if gap_count == 0 else f"{gap_count:,} interval gaps may affect peak timing.",
        }
    )
    flags.append(
        {
            "level": "ok" if missing_count == 0 else "watch",
            "label": "Missing values",
            "message": "No missing values were detected."
            if missing_count == 0
            else f"{missing_count:,} missing values were found during validation.",
        }
    )

    if not sensitivity.empty and "savings_rm" in sensitivity.columns:
        savings_column = "annual_savings_rm" if "annual_savings_rm" in sensitivity.columns else "savings_rm"
        min_savings = float(sensitivity[savings_column].min())
        max_savings = float(sensitivity[savings_column].max())
        sensitivity_text = (
            f"Across the active +/-10% tariff and CAPEX checks, savings range from "
            f"RM {min_savings:,.0f}/yr to RM {max_savings:,.0f}/yr versus RM {annual_savings:,.0f}/yr under current assumptions. "
            "Growth rate, EV load, and planning months update through a full Apply rerun."
        )

    return {
        "planning_basis_label": basis_label,
        "planning_basis_description": (
            "PeakLogic sizes the recommendation against high-demand periods so the selected plan is judged on peak-charge protection, "
            "not only average forecast accuracy."
        ),
        "what_changed": (
            f"For {site_id}, the selected scenario lowers the modeled bill from RM {bill_before:,.0f} "
            f"to RM {bill_after:,.0f} across the {period_months}-month planning period, saves RM {savings:,.0f} "
            f"in-period or RM {annual_savings:,.0f}/yr annualized, and reduces MD from {md_before:.0f} kW to {md_after:.0f} kW."
        ),
        "why_this_scenario": (
            f"The selected mix uses {battery_kw:.0f} kW / {battery_kwh:.0f} kWh battery capacity"
            f"{' plus ' + format(solar_kwp, '.0f') + ' kWp solar' if solar_kwp > 0 else ''} because it gives the strongest savings result "
            f"with RM {capex:,.0f} estimated CAPEX, RM {monthly_savings:,.0f} average monthly savings, "
            f"and an estimated payback of {payback_text} under the active assumptions."
        ),
        "savings_sensitivity": sensitivity_text,
        "confidence_flags": flags,
    }
