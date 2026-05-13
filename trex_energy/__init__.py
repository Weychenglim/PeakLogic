"""TREX competition app package."""

from .forecasting import (
    ForecastBacktestResult,
    AdaptiveP90Calibration,
    GatedP50CorrectionPolicy,
    MdRiskUpliftPolicy,
    MonthlyMDRiskCalibrator,
    apply_monthly_md_risk_calibration,
    backtest_md_stress_windows,
    backtest_site_forecast,
    evaluate_p90_calibration_candidates,
    fit_monthly_md_risk_calibrator,
    fit_adaptive_p90_calibration,
    forecast_adaptive_p90_planning_profile,
    forecast_corrected_long_horizon_profile,
    forecast_full_ml_planning_profile,
    forecast_gated_ml_planning_profile,
    forecast_long_horizon_model_profile,
    forecast_ml_md_risk_profile,
    forecast_next_intervals,
)
from .ingestion import SiteMetadata, load_site_workbook
from .optimization import OptimizationConfig, OptimizationResult, evaluate_risk_basis_tradeoff, evaluate_site_scenarios
from .reporting import build_executive_summary_text, build_site_comparison_summary, dataframe_to_csv_bytes
from .tariff import BillBreakdown, TariffConfig, calculate_bill_components
from .validation import ValidationReport, validate_intervals

__all__ = [
    "AdaptiveP90Calibration",
    "BillBreakdown",
    "ForecastBacktestResult",
    "GatedP50CorrectionPolicy",
    "MonthlyMDRiskCalibrator",
    "MdRiskUpliftPolicy",
    "OptimizationConfig",
    "OptimizationResult",
    "SiteMetadata",
    "TariffConfig",
    "ValidationReport",
    "apply_monthly_md_risk_calibration",
    "backtest_md_stress_windows",
    "backtest_site_forecast",
    "build_executive_summary_text",
    "build_site_comparison_summary",
    "calculate_bill_components",
    "dataframe_to_csv_bytes",
    "evaluate_site_scenarios",
    "evaluate_risk_basis_tradeoff",
    "evaluate_p90_calibration_candidates",
    "fit_adaptive_p90_calibration",
    "fit_monthly_md_risk_calibrator",
    "forecast_adaptive_p90_planning_profile",
    "forecast_corrected_long_horizon_profile",
    "forecast_full_ml_planning_profile",
    "forecast_gated_ml_planning_profile",
    "forecast_long_horizon_model_profile",
    "forecast_ml_md_risk_profile",
    "forecast_next_intervals",
    "load_site_workbook",
    "validate_intervals",
]
