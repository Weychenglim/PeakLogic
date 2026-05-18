from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Iterable

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


BASELINE_FEATURE_COLUMNS = [
    "hour",
    "day_of_week",
    "month",
    "is_weekend",
    "has_solar",
    "lag_1",
    "lag_2",
    "lag_48",
    "rolling_mean_4",
    "rolling_mean_48",
]

LAG_WINDOWS = [1, 2, 3, 6, 24, 48, 96, 336, 672]
ROLL_WINDOWS = [4, 24, 48]
PLANNING_INTERVALS_PER_MONTH = 30 * 48
LONG_HORIZON_MIN_HISTORY = 21 * 48
LONG_HORIZON_TRAINING_HORIZON = 30 * 48
KNOWN_BUNDLED_SOLAR_KWP = {
    "1. Load Profile (With Solar Installed) SoL": 944.880,
    "1. Load Profile (With Solar Installed) SoL.xlsx": 944.880,
    "4. Load Profile (With Solar) Mi2": 944.880,
    "4. Load Profile (With Solar) Mi2.xlsx": 944.880,
}


@dataclass(frozen=True)
class ForecastBacktestResult:
    predictions: pd.DataFrame
    metrics: dict[str, float]


@dataclass(frozen=True)
class MonthlyPlanningBacktestResult:
    predictions: pd.DataFrame
    metrics: dict[str, float]


@dataclass(frozen=True)
class MonthlyMDRiskCalibrator:
    uplift_factor: float
    intercept_kw: float
    training_folds: int
    coverage_before_pct: float
    coverage_after_pct: float


@dataclass(frozen=True)
class AdaptiveP90Calibration:
    recent_days: int
    p90_floor_multiplier: float
    stress_folds: int
    stress_coverage_pct: float
    stress_md_abs_error_kw: float
    stress_bias_kw: float
    score: float


@dataclass(frozen=True)
class MdRiskUpliftPolicy:
    p90_min_ratio: float = 0.90
    p90_max_ratio: float = 1.08
    p95_min_ratio: float = 0.90
    p95_max_ratio: float = 1.04
    low_risk_threshold: float = 0.35
    low_risk_max_ratio: float = 1.01
    timing_active_quantile: float = 0.88


@dataclass(frozen=True)
class GatedP50CorrectionPolicy:
    confidence_threshold: float = 0.55
    active_quantile: float = 0.88
    correction_strength: float = 0.30
    correction_cap_ratio: float = 0.04
    min_delta_ratio: float = 0.015


@dataclass(frozen=True)
class MonthlyMDCorrectionPolicy:
    p50_min_ratio: float = 0.88
    p50_max_ratio: float = 1.18
    p90_min_ratio: float = 0.90
    p90_max_ratio: float = 1.10
    p95_min_ratio: float = 0.92
    p95_max_ratio: float = 1.08
    p50_correction_strength: float = 0.25
    risk_correction_strength: float = 0.25
    active_quantile: float = 0.94


@dataclass(frozen=True)
class TrainedRidge:
    model: Pipeline
    feature_columns: list[str]
    alpha: float
    alpha_scores: pd.DataFrame
    normalize_targets: bool


def clear_sky_sine_solar_factor(timestamp: pd.Timestamp) -> float:
    hour = timestamp.hour + timestamp.minute / 60.0
    if hour <= 6.0 or hour >= 18.0:
        return 0.0
    return float(np.sin(np.pi * (hour - 6.0) / 12.0))


def resolve_existing_pv_kwp(
    *,
    site_id: str,
    source_file: str,
    has_solar: bool,
    user_existing_pv_kwp: float | None = None,
    metadata_existing_pv_kwp: float | None = None,
) -> float:
    if user_existing_pv_kwp is not None:
        return max(0.0, float(user_existing_pv_kwp))
    if metadata_existing_pv_kwp is not None:
        return max(0.0, float(metadata_existing_pv_kwp))
    if not has_solar:
        return 0.0
    return float(KNOWN_BUNDLED_SOLAR_KWP.get(source_file, KNOWN_BUNDLED_SOLAR_KWP.get(site_id, 0.0)))


def _add_peak_flags(forecast: pd.DataFrame) -> pd.DataFrame:
    tagged = forecast.copy()
    max_forecast = float(tagged["forecast_kw_import"].max()) if not tagged.empty else 0.0
    tagged["peak_risk_score"] = tagged["forecast_kw_import"] / max_forecast if max_forecast > 0 else 0.0
    threshold = tagged["forecast_kw_import"].quantile(0.9) if not tagged.empty else 0.0
    tagged["is_predicted_peak"] = tagged["forecast_kw_import"] >= threshold
    return tagged


def _add_planning_peak_flags(forecast: pd.DataFrame) -> pd.DataFrame:
    tagged = forecast.copy()
    score_basis = tagged["md_risk_envelope_kw"] if "md_risk_envelope_kw" in tagged.columns else tagged["forecast_kw_import"]
    max_risk = float(score_basis.max()) if not tagged.empty else 0.0
    tagged["peak_risk_score"] = score_basis / max_risk if max_risk > 0 else 0.0
    threshold = score_basis.quantile(0.9) if not tagged.empty else 0.0
    tagged["is_predicted_peak"] = score_basis >= threshold
    return _add_peak_risk_overlay(tagged)


def _normalized_score(series: pd.Series) -> pd.Series:
    values = series.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    lower = float(values.min()) if not values.empty else 0.0
    upper = float(values.max()) if not values.empty else 0.0
    if upper <= lower:
        return pd.Series(0.0, index=values.index)
    return (values - lower) / (upper - lower)


def _add_peak_risk_overlay(forecast: pd.DataFrame) -> pd.DataFrame:
    tagged = forecast.copy()
    if tagged.empty:
        tagged["peak_risk_overlay_score"] = []
        tagged["is_peak_risk_overlay"] = []
        return tagged

    risk_basis = tagged.get("md_risk_envelope_kw", tagged["forecast_kw_import"]).astype(float)
    expected = tagged.get("p50_forecast_kw", tagged["forecast_kw_import"]).astype(float)
    envelope_gap = (risk_basis - expected).clip(lower=0.0)
    ramp = risk_basis.diff().fillna(0.0).clip(lower=0.0)
    hour = tagged["interval_end"].dt.hour
    night_window = ((hour >= 18) | (hour < 6)).astype(float)
    floor_applied = (
        tagged["late_night_peak_floor_applied"].astype(float)
        if "late_night_peak_floor_applied" in tagged.columns
        else pd.Series(0.0, index=tagged.index)
    )

    raw_score = (
        0.52 * _normalized_score(risk_basis)
        + 0.20 * _normalized_score(envelope_gap)
        + 0.12 * _normalized_score(ramp)
        + 0.08 * night_window
        + 0.18 * floor_applied
    )
    smoothed = raw_score.rolling(window=3, min_periods=1, center=True).max()
    tagged["peak_risk_overlay_score"] = _normalized_score(smoothed).clip(lower=0.0, upper=1.0)
    threshold = float(tagged["peak_risk_overlay_score"].quantile(0.80))
    tagged["is_peak_risk_overlay"] = tagged["peak_risk_overlay_score"] >= threshold
    return tagged


def _slot_index(timestamp: pd.Timestamp) -> int:
    return int(timestamp.hour * 2 + timestamp.minute // 30)


def _is_in_hour_window(hour: float, start_hour: int, end_hour: int) -> bool:
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def forecast_monthly_planning_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    recent_days: int = 56,
    risk_quantile: float = 0.95,
    p90_floor_multiplier: float = 1.0,
    md_floor_multiplier: float = 1.03,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
    existing_pv_kwp: float | None = None,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")

    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    site_id = str(ordered["site_id"].iloc[0])
    source_file = str(ordered["source_file"].iloc[0]) if "source_file" in ordered.columns else site_id
    has_solar = bool(ordered["has_solar"].fillna(False).iloc[-1]) if "has_solar" in ordered.columns else False
    metadata_pv_kwp = None
    if "existing_pv_kwp" in ordered.columns:
        pv_values = pd.to_numeric(ordered["existing_pv_kwp"], errors="coerce").dropna()
        if not pv_values.empty:
            metadata_pv_kwp = float(pv_values.iloc[-1])
    resolved_existing_pv_kwp = resolve_existing_pv_kwp(
        site_id=site_id,
        source_file=source_file,
        has_solar=has_solar,
        user_existing_pv_kwp=existing_pv_kwp,
        metadata_existing_pv_kwp=metadata_pv_kwp,
    )
    ordered["estimated_existing_solar_kw"] = ordered["interval_end"].map(
        lambda ts: resolved_existing_pv_kwp * clear_sky_sine_solar_factor(pd.Timestamp(ts))
    )
    ordered["gross_load_kw"] = ordered["kw_import"].astype(float) + ordered["estimated_existing_solar_kw"].astype(float)
    recent_count = min(len(ordered), max(48, int(recent_days * 48)))
    recent = ordered.tail(recent_count).copy()
    recent["slot_index"] = recent["interval_end"].map(lambda ts: _slot_index(pd.Timestamp(ts)))
    recent["day_type"] = recent["interval_end"].dt.dayofweek.map(lambda day: "weekend" if day >= 5 else "weekday")
    forecast_basis = "gross_load_with_existing_solar" if resolved_existing_pv_kwp > 0 else "grid_import"

    grouped = (
        recent.groupby(["day_type", "slot_index"], observed=True)["gross_load_kw"]
        .agg(
            p50_kw="median",
            p90_kw=lambda values: values.quantile(0.90),
            p95_kw=lambda values: values.quantile(0.95),
            envelope_kw=lambda values: values.quantile(risk_quantile),
        )
        .reset_index()
    )
    grouped_lookup = {
        (str(row.day_type), int(row.slot_index)): (
            float(row.p50_kw),
            float(row.p90_kw),
            float(row.p95_kw),
            float(row.envelope_kw),
        )
        for row in grouped.itertuples(index=False)
    }

    slot_fallback = (
        recent.groupby("slot_index", observed=True)["gross_load_kw"]
        .agg(
            p50_kw="median",
            p90_kw=lambda values: values.quantile(0.90),
            p95_kw=lambda values: values.quantile(0.95),
            envelope_kw=lambda values: values.quantile(risk_quantile),
        )
        .reset_index()
    )
    slot_lookup = {
        int(row.slot_index): (
            float(row.p50_kw),
            float(row.p90_kw),
            float(row.p95_kw),
            float(row.envelope_kw),
        )
        for row in slot_fallback.itertuples(index=False)
    }
    global_p50 = float(recent["gross_load_kw"].median())
    global_p90 = float(recent["gross_load_kw"].quantile(0.90))
    global_p95 = float(recent["gross_load_kw"].quantile(0.95))
    global_envelope = float(recent["gross_load_kw"].quantile(risk_quantile))

    last_end = pd.Timestamp(ordered["interval_end"].iloc[-1])
    horizon = months * PLANNING_INTERVALS_PER_MONTH
    growth_multiplier = max(0.0, 1.0 + float(growth_rate_pct) / 100.0)

    recent_md_floor_kw = float(recent["kw_import"].max()) * growth_multiplier
    p90_md_floor_kw = max(0.0, recent_md_floor_kw * float(p90_floor_multiplier))
    p95_md_floor_kw = max(p90_md_floor_kw, recent_md_floor_kw * float(md_floor_multiplier))
    recent_hours = recent["interval_end"].dt.hour
    recent_night_mask = (recent_hours >= 18) | (recent_hours < 6)
    recent_night = recent.loc[recent_night_mask]
    recent_night_peak_kw = float(recent_night["kw_import"].max()) if not recent_night.empty else 0.0
    recent_overall_peak_kw = float(recent["kw_import"].max()) if not recent.empty else 0.0
    night_peak_enabled = (
        not has_solar
        and recent_night_peak_kw > 0.0
        and recent_overall_peak_kw > 0.0
        and recent_night_peak_kw >= 0.85 * recent_overall_peak_kw
        and recent_night_peak_kw > global_p95
    )
    peak_night_slots: set[int] = set()
    if night_peak_enabled:
        peak_rows = recent_night.loc[recent_night["kw_import"] >= 0.95 * recent_night_peak_kw]
        for slot in peak_rows["slot_index"].astype(int).tolist():
            peak_night_slots.update({(slot - 1) % 48, slot, (slot + 1) % 48})

    rows: list[dict[str, object]] = []
    for step in range(1, horizon + 1):
        interval_end = last_end + pd.Timedelta(minutes=30 * step)
        interval_start = interval_end - pd.Timedelta(minutes=30)
        day_type = "weekend" if interval_end.dayofweek >= 5 else "weekday"
        slot = _slot_index(interval_end)
        p50_kw, p90_kw, p95_kw, envelope_kw = grouped_lookup.get(
            (day_type, slot),
            slot_lookup.get(slot, (global_p50, global_p90, global_p95, global_envelope)),
        )

        hour = interval_end.hour + interval_end.minute / 60.0
        ev_adder = float(ev_load_kw) if ev_load_kw > 0 and _is_in_hour_window(hour, ev_start_hour, ev_end_hour) else 0.0
        forecast_existing_solar_kw = resolved_existing_pv_kwp * clear_sky_sine_solar_factor(interval_end)
        gross_p50_kw = max(p50_kw * growth_multiplier + ev_adder, 0.0)
        gross_p90_kw = max(p90_kw * growth_multiplier + ev_adder, gross_p50_kw)
        gross_p95_kw = max(p95_kw * growth_multiplier + ev_adder, gross_p90_kw)
        gross_envelope_kw = max(envelope_kw * growth_multiplier + ev_adder, gross_p90_kw)
        p50_forecast_kw = max(gross_p50_kw - forecast_existing_solar_kw, 0.0)
        p90_md_risk_kw = max(gross_p90_kw - forecast_existing_solar_kw, p50_forecast_kw, 0.0)
        p95_stress_kw = max(gross_p95_kw - forecast_existing_solar_kw, p90_md_risk_kw, 0.0)
        risk_envelope_kw = max(gross_envelope_kw - forecast_existing_solar_kw, p90_md_risk_kw, 0.0)
        is_late_horizon = step > 7 * 48
        is_night_risk_window = hour >= 18 or hour < 6
        slot_is_recent_peak_shape = slot in peak_night_slots
        late_night_shape_score = 0.0
        if night_peak_enabled and is_night_risk_window and slot_is_recent_peak_shape:
            late_night_shape_score = 0.70 + (0.20 if is_late_horizon else 0.0)
        late_night_floor_applied = bool(late_night_shape_score >= 0.80)
        if late_night_floor_applied:
            night_floor_kw = recent_night_peak_kw * growth_multiplier
            p90_md_risk_kw = max(p90_md_risk_kw, night_floor_kw * 0.95, p50_forecast_kw)
            p95_stress_kw = max(p95_stress_kw, night_floor_kw, p90_md_risk_kw)
            risk_envelope_kw = max(risk_envelope_kw, night_floor_kw, p90_md_risk_kw)

        rows.append(
            {
                "site_id": site_id,
                "interval_start": interval_start,
                "interval_end": interval_end,
                "forecast_kw_import": p50_forecast_kw,
                "forecast_gross_load_kw": gross_p50_kw,
                "estimated_existing_solar_kw": forecast_existing_solar_kw,
                "forecast_basis": forecast_basis,
                "md_risk_envelope_kw": p90_md_risk_kw,
                "p50_forecast_kw": p50_forecast_kw,
                "p90_md_risk_kw": p90_md_risk_kw,
                "p95_stress_kw": p95_stress_kw,
                "calibrated_p90_md_risk_kw": p90_md_risk_kw,
                "calibrated_p95_stress_kw": p95_stress_kw,
                "recent_observed_md_floor_kw": recent_md_floor_kw,
                "custom_risk_envelope_kw": risk_envelope_kw,
                "planning_month": ((step - 1) // PLANNING_INTERVALS_PER_MONTH) + 1,
                "planning_method": "recent_pattern_simulation",
                "growth_multiplier": growth_multiplier,
                "ev_load_kw": ev_adder,
                "late_night_peak_shape_score": late_night_shape_score,
                "late_night_peak_floor_applied": late_night_floor_applied,
            }
        )

    forecast = pd.DataFrame(rows)
    for _, indices in forecast.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        p90_peak_idx = forecast.loc[month_indices, "calibrated_p90_md_risk_kw"].idxmax()
        p95_peak_idx = forecast.loc[month_indices, "calibrated_p95_stress_kw"].idxmax()
        forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"] = max(
            float(forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"]),
            p90_md_floor_kw,
        )
        forecast.at[p95_peak_idx, "calibrated_p95_stress_kw"] = max(
            float(forecast.at[p95_peak_idx, "calibrated_p95_stress_kw"]),
            p95_md_floor_kw,
            float(forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"]),
        )

    forecast["md_risk_envelope_kw"] = forecast["calibrated_p95_stress_kw"]
    return _add_planning_peak_flags(forecast)


def backtest_monthly_planning_profile(
    frame: pd.DataFrame,
    train_days: int = 21,
    horizon_days: int = 30,
    step_days: int = 15,
    max_folds: int = 4,
    recent_days: int = 56,
    p90_floor_multiplier: float = 1.0,
    md_floor_multiplier: float = 1.03,
) -> MonthlyPlanningBacktestResult:
    ordered = frame.sort_values("interval_end").reset_index(drop=True)
    if ordered.empty:
        raise ValueError("Target frame is empty")

    train_intervals = int(train_days * 48)
    horizon_intervals = int(horizon_days * 48)
    step_intervals = int(step_days * 48)
    if min(train_intervals, horizon_intervals, step_intervals) <= 0:
        raise ValueError("train_days, horizon_days, and step_days must be positive")
    if len(ordered) < train_intervals + horizon_intervals:
        raise ValueError("Not enough rows to run monthly planning backtest")

    cutoffs = list(range(train_intervals, len(ordered) - horizon_intervals + 1, step_intervals))
    if len(cutoffs) > max_folds:
        cutoffs = cutoffs[-max_folds:]

    rows: list[dict[str, object]] = []
    for fold_index, cutoff in enumerate(cutoffs, start=1):
        train_frame = ordered.iloc[:cutoff].copy()
        actual_frame = ordered.iloc[cutoff : cutoff + horizon_intervals].copy()
        forecast = forecast_monthly_planning_profile(
            train_frame,
            months=1,
            recent_days=recent_days,
            p90_floor_multiplier=p90_floor_multiplier,
            md_floor_multiplier=md_floor_multiplier,
        ).head(len(actual_frame))

        actual_md_kw = float(actual_frame["kw_import"].max())
        p50_md_kw = float(forecast["p50_forecast_kw"].max())
        raw_p90_md_kw = float(forecast["p90_md_risk_kw"].max())
        raw_p95_md_kw = float(forecast["p95_stress_kw"].max())
        p90_md_kw = float(forecast["calibrated_p90_md_risk_kw"].max())
        p95_md_kw = float(forecast["calibrated_p95_stress_kw"].max())

        rows.append(
            {
                "fold": fold_index,
                "train_start": train_frame["interval_end"].iloc[0],
                "train_end": train_frame["interval_end"].iloc[-1],
                "actual_start": actual_frame["interval_end"].iloc[0],
                "actual_end": actual_frame["interval_end"].iloc[-1],
                "actual_md_kw": actual_md_kw,
                "p50_md_kw": p50_md_kw,
                "p90_md_kw": p90_md_kw,
                "p95_md_kw": p95_md_kw,
                "raw_p90_md_kw": raw_p90_md_kw,
                "raw_p95_md_kw": raw_p95_md_kw,
                "calibrated_p90_md_kw": p90_md_kw,
                "calibrated_p95_md_kw": p95_md_kw,
                "p50_md_error_kw": p50_md_kw - actual_md_kw,
                "p90_md_error_kw": p90_md_kw - actual_md_kw,
                "p95_md_error_kw": p95_md_kw - actual_md_kw,
                "p90_coverage": bool(p90_md_kw >= actual_md_kw),
                "p95_coverage": bool(p95_md_kw >= actual_md_kw),
                "recent_days": int(recent_days),
                "p90_floor_multiplier": float(p90_floor_multiplier),
                "md_floor_multiplier": float(md_floor_multiplier),
            }
        )

    predictions = pd.DataFrame(rows)
    metrics = {
        "folds": float(len(predictions)),
        "p50_md_abs_error_kw": float(predictions["p50_md_error_kw"].abs().mean()),
        "p90_md_abs_error_kw": float(predictions["p90_md_error_kw"].abs().mean()),
        "p95_md_abs_error_kw": float(predictions["p95_md_error_kw"].abs().mean()),
        "p50_md_bias_kw": float(predictions["p50_md_error_kw"].mean()),
        "p90_md_bias_kw": float(predictions["p90_md_error_kw"].mean()),
        "p95_md_bias_kw": float(predictions["p95_md_error_kw"].mean()),
        "p90_coverage_pct": float(predictions["p90_coverage"].mean() * 100.0),
        "p95_coverage_pct": float(predictions["p95_coverage"].mean() * 100.0),
    }
    return MonthlyPlanningBacktestResult(predictions=predictions, metrics=metrics)


def fit_monthly_md_risk_calibrator(
    frame: pd.DataFrame,
    train_days: int = 21,
    horizon_days: int = 30,
    step_days: int = 15,
    max_folds: int = 4,
) -> MonthlyMDRiskCalibrator:
    """Learn a conservative monthly-MD uplift from historical planning folds."""
    backtest = backtest_monthly_planning_profile(
        frame,
        train_days=train_days,
        horizon_days=horizon_days,
        step_days=step_days,
        max_folds=max_folds,
    )
    predictions = backtest.predictions.copy()
    if predictions.empty:
        raise ValueError("No monthly planning folds were produced")

    actual_md = predictions["actual_md_kw"].astype(float).to_numpy()
    predicted_md = predictions["calibrated_p95_md_kw"].astype(float).clip(lower=1e-6).to_numpy()
    ratios = actual_md / predicted_md
    uplift_factor = float(max(1.0, np.quantile(ratios, 0.90)))

    residuals = actual_md - (predicted_md * uplift_factor)
    intercept_kw = float(max(0.0, np.quantile(residuals, 0.90)))

    if len(predictions) >= 2:
        model = LinearRegression()
        model.fit(predicted_md.reshape(-1, 1), actual_md)
        uplift_factor = float(max(uplift_factor, float(model.coef_[0]), 1.0))
        intercept_kw = float(max(intercept_kw, float(model.intercept_), 0.0))

    adjusted_md = np.maximum(predicted_md, predicted_md * uplift_factor + intercept_kw)
    coverage_before_pct = float(np.mean(predicted_md >= actual_md) * 100.0)
    coverage_after_pct = float(np.mean(adjusted_md >= actual_md) * 100.0)

    return MonthlyMDRiskCalibrator(
        uplift_factor=uplift_factor,
        intercept_kw=intercept_kw,
        training_folds=int(len(predictions)),
        coverage_before_pct=coverage_before_pct,
        coverage_after_pct=coverage_after_pct,
    )


def apply_monthly_md_risk_calibration(
    forecast: pd.DataFrame,
    calibrator: MonthlyMDRiskCalibrator,
) -> pd.DataFrame:
    calibrated = forecast.copy()
    if "calibrated_p95_stress_kw" in calibrated.columns:
        source_column = "calibrated_p95_stress_kw"
    elif "md_risk_envelope_kw" in calibrated.columns:
        source_column = "md_risk_envelope_kw"
    else:
        raise ValueError("Forecast must include a calibrated p95 or MD-risk envelope column")

    source_values = calibrated[source_column].astype(float)
    adjusted_values = np.maximum(
        source_values,
        source_values * float(calibrator.uplift_factor) + float(calibrator.intercept_kw),
    )
    calibrated["calibrated_p95_stress_kw"] = adjusted_values
    calibrated["md_risk_envelope_kw"] = adjusted_values
    if "calibrated_p90_md_risk_kw" in calibrated.columns and "p90_md_risk_kw" in calibrated.columns:
        calibrated["calibrated_p90_md_risk_kw"] = np.maximum(
            calibrated["calibrated_p90_md_risk_kw"].astype(float),
            calibrated["p90_md_risk_kw"].astype(float),
        )
    calibrated["md_risk_calibration_method"] = "trained_monthly_md_risk_calibrator"
    calibrated["md_risk_calibration_uplift_factor"] = float(calibrator.uplift_factor)
    calibrated["md_risk_calibration_intercept_kw"] = float(calibrator.intercept_kw)
    calibrated["md_risk_calibration_training_folds"] = int(calibrator.training_folds)
    calibrated["md_risk_calibration_coverage_before_pct"] = float(calibrator.coverage_before_pct)
    calibrated["md_risk_calibration_coverage_after_pct"] = float(calibrator.coverage_after_pct)
    return _add_planning_peak_flags(calibrated)


def backtest_md_stress_windows(
    frame: pd.DataFrame,
    window_days: Iterable[int] = (7, 14),
    train_days: int = 21,
    step_days: int = 7,
    max_folds: int = 8,
    recent_days: int = 56,
    p90_floor_multiplier: float = 1.0,
    md_floor_multiplier: float = 1.03,
) -> pd.DataFrame:
    rows: list[dict[str, float | int | str]] = []
    for days in window_days:
        horizon_days = int(days)
        if horizon_days <= 0:
            raise ValueError("window_days must contain positive integers")
        result = backtest_monthly_planning_profile(
            frame,
            train_days=train_days,
            horizon_days=horizon_days,
            step_days=step_days,
            max_folds=max_folds,
            recent_days=recent_days,
            p90_floor_multiplier=p90_floor_multiplier,
            md_floor_multiplier=md_floor_multiplier,
        )
        rows.append(
            {
                "validation_type": "rolling_stress_window",
                "window_days": horizon_days,
                "recent_days": int(recent_days),
                "p90_floor_multiplier": float(p90_floor_multiplier),
                "folds": int(result.metrics["folds"]),
                "p50_md_abs_error_kw": float(result.metrics["p50_md_abs_error_kw"]),
                "p90_md_abs_error_kw": float(result.metrics["p90_md_abs_error_kw"]),
                "p95_md_abs_error_kw": float(result.metrics["p95_md_abs_error_kw"]),
                "p50_md_bias_kw": float(result.metrics["p50_md_bias_kw"]),
                "p90_md_bias_kw": float(result.metrics["p90_md_bias_kw"]),
                "p95_md_bias_kw": float(result.metrics["p95_md_bias_kw"]),
                "p90_coverage_pct": float(result.metrics["p90_coverage_pct"]),
                "p95_coverage_pct": float(result.metrics["p95_coverage_pct"]),
            }
        )
    return pd.DataFrame(rows)


def evaluate_p90_calibration_candidates(
    frame: pd.DataFrame,
    recent_days_options: Iterable[int] = (21, 28, 42, 56),
    p90_floor_multipliers: Iterable[float] = (1.0, 1.02, 1.05, 1.08),
    stress_window_days: Iterable[int] = (7, 14),
    train_days: int = 21,
    step_days: int = 7,
    max_folds: int = 8,
    target_coverage_pct: float = 90.0,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for recent_days in recent_days_options:
        for p90_floor_multiplier in p90_floor_multipliers:
            stress = backtest_md_stress_windows(
                frame,
                window_days=stress_window_days,
                train_days=train_days,
                step_days=step_days,
                max_folds=max_folds,
                recent_days=int(recent_days),
                p90_floor_multiplier=float(p90_floor_multiplier),
            )
            stress_folds = int(stress["folds"].sum())
            coverage_pct = float(np.average(stress["p90_coverage_pct"], weights=stress["folds"]))
            md_abs_error_kw = float(np.average(stress["p90_md_abs_error_kw"], weights=stress["folds"]))
            bias_kw = float(np.average(stress["p90_md_bias_kw"], weights=stress["folds"]))
            coverage_shortfall = max(0.0, float(target_coverage_pct) - coverage_pct)
            positive_bias = max(0.0, bias_kw)
            score = coverage_shortfall * 1000.0 + md_abs_error_kw + positive_bias * 0.25
            rows.append(
                {
                    "recent_days": int(recent_days),
                    "p90_floor_multiplier": float(p90_floor_multiplier),
                    "stress_folds": stress_folds,
                    "stress_coverage_pct": coverage_pct,
                    "stress_md_abs_error_kw": md_abs_error_kw,
                    "stress_bias_kw": bias_kw,
                    "coverage_shortfall_pct": coverage_shortfall,
                    "score": float(score),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["score", "stress_md_abs_error_kw", "p90_floor_multiplier"],
        ascending=[True, True, True],
    ).reset_index(drop=True)


def fit_adaptive_p90_calibration(
    frame: pd.DataFrame,
    recent_days_options: Iterable[int] = (21, 28, 42, 56),
    p90_floor_multipliers: Iterable[float] = (1.0, 1.02, 1.05, 1.08),
    stress_window_days: Iterable[int] = (7, 14),
    train_days: int = 21,
    step_days: int = 7,
    max_folds: int = 8,
    target_coverage_pct: float = 90.0,
) -> AdaptiveP90Calibration:
    candidates = evaluate_p90_calibration_candidates(
        frame,
        recent_days_options=recent_days_options,
        p90_floor_multipliers=p90_floor_multipliers,
        stress_window_days=stress_window_days,
        train_days=train_days,
        step_days=step_days,
        max_folds=max_folds,
        target_coverage_pct=target_coverage_pct,
    )
    if candidates.empty:
        raise ValueError("No adaptive p90 calibration candidates were produced")

    best = candidates.iloc[0]
    return AdaptiveP90Calibration(
        recent_days=int(best["recent_days"]),
        p90_floor_multiplier=float(best["p90_floor_multiplier"]),
        stress_folds=int(best["stress_folds"]),
        stress_coverage_pct=float(best["stress_coverage_pct"]),
        stress_md_abs_error_kw=float(best["stress_md_abs_error_kw"]),
        stress_bias_kw=float(best["stress_bias_kw"]),
        score=float(best["score"]),
    )


def forecast_adaptive_p90_planning_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    calibration: AdaptiveP90Calibration | None = None,
    recent_days_options: Iterable[int] = (21, 28, 42, 56),
    p90_floor_multipliers: Iterable[float] = (1.0, 1.02, 1.05, 1.08),
    stress_window_days: Iterable[int] = (7, 14),
    train_days: int = 21,
    step_days: int = 7,
    max_folds: int = 8,
    target_coverage_pct: float = 90.0,
    **forecast_kwargs: object,
) -> pd.DataFrame:
    selected = calibration or fit_adaptive_p90_calibration(
        target_frame,
        recent_days_options=recent_days_options,
        p90_floor_multipliers=p90_floor_multipliers,
        stress_window_days=stress_window_days,
        train_days=train_days,
        step_days=step_days,
        max_folds=max_folds,
        target_coverage_pct=target_coverage_pct,
    )
    forecast = forecast_monthly_planning_profile(
        target_frame,
        months=months,
        recent_days=selected.recent_days,
        p90_floor_multiplier=selected.p90_floor_multiplier,
        **forecast_kwargs,
    )
    forecast["adaptive_p90_recent_days"] = int(selected.recent_days)
    forecast["adaptive_p90_floor_multiplier"] = float(selected.p90_floor_multiplier)
    forecast["adaptive_p90_stress_folds"] = int(selected.stress_folds)
    forecast["adaptive_p90_stress_coverage_pct"] = float(selected.stress_coverage_pct)
    forecast["adaptive_p90_stress_md_abs_error_kw"] = float(selected.stress_md_abs_error_kw)
    forecast["adaptive_p90_stress_bias_kw"] = float(selected.stress_bias_kw)
    forecast["adaptive_p90_score"] = float(selected.score)
    return forecast


def _safe_quantile(values: pd.Series, quantile: float, default: float) -> float:
    numeric = pd.to_numeric(values, errors="coerce").dropna().astype(float)
    if numeric.empty:
        return float(default)
    return float(numeric.quantile(quantile))


def _long_horizon_context(history_frame: pd.DataFrame, site_scale: float) -> dict[str, object]:
    history = history_frame.sort_values("interval_end").reset_index(drop=True).copy()
    recent_count = min(len(history), 56 * 48)
    recent = history.tail(recent_count).copy()
    recent_values = pd.to_numeric(recent["kw_import"], errors="coerce").astype(float)
    global_median = float(recent_values.median()) if not recent_values.empty else 0.0
    scale = max(float(site_scale), 1.0)

    recent["slot_index"] = recent["interval_end"].map(lambda ts: _slot_index(pd.Timestamp(ts)))
    recent["day_type"] = recent["interval_end"].dt.dayofweek.map(lambda day: 1.0 if day >= 5 else 0.0)
    slot_stats = {
        int(slot): (
            _safe_quantile(group["kw_import"], 0.50, global_median) / scale,
            _safe_quantile(group["kw_import"], 0.90, global_median) / scale,
            _safe_quantile(group["kw_import"], 0.95, global_median) / scale,
        )
        for slot, group in recent.groupby("slot_index", observed=True)
    }
    day_slot_stats = {
        (float(day_type), int(slot)): (
            _safe_quantile(group["kw_import"], 0.50, global_median) / scale,
            _safe_quantile(group["kw_import"], 0.90, global_median) / scale,
        )
        for (day_type, slot), group in recent.groupby(["day_type", "slot_index"], observed=True)
    }

    recent_48 = recent_values.tail(48)
    recent_336 = recent_values.tail(336)
    recent_1344 = recent_values.tail(1344)
    recent_7d_mean = float(recent_336.mean()) if not recent_336.empty else global_median
    recent_28d = recent_values.tail(28 * 48)
    recent_28d_mean = float(recent_28d.mean()) if not recent_28d.empty else recent_7d_mean
    lookup = {
        pd.Timestamp(row.interval_end): float(row.kw_import)
        for row in history.loc[:, ["interval_end", "kw_import"]].itertuples(index=False)
    }

    return {
        "history": history,
        "lookup": lookup,
        "global_median": global_median,
        "scale": scale,
        "has_solar": float(bool(history["has_solar"].iloc[-1])) if "has_solar" in history else 0.0,
        "recent_mean_48": float(recent_48.mean()) / scale if not recent_48.empty else global_median / scale,
        "recent_mean_336": recent_7d_mean / scale,
        "recent_max_336": float(recent_336.max()) / scale if not recent_336.empty else global_median / scale,
        "recent_p90_1344": _safe_quantile(recent_1344, 0.90, global_median) / scale,
        "recent_p95_1344": _safe_quantile(recent_1344, 0.95, global_median) / scale,
        "recent_std_336": float(recent_336.std()) / scale if len(recent_336) > 1 else 0.0,
        "recent_trend_7d_vs_28d": (recent_7d_mean - recent_28d_mean) / scale,
        "slot_stats": slot_stats,
        "day_slot_stats": day_slot_stats,
    }


def _long_horizon_feature_row_from_context(
    context: dict[str, object],
    next_end: pd.Timestamp,
    horizon_step: int,
) -> dict[str, float]:
    global_median = float(context["global_median"])
    scale = float(context["scale"])
    lookup = context["lookup"]
    assert isinstance(lookup, dict)
    slot_stats = context["slot_stats"]
    day_slot_stats = context["day_slot_stats"]
    assert isinstance(slot_stats, dict)
    assert isinstance(day_slot_stats, dict)

    slot = _slot_index(next_end)
    day_type = 1.0 if next_end.dayofweek >= 5 else 0.0
    slot_p50, slot_p90, slot_p95 = slot_stats.get(
        slot,
        (global_median / scale, global_median / scale, global_median / scale),
    )
    daytype_slot_p50, daytype_slot_p90 = day_slot_stats.get((day_type, slot), (slot_p50, slot_p90))

    def lag_at(delta: pd.Timedelta, fallback: float) -> float:
        value = lookup.get(next_end - delta, fallback)
        return float(value) if pd.notna(value) else float(fallback)

    hour = next_end.hour + next_end.minute / 60.0
    day_of_week = float(next_end.dayofweek)
    month = float(next_end.month)
    return {
        "horizon_step": float(horizon_step),
        "horizon_day": float((horizon_step - 1) // 48),
        "hour_sin": float(np.sin(2 * np.pi * hour / 24.0)),
        "hour_cos": float(np.cos(2 * np.pi * hour / 24.0)),
        "dow_sin": float(np.sin(2 * np.pi * day_of_week / 7.0)),
        "dow_cos": float(np.cos(2 * np.pi * day_of_week / 7.0)),
        "month_sin": float(np.sin(2 * np.pi * month / 12.0)),
        "month_cos": float(np.cos(2 * np.pi * month / 12.0)),
        "is_weekend": float(next_end.dayofweek >= 5),
        "daylight": float(6 <= hour < 18),
        "tariff_peak": float(14 <= hour < 22),
        "has_solar_int": float(context["has_solar"]),
        "site_scale_kw": scale,
        "recent_mean_48": float(context["recent_mean_48"]),
        "recent_mean_336": float(context["recent_mean_336"]),
        "recent_max_336": float(context["recent_max_336"]),
        "recent_p90_1344": float(context["recent_p90_1344"]),
        "recent_p95_1344": float(context["recent_p95_1344"]),
        "recent_std_336": float(context["recent_std_336"]),
        "slot_p50": slot_p50,
        "slot_p90": slot_p90,
        "slot_p95": slot_p95,
        "daytype_slot_p50": daytype_slot_p50,
        "daytype_slot_p90": daytype_slot_p90,
        "same_slot_prev_day": lag_at(pd.Timedelta(days=1), global_median) / scale,
        "same_slot_prev_week": lag_at(pd.Timedelta(days=7), global_median) / scale,
        "recent_trend_7d_vs_28d": float(context["recent_trend_7d_vs_28d"]),
    }


def _long_horizon_feature_row(
    history_frame: pd.DataFrame,
    next_end: pd.Timestamp,
    horizon_step: int,
    site_scale: float,
) -> dict[str, float]:
    context = _long_horizon_context(history_frame, site_scale)
    return _long_horizon_feature_row_from_context(context, next_end, horizon_step)


def _build_long_horizon_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 12000,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        if len(ordered) <= LONG_HORIZON_MIN_HISTORY + 48:
            continue

        site_scale = site_scale_from_frame(ordered)
        cutoffs = range(LONG_HORIZON_MIN_HISTORY, len(ordered) - 1, 336)
        for cutoff in cutoffs:
            history = ordered.iloc[:cutoff].copy()
            context = _long_horizon_context(history, site_scale)
            max_future = min(len(ordered), cutoff + LONG_HORIZON_TRAINING_HORIZON)
            for actual_index in range(cutoff, max_future, 48):
                actual = ordered.iloc[actual_index]
                horizon_step = int(actual_index - cutoff + 1)
                feature_row = _long_horizon_feature_row_from_context(context, pd.Timestamp(actual["interval_end"]), horizon_step)
                target = float(actual["kw_import"]) / max(site_scale, 1.0)
                if np.isfinite(target):
                    rows.append({**feature_row, "target_kw_import_norm": target})
                if len(rows) >= max_training_rows:
                    break
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No long-horizon model training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if len(training_rows) > max_training_rows:
        indices = np.linspace(0, len(training_rows) - 1, max_training_rows).round().astype(int)
        training_rows = training_rows.iloc[indices].reset_index(drop=True)

    target = training_rows["target_kw_import_norm"].astype(float)
    training_rows["target_kw_import_norm"] = target.clip(
        lower=float(target.quantile(0.005)),
        upper=float(target.quantile(0.995)),
    )
    feature_columns = [column for column in training_rows.columns if column != "target_kw_import_norm"]
    return training_rows, feature_columns


def _fit_long_horizon_models(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[float, LGBMRegressor]:
    models: dict[float, LGBMRegressor] = {}
    for quantile in (0.50, 0.90, 0.95):
        model = LGBMRegressor(
            objective="quantile",
            alpha=quantile,
            n_estimators=60,
            learning_rate=0.06,
            num_leaves=15,
            min_child_samples=20,
            reg_lambda=0.02,
            n_jobs=1,
            verbosity=-1,
            random_state=17,
        )
        model.fit(training_rows[feature_columns], training_rows["target_kw_import_norm"])
        models[quantile] = model
    return models


def forecast_long_horizon_model_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 2400,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        return forecast_monthly_planning_profile(
            target_frame,
            months=months,
            growth_rate_pct=growth_rate_pct,
            ev_load_kw=ev_load_kw,
            ev_start_hour=ev_start_hour,
            ev_end_hour=ev_end_hour,
        )

    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    frames = list(reference_frames or []) + [ordered]
    try:
        training_rows, feature_columns = _build_long_horizon_training_rows(
            frames,
            max_training_rows=max_training_rows,
        )
        if len(training_rows) < 200:
            raise ValueError("Not enough long-horizon training rows")
        models = _fit_long_horizon_models(training_rows, feature_columns)
    except ValueError:
        return forecast_monthly_planning_profile(
            target_frame,
            months=months,
            growth_rate_pct=growth_rate_pct,
            ev_load_kw=ev_load_kw,
            ev_start_hour=ev_start_hour,
            ev_end_hour=ev_end_hour,
        )

    site_scale = site_scale_from_frame(ordered)
    site_id = str(ordered["site_id"].iloc[0])
    last_end = pd.Timestamp(ordered["interval_end"].iloc[-1])
    horizon = months * PLANNING_INTERVALS_PER_MONTH
    growth_multiplier = max(0.0, 1.0 + float(growth_rate_pct) / 100.0)
    recent_md_floor_kw = float(ordered.tail(min(len(ordered), 56 * 48))["kw_import"].max())

    rows: list[dict[str, object]] = []
    forecast_context = _long_horizon_context(ordered, site_scale)
    for step in range(1, horizon + 1):
        interval_end = last_end + pd.Timedelta(minutes=30 * step)
        feature_row = _long_horizon_feature_row_from_context(forecast_context, interval_end, step)
        feature_frame = pd.DataFrame([feature_row], columns=feature_columns).fillna(0.0)

        hour = interval_end.hour + interval_end.minute / 60.0
        ev_adder = float(ev_load_kw) if ev_load_kw > 0 and _is_in_hour_window(hour, ev_start_hour, ev_end_hour) else 0.0
        p50 = max(float(models[0.50].predict(feature_frame)[0]) * site_scale * growth_multiplier + ev_adder, 0.0)
        p90 = max(float(models[0.90].predict(feature_frame)[0]) * site_scale * growth_multiplier + ev_adder, p50)
        p95 = max(float(models[0.95].predict(feature_frame)[0]) * site_scale * growth_multiplier + ev_adder, p90)

        rows.append(
            {
                "site_id": site_id,
                "interval_start": interval_end - pd.Timedelta(minutes=30),
                "interval_end": interval_end,
                "forecast_kw_import": p50,
                "p50_forecast_kw": p50,
                "p90_md_risk_kw": p90,
                "p95_stress_kw": p95,
                "calibrated_p90_md_risk_kw": p90,
                "calibrated_p95_stress_kw": p95,
                "md_risk_envelope_kw": p95,
                "recent_observed_md_floor_kw": recent_md_floor_kw,
                "custom_risk_envelope_kw": p95,
                "planning_month": ((step - 1) // PLANNING_INTERVALS_PER_MONTH) + 1,
                "planning_method": "direct_long_horizon_gradient_boosting",
                "growth_multiplier": growth_multiplier,
                "ev_load_kw": ev_adder,
                "late_night_peak_shape_score": 0.0,
                "late_night_peak_floor_applied": False,
            }
        )

    forecast = pd.DataFrame(rows)
    for _, indices in forecast.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        p90_peak_idx = forecast.loc[month_indices, "calibrated_p90_md_risk_kw"].idxmax()
        p95_peak_idx = forecast.loc[month_indices, "calibrated_p95_stress_kw"].idxmax()
        forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"] = max(
            float(forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"]),
            recent_md_floor_kw * growth_multiplier,
        )
        forecast.at[p95_peak_idx, "calibrated_p95_stress_kw"] = max(
            float(forecast.at[p95_peak_idx, "calibrated_p95_stress_kw"]),
            recent_md_floor_kw * growth_multiplier * 1.03,
            float(forecast.at[p90_peak_idx, "calibrated_p90_md_risk_kw"]),
        )

    forecast["p90_md_risk_kw"] = np.maximum(
        forecast["p90_md_risk_kw"].astype(float),
        forecast["calibrated_p90_md_risk_kw"].astype(float),
    )
    forecast["p95_stress_kw"] = np.maximum(
        np.maximum(forecast["p95_stress_kw"].astype(float), forecast["calibrated_p95_stress_kw"].astype(float)),
        forecast["p90_md_risk_kw"].astype(float),
    )
    forecast["calibrated_p95_stress_kw"] = np.maximum(
        forecast["calibrated_p95_stress_kw"].astype(float),
        forecast["p90_md_risk_kw"].astype(float),
    )
    forecast["md_risk_envelope_kw"] = forecast["calibrated_p95_stress_kw"]
    forecast["custom_risk_envelope_kw"] = forecast["md_risk_envelope_kw"]
    return _add_planning_peak_flags(forecast)


def _correction_feature_row(
    context: dict[str, object],
    baseline_row: pd.Series,
    next_end: pd.Timestamp,
    horizon_step: int,
) -> dict[str, float]:
    features = _long_horizon_feature_row_from_context(context, next_end, horizon_step)
    scale = max(float(context["scale"]), 1.0)
    p50 = float(baseline_row.get("p50_forecast_kw", baseline_row.get("forecast_kw_import", 0.0)))
    p90 = float(baseline_row.get("p90_md_risk_kw", p50))
    p95 = float(baseline_row.get("p95_stress_kw", p90))
    recent_md = float(baseline_row.get("recent_observed_md_floor_kw", 0.0))
    features.update(
        {
            "baseline_p50_norm": p50 / scale,
            "baseline_p90_norm": p90 / scale,
            "baseline_p95_norm": p95 / scale,
            "baseline_p90_gap_norm": max(p90 - p50, 0.0) / scale,
            "baseline_p95_gap_norm": max(p95 - p90, 0.0) / scale,
            "baseline_peak_score": float(baseline_row.get("peak_risk_overlay_score", 0.0)),
            "baseline_is_peak": float(bool(baseline_row.get("is_peak_risk_overlay", False))),
            "baseline_to_recent_md_gap_norm": (recent_md - p50) / scale,
        }
    )
    return features


def _build_correction_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 2400,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        if len(ordered) <= LONG_HORIZON_MIN_HISTORY + LONG_HORIZON_TRAINING_HORIZON:
            continue

        site_scale = site_scale_from_frame(ordered)
        cutoffs = range(LONG_HORIZON_MIN_HISTORY, len(ordered) - 48, 336)
        for cutoff in cutoffs:
            history = ordered.iloc[:cutoff].copy()
            actual_frame = ordered.iloc[cutoff : min(len(ordered), cutoff + LONG_HORIZON_TRAINING_HORIZON)].copy()
            if actual_frame.empty:
                continue
            baseline = forecast_monthly_planning_profile(history, months=1).head(len(actual_frame)).reset_index(drop=True)
            context = _long_horizon_context(history, site_scale)

            for local_index in range(0, len(actual_frame), 24):
                actual = actual_frame.iloc[local_index]
                baseline_row = baseline.iloc[local_index]
                horizon_step = local_index + 1
                features = _correction_feature_row(
                    context,
                    baseline_row,
                    pd.Timestamp(actual["interval_end"]),
                    horizon_step,
                )
                actual_norm = float(actual["kw_import"]) / max(site_scale, 1.0)
                rows.append(
                    {
                        **features,
                        "p50_residual_norm": actual_norm - float(features["baseline_p50_norm"]),
                        "p90_residual_norm": actual_norm - float(features["baseline_p90_norm"]),
                        "p95_residual_norm": actual_norm - float(features["baseline_p95_norm"]),
                    }
                )
                if len(rows) >= max_training_rows:
                    break
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No correction-model training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_columns = ["p50_residual_norm", "p90_residual_norm", "p95_residual_norm"]
    for column in target_columns:
        target = training_rows[column].astype(float)
        training_rows[column] = target.clip(
            lower=float(target.quantile(0.01)),
            upper=float(target.quantile(0.99)),
        )
    feature_columns = [column for column in training_rows.columns if column not in target_columns]
    return training_rows, feature_columns


def _fit_correction_models(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, LGBMRegressor]:
    specs = {
        "p50": ("quantile", 0.50, "p50_residual_norm"),
        "p90": ("quantile", 0.90, "p90_residual_norm"),
        "p95": ("quantile", 0.95, "p95_residual_norm"),
    }
    models: dict[str, LGBMRegressor] = {}
    for name, (objective, alpha, target_column) in specs.items():
        model = LGBMRegressor(
            objective=objective,
            alpha=alpha,
            n_estimators=50,
            learning_rate=0.05,
            num_leaves=11,
            min_child_samples=16,
            reg_lambda=0.05,
            n_jobs=1,
            verbosity=-1,
            random_state=23,
        )
        model.fit(training_rows[feature_columns], training_rows[target_column])
        models[name] = model
    return models


def forecast_corrected_long_horizon_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 2400,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        raise ValueError("Not enough history for correction model development")

    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    training_frames = list(reference_frames or []) + [ordered]
    training_rows, feature_columns = _build_correction_training_rows(
        training_frames,
        max_training_rows=max_training_rows,
    )
    if len(training_rows) < 120:
        raise ValueError("Not enough correction-model training rows")

    models = _fit_correction_models(training_rows, feature_columns)
    baseline = forecast_monthly_planning_profile(
        ordered,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
    ).reset_index(drop=True)
    context = _long_horizon_context(ordered, site_scale_from_frame(ordered))

    corrected = baseline.copy()
    for row_index, row in corrected.iterrows():
        feature_row = _correction_feature_row(
            context,
            row,
            pd.Timestamp(row["interval_end"]),
            row_index + 1,
        )
        feature_frame = pd.DataFrame([feature_row], columns=feature_columns).fillna(0.0)
        scale = max(float(context["scale"]), 1.0)
        p50_base = float(row["p50_forecast_kw"])
        p90_base = float(row["p90_md_risk_kw"])
        p95_base = float(row["p95_stress_kw"])

        p50_delta = 0.50 * float(models["p50"].predict(feature_frame)[0]) * scale

        p50 = max(p50_base + float(np.clip(p50_delta, -0.10 * max(p50_base, 1.0), 0.10 * max(p50_base, 1.0))), 0.0)
        p90 = max(p50, p90_base)
        p95 = max(p90, p95_base)

        corrected.at[row_index, "forecast_kw_import"] = p50
        corrected.at[row_index, "p50_forecast_kw"] = p50
        corrected.at[row_index, "p90_md_risk_kw"] = p90
        corrected.at[row_index, "calibrated_p90_md_risk_kw"] = max(
            p90,
            float(row.get("calibrated_p90_md_risk_kw", p90)),
        )
        corrected.at[row_index, "p95_stress_kw"] = p95
        corrected.at[row_index, "calibrated_p95_stress_kw"] = max(
            p95,
            float(row.get("calibrated_p95_stress_kw", p95)),
            float(corrected.at[row_index, "calibrated_p90_md_risk_kw"]),
        )

    corrected["md_risk_envelope_kw"] = corrected["calibrated_p95_stress_kw"]
    corrected["custom_risk_envelope_kw"] = corrected["md_risk_envelope_kw"]
    corrected["planning_method"] = "baseline_correction_gradient_boosting"
    return _add_planning_peak_flags(corrected)


def _full_ml_feature_row(
    context: dict[str, object],
    baseline_row: pd.Series,
    next_end: pd.Timestamp,
    horizon_step: int,
    md_features: dict[str, float],
) -> dict[str, float]:
    features = _correction_feature_row(context, baseline_row, next_end, horizon_step)
    for key, value in md_features.items():
        features[f"md_{key}"] = float(value)
    return features


def _build_full_ml_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 2400,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        if len(ordered) <= LONG_HORIZON_MIN_HISTORY + LONG_HORIZON_TRAINING_HORIZON:
            continue

        site_scale = site_scale_from_frame(ordered)
        cutoffs = range(LONG_HORIZON_MIN_HISTORY, len(ordered) - LONG_HORIZON_TRAINING_HORIZON + 1, 7 * 48)
        for cutoff in cutoffs:
            history = ordered.iloc[:cutoff].copy()
            actual_frame = ordered.iloc[cutoff : cutoff + LONG_HORIZON_TRAINING_HORIZON].copy().reset_index(drop=True)
            if actual_frame.empty:
                continue
            baseline = forecast_monthly_planning_profile(history, months=1).head(len(actual_frame)).reset_index(drop=True)
            context = _long_horizon_context(history, site_scale)
            md_features = _md_risk_model_features(history, baseline)

            for local_index in range(0, len(actual_frame), 8):
                actual = float(actual_frame.iloc[local_index]["kw_import"])
                baseline_row = baseline.iloc[local_index]
                features = _full_ml_feature_row(
                    context,
                    baseline_row,
                    pd.Timestamp(actual_frame.iloc[local_index]["interval_end"]),
                    local_index + 1,
                    md_features,
                )
                scale = max(float(context["scale"]), 1.0)
                rows.append(
                    {
                        **features,
                        "p50_residual_norm": (actual - float(baseline_row["p50_forecast_kw"])) / scale,
                        "p90_residual_norm": (actual - float(baseline_row["p90_md_risk_kw"])) / scale,
                        "p95_residual_norm": (actual - float(baseline_row["p95_stress_kw"])) / scale,
                    }
                )
                if len(rows) >= max_training_rows:
                    break
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No full-ML planning training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_columns = ["p50_residual_norm", "p90_residual_norm", "p95_residual_norm"]
    for column in target_columns:
        target = training_rows[column].astype(float)
        training_rows[column] = target.clip(
            lower=float(target.quantile(0.01)),
            upper=float(target.quantile(0.99)),
        )
    feature_columns = [column for column in training_rows.columns if column not in target_columns]
    return training_rows, feature_columns


def _fit_full_ml_planning_models(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, LGBMRegressor]:
    specs = {
        "p50": (0.50, "p50_residual_norm", 43),
        "p90": (0.90, "p90_residual_norm", 47),
        "p95": (0.95, "p95_residual_norm", 53),
    }
    models: dict[str, LGBMRegressor] = {}
    for name, (alpha, target_column, random_state) in specs.items():
        model = LGBMRegressor(
            objective="quantile",
            alpha=alpha,
            n_estimators=55,
            learning_rate=0.05,
            num_leaves=11,
            min_child_samples=8,
            reg_lambda=0.08,
            n_jobs=1,
            verbosity=-1,
            random_state=random_state,
        )
        model.fit(training_rows[feature_columns], training_rows[target_column])
        models[name] = model
    return models


def forecast_full_ml_planning_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 2400,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        raise ValueError("Not enough history for full ML planning model development")

    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    training_frames = list(reference_frames or []) + [ordered]
    training_rows, feature_columns = _build_full_ml_training_rows(
        training_frames,
        max_training_rows=max_training_rows,
    )
    if len(training_rows) < 80:
        raise ValueError("Not enough full ML planning training rows")

    models = _fit_full_ml_planning_models(training_rows, feature_columns)
    baseline = forecast_monthly_planning_profile(
        ordered,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
    ).reset_index(drop=True)
    context = _long_horizon_context(ordered, site_scale_from_frame(ordered))

    adjusted = baseline.copy()
    for _, indices in adjusted.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        month_forecast = adjusted.loc[month_indices].copy()
        md_features = _md_risk_model_features(ordered, month_forecast)

        for local_position, row_index in enumerate(month_indices, start=1):
            row = adjusted.loc[row_index]
            feature_row = _full_ml_feature_row(
                context,
                row,
                pd.Timestamp(row["interval_end"]),
                local_position,
                md_features,
            )
            feature_frame = pd.DataFrame([feature_row], columns=feature_columns).fillna(0.0)
            scale = max(float(context["scale"]), 1.0)
            p50_base = float(row["p50_forecast_kw"])
            p90_base = float(row["p90_md_risk_kw"])
            p95_base = float(row["p95_stress_kw"])

            p50_delta = 0.35 * float(models["p50"].predict(feature_frame)[0]) * scale
            p90_delta = float(models["p90"].predict(feature_frame)[0]) * scale
            p95_delta = float(models["p95"].predict(feature_frame)[0]) * scale

            p50 = max(
                p50_base
                + float(np.clip(p50_delta, -0.08 * max(p50_base, 1.0), 0.08 * max(p50_base, 1.0))),
                0.0,
            )
            p90 = max(
                p50,
                p90_base
                + float(np.clip(p90_delta, -0.12 * max(p90_base, 1.0), 0.18 * max(p90_base, 1.0))),
            )
            p95 = max(
                p90,
                p95_base
                + float(np.clip(p95_delta, -0.10 * max(p95_base, 1.0), 0.16 * max(p95_base, 1.0))),
            )

            adjusted.at[row_index, "forecast_kw_import"] = p50
            adjusted.at[row_index, "p50_forecast_kw"] = p50
            adjusted.at[row_index, "p90_md_risk_kw"] = p90
            adjusted.at[row_index, "calibrated_p90_md_risk_kw"] = max(
                p90,
                float(row.get("calibrated_p90_md_risk_kw", p90)),
                p50,
            )
            adjusted.at[row_index, "p95_stress_kw"] = p95
            adjusted.at[row_index, "calibrated_p95_stress_kw"] = max(
                p95,
                float(row.get("calibrated_p95_stress_kw", p95)),
                float(adjusted.at[row_index, "calibrated_p90_md_risk_kw"]),
            )

    adjusted["md_risk_envelope_kw"] = adjusted["calibrated_p95_stress_kw"]
    adjusted["custom_risk_envelope_kw"] = adjusted["md_risk_envelope_kw"]
    adjusted["planning_method"] = "full_ml_planning_gradient_boosting"
    return _add_planning_peak_flags(adjusted)


def forecast_gated_ml_planning_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 2400,
    correction_policy: GatedP50CorrectionPolicy | None = None,
    uplift_policy: MdRiskUpliftPolicy | None = None,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        raise ValueError("Not enough history for gated ML planning model development")

    policy = correction_policy or GatedP50CorrectionPolicy()
    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    training_frames = list(reference_frames or []) + [ordered]
    training_rows, feature_columns = _build_full_ml_training_rows(
        training_frames,
        max_training_rows=max_training_rows,
    )
    if len(training_rows) < 80:
        raise ValueError("Not enough gated ML planning training rows")

    models = _fit_full_ml_planning_models(training_rows, feature_columns)
    adjusted = forecast_ml_md_risk_profile(
        ordered,
        months=months,
        reference_frames=reference_frames,
        max_training_rows=max_training_rows,
        uplift_policy=uplift_policy,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
    ).reset_index(drop=True)
    adjusted["ml_p50_correction_confidence"] = 0.0
    adjusted["ml_p50_correction_applied"] = False
    adjusted["ml_p50_correction_kw"] = 0.0

    context = _long_horizon_context(ordered, site_scale_from_frame(ordered))
    for _, indices in adjusted.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        month_forecast = adjusted.loc[month_indices].copy()
        md_features = _md_risk_model_features(ordered, month_forecast)
        raw_deltas: list[float] = []
        base_values: list[float] = []

        for local_position, row_index in enumerate(month_indices, start=1):
            row = adjusted.loc[row_index]
            feature_row = _full_ml_feature_row(
                context,
                row,
                pd.Timestamp(row["interval_end"]),
                local_position,
                md_features,
            )
            feature_frame = pd.DataFrame([feature_row], columns=feature_columns).fillna(0.0)
            scale = max(float(context["scale"]), 1.0)
            raw_deltas.append(float(models["p50"].predict(feature_frame)[0]) * scale)
            base_values.append(float(row["p50_forecast_kw"]))

        delta_series = pd.Series(raw_deltas, index=month_indices, dtype=float)
        base_series = pd.Series(base_values, index=month_indices, dtype=float).clip(lower=1.0)
        delta_ratio = (delta_series.abs() / base_series).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        magnitude_confidence = _normalized_score(delta_ratio)
        peak_confidence = adjusted.loc[month_indices, "peak_risk_overlay_score"].astype(float).clip(lower=0.0, upper=1.0)
        confidence = (0.70 * magnitude_confidence + 0.30 * peak_confidence).clip(lower=0.0, upper=1.0)
        active_threshold = max(float(policy.confidence_threshold), float(confidence.quantile(policy.active_quantile)))
        active = (confidence >= active_threshold) & (delta_ratio >= float(policy.min_delta_ratio))
        if not bool(active.any()) and float(delta_ratio.max()) >= float(policy.min_delta_ratio):
            active.loc[delta_ratio.idxmax()] = True

        for row_index in month_indices:
            adjusted.at[row_index, "ml_p50_correction_confidence"] = float(confidence.loc[row_index])
            if not bool(active.loc[row_index]):
                continue

            row = adjusted.loc[row_index]
            p50_base = float(row["p50_forecast_kw"])
            correction = float(policy.correction_strength) * float(delta_series.loc[row_index])
            correction = float(
                np.clip(
                    correction,
                    -float(policy.correction_cap_ratio) * max(p50_base, 1.0),
                    float(policy.correction_cap_ratio) * max(p50_base, 1.0),
                )
            )
            if abs(correction) <= 1.0e-9:
                continue

            p50 = max(p50_base + correction, 0.0)
            adjusted.at[row_index, "forecast_kw_import"] = p50
            adjusted.at[row_index, "p50_forecast_kw"] = p50
            adjusted.at[row_index, "p90_md_risk_kw"] = max(float(row["p90_md_risk_kw"]), p50)
            adjusted.at[row_index, "calibrated_p90_md_risk_kw"] = max(
                float(row["calibrated_p90_md_risk_kw"]),
                float(adjusted.at[row_index, "p90_md_risk_kw"]),
            )
            adjusted.at[row_index, "p95_stress_kw"] = max(
                float(row["p95_stress_kw"]),
                float(adjusted.at[row_index, "calibrated_p90_md_risk_kw"]),
            )
            adjusted.at[row_index, "calibrated_p95_stress_kw"] = max(
                float(row["calibrated_p95_stress_kw"]),
                float(adjusted.at[row_index, "p95_stress_kw"]),
            )
            adjusted.at[row_index, "ml_p50_correction_applied"] = True
            adjusted.at[row_index, "ml_p50_correction_kw"] = correction

    adjusted["md_risk_envelope_kw"] = adjusted["calibrated_p95_stress_kw"]
    adjusted["custom_risk_envelope_kw"] = adjusted["md_risk_envelope_kw"]
    adjusted["planning_method"] = "gated_ml_planning_gradient_boosting"
    return _add_planning_peak_flags(adjusted)


def _monthly_md_correction_features(history_frame: pd.DataFrame, baseline_forecast: pd.DataFrame) -> dict[str, float]:
    features = _md_risk_model_features(history_frame, baseline_forecast)
    ordered = history_frame.sort_values("interval_end").reset_index(drop=True).copy()
    values = pd.to_numeric(ordered["kw_import"], errors="coerce").astype(float)
    scale = max(site_scale_from_frame(ordered), 1.0)
    recent_7d = values.tail(7 * 48)
    recent_14d = values.tail(14 * 48)
    recent_28d = values.tail(28 * 48)
    p50_md = float(baseline_forecast["p50_forecast_kw"].max())
    p90_md = float(baseline_forecast["p90_md_risk_kw"].max())
    p95_md = float(baseline_forecast["p95_stress_kw"].max())

    features.update(
        {
            "recent_7d_md_norm": (float(recent_7d.max()) if not recent_7d.empty else 0.0) / scale,
            "recent_14d_md_norm": (float(recent_14d.max()) if not recent_14d.empty else 0.0) / scale,
            "recent_28d_md_norm": (float(recent_28d.max()) if not recent_28d.empty else 0.0) / scale,
            "recent_7d_p95_norm": _safe_quantile(recent_7d, 0.95, 0.0) / scale,
            "recent_14d_p95_norm": _safe_quantile(recent_14d, 0.95, 0.0) / scale,
            "planner_p50_to_recent_28d_md_ratio": p50_md / max(float(recent_28d.max()) if not recent_28d.empty else p50_md, 1.0),
            "planner_p90_to_p50_ratio": p90_md / max(p50_md, 1.0),
            "planner_p95_to_p50_ratio": p95_md / max(p50_md, 1.0),
        }
    )
    return features


def _build_monthly_md_correction_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 400,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    horizon = 30 * 48
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        if len(ordered) <= LONG_HORIZON_MIN_HISTORY + horizon:
            continue

        cutoffs = range(LONG_HORIZON_MIN_HISTORY, len(ordered) - horizon + 1, 7 * 48)
        for cutoff in cutoffs:
            history = ordered.iloc[:cutoff].copy()
            actual = ordered.iloc[cutoff : cutoff + horizon].copy()
            if actual.empty:
                continue
            baseline = forecast_monthly_planning_profile(history, months=1)
            actual_md = float(actual["kw_import"].max())
            p50_md = float(baseline["p50_forecast_kw"].max())
            p90_md = float(baseline["p90_md_risk_kw"].max())
            p95_md = float(baseline["p95_stress_kw"].max())
            rows.append(
                {
                    **_monthly_md_correction_features(history, baseline),
                    "p50_md_ratio": float(np.clip(actual_md / max(p50_md, 1.0), 0.70, 1.45)),
                    "p90_md_ratio": float(np.clip(actual_md / max(p90_md, 1.0), 0.75, 1.35)),
                    "p95_md_ratio": float(np.clip(actual_md / max(p95_md, 1.0), 0.75, 1.30)),
                }
            )
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No monthly MD correction training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    target_columns = ["p50_md_ratio", "p90_md_ratio", "p95_md_ratio"]
    feature_columns = [column for column in training_rows.columns if column not in target_columns]
    return training_rows, feature_columns


def _fit_monthly_md_correction_models(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, LGBMRegressor]:
    models: dict[str, LGBMRegressor] = {}
    for name, target_column, random_state in (
        ("p50", "p50_md_ratio", 61),
        ("p90", "p90_md_ratio", 67),
        ("p95", "p95_md_ratio", 71),
    ):
        model = LGBMRegressor(
            objective="regression",
            n_estimators=45,
            learning_rate=0.05,
            num_leaves=7,
            min_child_samples=4,
            reg_lambda=0.08,
            n_jobs=1,
            verbosity=-1,
            random_state=random_state,
        )
        model.fit(training_rows[feature_columns], training_rows[target_column])
        models[name] = model
    return models


def _localized_monthly_md_correction(
    base_values: pd.Series,
    target_md_kw: float,
    timing_scores: pd.Series,
    active_quantile: float,
) -> pd.Series:
    base = base_values.astype(float).copy()
    current_md = float(base.max()) if not base.empty else 0.0
    if current_md <= 0 or abs(target_md_kw - current_md) <= 1.0e-9:
        return base

    scores = timing_scores.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if float(scores.max()) <= 0:
        active = base == current_md
        normalized = pd.Series(1.0, index=base.index)
    else:
        threshold = float(scores.quantile(active_quantile))
        active = scores >= threshold
        if not bool(active.any()):
            active = scores == scores.max()
        normalized = scores / max(float(scores.max()), 1.0e-9)

    adjusted = base.copy()
    delta = float(target_md_kw) - current_md
    adjusted.loc[active] = adjusted.loc[active] + delta * normalized.loc[active]
    peak_idx = scores.idxmax() if float(scores.max()) > 0 else base.idxmax()
    adjusted.loc[peak_idx] = target_md_kw
    return adjusted.clip(lower=0.0)


def forecast_monthly_md_corrected_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 400,
    correction_policy: MonthlyMDCorrectionPolicy | None = None,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
    existing_pv_kwp: float | None = None,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        raise ValueError("Not enough history for monthly MD correction model development")

    policy = correction_policy or MonthlyMDCorrectionPolicy()
    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    training_frames = list(reference_frames or []) + [ordered]
    training_rows, feature_columns = _build_monthly_md_correction_training_rows(
        training_frames,
        max_training_rows=max_training_rows,
    )
    if len(training_rows) < 4:
        raise ValueError("Not enough monthly MD correction training rows")

    models = _fit_monthly_md_correction_models(training_rows, feature_columns)
    adjusted = forecast_monthly_planning_profile(
        ordered,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
        existing_pv_kwp=existing_pv_kwp,
    ).reset_index(drop=True)
    adjusted["ml_monthly_md_target_kw"] = 0.0
    adjusted["ml_monthly_md_correction_applied"] = False
    adjusted["ml_monthly_md_correction_kw"] = 0.0

    for _, indices in adjusted.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        month_forecast = adjusted.loc[month_indices].copy()
        features = _monthly_md_correction_features(ordered, month_forecast)
        feature_frame = pd.DataFrame([features], columns=feature_columns).fillna(0.0)

        base_p50_md = float(month_forecast["p50_forecast_kw"].max())
        base_p90_md = float(month_forecast["p90_md_risk_kw"].max())
        base_p95_md = float(month_forecast["p95_stress_kw"].max())
        p50_ratio = float(np.clip(models["p50"].predict(feature_frame)[0], policy.p50_min_ratio, policy.p50_max_ratio))
        p90_ratio = float(np.clip(models["p90"].predict(feature_frame)[0], policy.p90_min_ratio, policy.p90_max_ratio))
        p95_ratio = float(np.clip(models["p95"].predict(feature_frame)[0], policy.p95_min_ratio, policy.p95_max_ratio))

        target_p50_md = base_p50_md + policy.p50_correction_strength * ((base_p50_md * p50_ratio) - base_p50_md)
        target_p90_md = max(
            target_p50_md,
            base_p90_md + policy.risk_correction_strength * ((base_p90_md * p90_ratio) - base_p90_md),
        )
        target_p95_md = max(
            target_p90_md,
            base_p95_md + policy.risk_correction_strength * ((base_p95_md * p95_ratio) - base_p95_md),
        )

        timing_scores = adjusted.loc[month_indices, "peak_risk_overlay_score"].astype(float)
        original_p50 = adjusted.loc[month_indices, "p50_forecast_kw"].astype(float)
        corrected_p50 = _localized_monthly_md_correction(
            original_p50,
            target_p50_md,
            timing_scores,
            active_quantile=policy.active_quantile,
        )
        adjusted.loc[month_indices, "forecast_kw_import"] = corrected_p50.to_numpy()
        adjusted.loc[month_indices, "p50_forecast_kw"] = corrected_p50.to_numpy()
        adjusted.loc[month_indices, "ml_monthly_md_target_kw"] = target_p50_md
        adjusted.loc[month_indices, "ml_monthly_md_correction_kw"] = (corrected_p50 - original_p50).to_numpy()
        adjusted.loc[month_indices, "ml_monthly_md_correction_applied"] = (
            (corrected_p50 - original_p50).abs() > 1.0e-9
        ).to_numpy()

        corrected_p90 = _localized_monthly_md_correction(
            month_forecast["p90_md_risk_kw"].astype(float),
            target_p90_md,
            timing_scores,
            active_quantile=policy.active_quantile,
        )
        adjusted.loc[month_indices, "p90_md_risk_kw"] = np.maximum(
            corrected_p90.astype(float).to_numpy(),
            adjusted.loc[month_indices, "p50_forecast_kw"].astype(float).to_numpy(),
        )
        adjusted.loc[month_indices, "calibrated_p90_md_risk_kw"] = np.maximum(
            adjusted.loc[month_indices, "p90_md_risk_kw"].astype(float).to_numpy(),
            month_forecast["calibrated_p90_md_risk_kw"].astype(float).to_numpy(),
        )

        corrected_p95 = _localized_monthly_md_correction(
            month_forecast["p95_stress_kw"].astype(float),
            target_p95_md,
            timing_scores,
            active_quantile=policy.active_quantile,
        )
        adjusted.loc[month_indices, "p95_stress_kw"] = np.maximum(
            corrected_p95.astype(float).to_numpy(),
            adjusted.loc[month_indices, "calibrated_p90_md_risk_kw"].astype(float).to_numpy(),
        )
        adjusted.loc[month_indices, "calibrated_p95_stress_kw"] = np.maximum(
            adjusted.loc[month_indices, "p95_stress_kw"].astype(float).to_numpy(),
            month_forecast["calibrated_p95_stress_kw"].astype(float).to_numpy(),
        )

    adjusted["md_risk_envelope_kw"] = adjusted["calibrated_p95_stress_kw"]
    adjusted["custom_risk_envelope_kw"] = adjusted["md_risk_envelope_kw"]
    adjusted["planning_method"] = "monthly_md_correction_gradient_boosting"
    return _add_planning_peak_flags(adjusted)


def _md_risk_model_features(history_frame: pd.DataFrame, baseline_forecast: pd.DataFrame) -> dict[str, float]:
    ordered = history_frame.sort_values("interval_end").reset_index(drop=True).copy()
    recent = ordered.tail(min(len(ordered), 56 * 48)).copy()
    recent_values = pd.to_numeric(recent["kw_import"], errors="coerce").astype(float)
    scale = site_scale_from_frame(ordered)
    recent_md = float(recent_values.max()) if not recent_values.empty else 0.0
    recent_p95 = _safe_quantile(recent_values, 0.95, recent_md)
    recent_p90 = _safe_quantile(recent_values, 0.90, recent_md)
    recent_7d = recent_values.tail(7 * 48)
    recent_28d = recent_values.tail(28 * 48)
    recent_7d_mean = float(recent_7d.mean()) if not recent_7d.empty else 0.0
    recent_28d_mean = float(recent_28d.mean()) if not recent_28d.empty else recent_7d_mean
    recent_7d_max = float(recent_7d.max()) if not recent_7d.empty else recent_md
    recent_28d_max = float(recent_28d.max()) if not recent_28d.empty else recent_md
    has_solar = bool(ordered["has_solar"].iloc[-1]) if "has_solar" in ordered else False

    if recent_values.empty:
        recent_peak_end = pd.Timestamp(ordered["interval_end"].iloc[-1])
        recent_peak_hour = float(recent_peak_end.hour + recent_peak_end.minute / 60.0)
        recent_peak_is_daylight = float(6 <= recent_peak_hour < 18)
        recent_peak_is_weekend = float(recent_peak_end.dayofweek >= 5)
        recent_peak_slot_concentration = 0.0
    else:
        recent_peak_index = recent_values.idxmax()
        recent_peak_end = pd.Timestamp(recent.loc[recent_peak_index, "interval_end"])
        recent_peak_hour = float(recent_peak_end.hour + recent_peak_end.minute / 60.0)
        recent_peak_is_daylight = float(6 <= recent_peak_hour < 18)
        recent_peak_is_weekend = float(recent_peak_end.dayofweek >= 5)
        peak_threshold = max(float(recent_values.quantile(0.90)), 0.95 * recent_md)
        peak_rows = recent.loc[recent_values >= peak_threshold].copy()
        if peak_rows.empty:
            recent_peak_slot_concentration = 0.0
        else:
            peak_slots = peak_rows["interval_end"].map(lambda ts: _slot_index(pd.Timestamp(ts)))
            recent_peak_slot_concentration = float(peak_slots.value_counts(normalize=True).max())

    p50_md = float(baseline_forecast["p50_forecast_kw"].max())
    p90_md = float(baseline_forecast["p90_md_risk_kw"].max())
    p95_md = float(baseline_forecast["p95_stress_kw"].max())
    peak_row = baseline_forecast.loc[baseline_forecast["p95_stress_kw"].astype(float).idxmax()]
    peak_end = pd.Timestamp(peak_row["interval_end"])

    return {
        "site_scale_kw": float(scale),
        "has_solar_int": float(has_solar),
        "history_days": float(len(ordered) / 48.0),
        "recent_md_norm": recent_md / scale,
        "recent_p95_norm": recent_p95 / scale,
        "recent_p90_norm": recent_p90 / scale,
        "recent_md_to_p95_ratio": recent_md / max(recent_p95, 1.0),
        "recent_trend_7d_vs_28d_norm": (recent_7d_mean - recent_28d_mean) / scale,
        "recent_7d_max_to_28d_max_ratio": recent_7d_max / max(recent_28d_max, 1.0),
        "recent_peak_hour": recent_peak_hour,
        "recent_peak_is_daylight": recent_peak_is_daylight,
        "recent_peak_is_weekend": recent_peak_is_weekend,
        "recent_peak_slot_concentration": recent_peak_slot_concentration,
        "non_solar_night_peak_indicator": float((not has_solar) and recent_peak_is_daylight < 0.5),
        "solar_daylight_peak_interaction": float(has_solar) * recent_peak_is_daylight,
        "baseline_p50_md_norm": p50_md / scale,
        "baseline_p90_md_norm": p90_md / scale,
        "baseline_p95_md_norm": p95_md / scale,
        "baseline_p90_gap_norm": max(p90_md - p50_md, 0.0) / scale,
        "baseline_p95_gap_norm": max(p95_md - p90_md, 0.0) / scale,
        "baseline_p95_to_recent_md_ratio": p95_md / max(recent_md, 1.0),
        "peak_hour": float(peak_end.hour + peak_end.minute / 60.0),
        "peak_is_weekend": float(peak_end.dayofweek >= 5),
    }


def _build_md_risk_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 400,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        horizon = 30 * 48
        min_train = LONG_HORIZON_MIN_HISTORY
        if len(ordered) <= min_train + horizon:
            continue
        cutoffs = list(range(min_train, len(ordered) - horizon + 1, 7 * 48))
        for cutoff in cutoffs[-8:]:
            history = ordered.iloc[:cutoff].copy()
            actual = ordered.iloc[cutoff : cutoff + horizon].copy()
            baseline = forecast_monthly_planning_profile(history, months=1)
            actual_md = float(actual["kw_import"].max())
            p90_md = float(baseline["p90_md_risk_kw"].max())
            p95_md = float(baseline["p95_stress_kw"].max())
            features = _md_risk_model_features(history, baseline)
            rows.append(
                {
                    **features,
                    "p90_md_ratio": float(np.clip(actual_md / max(p90_md, 1.0), 0.75, 1.40)),
                    "p95_md_ratio": float(np.clip(actual_md / max(p95_md, 1.0), 0.75, 1.35)),
                    "p90_undercovered": float(actual_md > p90_md),
                    "p95_undercovered": float(actual_md > p95_md),
                }
            )
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No MD-risk training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    feature_columns = [
        column
        for column in training_rows.columns
        if column not in {"p90_md_ratio", "p95_md_ratio", "p90_undercovered", "p95_undercovered"}
    ]
    return training_rows, feature_columns


def _fit_md_risk_models(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, LGBMRegressor]:
    models: dict[str, LGBMRegressor] = {}
    for name, target_column in {"p90": "p90_md_ratio", "p95": "p95_md_ratio"}.items():
        model = LGBMRegressor(
            objective="regression",
            n_estimators=40,
            learning_rate=0.05,
            num_leaves=7,
            min_child_samples=4,
            reg_lambda=0.05,
            n_jobs=1,
            verbosity=-1,
            random_state=31,
        )
        model.fit(training_rows[feature_columns], training_rows[target_column])
        models[name] = model
    return models


class _ConstantUndercoverageClassifier:
    def __init__(self, probability: float) -> None:
        self.probability = float(np.clip(probability, 0.0, 1.0))

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        positive = np.full(len(features), self.probability, dtype=float)
        negative = 1.0 - positive
        return np.column_stack([negative, positive])


def _fit_md_undercoverage_classifiers(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> dict[str, object]:
    classifiers: dict[str, object] = {}
    for name, target_column in {"p90": "p90_undercovered", "p95": "p95_undercovered"}.items():
        y = training_rows[target_column].astype(int)
        if y.nunique() < 2:
            classifiers[name] = _ConstantUndercoverageClassifier(float(y.mean()))
            continue

        classifier = LGBMClassifier(
            objective="binary",
            n_estimators=35,
            learning_rate=0.05,
            num_leaves=7,
            min_child_samples=4,
            reg_lambda=0.05,
            n_jobs=1,
            verbosity=-1,
            random_state=37,
        )
        classifier.fit(training_rows[feature_columns], y)
        classifiers[name] = classifier
    return classifiers


def _undercoverage_probability(classifier: object, features: pd.DataFrame) -> float:
    probabilities = classifier.predict_proba(features)
    return float(np.clip(probabilities[0, 1], 0.0, 1.0))


def _build_peak_timing_training_rows(
    frames: Iterable[pd.DataFrame],
    max_training_rows: int = 1600,
) -> tuple[pd.DataFrame, list[str]]:
    rows: list[dict[str, float]] = []
    for frame in frames:
        if len(rows) >= max_training_rows:
            break
        ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
        horizon = 30 * 48
        min_train = LONG_HORIZON_MIN_HISTORY
        if len(ordered) <= min_train + horizon:
            continue

        cutoffs = list(range(min_train, len(ordered) - horizon + 1, 7 * 48))
        for cutoff in cutoffs[-6:]:
            history = ordered.iloc[:cutoff].copy()
            actual = ordered.iloc[cutoff : cutoff + horizon].copy().reset_index(drop=True)
            baseline = forecast_monthly_planning_profile(history, months=1).head(len(actual)).reset_index(drop=True)
            context = _long_horizon_context(history, site_scale_from_frame(history))
            peak_threshold = float(actual["kw_import"].quantile(0.90))

            for local_index in range(0, len(actual), 8):
                actual_row = actual.iloc[local_index]
                baseline_row = baseline.iloc[local_index]
                features = _correction_feature_row(
                    context,
                    baseline_row,
                    pd.Timestamp(actual_row["interval_end"]),
                    local_index + 1,
                )
                rows.append(
                    {
                        **features,
                        "is_actual_peak_window": float(float(actual_row["kw_import"]) >= peak_threshold),
                    }
                )
                if len(rows) >= max_training_rows:
                    break
            if len(rows) >= max_training_rows:
                break

    if not rows:
        raise ValueError("No peak-timing training rows were produced")

    training_rows = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    feature_columns = [column for column in training_rows.columns if column != "is_actual_peak_window"]
    return training_rows, feature_columns


def _fit_peak_timing_classifier(
    training_rows: pd.DataFrame,
    feature_columns: list[str],
) -> object:
    y = training_rows["is_actual_peak_window"].astype(int)
    if y.nunique() < 2:
        return _ConstantUndercoverageClassifier(float(y.mean()))

    classifier = LGBMClassifier(
        objective="binary",
        n_estimators=45,
        learning_rate=0.05,
        num_leaves=9,
        min_child_samples=8,
        reg_lambda=0.05,
        n_jobs=1,
        verbosity=-1,
        random_state=41,
    )
    classifier.fit(training_rows[feature_columns], y)
    return classifier


def _localized_risk_envelope(
    base_values: pd.Series,
    target_md_kw: float,
    timing_scores: pd.Series,
    active_quantile: float = 0.82,
) -> pd.Series:
    base = base_values.astype(float).copy()
    current_md = float(base.max()) if not base.empty else 0.0
    if current_md <= 0 or target_md_kw <= current_md:
        return base

    scores = timing_scores.astype(float).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if float(scores.max()) <= 0:
        peak_idx = base.idxmax()
        adjusted = base.copy()
        adjusted.loc[peak_idx] = max(float(adjusted.loc[peak_idx]), float(target_md_kw))
        return adjusted

    threshold = float(scores.quantile(active_quantile))
    active = scores >= threshold
    if not bool(active.any()):
        active = scores == scores.max()

    normalized = scores / max(float(scores.max()), 1.0e-9)
    adjusted = base.copy()
    uplift = float(target_md_kw) - current_md
    adjusted.loc[active] = adjusted.loc[active] + uplift * normalized.loc[active]
    peak_idx = scores.idxmax()
    adjusted.loc[peak_idx] = max(float(adjusted.loc[peak_idx]), float(target_md_kw))
    return np.maximum(adjusted, base)


def _scale_monthly_risk_envelope(
    forecast: pd.DataFrame,
    column: str,
    target_md_kw: float,
) -> pd.Series:
    values = forecast[column].astype(float)
    current_md = float(values.max())
    if current_md <= 0:
        return values
    multiplier = float(np.clip(target_md_kw / current_md, 0.85, 1.20))
    return values * multiplier


def forecast_ml_md_risk_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 400,
    uplift_policy: MdRiskUpliftPolicy | None = None,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
    existing_pv_kwp: float | None = None,
) -> pd.DataFrame:
    if months not in {1, 2, 3}:
        raise ValueError("months must be 1, 2, or 3")
    if target_frame.empty:
        raise ValueError("Target frame is empty")
    if len(target_frame) < LONG_HORIZON_MIN_HISTORY + 48:
        raise ValueError("Not enough history for MD-risk model development")

    policy = uplift_policy or MdRiskUpliftPolicy()
    ordered = target_frame.sort_values("interval_end").reset_index(drop=True).copy()
    baseline = forecast_monthly_planning_profile(
        ordered,
        months=months,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
        existing_pv_kwp=existing_pv_kwp,
    ).reset_index(drop=True)
    training_frames = list(reference_frames or []) + [ordered]
    training_rows, feature_columns = _build_md_risk_training_rows(
        training_frames,
        max_training_rows=max_training_rows,
    )
    if len(training_rows) < 4:
        raise ValueError("Not enough MD-risk training rows")

    models = _fit_md_risk_models(training_rows, feature_columns)
    classifiers = _fit_md_undercoverage_classifiers(training_rows, feature_columns)
    timing_rows, timing_feature_columns = _build_peak_timing_training_rows(
        training_frames,
        max_training_rows=max(400, max_training_rows * 4),
    )
    timing_classifier = _fit_peak_timing_classifier(timing_rows, timing_feature_columns)
    adjusted = baseline.copy()
    for _, indices in adjusted.groupby("planning_month", sort=False).groups.items():
        month_indices = list(indices)
        month_forecast = adjusted.loc[month_indices].copy()
        features = _md_risk_model_features(ordered, month_forecast)
        feature_frame = pd.DataFrame([features], columns=feature_columns).fillna(0.0)
        base_p90_md = float(month_forecast["p90_md_risk_kw"].max())
        base_p95_md = float(month_forecast["p95_stress_kw"].max())
        p90_undercoverage_risk = _undercoverage_probability(classifiers["p90"], feature_frame)
        p95_undercoverage_risk = _undercoverage_probability(classifiers["p95"], feature_frame)
        raw_p90_ratio = float(
            np.clip(models["p90"].predict(feature_frame)[0], policy.p90_min_ratio, policy.p90_max_ratio)
        )
        raw_p95_ratio = float(
            np.clip(models["p95"].predict(feature_frame)[0], policy.p95_min_ratio, policy.p95_max_ratio)
        )

        p90_ratio = 1.0 + max(raw_p90_ratio - 1.0, 0.0) * p90_undercoverage_risk
        p95_ratio = 1.0 + max(raw_p95_ratio - 1.0, 0.0) * p95_undercoverage_risk
        if p90_undercoverage_risk < policy.low_risk_threshold:
            p90_ratio = min(p90_ratio, policy.low_risk_max_ratio)
        if p95_undercoverage_risk < policy.low_risk_threshold:
            p95_ratio = min(p95_ratio, policy.low_risk_max_ratio)

        target_p90_md = max(base_p90_md * p90_ratio, float(month_forecast["p50_forecast_kw"].max()))
        target_p95_md = max(base_p95_md * p95_ratio, target_p90_md)

        timing_scores: list[float] = []
        forecast_context = _long_horizon_context(ordered, site_scale_from_frame(ordered))
        for local_position, (_, interval_row) in enumerate(month_forecast.iterrows(), start=1):
            timing_features = _correction_feature_row(
                forecast_context,
                interval_row,
                pd.Timestamp(interval_row["interval_end"]),
                local_position,
            )
            timing_frame = pd.DataFrame([timing_features], columns=timing_feature_columns).fillna(0.0)
            timing_scores.append(_undercoverage_probability(timing_classifier, timing_frame))
        timing_score_series = pd.Series(timing_scores, index=month_indices, dtype=float)

        adjusted.loc[month_indices, "p90_md_risk_kw"] = _localized_risk_envelope(
            month_forecast["p90_md_risk_kw"],
            target_p90_md,
            timing_score_series,
            active_quantile=policy.timing_active_quantile,
        ).to_numpy()
        adjusted.loc[month_indices, "calibrated_p90_md_risk_kw"] = np.maximum(
            adjusted.loc[month_indices, "p90_md_risk_kw"].astype(float).to_numpy(),
            month_forecast["p50_forecast_kw"].astype(float).to_numpy(),
        )
        adjusted.loc[month_indices, "p95_stress_kw"] = _localized_risk_envelope(
            month_forecast["p95_stress_kw"],
            target_p95_md,
            timing_score_series,
            active_quantile=policy.timing_active_quantile,
        ).to_numpy()
        adjusted.loc[month_indices, "calibrated_p95_stress_kw"] = np.maximum(
            adjusted.loc[month_indices, "p95_stress_kw"].astype(float).to_numpy(),
            adjusted.loc[month_indices, "calibrated_p90_md_risk_kw"].astype(float).to_numpy(),
        )
        adjusted.loc[month_indices, "ml_p90_undercoverage_risk"] = p90_undercoverage_risk
        adjusted.loc[month_indices, "ml_p95_undercoverage_risk"] = p95_undercoverage_risk
        adjusted.loc[month_indices, "ml_md_peak_timing_score"] = timing_score_series.to_numpy()

    adjusted["md_risk_envelope_kw"] = adjusted["calibrated_p95_stress_kw"]
    adjusted["custom_risk_envelope_kw"] = adjusted["md_risk_envelope_kw"]
    adjusted["planning_method"] = "ml_md_risk_gradient_boosting"
    return _add_planning_peak_flags(adjusted)


def forecast_md_ensemble_profile(
    target_frame: pd.DataFrame,
    months: int = 1,
    reference_frames: Iterable[pd.DataFrame] | None = None,
    max_training_rows: int = 400,
    correction_policy: MonthlyMDCorrectionPolicy | None = None,
    uplift_policy: MdRiskUpliftPolicy | None = None,
    growth_rate_pct: float = 0.0,
    ev_load_kw: float = 0.0,
    ev_start_hour: int = 18,
    ev_end_hour: int = 23,
    existing_pv_kwp: float | None = None,
) -> pd.DataFrame:
    ensemble_correction_policy = correction_policy or MonthlyMDCorrectionPolicy(p50_correction_strength=0.20)
    reference_frame_list = list(reference_frames or [])
    risk_forecast = forecast_ml_md_risk_profile(
        target_frame,
        months=months,
        reference_frames=reference_frame_list,
        max_training_rows=max_training_rows,
        uplift_policy=uplift_policy,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
        existing_pv_kwp=existing_pv_kwp,
    ).reset_index(drop=True)
    p50_forecast = forecast_monthly_md_corrected_profile(
        target_frame,
        months=months,
        reference_frames=reference_frame_list,
        max_training_rows=max_training_rows,
        correction_policy=ensemble_correction_policy,
        growth_rate_pct=growth_rate_pct,
        ev_load_kw=ev_load_kw,
        ev_start_hour=ev_start_hour,
        ev_end_hour=ev_end_hour,
        existing_pv_kwp=existing_pv_kwp,
    ).reset_index(drop=True)

    adjusted = risk_forecast.copy()
    adjusted["forecast_kw_import"] = p50_forecast["forecast_kw_import"].astype(float).to_numpy()
    adjusted["p50_forecast_kw"] = p50_forecast["p50_forecast_kw"].astype(float).to_numpy()
    for column in (
        "ml_monthly_md_target_kw",
        "ml_monthly_md_correction_applied",
        "ml_monthly_md_correction_kw",
    ):
        if column in p50_forecast.columns:
            adjusted[column] = p50_forecast[column].to_numpy()

    p50_values = adjusted["p50_forecast_kw"].astype(float).to_numpy()
    adjusted["p90_md_risk_kw"] = np.maximum(adjusted["p90_md_risk_kw"].astype(float).to_numpy(), p50_values)
    adjusted["calibrated_p90_md_risk_kw"] = np.maximum(
        adjusted["calibrated_p90_md_risk_kw"].astype(float).to_numpy(),
        adjusted["p90_md_risk_kw"].astype(float).to_numpy(),
    )
    adjusted["p95_stress_kw"] = np.maximum(
        adjusted["p95_stress_kw"].astype(float).to_numpy(),
        adjusted["calibrated_p90_md_risk_kw"].astype(float).to_numpy(),
    )
    adjusted["calibrated_p95_stress_kw"] = np.maximum(
        adjusted["calibrated_p95_stress_kw"].astype(float).to_numpy(),
        adjusted["p95_stress_kw"].astype(float).to_numpy(),
    )
    adjusted["md_risk_envelope_kw"] = adjusted["calibrated_p95_stress_kw"]
    adjusted["custom_risk_envelope_kw"] = adjusted["md_risk_envelope_kw"]
    adjusted["planning_method"] = "md_ensemble_gradient_boosting"
    return _add_planning_peak_flags(adjusted)


def _prepare_baseline_training_rows(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
    ordered["hour"] = ordered["interval_end"].dt.hour
    ordered["day_of_week"] = ordered["interval_end"].dt.dayofweek
    ordered["month"] = ordered["interval_end"].dt.month
    ordered["is_weekend"] = (ordered["day_of_week"] >= 5).astype(int)
    ordered["has_solar"] = ordered["has_solar"].astype(int)
    ordered["lag_1"] = ordered["kw_import"].shift(1)
    ordered["lag_2"] = ordered["kw_import"].shift(2)
    ordered["lag_48"] = ordered["kw_import"].shift(48)
    ordered["rolling_mean_4"] = ordered["kw_import"].shift(1).rolling(window=4, min_periods=1).mean()
    ordered["rolling_mean_48"] = ordered["kw_import"].shift(1).rolling(window=48, min_periods=1).mean()
    return ordered.dropna(subset=BASELINE_FEATURE_COLUMNS + ["kw_import"]).reset_index(drop=True)


def _fit_baseline_model(frames: list[pd.DataFrame]) -> Ridge:
    training_rows = pd.concat([_prepare_baseline_training_rows(frame) for frame in frames], ignore_index=True)
    if training_rows.empty:
        raise ValueError("No valid baseline training rows were produced")
    model = Ridge(alpha=1.0)
    model.fit(training_rows[BASELINE_FEATURE_COLUMNS], training_rows["kw_import"])
    return model


def _baseline_feature_row_for_timestamp(
    history: list[float],
    next_end: pd.Timestamp,
    has_solar: bool,
) -> dict[str, float | int]:
    lag_1 = history[-1]
    lag_2 = history[-2] if len(history) >= 2 else history[-1]
    lag_48 = history[-48] if len(history) >= 48 else history[-1]
    recent_4 = history[-4:] if len(history) >= 4 else history
    recent_48 = history[-48:] if len(history) >= 48 else history

    return {
        "hour": next_end.hour,
        "day_of_week": next_end.dayofweek,
        "month": next_end.month,
        "is_weekend": int(next_end.dayofweek >= 5),
        "has_solar": int(has_solar),
        "lag_1": float(lag_1),
        "lag_2": float(lag_2),
        "lag_48": float(lag_48),
        "rolling_mean_4": float(sum(recent_4) / len(recent_4)),
        "rolling_mean_48": float(sum(recent_48) / len(recent_48)),
    }


def _forecast_with_baseline_model(
    model: Ridge,
    target_frame: pd.DataFrame,
    horizon: int,
) -> pd.DataFrame:
    ordered = target_frame.sort_values("interval_end").reset_index(drop=True)
    history = ordered["kw_import"].astype(float).tolist()
    has_solar = bool(ordered["has_solar"].iloc[0])
    site_id = str(ordered["site_id"].iloc[0])
    last_end = pd.Timestamp(ordered["interval_end"].iloc[-1])

    forecast_rows: list[dict[str, object]] = []
    for step in range(1, horizon + 1):
        next_end = last_end + pd.Timedelta(minutes=30 * step)
        feature_row = _baseline_feature_row_for_timestamp(history, next_end, has_solar)
        feature_frame = pd.DataFrame([feature_row], columns=BASELINE_FEATURE_COLUMNS)
        prediction = max(float(model.predict(feature_frame)[0]), 0.0)
        history.append(prediction)
        forecast_rows.append(
            {
                "site_id": site_id,
                "interval_start": next_end - pd.Timedelta(minutes=30),
                "interval_end": next_end,
                "forecast_kw_import": prediction,
            }
        )

    return _add_peak_flags(pd.DataFrame(forecast_rows))


def site_scale_from_frame(
    frame: pd.DataFrame,
    baseline_quantile: float = 0.50,
    min_scale: float = 1.0,
) -> float:
    series = pd.to_numeric(frame["kw_import"], errors="coerce").astype(float)
    positive = series[series > 0]
    if positive.empty:
        return float(min_scale)

    baseline = float(positive.quantile(baseline_quantile))
    if not np.isfinite(baseline) or baseline <= 0:
        baseline = float(np.nanmedian(positive.to_numpy()))
    if not np.isfinite(baseline) or baseline <= 0:
        baseline = float(min_scale)
    return float(max(min_scale, baseline))


def normalize_site_frame(
    frame: pd.DataFrame,
    site_scale: float | None = None,
) -> tuple[pd.DataFrame, float]:
    scale = float(site_scale if site_scale is not None else site_scale_from_frame(frame))
    if scale <= 0 or not np.isfinite(scale):
        scale = 1.0

    normalized = frame.copy()
    normalized["kw_import"] = pd.to_numeric(normalized["kw_import"], errors="coerce").astype(float) / scale
    return normalized, scale


def add_enhanced_features(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    ordered = frame.sort_values("interval_end").reset_index(drop=True).copy()
    ts = pd.to_datetime(ordered["interval_end"])

    hour = ts.dt.hour + ts.dt.minute / 60.0
    day_of_week = ts.dt.dayofweek
    month = ts.dt.month

    ordered["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    ordered["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    ordered["dow_sin"] = np.sin(2 * np.pi * day_of_week / 7)
    ordered["dow_cos"] = np.cos(2 * np.pi * day_of_week / 7)
    ordered["month_sin"] = np.sin(2 * np.pi * month / 12)
    ordered["month_cos"] = np.cos(2 * np.pi * month / 12)

    ordered["is_weekend"] = (day_of_week >= 5).astype(int)
    ordered["is_monday"] = (day_of_week == 0).astype(int)
    ordered["is_post_weekend"] = ((day_of_week == 0) & (hour < 18)).astype(int)
    ordered["weekday_daylight"] = ((day_of_week < 5) & (hour >= 6) & (hour < 18)).astype(int)
    ordered["tariff_peak"] = ((hour >= 14) & (hour < 22)).astype(int)
    ordered["daylight"] = ((hour >= 6) & (hour < 18)).astype(int)
    ordered["has_solar_int"] = ordered["has_solar"].astype(int)
    ordered["solar_daylight_interaction"] = ordered["has_solar_int"] * ordered["daylight"]
    ordered["solar_weekday_daylight_interaction"] = ordered["has_solar_int"] * ordered["weekday_daylight"]
    ordered["solar_post_weekend_interaction"] = ordered["has_solar_int"] * ordered["is_post_weekend"]

    ordered["morning_ramp_indicator"] = ((hour >= 6) & (hour < 10)).astype(int)
    ordered["afternoon_decline_indicator"] = ((hour >= 14) & (hour < 18)).astype(int)
    ordered["daylight_progress"] = np.where(
        ordered["daylight"].astype(bool),
        np.clip((hour - 6.0) / 12.0, 0.0, 1.0),
        0.0,
    )
    ordered["solar_daylight_progress"] = ordered["has_solar_int"] * ordered["daylight_progress"]
    ordered["solar_hour_sin_interaction"] = ordered["has_solar_int"] * ordered["daylight"] * ordered["hour_sin"]
    ordered["solar_hour_cos_interaction"] = ordered["has_solar_int"] * ordered["daylight"] * ordered["hour_cos"]
    ordered["solar_tariff_peak_interaction"] = ordered["has_solar_int"] * ordered["tariff_peak"]
    ordered["solar_morning_ramp_interaction"] = ordered["has_solar_int"] * ordered["morning_ramp_indicator"]
    ordered["solar_afternoon_decline_interaction"] = ordered["has_solar_int"] * ordered["afternoon_decline_indicator"]

    target = pd.to_numeric(ordered["kw_import"], errors="coerce").astype(float)
    for lag in LAG_WINDOWS:
        ordered[f"lag_{lag}"] = target.shift(lag)

    shifted = target.shift(1)
    for window in ROLL_WINDOWS:
        ordered[f"rolling_mean_{window}"] = shifted.rolling(window=window, min_periods=1).mean()
        ordered[f"rolling_std_{window}"] = shifted.rolling(window=window, min_periods=2).std().fillna(0.0)
        ordered[f"rolling_max_{window}"] = shifted.rolling(window=window, min_periods=1).max()

    ordered["delta_lag_1_2"] = target.shift(1) - target.shift(2)
    ordered["delta_lag_2_3"] = target.shift(2) - target.shift(3)
    ordered["delta_lag_1_48"] = target.shift(1) - target.shift(48)
    ordered["delta_lag_1_336"] = target.shift(1) - target.shift(336)
    ordered["same_slot_prev_day_delta"] = target.shift(48) - target.shift(96)
    ordered["same_slot_prev_week_delta"] = target.shift(336) - target.shift(672)
    ordered["same_slot_day_vs_week_gap"] = target.shift(48) - target.shift(336)

    delta_series = target.diff().shift(1)
    ordered["rolling_delta_mean_4"] = delta_series.rolling(window=4, min_periods=1).mean()
    ordered["rolling_delta_std_4"] = delta_series.rolling(window=4, min_periods=2).std().fillna(0.0)
    ordered["rolling_delta_mean_24"] = delta_series.rolling(window=24, min_periods=1).mean()
    ordered["rolling_delta_std_24"] = delta_series.rolling(window=24, min_periods=2).std().fillna(0.0)

    feature_columns = [
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "month_sin",
        "month_cos",
        "is_weekend",
        "is_monday",
        "is_post_weekend",
        "weekday_daylight",
        "tariff_peak",
        "daylight",
        "has_solar_int",
        "solar_daylight_interaction",
        "solar_weekday_daylight_interaction",
        "solar_post_weekend_interaction",
        "morning_ramp_indicator",
        "afternoon_decline_indicator",
        "daylight_progress",
        "solar_daylight_progress",
        "solar_hour_sin_interaction",
        "solar_hour_cos_interaction",
        "solar_tariff_peak_interaction",
        "solar_morning_ramp_interaction",
        "solar_afternoon_decline_interaction",
        *[f"lag_{lag}" for lag in LAG_WINDOWS],
        *[f"rolling_mean_{window}" for window in ROLL_WINDOWS],
        *[f"rolling_std_{window}" for window in ROLL_WINDOWS],
        *[f"rolling_max_{window}" for window in ROLL_WINDOWS],
        "delta_lag_1_2",
        "delta_lag_2_3",
        "delta_lag_1_48",
        "delta_lag_1_336",
        "same_slot_prev_day_delta",
        "same_slot_prev_week_delta",
        "same_slot_day_vs_week_gap",
        "rolling_delta_mean_4",
        "rolling_delta_std_4",
        "rolling_delta_mean_24",
        "rolling_delta_std_24",
    ]

    prepared = ordered.dropna(subset=feature_columns + ["kw_import"]).reset_index(drop=True)
    return prepared, feature_columns


def _winsorize_target(series: pd.Series, lower_q: float = 0.01, upper_q: float = 0.995) -> pd.Series:
    lower = float(series.quantile(lower_q))
    upper = float(series.quantile(upper_q))
    if lower > upper:
        lower, upper = upper, lower
    return series.clip(lower=lower, upper=upper)


def build_training_rows(
    frames: Iterable[pd.DataFrame],
    lower_q: float = 0.01,
    upper_q: float = 0.995,
    normalize_targets: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    prepared_frames: list[pd.DataFrame] = []
    feature_columns_ref: list[str] | None = None

    for frame in frames:
        working_frame = normalize_site_frame(frame)[0] if normalize_targets else frame.copy()
        prepared, feature_columns = add_enhanced_features(working_frame)
        if prepared.empty:
            continue

        prepared = prepared.copy()
        prepared["kw_import"] = _winsorize_target(
            prepared["kw_import"].astype(float),
            lower_q=lower_q,
            upper_q=upper_q,
        )
        prepared_frames.append(prepared)
        feature_columns_ref = feature_columns

    if not prepared_frames or feature_columns_ref is None:
        raise ValueError("No frames were provided for enhanced training row construction")

    rows = pd.concat(prepared_frames, ignore_index=True)
    rows = rows.sort_values("interval_end").reset_index(drop=True)
    return rows, feature_columns_ref


def tune_ridge_alpha(
    rows: pd.DataFrame,
    feature_columns: list[str],
    alpha_grid: Iterable[float] | None = None,
    n_splits: int = 4,
) -> pd.DataFrame:
    if alpha_grid is None:
        alpha_grid = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]

    dynamic_splits = max(2, min(n_splits, max(2, len(rows) // 500)))
    dynamic_splits = min(dynamic_splits, len(rows) - 1)
    if dynamic_splits < 2:
        raise ValueError("Not enough rows for time-based CV tuning")

    splitter = TimeSeriesSplit(n_splits=dynamic_splits)
    scores = []
    for alpha in alpha_grid:
        fold_rmses: list[float] = []
        fold_md_errors: list[float] = []
        for train_idx, val_idx in splitter.split(rows):
            train_rows = rows.iloc[train_idx]
            val_rows = rows.iloc[val_idx]

            model = Pipeline(
                steps=[
                    ("scaler", StandardScaler()),
                    ("ridge", Ridge(alpha=float(alpha))),
                ]
            )
            model.fit(train_rows[feature_columns], train_rows["kw_import"])

            val_pred = np.clip(model.predict(val_rows[feature_columns]), 0.0, None)
            val_true = val_rows["kw_import"].to_numpy()

            fold_rmse = float(np.sqrt(mean_squared_error(val_true, val_pred)))
            fold_md_error = float(abs(np.max(val_true) - np.max(val_pred)))
            fold_rmses.append(fold_rmse)
            fold_md_errors.append(fold_md_error)

        cv_rmse = float(np.mean(fold_rmses))
        cv_md = float(np.mean(fold_md_errors))
        cv_objective = 0.75 * cv_rmse + 0.25 * cv_md
        scores.append(
            {
                "alpha": float(alpha),
                "cv_rmse": cv_rmse,
                "cv_md_abs_error": cv_md,
                "cv_objective": cv_objective,
            }
        )

    return pd.DataFrame(scores).sort_values(["cv_objective", "cv_rmse"]).reset_index(drop=True)


def fit_global_enhanced_ridge(
    frames: Iterable[pd.DataFrame],
    alpha_grid: Iterable[float] | None = None,
    n_splits: int = 4,
    normalize_targets: bool = True,
) -> TrainedRidge:
    rows, feature_columns = build_training_rows(frames, normalize_targets=normalize_targets)
    alpha_scores = tune_ridge_alpha(rows, feature_columns, alpha_grid=alpha_grid, n_splits=n_splits)
    best_alpha = float(alpha_scores.iloc[0]["alpha"])

    model = Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            ("ridge", Ridge(alpha=best_alpha)),
        ]
    )
    model.fit(rows[feature_columns], rows["kw_import"])

    return TrainedRidge(
        model=model,
        feature_columns=feature_columns,
        alpha=best_alpha,
        alpha_scores=alpha_scores,
        normalize_targets=normalize_targets,
    )


def _lag_value(history: list[float], lag: int) -> float:
    return float(history[-lag]) if len(history) >= lag else float(history[-1])


def enhanced_feature_row(history: list[float], next_end: pd.Timestamp, has_solar: bool) -> dict[str, float]:
    hour = next_end.hour + next_end.minute / 60.0
    day_of_week = float(next_end.dayofweek)
    month = float(next_end.month)

    def recent_values(window: int) -> list[float]:
        return history[-window:] if len(history) >= window else history

    row: dict[str, float] = {
        "hour_sin": float(np.sin(2 * np.pi * hour / 24)),
        "hour_cos": float(np.cos(2 * np.pi * hour / 24)),
        "dow_sin": float(np.sin(2 * np.pi * day_of_week / 7)),
        "dow_cos": float(np.cos(2 * np.pi * day_of_week / 7)),
        "month_sin": float(np.sin(2 * np.pi * month / 12)),
        "month_cos": float(np.cos(2 * np.pi * month / 12)),
        "is_weekend": float(next_end.dayofweek >= 5),
        "is_monday": float(next_end.dayofweek == 0),
        "is_post_weekend": float(next_end.dayofweek == 0 and hour < 18),
        "weekday_daylight": float(next_end.dayofweek < 5 and 6 <= hour < 18),
        "tariff_peak": float(14 <= hour < 22),
        "daylight": float(6 <= hour < 18),
        "has_solar_int": float(int(has_solar)),
    }
    row["solar_daylight_interaction"] = row["has_solar_int"] * row["daylight"]
    row["solar_weekday_daylight_interaction"] = row["has_solar_int"] * row["weekday_daylight"]
    row["solar_post_weekend_interaction"] = row["has_solar_int"] * row["is_post_weekend"]

    row["morning_ramp_indicator"] = float(6 <= hour < 10)
    row["afternoon_decline_indicator"] = float(14 <= hour < 18)
    row["daylight_progress"] = float(np.clip((hour - 6.0) / 12.0, 0.0, 1.0) if 6 <= hour < 18 else 0.0)
    row["solar_daylight_progress"] = row["has_solar_int"] * row["daylight_progress"]
    row["solar_hour_sin_interaction"] = row["has_solar_int"] * row["daylight"] * row["hour_sin"]
    row["solar_hour_cos_interaction"] = row["has_solar_int"] * row["daylight"] * row["hour_cos"]
    row["solar_tariff_peak_interaction"] = row["has_solar_int"] * row["tariff_peak"]
    row["solar_morning_ramp_interaction"] = row["has_solar_int"] * row["morning_ramp_indicator"]
    row["solar_afternoon_decline_interaction"] = row["has_solar_int"] * row["afternoon_decline_indicator"]

    for lag in LAG_WINDOWS:
        row[f"lag_{lag}"] = _lag_value(history, lag)

    for window in ROLL_WINDOWS:
        values = recent_values(window)
        row[f"rolling_mean_{window}"] = float(np.mean(values))
        row[f"rolling_std_{window}"] = float(np.std(values)) if len(values) > 1 else 0.0
        row[f"rolling_max_{window}"] = float(np.max(values))

    row["delta_lag_1_2"] = row["lag_1"] - row["lag_2"]
    row["delta_lag_2_3"] = row["lag_2"] - row["lag_3"]
    row["delta_lag_1_48"] = row["lag_1"] - row["lag_48"]
    row["delta_lag_1_336"] = row["lag_1"] - row["lag_336"]
    row["same_slot_prev_day_delta"] = row["lag_48"] - row["lag_96"]
    row["same_slot_prev_week_delta"] = row["lag_336"] - row["lag_672"]
    row["same_slot_day_vs_week_gap"] = row["lag_48"] - row["lag_336"]

    diffs = np.diff(history[-25:]) if len(history) >= 25 else np.diff(history)
    recent_diffs_4 = diffs[-4:] if len(diffs) >= 4 else diffs
    recent_diffs_24 = diffs[-24:] if len(diffs) >= 24 else diffs
    row["rolling_delta_mean_4"] = float(np.mean(recent_diffs_4)) if len(recent_diffs_4) > 0 else 0.0
    row["rolling_delta_std_4"] = float(np.std(recent_diffs_4)) if len(recent_diffs_4) > 1 else 0.0
    row["rolling_delta_mean_24"] = float(np.mean(recent_diffs_24)) if len(recent_diffs_24) > 0 else 0.0
    row["rolling_delta_std_24"] = float(np.std(recent_diffs_24)) if len(recent_diffs_24) > 1 else 0.0
    return row


def seasonal_anchor_components(history: list[float], next_end: pd.Timestamp) -> dict[str, float | bool]:
    hour = next_end.hour + next_end.minute / 60.0
    prev_day = _lag_value(history, 48)
    prev_week = _lag_value(history, 336)
    prev_two_weeks = _lag_value(history, 672) if len(history) >= 672 else prev_week
    is_daylight = 6 <= hour < 18
    is_monday = next_end.dayofweek == 0
    is_weekday_daylight = next_end.dayofweek < 5 and is_daylight

    if is_monday:
        daily_weight, weekly_weight = 0.2, 0.8
    elif is_weekday_daylight:
        daily_weight, weekly_weight = 0.4, 0.6
    else:
        daily_weight, weekly_weight = 0.7, 0.3

    anchor = daily_weight * prev_day + weekly_weight * prev_week
    floor_reference = max(prev_day, prev_week, 0.9 * prev_two_weeks)
    return {
        "anchor": float(anchor),
        "floor_reference": float(floor_reference),
        "is_daylight": bool(is_daylight),
        "is_monday": bool(is_monday),
        "is_weekday_daylight": bool(is_weekday_daylight),
    }


def fit_site_calibration(
    model: Pipeline,
    site_train_frame: pd.DataFrame,
    feature_columns: list[str],
    window: int = 336,
    shrink_to_identity: float = 0.60,
    slope_bounds: tuple[float, float] = (0.90, 1.10),
    intercept_std_factor: float = 0.15,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> tuple[float, float]:
    working_frame = normalize_site_frame(site_train_frame, site_scale)[0] if normalize_targets else site_train_frame.copy()
    prepared, _ = add_enhanced_features(working_frame)
    if prepared.empty:
        return 0.0, 1.0

    calibration_rows = prepared.tail(window)
    x_raw = model.predict(calibration_rows[feature_columns]).astype(float)
    y_true = calibration_rows["kw_import"].to_numpy(dtype=float)

    if len(x_raw) < 2 or len(np.unique(x_raw)) < 2:
        return 0.0, 1.0

    calibrator = LinearRegression()
    calibrator.fit(x_raw.reshape(-1, 1), y_true)
    raw_intercept = float(calibrator.intercept_)
    raw_slope = float(calibrator.coef_[0])

    shrink = float(np.clip(shrink_to_identity, 0.0, 1.0))
    slope = shrink * 1.0 + (1.0 - shrink) * raw_slope
    intercept = (1.0 - shrink) * raw_intercept

    y_std = float(np.std(y_true))
    if y_std > 0:
        max_abs_intercept = intercept_std_factor * y_std
        intercept = float(np.clip(intercept, -max_abs_intercept, max_abs_intercept))

    slope = float(np.clip(slope, slope_bounds[0], slope_bounds[1]))
    return intercept, slope


def _prediction_guardrails(
    history: list[float],
    recent_window: int = 96,
    lower_quantile: float = 0.05,
    upper_quantile: float = 0.95,
    expansion: float = 0.10,
    seasonal_floor: float | None = None,
    is_weekday_daylight: bool = False,
    is_monday: bool = False,
) -> tuple[float, float]:
    recent = history[-recent_window:] if len(history) >= recent_window else history
    series = np.asarray(recent, dtype=float)
    q_low, q_high = np.quantile(series, [lower_quantile, upper_quantile])
    span = max(float(q_high - q_low), 1.0e-6)
    lower = max(0.0, float(q_low - expansion * span))
    upper = float(q_high + expansion * span)

    if seasonal_floor is not None and is_weekday_daylight:
        floor_ratio = 0.70 if is_monday else 0.60
        cap_ratio = 1.25 if is_monday else 1.15
        lower = max(lower, floor_ratio * float(seasonal_floor))
        upper = max(upper, cap_ratio * float(seasonal_floor))

    return lower, upper


def forecast_with_enhanced_model(
    model: Pipeline,
    feature_columns: list[str],
    target_frame: pd.DataFrame,
    horizon: int = 48,
    blend_weight: float = 0.70,
    calibration: tuple[float, float] = (0.0, 1.0),
    max_step_change_ratio: float = 0.16,
    solar_daylight_anchor: float = 0.15,
    horizon_blend_floor: float = 0.20,
    horizon_blend_decay: float = 0.25,
    solar_daytime_extra_decay: float = 0.05,
    solar_daytime_floor_ratio: float = 0.78,
    solar_daytime_up_ratio: float = 0.55,
    solar_daytime_down_ratio: float = 0.18,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> pd.DataFrame:
    ordered = target_frame.sort_values("interval_end").reset_index(drop=True)
    working_frame, inferred_scale = (
        normalize_site_frame(ordered, site_scale)
        if normalize_targets
        else (ordered.copy(), 1.0)
    )
    history = working_frame["kw_import"].astype(float).tolist()
    has_solar = bool(ordered["has_solar"].iloc[0])
    site_id = str(ordered["site_id"].iloc[0])
    last_end = pd.Timestamp(ordered["interval_end"].iloc[-1])

    offset, scale = calibration
    rows: list[dict[str, object]] = []
    for step in range(1, horizon + 1):
        next_end = last_end + pd.Timedelta(minutes=30 * step)
        anchor_info = seasonal_anchor_components(history, next_end)
        is_daylight = bool(anchor_info["is_daylight"])
        is_weekday_daylight = bool(anchor_info["is_weekday_daylight"])
        is_monday = bool(anchor_info["is_monday"])

        feature_row = enhanced_feature_row(history, next_end, has_solar)
        feature_frame = pd.DataFrame([feature_row], columns=feature_columns)

        ridge_pred = max(float(model.predict(feature_frame)[0]), 0.0)
        seasonal_pred = float(anchor_info["anchor"])
        floor_reference = float(max(anchor_info["floor_reference"], seasonal_pred))

        progress = float(step - 1) / float(max(horizon - 1, 1))
        effective_blend = float(np.clip(blend_weight * (1.0 - horizon_blend_decay * progress), horizon_blend_floor, 1.0))

        if has_solar and is_weekday_daylight:
            min_seasonal_share = 0.45 if is_monday else 0.35
            effective_blend = min(effective_blend, 1.0 - min_seasonal_share)

        if has_solar and is_daylight and solar_daytime_extra_decay > 0:
            effective_blend = float(
                np.clip(
                    effective_blend * (1.0 - solar_daytime_extra_decay * progress),
                    max(0.05, horizon_blend_floor * 0.75),
                    1.0,
                )
            )

        blended_pred = effective_blend * ridge_pred + (1.0 - effective_blend) * seasonal_pred

        if has_solar and is_weekday_daylight and solar_daylight_anchor > 0:
            extra_anchor = 0.15 if is_monday else 0.05
            anchor = float(np.clip(solar_daylight_anchor + extra_anchor, 0.0, 0.85))
            blended_pred = (1.0 - anchor) * blended_pred + anchor * seasonal_pred

        calibrated_pred = max(offset + scale * blended_pred, 0.0)
        lower_guard, upper_guard = _prediction_guardrails(
            history,
            seasonal_floor=floor_reference if has_solar else None,
            is_weekday_daylight=is_weekday_daylight if has_solar else False,
            is_monday=is_monday if has_solar else False,
        )
        prev = float(history[-1])

        if has_solar and is_weekday_daylight:
            reference_level = max(prev, seasonal_pred, floor_reference, 1.0e-6)
            up_ratio = float(np.clip(solar_daytime_up_ratio + (0.20 if is_monday else 0.0), 0.10, 1.20))
            down_ratio = float(np.clip(solar_daytime_down_ratio, 0.05, 0.50))
            max_up_delta = max(0.08, up_ratio * reference_level)
            max_down_delta = max(0.03, down_ratio * reference_level)
        else:
            reference_level = max(prev, seasonal_pred, 1.0e-6)
            step_delta = max(0.04, max_step_change_ratio * reference_level)
            max_up_delta = step_delta
            max_down_delta = step_delta

        step_low = max(0.0, prev - max_down_delta)
        step_high = prev + max_up_delta

        guarded_pred = float(np.clip(calibrated_pred, step_low, step_high))
        final_pred = float(np.clip(guarded_pred, lower_guard, upper_guard))

        if has_solar and is_weekday_daylight and solar_daytime_floor_ratio > 0:
            floor_ratio = float(np.clip(solar_daytime_floor_ratio + (0.08 if is_monday else 0.0), 0.0, 1.30))
            daytime_floor = max(lower_guard, floor_ratio * floor_reference)
            final_pred = max(final_pred, daytime_floor)

        history.append(final_pred)
        output_scale = float(inferred_scale)
        rows.append(
            {
                "site_id": site_id,
                "interval_start": next_end - pd.Timedelta(minutes=30),
                "interval_end": next_end,
                "forecast_kw_import": final_pred * output_scale,
                "ridge_component": ridge_pred * output_scale,
                "seasonal_component": seasonal_pred * output_scale,
                "effective_blend_weight": effective_blend,
                "guardrail_lower": lower_guard * output_scale,
                "guardrail_upper": upper_guard * output_scale,
            }
        )

    return _add_peak_flags(pd.DataFrame(rows))


def _validation_cutoffs(
    frame_length: int,
    horizon: int,
    min_train: int = 48 * 10,
    step: int = 48,
    max_folds: int = 7,
) -> list[int]:
    cutoffs = []
    cutoff = min_train
    while cutoff + horizon <= frame_length:
        cutoffs.append(cutoff)
        cutoff += step

    if len(cutoffs) > max_folds:
        cutoffs = cutoffs[-max_folds:]
    return cutoffs


def select_blend_weight(
    model: Pipeline,
    site_train_frame: pd.DataFrame,
    feature_columns: list[str],
    horizon: int = 48,
    candidates: Iterable[float] | None = None,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> tuple[float, pd.DataFrame]:
    if candidates is None:
        candidates = np.linspace(0.20, 0.75, 8)

    if len(site_train_frame) <= horizon + 336:
        default_table = pd.DataFrame(
            {
                "blend_weight": [0.65],
                "rmse": [np.nan],
                "md_abs_error": [np.nan],
                "objective": [np.nan],
            }
        )
        return 0.65, default_table

    cutoffs = _validation_cutoffs(len(site_train_frame), horizon=horizon)
    if not cutoffs:
        default_table = pd.DataFrame(
            {
                "blend_weight": [0.65],
                "rmse": [np.nan],
                "md_abs_error": [np.nan],
                "objective": [np.nan],
            }
        )
        return 0.65, default_table

    inferred_scale = site_scale_from_frame(site_train_frame) if normalize_targets and site_scale is None else site_scale

    rows = []
    for weight in candidates:
        fold_rmses: list[float] = []
        fold_md_errors: list[float] = []

        for cutoff in cutoffs:
            inner_train = site_train_frame.iloc[:cutoff].copy()
            inner_actual = site_train_frame.iloc[cutoff : cutoff + horizon]["kw_import"].to_numpy()

            calibration = fit_site_calibration(
                model,
                inner_train,
                feature_columns,
                normalize_targets=normalize_targets,
                site_scale=inferred_scale,
            )

            pred = forecast_with_enhanced_model(
                model=model,
                feature_columns=feature_columns,
                target_frame=inner_train,
                horizon=horizon,
                blend_weight=float(weight),
                calibration=calibration,
                normalize_targets=normalize_targets,
                site_scale=inferred_scale,
            )["forecast_kw_import"].to_numpy()

            rmse = float(np.sqrt(mean_squared_error(inner_actual, pred)))
            md_abs_error = float(abs(np.max(inner_actual) - np.max(pred)))
            fold_rmses.append(rmse)
            fold_md_errors.append(md_abs_error)

        mean_rmse = float(np.mean(fold_rmses))
        mean_md = float(np.mean(fold_md_errors))
        objective = 0.70 * mean_rmse + 0.30 * mean_md
        rows.append(
            {
                "blend_weight": float(weight),
                "rmse": mean_rmse,
                "md_abs_error": mean_md,
                "objective": objective,
            }
        )

    table = pd.DataFrame(rows).sort_values(["objective", "rmse"]).reset_index(drop=True)
    best_weight = float(table.iloc[0]["blend_weight"])
    return best_weight, table


def forecast_next_intervals(
    frames: list[pd.DataFrame],
    target_frame: pd.DataFrame,
    horizon: int = 48,
) -> pd.DataFrame:
    if not frames:
        raise ValueError("At least one training frame is required")
    if target_frame.empty:
        raise ValueError("Target frame is empty")

    min_enhanced_history = max(LAG_WINDOWS) + 1
    eligible_frames = [frame for frame in frames if len(frame) >= min_enhanced_history]
    can_use_enhanced = len(target_frame) >= min_enhanced_history and len(eligible_frames) > 0

    if not can_use_enhanced:
        baseline_model = _fit_baseline_model(frames)
        return _forecast_with_baseline_model(baseline_model, target_frame, horizon)

    try:
        enhanced = fit_global_enhanced_ridge(eligible_frames, normalize_targets=True)
        inferred_scale = site_scale_from_frame(target_frame) if enhanced.normalize_targets else None
        calibration = fit_site_calibration(
            enhanced.model,
            target_frame,
            enhanced.feature_columns,
            normalize_targets=enhanced.normalize_targets,
            site_scale=inferred_scale,
        )
        blend_weight, _ = select_blend_weight(
            enhanced.model,
            target_frame,
            enhanced.feature_columns,
            horizon=horizon,
            normalize_targets=enhanced.normalize_targets,
            site_scale=inferred_scale,
        )
        return forecast_with_enhanced_model(
            model=enhanced.model,
            feature_columns=enhanced.feature_columns,
            target_frame=target_frame,
            horizon=horizon,
            blend_weight=blend_weight,
            calibration=calibration,
            normalize_targets=enhanced.normalize_targets,
            site_scale=inferred_scale,
        )
    except ValueError:
        baseline_model = _fit_baseline_model(frames)
        return _forecast_with_baseline_model(baseline_model, target_frame, horizon)


def backtest_site_forecast(frame: pd.DataFrame, horizon: int = 48) -> ForecastBacktestResult:
    ordered = frame.sort_values("interval_end").reset_index(drop=True)
    if len(ordered) <= horizon:
        raise ValueError("Not enough rows to run backtest")

    train_frame = ordered.iloc[:-horizon].copy()
    actual_frame = ordered.iloc[-horizon:].copy()
    predictions = forecast_next_intervals(frames=[train_frame], target_frame=train_frame, horizon=horizon)
    predictions = predictions.copy()
    predictions["actual_kw_import"] = actual_frame["kw_import"].to_numpy()

    errors = predictions["forecast_kw_import"] - predictions["actual_kw_import"]
    mae = float(errors.abs().mean())
    rmse = float(sqrt((errors.pow(2)).mean()))
    denominator = actual_frame["kw_import"].replace(0, pd.NA)
    mape = float(((errors.abs() / denominator).dropna()).mean() * 100)

    return ForecastBacktestResult(
        predictions=predictions,
        metrics={
            "mae_kw": mae,
            "rmse_kw": rmse,
            "mape_pct": mape,
        },
    )
