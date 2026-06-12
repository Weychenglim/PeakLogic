from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import importlib
import os
from typing import Iterable, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingRegressor, HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


LAG_WINDOWS = [1, 2, 3, 6, 24, 48, 96, 336, 672]
ROLL_WINDOWS = [4, 24, 48]
FORECAST_LEAKAGE_COLUMNS = {
    "kw_import",
    "kw_export",
    "kvar_import",
    "kvar_export",
    "gross_load",
    "solar_generated",
    "actual_kw_import",
}


@dataclass
class TrainedRidge:
    model: Pipeline | SegmentedRidgeModel
    feature_columns: list[str]
    alpha: float | dict[str, float]
    alpha_scores: pd.DataFrame
    normalize_targets: bool


@dataclass
class PeakRiskOverlay:
    model: Pipeline | None
    feature_columns: list[str]
    peak_quantile: float
    threshold_kw: float
    constant_probability: float | None = None


@dataclass(frozen=True)
class PeakAlertPolicy:
    alert_quantile: float
    match_window_intervals: int = 2
    score_smoothing_window: int = 1
    overlay_weight: float = 0.60


@dataclass(frozen=True)
class MdPeakCalibration:
    multiplier: float
    intercept_kw: float = 0.0


@dataclass(frozen=True)
class LateHorizonPeakEnvelope:
    slot_floors_kw: dict[tuple[int, int, int], float]
    half_hour_floors_kw: dict[tuple[int, int], float]
    global_floor_kw: float
    site_peak_floor_kw: float = 0.0


@dataclass
class DirectHorizonBoostedModel:
    model: HistGradientBoostingRegressor | GradientBoostingRegressor
    feature_columns: list[str]
    horizon: int
    normalize_targets: bool
    estimator_name: str = "hist_gradient_boosting"


@dataclass
class DirectHorizonQuantileModel:
    quantile_models: dict[float, object]
    feature_columns: list[str]
    horizon: int
    normalize_targets: bool
    md_risk_model: object | None = None
    md_risk_constant_probability: float | None = None


DEFAULT_SOLAR_PEAK_ALERT_POLICY = PeakAlertPolicy(alert_quantile=0.80)
DEFAULT_NONSOLAR_PEAK_ALERT_POLICY = PeakAlertPolicy(alert_quantile=0.80)


def peak_alert_policy_for_site(has_solar: bool) -> PeakAlertPolicy:
    return DEFAULT_SOLAR_PEAK_ALERT_POLICY if bool(has_solar) else DEFAULT_NONSOLAR_PEAK_ALERT_POLICY


class _CombinedRidgeView:
    def __init__(self, coef: np.ndarray):
        self.coef_ = coef


class SegmentedRidgeModel:
    def __init__(
        self,
        segment_models: dict[str, Pipeline],
        segment_feature_columns: dict[str, list[str]],
        segment_row_counts: dict[str, int],
    ) -> None:
        self.segment_models = segment_models
        self.segment_feature_columns = segment_feature_columns
        self.segment_row_counts = segment_row_counts
        self.named_steps = {"ridge": _CombinedRidgeView(self._combined_coef())}

    def _combined_coef(self) -> np.ndarray:
        weighted = []
        total = max(sum(self.segment_row_counts.values()), 1)
        for segment_key, model in self.segment_models.items():
            ridge = model.named_steps["ridge"]
            weight = float(self.segment_row_counts.get(segment_key, 0)) / float(total)
            weighted.append(weight * np.asarray(ridge.coef_, dtype=float))
        return np.sum(weighted, axis=0) if weighted else np.array([], dtype=float)

    def predict(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        if not isinstance(features, pd.DataFrame):
            raise TypeError("SegmentedRidgeModel.predict expects a pandas DataFrame with feature columns")

        if "has_solar_int" not in features.columns:
            raise ValueError("Feature frame must contain 'has_solar_int' for segmented prediction")

        predictions = np.zeros(len(features), dtype=float)
        solar_mask = features["has_solar_int"].to_numpy(dtype=float) >= 0.5
        segment_masks = {
            "solar": solar_mask,
            "non_solar": ~solar_mask,
        }

        for segment_key, mask in segment_masks.items():
            if not np.any(mask):
                continue
            model = self.segment_models[segment_key]
            feature_columns = self.segment_feature_columns[segment_key]
            predictions[mask] = model.predict(features.loc[mask, feature_columns])

        return predictions


def _segment_key(has_solar: bool) -> str:
    return "solar" if bool(has_solar) else "non_solar"


def _segment_key_from_frame(frame: pd.DataFrame) -> str:
    return _segment_key(bool(frame["has_solar"].iloc[0]))


def _segment_site_counts(frames: Iterable[pd.DataFrame]) -> dict[str, int]:
    counts = {"solar": 0, "non_solar": 0}
    seen_site_ids: dict[str, set[str]] = {"solar": set(), "non_solar": set()}

    for frame in frames:
        segment_key = _segment_key_from_frame(frame)
        site_id = str(frame["site_id"].iloc[0])
        if site_id not in seen_site_ids[segment_key]:
            seen_site_ids[segment_key].add(site_id)
            counts[segment_key] += 1

    return counts


def should_use_segmented_training(
    frames: Iterable[pd.DataFrame],
    enable_segmented_training: bool = False,
    segmented_min_sites_per_segment: int = 2,
) -> bool:
    if not enable_segmented_training:
        return False

    counts = _segment_site_counts(frames)
    return (
        counts["solar"] >= segmented_min_sites_per_segment
        and counts["non_solar"] >= segmented_min_sites_per_segment
    )


def _regime_labels(timestamp: pd.Timestamp) -> tuple[str, str]:
    light_regime = "daylight" if 6 <= (timestamp.hour + timestamp.minute / 60.0) < 18 else "night"
    period_type = "weekend" if timestamp.dayofweek >= 5 else "weekday"
    return light_regime, period_type


def _regime_key(timestamp: pd.Timestamp) -> tuple[str, str]:
    return _regime_labels(timestamp)


def site_evaluation_settings(has_solar: bool) -> dict[str, object]:
    if has_solar:
        return {
            "alpha_grid": [3.0, 10.0, 30.0, 100.0],
            "blend_candidates": np.linspace(0.20, 0.65, 6),
            "forecast_kwargs": {
                "solar_daylight_anchor": 0.18,
                "max_step_change_ratio": 0.16,
                "horizon_blend_floor": 0.18,
                "horizon_blend_decay": 0.25,
                "solar_daytime_extra_decay": 0.08,
                "solar_daytime_floor_ratio": 0.82,
                "solar_daytime_floor_enabled": True,
                "solar_daytime_up_ratio": 0.60,
                "solar_monday_step_up_bonus": 0.20,
                "solar_daytime_down_ratio": 0.18,
            },
            "inner_forecast_kwargs": {
                "inner_solar_daylight_anchor": 0.18,
                "inner_max_step_change_ratio": 0.16,
                "inner_horizon_blend_floor": 0.18,
                "inner_horizon_blend_decay": 0.25,
                "inner_solar_daytime_extra_decay": 0.08,
                "inner_solar_daytime_floor_ratio": 0.82,
                "inner_solar_daytime_floor_enabled": True,
                "inner_solar_daytime_up_ratio": 0.60,
                "inner_solar_monday_step_up_bonus": 0.20,
                "inner_solar_daytime_down_ratio": 0.18,
            },
        }

    return {
        "alpha_grid": None,
        "blend_candidates": np.linspace(0.30, 0.75, 6),
            "forecast_kwargs": {
                "solar_daylight_anchor": 0.0,
                "max_step_change_ratio": 0.16,
                "horizon_blend_floor": 0.25,
                "horizon_blend_decay": 0.30,
                "solar_daytime_extra_decay": 0.0,
                "solar_daytime_floor_ratio": 0.0,
                "solar_daytime_floor_enabled": False,
                "solar_daytime_up_ratio": 0.0,
                "solar_monday_step_up_bonus": 0.0,
                "solar_daytime_down_ratio": 0.0,
            },
            "inner_forecast_kwargs": {
                "inner_solar_daylight_anchor": 0.0,
                "inner_max_step_change_ratio": 0.16,
                "inner_horizon_blend_floor": 0.25,
                "inner_horizon_blend_decay": 0.30,
                "inner_solar_daytime_extra_decay": 0.0,
                "inner_solar_daytime_floor_ratio": 0.0,
                "inner_solar_daytime_floor_enabled": False,
                "inner_solar_daytime_up_ratio": 0.0,
                "inner_solar_monday_step_up_bonus": 0.0,
                "inner_solar_daytime_down_ratio": 0.0,
            },
        }


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
    ts = ordered["interval_end"]

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

    target = ordered["kw_import"].astype(float)
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
    ordered["recent_slope_4"] = (target.shift(1) - target.shift(5)) / 4.0
    ordered["recent_slope_8"] = (target.shift(1) - target.shift(9)) / 8.0
    ordered["recent_acceleration_4"] = ordered["recent_slope_4"] - ordered["recent_slope_4"].shift(4)
    ordered["gap_to_rolling_max_48"] = ordered["rolling_max_48"] - target.shift(1)
    ordered["rolling_max_ratio_48"] = (
        target.shift(1) / ordered["rolling_max_48"].replace(0.0, np.nan)
    ).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    ordered["ramp_to_tariff_peak_interaction"] = ordered["recent_slope_4"] * ordered["tariff_peak"]
    ordered["solar_ramp_to_daylight_interaction"] = ordered["recent_slope_4"] * ordered["solar_daylight_interaction"]

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
        "recent_slope_4",
        "recent_slope_8",
        "recent_acceleration_4",
        "gap_to_rolling_max_48",
        "rolling_max_ratio_48",
        "ramp_to_tariff_peak_interaction",
        "solar_ramp_to_daylight_interaction",
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
        prepared = prepared.copy()
        prepared["kw_import"] = _winsorize_target(
            prepared["kw_import"].astype(float),
            lower_q=lower_q,
            upper_q=upper_q,
        )
        prepared_frames.append(prepared)
        feature_columns_ref = feature_columns

    if feature_columns_ref is None:
        raise ValueError("No frames were provided for training row construction")

    rows = pd.concat(prepared_frames, ignore_index=True)
    rows = rows.sort_values("interval_end").reset_index(drop=True)
    return rows, feature_columns_ref


def _target_time_features(timestamp: pd.Timestamp, horizon_step: int, horizon: int) -> dict[str, float]:
    hour = float(timestamp.hour + timestamp.minute / 60.0)
    day_of_week = int(timestamp.dayofweek)
    month = int(timestamp.month)
    return {
        "horizon_step": float(horizon_step),
        "horizon_fraction": float(horizon_step) / float(max(int(horizon), 1)),
        "target_hour_sin": float(np.sin(2 * np.pi * hour / 24.0)),
        "target_hour_cos": float(np.cos(2 * np.pi * hour / 24.0)),
        "target_dow_sin": float(np.sin(2 * np.pi * day_of_week / 7.0)),
        "target_dow_cos": float(np.cos(2 * np.pi * day_of_week / 7.0)),
        "target_month_sin": float(np.sin(2 * np.pi * month / 12.0)),
        "target_month_cos": float(np.cos(2 * np.pi * month / 12.0)),
        "target_day_of_week": float(day_of_week),
        "target_is_weekend": float(day_of_week >= 5),
        "target_is_daylight": float(6.0 <= hour < 18.0),
        "target_tariff_peak": float(14.0 <= hour < 22.0),
    }


DIRECT_HORIZON_TIME_FEATURES = [
    "horizon_step",
    "horizon_fraction",
    "target_hour_sin",
    "target_hour_cos",
    "target_dow_sin",
    "target_dow_cos",
    "target_month_sin",
    "target_month_cos",
    "target_day_of_week",
    "target_is_weekend",
    "target_is_daylight",
    "target_tariff_peak",
]


def require_lightgbm():
    try:
        return importlib.import_module("lightgbm")
    except ImportError as exc:
        raise ImportError(
            "LightGBM is required for the direct-horizon quantile benchmark. "
            "Install it with `python -m pip install lightgbm`."
        ) from exc


def build_direct_horizon_training_rows(
    frames: Iterable[pd.DataFrame],
    horizon: int = 48,
    lower_q: float = 0.01,
    upper_q: float = 0.995,
    normalize_targets: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    prepared_rows: list[pd.DataFrame] = []
    feature_columns_ref: list[str] | None = None
    bounded_horizon = max(int(horizon), 1)

    for frame in frames:
        working_frame = normalize_site_frame(frame)[0] if normalize_targets else frame.copy()
        prepared, feature_columns = add_enhanced_features(working_frame)
        prepared = prepared.copy()
        prepared["kw_import"] = _winsorize_target(
            prepared["kw_import"].astype(float),
            lower_q=lower_q,
            upper_q=upper_q,
        )
        feature_columns_ref = feature_columns

        for step in range(1, bounded_horizon + 1):
            step_rows = prepared.iloc[:-step].copy()
            if step_rows.empty:
                continue
            target_values = prepared["kw_import"].shift(-step).iloc[:-step].astype(float).to_numpy()
            target_timestamps = pd.to_datetime(prepared["interval_end"].shift(-step).iloc[:-step])
            step_rows["target_kw_import"] = target_values
            for column in DIRECT_HORIZON_TIME_FEATURES:
                step_rows[column] = [
                    _target_time_features(timestamp, step, bounded_horizon)[column]
                    for timestamp in target_timestamps
                ]
            prepared_rows.append(step_rows)

    if feature_columns_ref is None:
        raise ValueError("No frames were provided for direct-horizon training row construction")
    if not prepared_rows:
        raise ValueError("No direct-horizon training rows could be built")

    feature_columns = [*feature_columns_ref, *DIRECT_HORIZON_TIME_FEATURES]
    rows = pd.concat(prepared_rows, ignore_index=True)
    rows = rows.dropna(subset=feature_columns + ["target_kw_import"]).sort_values("interval_end").reset_index(drop=True)
    return rows, feature_columns


def build_direct_horizon_quantile_rows(
    frames: Sequence[pd.DataFrame] | Iterable[pd.DataFrame],
    horizon: int = 48,
    peak_quantile: float = 0.90,
    normalize_targets: bool = True,
) -> tuple[pd.DataFrame, list[str]]:
    rows, feature_columns = build_direct_horizon_training_rows(
        frames,
        horizon=horizon,
        normalize_targets=normalize_targets,
    )
    if rows.empty:
        return rows, feature_columns

    quantile = float(np.clip(peak_quantile, 0.0, 1.0))
    threshold_by_site = rows.groupby("site_id")["target_kw_import"].transform(
        lambda values: float(np.quantile(values.astype(float), quantile))
    )
    rows = rows.copy()
    rows["is_md_risk_interval"] = (rows["target_kw_import"].astype(float) >= threshold_by_site).astype(int)
    return rows, feature_columns


def fit_direct_horizon_boosted_model(
    frames: Iterable[pd.DataFrame],
    horizon: int = 48,
    max_iter: int = 120,
    learning_rate: float = 0.06,
    max_leaf_nodes: int = 31,
    l2_regularization: float = 0.05,
    normalize_targets: bool = True,
    random_state: int = 42,
) -> DirectHorizonBoostedModel:
    rows, feature_columns = build_direct_horizon_training_rows(
        frames,
        horizon=horizon,
        normalize_targets=normalize_targets,
    )
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=int(max_iter),
        learning_rate=float(learning_rate),
        max_leaf_nodes=int(max_leaf_nodes),
        l2_regularization=float(l2_regularization),
        random_state=int(random_state),
    )
    estimator_name = "hist_gradient_boosting"
    try:
        model.fit(rows[feature_columns], rows["target_kw_import"].astype(float))
    except PermissionError:
        model = GradientBoostingRegressor(
            loss="squared_error",
            n_estimators=int(max_iter),
            learning_rate=float(learning_rate),
            max_leaf_nodes=int(max_leaf_nodes),
            random_state=int(random_state),
        )
        model.fit(rows[feature_columns], rows["target_kw_import"].astype(float))
        estimator_name = "gradient_boosting_fallback"
    return DirectHorizonBoostedModel(
        model=model,
        feature_columns=feature_columns,
        horizon=max(int(horizon), 1),
        normalize_targets=normalize_targets,
        estimator_name=estimator_name,
    )


def _direct_horizon_prediction_features(
    target_frame: pd.DataFrame,
    horizon: int,
    normalize_targets: bool,
    site_scale: float | None = None,
) -> tuple[pd.DataFrame, float]:
    output_scale = float(site_scale if site_scale is not None else site_scale_from_frame(target_frame))
    working_frame = normalize_site_frame(target_frame, output_scale)[0] if normalize_targets else target_frame.copy()
    prepared, base_feature_columns = add_enhanced_features(working_frame)
    if prepared.empty:
        raise ValueError("Not enough history for direct-horizon boosted prediction")

    origin = prepared.sort_values("interval_end").iloc[-1]
    origin_end = pd.Timestamp(origin["interval_end"])
    rows: list[dict[str, float | pd.Timestamp]] = []
    bounded_horizon = max(int(horizon), 1)
    for step in range(1, bounded_horizon + 1):
        target_end = origin_end + pd.Timedelta(minutes=30 * step)
        feature_row = {column: float(origin[column]) for column in base_feature_columns}
        feature_row.update(_target_time_features(target_end, step, bounded_horizon))
        feature_row["interval_end"] = target_end
        rows.append(feature_row)

    return pd.DataFrame(rows), output_scale


def forecast_with_direct_horizon_boosted_model(
    model: DirectHorizonBoostedModel,
    target_frame: pd.DataFrame,
    horizon: int | None = None,
    site_scale: float | None = None,
) -> pd.DataFrame:
    forecast_horizon = int(horizon if horizon is not None else model.horizon)
    feature_frame, output_scale = _direct_horizon_prediction_features(
        target_frame,
        horizon=forecast_horizon,
        normalize_targets=model.normalize_targets,
        site_scale=site_scale,
    )
    predictions = model.model.predict(feature_frame[model.feature_columns]).astype(float)
    if model.normalize_targets:
        predictions = predictions * output_scale
    predictions = np.maximum(0.0, predictions)

    forecast = pd.DataFrame(
        {
            "interval_end": feature_frame["interval_end"].to_numpy(),
            "horizon_step": np.arange(1, len(feature_frame) + 1),
            "forecast_kw_import": predictions,
        }
    )
    max_forecast = float(forecast["forecast_kw_import"].max()) if not forecast.empty else 0.0
    forecast["peak_risk_score"] = forecast["forecast_kw_import"] / max_forecast if max_forecast > 0 else 0.0
    threshold = forecast["forecast_kw_import"].quantile(0.9) if not forecast.empty else 0.0
    forecast["is_predicted_peak"] = forecast["forecast_kw_import"] >= threshold
    return forecast


def fit_direct_horizon_lightgbm_quantile_model(
    frames: Sequence[pd.DataFrame] | Iterable[pd.DataFrame],
    horizon: int = 48,
    quantiles: Sequence[float] = (0.50, 0.80, 0.90),
    n_estimators: int = 120,
    learning_rate: float = 0.04,
    num_leaves: int = 31,
    normalize_targets: bool = True,
    random_state: int = 42,
) -> DirectHorizonQuantileModel:
    lgb = require_lightgbm()
    rows, feature_columns = build_direct_horizon_quantile_rows(
        frames,
        horizon=horizon,
        normalize_targets=normalize_targets,
    )
    if rows.empty:
        raise ValueError("not enough rows to train direct-horizon quantile model")

    x_train = rows[feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    y_train = rows["target_kw_import"].astype(float)

    quantile_models: dict[float, object] = {}
    for quantile in quantiles:
        bounded_quantile = float(np.clip(float(quantile), 0.01, 0.99))
        model = lgb.LGBMRegressor(
            objective="quantile",
            alpha=bounded_quantile,
            n_estimators=int(n_estimators),
            learning_rate=float(learning_rate),
            num_leaves=int(num_leaves),
            random_state=int(random_state),
            verbose=-1,
            n_jobs=1,
        )
        model.fit(x_train, y_train)
        quantile_models[bounded_quantile] = model

    target = rows["is_md_risk_interval"].astype(int)
    md_risk_model = None
    md_risk_constant_probability: float | None = None
    if target.nunique() < 2:
        md_risk_constant_probability = float(target.mean())
    else:
        md_risk_model = lgb.LGBMClassifier(
            n_estimators=max(40, int(n_estimators // 2)),
            learning_rate=float(learning_rate),
            num_leaves=int(num_leaves),
            random_state=int(random_state),
            verbose=-1,
            n_jobs=1,
            class_weight="balanced",
        )
        md_risk_model.fit(x_train, target)

    return DirectHorizonQuantileModel(
        quantile_models=quantile_models,
        feature_columns=feature_columns,
        horizon=max(int(horizon), 1),
        normalize_targets=normalize_targets,
        md_risk_model=md_risk_model,
        md_risk_constant_probability=md_risk_constant_probability,
    )


def _nearest_quantile_key(quantile_models: dict[float, object], requested: float) -> float:
    if not quantile_models:
        raise ValueError("direct-horizon quantile model has no fitted quantile estimators")
    return min(quantile_models.keys(), key=lambda value: abs(float(value) - float(requested)))


def forecast_with_direct_horizon_lightgbm_quantile_model(
    model: DirectHorizonQuantileModel,
    target_frame: pd.DataFrame,
    horizon: int | None = None,
    site_scale: float | None = None,
) -> pd.DataFrame:
    forecast_horizon = int(horizon if horizon is not None else model.horizon)
    feature_frame, output_scale = _direct_horizon_prediction_features(
        target_frame,
        horizon=forecast_horizon,
        normalize_targets=model.normalize_targets,
        site_scale=site_scale,
    )
    x_future = feature_frame[model.feature_columns].replace([np.inf, -np.inf], np.nan).fillna(0.0)

    forecast = pd.DataFrame(
        {
            "interval_end": feature_frame["interval_end"].to_numpy(),
            "horizon_step": np.arange(1, len(feature_frame) + 1),
        }
    )
    for requested, column in [
        (0.50, "forecast_p50_kw_import"),
        (0.80, "forecast_p80_kw_import"),
        (0.90, "forecast_p90_kw_import"),
    ]:
        quantile_key = _nearest_quantile_key(model.quantile_models, requested)
        predictions = model.quantile_models[quantile_key].predict(x_future).astype(float)
        if model.normalize_targets:
            predictions = predictions * output_scale
        forecast[column] = np.maximum(0.0, predictions)

    forecast["forecast_p80_kw_import"] = np.maximum(
        forecast["forecast_p80_kw_import"],
        forecast["forecast_p50_kw_import"],
    )
    forecast["forecast_p90_kw_import"] = np.maximum(
        forecast["forecast_p90_kw_import"],
        forecast["forecast_p80_kw_import"],
    )
    forecast["forecast_kw_import"] = forecast["forecast_p50_kw_import"]
    forecast["md_risk_value_kw_import"] = forecast["forecast_p90_kw_import"]

    if model.md_risk_model is not None:
        forecast["md_risk_head_score"] = model.md_risk_model.predict_proba(x_future)[:, 1]
    else:
        probability = float(model.md_risk_constant_probability or 0.0)
        forecast["md_risk_head_score"] = probability

    max_forecast = float(forecast["forecast_p90_kw_import"].max()) if not forecast.empty else 0.0
    forecast["peak_risk_score"] = forecast["forecast_p90_kw_import"] / max_forecast if max_forecast > 0 else 0.0
    threshold = forecast["forecast_p90_kw_import"].quantile(0.9) if not forecast.empty else 0.0
    forecast["is_predicted_peak"] = forecast["forecast_p90_kw_import"] >= threshold
    return forecast


def tune_ridge_alpha(
    rows: pd.DataFrame,
    feature_columns: list[str],
    alpha_grid: Iterable[float] | None = None,
    n_splits: int = 4,
) -> pd.DataFrame:
    if alpha_grid is None:
        alpha_grid = [0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0]

    dynamic_splits = max(2, min(n_splits, len(rows) // 500))
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
    enable_segmented_training: bool = False,
    segmented_min_sites_per_segment: int = 2,
) -> TrainedRidge:
    frame_list = list(frames)
    if not frame_list:
        raise ValueError("At least one frame is required to fit the enhanced ridge model")

    segment_keys = {_segment_key_from_frame(frame) for frame in frame_list}
    if len(segment_keys) > 1 and should_use_segmented_training(
        frame_list,
        enable_segmented_training=enable_segmented_training,
        segmented_min_sites_per_segment=segmented_min_sites_per_segment,
    ):
        segment_models: dict[str, Pipeline] = {}
        segment_feature_columns: dict[str, list[str]] = {}
        segment_row_counts: dict[str, int] = {}
        segment_alphas: dict[str, float] = {}
        segment_scores: list[pd.DataFrame] = []

        for segment_key in sorted(segment_keys):
            segment_frames = [frame for frame in frame_list if _segment_key_from_frame(frame) == segment_key]
            rows, feature_columns = build_training_rows(segment_frames, normalize_targets=normalize_targets)
            alpha_scores = tune_ridge_alpha(rows, feature_columns, alpha_grid=alpha_grid, n_splits=n_splits)
            best_alpha = float(alpha_scores.iloc[0]["alpha"])

            model = Pipeline(
                steps=[
                    ("scaler", StandardScaler()),
                    ("ridge", Ridge(alpha=best_alpha)),
                ]
            )
            model.fit(rows[feature_columns], rows["kw_import"])

            segment_models[segment_key] = model
            segment_feature_columns[segment_key] = feature_columns
            segment_row_counts[segment_key] = len(rows)
            segment_alphas[segment_key] = best_alpha

            tagged_scores = alpha_scores.copy()
            tagged_scores["segment"] = segment_key
            segment_scores.append(tagged_scores)

        return TrainedRidge(
            model=SegmentedRidgeModel(segment_models, segment_feature_columns, segment_row_counts),
            feature_columns=segment_feature_columns[sorted(segment_feature_columns.keys())[0]],
            alpha=segment_alphas,
            alpha_scores=pd.concat(segment_scores, ignore_index=True),
            normalize_targets=normalize_targets,
        )

    rows, feature_columns = build_training_rows(frame_list, normalize_targets=normalize_targets)
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
    row["recent_slope_4"] = float((history[-1] - history[-5]) / 4.0) if len(history) >= 5 else 0.0
    row["recent_slope_8"] = float((history[-1] - history[-9]) / 8.0) if len(history) >= 9 else 0.0
    previous_slope_4 = float((history[-5] - history[-9]) / 4.0) if len(history) >= 9 else 0.0
    row["recent_acceleration_4"] = row["recent_slope_4"] - previous_slope_4
    rolling_max_48 = float(row["rolling_max_48"])
    last_value = float(history[-1]) if history else 0.0
    row["gap_to_rolling_max_48"] = rolling_max_48 - last_value
    row["rolling_max_ratio_48"] = last_value / rolling_max_48 if rolling_max_48 > 0 else 0.0
    row["ramp_to_tariff_peak_interaction"] = row["recent_slope_4"] * row["tariff_peak"]
    row["solar_ramp_to_daylight_interaction"] = row["recent_slope_4"] * row["solar_daylight_interaction"]

    return row


def seasonal_anchor_components(
    history: list[float],
    next_end: pd.Timestamp,
    has_solar: bool | None = None,
) -> dict[str, float | bool]:
    hour = next_end.hour + next_end.minute / 60.0
    prev_day = _lag_value(history, 48)
    prev_week_raw = _lag_value(history, 336)
    prev_week = prev_week_raw
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

    anchor_gap_ratio = abs(prev_week_raw - prev_day) / max(abs(prev_day), 1.0)
    if has_solar is False and anchor_gap_ratio > 0.20:
        capped_low = 0.85 * prev_day
        capped_high = 1.15 * prev_day
        prev_week = float(np.clip(prev_week_raw, capped_low, capped_high))
        weekly_weight = min(weekly_weight, 0.15)
        daily_weight = 1.0 - weekly_weight

    anchor = daily_weight * prev_day + weekly_weight * prev_week
    floor_reference = max(prev_day, prev_week, 0.9 * prev_two_weeks)
    return {
        "prev_day": float(prev_day),
        "prev_week_raw": float(prev_week_raw),
        "prev_week": float(prev_week),
        "prev_two_weeks": float(prev_two_weeks),
        "daily_weight": float(daily_weight),
        "weekly_weight": float(weekly_weight),
        "anchor_gap_ratio": float(anchor_gap_ratio),
        "anchor": float(anchor),
        "floor_reference": float(floor_reference),
        "is_daylight": bool(is_daylight),
        "is_monday": bool(is_monday),
        "is_weekday_daylight": bool(is_weekday_daylight),
    }


def seasonal_anchor_prediction(
    history: list[float],
    next_end: pd.Timestamp,
    has_solar: bool | None = None,
) -> float:
    return float(seasonal_anchor_components(history, next_end, has_solar=has_solar)["anchor"])


FORECAST_METRIC_COLUMNS = [
    "mae_kw",
    "rmse_kw",
    "mean_error_kw",
    "wape_pct",
    "smape_pct",
    "mape_pct",
    "nrmse_by_median_pct",
    "nrmse_by_peak_pct",
    "peak_precision",
    "peak_recall",
    "peak_f1",
    "peak_false_negative_count",
    "peak_false_positive_count",
    "peak_capture_rate_at_k",
    "md_peak_rank",
    "peak_time_error_intervals",
    "md_abs_error_kw",
]


def _rank_of_index(scores: np.ndarray, target_index: int) -> float:
    order = np.argsort(-scores, kind="mergesort")
    matches = np.where(order == int(target_index))[0]
    return float(matches[0] + 1) if len(matches) else float("nan")


def _peak_hits_with_window(source_peak: np.ndarray, target_peak: np.ndarray, window: int) -> np.ndarray:
    peak_indices = np.where(source_peak)[0]
    target_indices = np.where(target_peak)[0]
    if len(peak_indices) == 0:
        return np.zeros(0, dtype=bool)
    if len(target_indices) == 0:
        return np.zeros(len(peak_indices), dtype=bool)

    allowed_window = max(int(window), 0)
    hits = []
    for idx in peak_indices:
        hits.append(bool(np.any(np.abs(target_indices - idx) <= allowed_window)))
    return np.asarray(hits, dtype=bool)


def evaluate_forecast(
    actual: np.ndarray | pd.Series,
    predicted: np.ndarray | pd.Series,
    peak_quantile: float = 0.9,
    peak_score: np.ndarray | pd.Series | None = None,
    predicted_peak_quantile: float | None = None,
    peak_match_window: int = 0,
) -> dict[str, float]:
    actual_array = np.asarray(actual, dtype=float)
    predicted_array = np.asarray(predicted, dtype=float)
    score_array = np.asarray(peak_score, dtype=float) if peak_score is not None else predicted_array
    if len(score_array) != len(actual_array):
        raise ValueError("peak_score must have the same length as actual and predicted")

    errors = predicted_array - actual_array

    mae = float(mean_absolute_error(actual_array, predicted_array))
    rmse = float(np.sqrt(mean_squared_error(actual_array, predicted_array)))
    mean_error = float(np.mean(errors))

    abs_actual = np.abs(actual_array)
    abs_predicted = np.abs(predicted_array)
    abs_error = np.abs(errors)

    denominator = np.where(actual_array == 0, np.nan, actual_array)
    mape = float(np.nanmean(np.abs(actual_array - predicted_array) / np.abs(denominator)) * 100)

    wape_denominator = float(np.sum(abs_actual))
    wape = float(100.0 * np.sum(abs_error) / wape_denominator) if wape_denominator > 0 else np.nan

    smape_denominator = abs_actual + abs_predicted
    smape = float(
        np.nanmean(
            np.where(smape_denominator == 0.0, np.nan, (2.0 * abs_error) / smape_denominator)
        )
        * 100.0
    )

    positive_actual = actual_array[actual_array > 0]
    median_scale = float(np.nanmedian(positive_actual)) if positive_actual.size > 0 else float(np.nanmedian(abs_actual))
    if not np.isfinite(median_scale) or median_scale <= 0:
        median_scale = 1.0
    peak_scale = float(np.nanmax(abs_actual)) if abs_actual.size > 0 else 1.0
    if not np.isfinite(peak_scale) or peak_scale <= 0:
        peak_scale = 1.0

    actual_threshold = float(np.quantile(actual_array, peak_quantile))
    alert_quantile = float(peak_quantile if predicted_peak_quantile is None else predicted_peak_quantile)
    predicted_threshold = float(np.quantile(score_array, alert_quantile))

    actual_peak = actual_array >= actual_threshold
    predicted_peak = score_array >= predicted_threshold

    actual_hits = _peak_hits_with_window(actual_peak, predicted_peak, peak_match_window)
    predicted_hits = _peak_hits_with_window(predicted_peak, actual_peak, peak_match_window)
    true_positive = float(np.sum(actual_hits))
    predicted_positive = float(np.sum(predicted_peak))
    actual_positive = float(np.sum(actual_peak))

    precision = float(true_positive / predicted_positive) if predicted_positive > 0 else 0.0
    recall = float(true_positive / actual_positive) if actual_positive > 0 else 0.0
    f1 = float((2.0 * precision * recall) / (precision + recall)) if precision + recall > 0 else 0.0
    false_negative_count = float(actual_positive - np.sum(actual_hits))
    false_positive_count = float(predicted_positive - np.sum(predicted_hits))
    capture_k = max(1, int(actual_positive)) if len(actual_array) else 0
    if capture_k:
        top_k_indices = np.argsort(-score_array, kind="mergesort")[:capture_k]
        peak_capture_rate_at_k = float(np.sum(actual_peak[top_k_indices]) / actual_positive) if actual_positive > 0 else 0.0
    else:
        peak_capture_rate_at_k = 0.0

    actual_md_index = int(np.argmax(actual_array)) if len(actual_array) else 0
    predicted_md_index = int(np.argmax(predicted_array)) if len(predicted_array) else 0
    md_abs_error_kw = float(abs(np.max(actual_array) - np.max(predicted_array)))
    peak_time_error_intervals = float(abs(predicted_md_index - actual_md_index))
    md_peak_rank = _rank_of_index(score_array, actual_md_index) if len(score_array) else float("nan")

    return {
        "mae_kw": mae,
        "rmse_kw": rmse,
        "mean_error_kw": mean_error,
        "wape_pct": wape,
        "smape_pct": smape,
        "mape_pct": mape,
        "nrmse_by_median_pct": float(100.0 * rmse / median_scale),
        "nrmse_by_peak_pct": float(100.0 * rmse / peak_scale),
        "peak_precision": precision,
        "peak_recall": recall,
        "peak_f1": f1,
        "peak_false_negative_count": false_negative_count,
        "peak_false_positive_count": false_positive_count,
        "peak_capture_rate_at_k": peak_capture_rate_at_k,
        "md_peak_rank": md_peak_rank,
        "peak_time_error_intervals": peak_time_error_intervals,
        "md_abs_error_kw": md_abs_error_kw,
    }


def evaluate_forecast_components(
    actual: np.ndarray | pd.Series,
    forecast: pd.DataFrame,
    component_columns: dict[str, str] | None = None,
    peak_quantile: float = 0.90,
    peak_match_window: int = 0,
    overlay_alert_quantile: float = 0.90,
) -> pd.DataFrame:
    column_map = component_columns or {
        "enhanced": "forecast_kw_import",
        "ridge_only": "ridge_component",
        "seasonal": "seasonal_component",
    }

    rows: list[dict[str, float | str]] = []
    for model_name, column_name in column_map.items():
        if column_name not in forecast.columns:
            continue
        rows.append(
            {
                "model": model_name,
                **evaluate_forecast(
                    actual,
                    forecast[column_name].to_numpy(dtype=float),
                    peak_quantile=peak_quantile,
                    peak_match_window=peak_match_window,
                ),
            }
        )

    if "peak_risk_overlay_score" in forecast.columns and "forecast_kw_import" in forecast.columns:
        rows.append(
            {
                "model": "enhanced_peak_priority",
                **evaluate_forecast(
                    actual,
                    forecast["forecast_kw_import"].to_numpy(dtype=float),
                    peak_quantile=peak_quantile,
                    peak_score=forecast["peak_risk_overlay_score"].to_numpy(dtype=float),
                    predicted_peak_quantile=overlay_alert_quantile,
                    peak_match_window=peak_match_window,
                ),
            }
        )

    return pd.DataFrame(rows)


def compare_peak_alert_policies(
    actual: np.ndarray | pd.Series,
    forecast: pd.DataFrame,
    policies: dict[str, PeakAlertPolicy],
    actual_peak_quantile: float = 0.90,
) -> pd.DataFrame:
    if "forecast_kw_import" not in forecast.columns:
        raise ValueError("forecast must include forecast_kw_import")
    if "peak_risk_overlay_score" not in forecast.columns:
        raise ValueError("forecast must include peak_risk_overlay_score")

    rows: list[dict[str, float | str]] = []
    for policy_name, policy in policies.items():
        score = smooth_peak_scores(
            forecast["peak_risk_overlay_score"].to_numpy(dtype=float),
            window=policy.score_smoothing_window,
        )
        metrics = evaluate_forecast(
            actual,
            forecast["forecast_kw_import"].to_numpy(dtype=float),
            peak_quantile=actual_peak_quantile,
            peak_score=score,
            predicted_peak_quantile=policy.alert_quantile,
            peak_match_window=policy.match_window_intervals,
        )
        rows.append(
            {
                "policy": policy_name,
                "alert_quantile": float(policy.alert_quantile),
                "match_window_intervals": float(policy.match_window_intervals),
                "score_smoothing_window": float(policy.score_smoothing_window),
                **metrics,
            }
        )

    return pd.DataFrame(rows).sort_values(
        ["peak_recall", "peak_precision", "peak_f1"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def confirm_peak_alerts(
    forecast: pd.DataFrame,
    alert_quantile: float = 0.80,
    value_quantile: float = 0.75,
    score_column: str = "peak_risk_overlay_score",
) -> pd.DataFrame:
    required = {"forecast_kw_import", score_column}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError(f"Peak confirmation forecast missing columns: {missing}")

    confirmed = forecast.copy()
    score = confirmed[score_column].astype(float).to_numpy()
    forecast_values = confirmed["forecast_kw_import"].astype(float).to_numpy()
    risk_threshold = float(np.quantile(score, alert_quantile, method="lower"))
    value_threshold = float(np.quantile(forecast_values, value_quantile, method="lower"))

    near_value_peak = forecast_values >= value_threshold
    if "ridge_component" in confirmed.columns and "seasonal_component" in confirmed.columns:
        component_support = (
            confirmed["ridge_component"].astype(float).to_numpy()
            >= confirmed["seasonal_component"].astype(float).to_numpy()
        )
    else:
        component_support = np.ones(len(confirmed), dtype=bool)

    confirmed_mask = (score >= risk_threshold) & near_value_peak & component_support
    confirmed["confirmed_peak_score"] = np.where(confirmed_mask, score, -1.0)
    confirmed["is_confirmed_peak_alert"] = confirmed_mask
    return confirmed


def rank_alert_episodes(
    forecast: pd.DataFrame,
    max_gap_intervals: int = 2,
) -> pd.DataFrame:
    required = {"interval_end", "is_confirmed_peak_alert", "confirmed_peak_score", "forecast_kw_import"}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError(f"Alert episode forecast missing columns: {missing}")

    working = forecast.sort_values("interval_end").reset_index(drop=True).copy()
    alert_indices = np.where(working["is_confirmed_peak_alert"].astype(bool).to_numpy())[0]
    if len(alert_indices) == 0:
        return pd.DataFrame(
            columns=[
                "episode_id",
                "start_interval",
                "end_interval",
                "alert_count",
                "max_score",
                "max_forecast_kw",
                "episode_score",
            ]
        )

    episodes: list[list[int]] = [[int(alert_indices[0])]]
    for idx in alert_indices[1:]:
        if int(idx) - episodes[-1][-1] <= max_gap_intervals:
            episodes[-1].append(int(idx))
        else:
            episodes.append([int(idx)])

    rows = []
    for episode_id, indices in enumerate(episodes, start=1):
        block = working.iloc[indices]
        max_score = float(block["confirmed_peak_score"].max())
        max_forecast = float(block["forecast_kw_import"].max())
        rows.append(
            {
                "episode_id": episode_id,
                "start_interval": block["interval_end"].iloc[0],
                "end_interval": block["interval_end"].iloc[-1],
                "alert_count": int(len(block)),
                "max_score": max_score,
                "max_forecast_kw": max_forecast,
                "episode_score": max_score * max_forecast,
            }
        )

    return pd.DataFrame(rows).sort_values(["episode_score"], ascending=False).reset_index(drop=True)


def confirmed_alert_quantile(confirmed_alerts: pd.Series | np.ndarray) -> float:
    alert_array = np.asarray(confirmed_alerts, dtype=bool)
    if len(alert_array) == 0:
        return 1.0
    alert_share = float(np.sum(alert_array)) / float(len(alert_array))
    return float(np.clip(1.0 - alert_share, 0.0, 1.0))


def fit_md_peak_calibration(
    actual_peaks: np.ndarray | pd.Series,
    predicted_peaks: np.ndarray | pd.Series,
    min_multiplier: float = 0.85,
    max_multiplier: float = 1.20,
) -> MdPeakCalibration:
    actual_array = np.asarray(actual_peaks, dtype=float)
    predicted_array = np.asarray(predicted_peaks, dtype=float)
    valid = np.isfinite(actual_array) & np.isfinite(predicted_array) & (predicted_array > 0)
    if not np.any(valid):
        return MdPeakCalibration(multiplier=1.0)

    ratios = actual_array[valid] / predicted_array[valid]
    multiplier = float(np.clip(np.median(ratios), min_multiplier, max_multiplier))
    return MdPeakCalibration(multiplier=multiplier)


def apply_md_peak_calibration(
    forecast: pd.DataFrame,
    calibration: MdPeakCalibration,
    score_column: str = "peak_risk_score",
    top_quantile: float = 0.80,
) -> pd.DataFrame:
    corrected = forecast.copy()
    if corrected.empty or "forecast_kw_import" not in corrected.columns:
        corrected["md_calibrated_kw_import"] = []
        return corrected

    values = corrected["forecast_kw_import"].astype(float).to_numpy()
    adjusted = values.copy()
    if score_column in corrected.columns:
        scores = corrected[score_column].astype(float).to_numpy()
    else:
        scores = values

    threshold = float(np.quantile(scores, top_quantile))
    mask = scores >= threshold
    adjusted[mask] = np.maximum(0.0, calibration.intercept_kw + calibration.multiplier * adjusted[mask])
    corrected["forecast_kw_import"] = adjusted
    corrected["md_calibrated_kw_import"] = adjusted
    return corrected


def fit_late_horizon_peak_envelope(
    history: pd.DataFrame,
    envelope_quantile: float = 0.90,
    lookback_intervals: int = 48 * 28,
) -> LateHorizonPeakEnvelope:
    required = {"interval_end", "kw_import"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError(f"Peak envelope history missing columns: {missing}")

    ordered = history.sort_values("interval_end").tail(max(int(lookback_intervals), 1)).copy()
    if ordered.empty:
        return LateHorizonPeakEnvelope(slot_floors_kw={}, half_hour_floors_kw={}, global_floor_kw=0.0)

    ordered["kw_import"] = pd.to_numeric(ordered["kw_import"], errors="coerce")
    ordered = ordered[np.isfinite(ordered["kw_import"].to_numpy(dtype=float))]
    if ordered.empty:
        return LateHorizonPeakEnvelope(slot_floors_kw={}, half_hour_floors_kw={}, global_floor_kw=0.0)

    timestamps = pd.to_datetime(ordered["interval_end"])
    ordered["day_of_week"] = timestamps.dt.dayofweek.astype(int)
    ordered["hour"] = timestamps.dt.hour.astype(int)
    ordered["minute"] = timestamps.dt.minute.astype(int)

    quantile = float(np.clip(envelope_quantile, 0.50, 0.99))
    slot_floors = {
        (int(day), int(hour), int(minute)): float(value)
        for (day, hour, minute), value in ordered.groupby(["day_of_week", "hour", "minute"])["kw_import"].quantile(quantile).items()
    }
    half_hour_floors = {
        (int(hour), int(minute)): float(value)
        for (hour, minute), value in ordered.groupby(["hour", "minute"])["kw_import"].quantile(quantile).items()
    }
    global_floor = float(ordered["kw_import"].quantile(quantile))
    daily_peak_floor = float(ordered.groupby(timestamps.dt.date)["kw_import"].max().quantile(quantile))

    return LateHorizonPeakEnvelope(
        slot_floors_kw=slot_floors,
        half_hour_floors_kw=half_hour_floors,
        global_floor_kw=global_floor,
        site_peak_floor_kw=daily_peak_floor,
    )


def apply_late_horizon_peak_uplift(
    forecast: pd.DataFrame,
    envelope: LateHorizonPeakEnvelope,
    start_step: int = 33,
    score_quantile: float = 0.80,
    floor_ratio: float = 0.88,
    max_uplift_kw: float = 250.0,
    score_column: str = "peak_risk_overlay_score",
    has_solar: bool | None = None,
    use_site_peak_floor_for_nonsolar_night: bool = False,
) -> pd.DataFrame:
    required = {"interval_end", "forecast_kw_import"}
    missing = sorted(required - set(forecast.columns))
    if missing:
        raise ValueError(f"Late-horizon uplift forecast missing columns: {missing}")

    uplifted = forecast.sort_values("interval_end").reset_index(drop=True).copy()
    if uplifted.empty:
        uplifted["late_peak_envelope_floor_kw"] = []
        uplifted["late_peak_uplift_kw_import"] = []
        uplifted["late_peak_uplift_applied"] = []
        return uplifted

    values = uplifted["forecast_kw_import"].astype(float).to_numpy()
    if score_column in uplifted.columns:
        scores = uplifted[score_column].astype(float).to_numpy()
    elif "peak_risk_score" in uplifted.columns:
        scores = uplifted["peak_risk_score"].astype(float).to_numpy()
    else:
        scores = values.copy()

    top_count = max(1, int(np.ceil((1.0 - float(np.clip(score_quantile, 0.0, 0.99))) * len(scores))))
    top_indices = np.argsort(scores)[-top_count:]
    likely_peak = np.zeros(len(scores), dtype=bool)
    likely_peak[top_indices] = True

    timestamps = pd.to_datetime(uplifted["interval_end"])
    floors: list[float] = []
    if has_solar is None and "has_solar" in uplifted.columns and not uplifted["has_solar"].empty:
        site_has_solar = bool(uplifted["has_solar"].iloc[0])
    else:
        site_has_solar = bool(has_solar) if has_solar is not None else True

    for timestamp in timestamps:
        slot_key = (int(timestamp.dayofweek), int(timestamp.hour), int(timestamp.minute))
        half_hour_key = (int(timestamp.hour), int(timestamp.minute))
        floor = float(
            envelope.slot_floors_kw.get(
                slot_key,
                envelope.half_hour_floors_kw.get(half_hour_key, envelope.global_floor_kw),
            )
        )
        if use_site_peak_floor_for_nonsolar_night and (not site_has_solar) and (timestamp.hour < 6 or timestamp.hour >= 18):
            floor = max(floor, float(envelope.site_peak_floor_kw))
        floors.append(floor)

    floor_values = np.asarray(floors, dtype=float) * float(np.clip(floor_ratio, 0.0, 1.5))
    steps = np.arange(1, len(values) + 1)
    late_horizon = steps >= int(start_step)
    candidate_mask = late_horizon & likely_peak & np.isfinite(floor_values)

    adjusted = values.copy()
    capped_floor = np.minimum(floor_values, values + max(float(max_uplift_kw), 0.0))
    adjusted[candidate_mask] = np.maximum(values[candidate_mask], capped_floor[candidate_mask])

    uplifted["late_peak_envelope_floor_kw"] = floor_values
    uplifted["late_peak_uplift_kw_import"] = adjusted
    uplifted["late_peak_uplift_applied"] = adjusted > values
    return uplifted


def summarize_rolling_error_diagnostics(predictions: pd.DataFrame) -> pd.DataFrame:
    required = {"site_id", "fold", "step", "actual_kw_import", "enhanced_kw_import", "has_solar", "is_daylight"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"Diagnostic predictions missing columns: {missing}")

    working = predictions.copy()
    working["error_kw"] = working["enhanced_kw_import"].astype(float) - working["actual_kw_import"].astype(float)
    working["abs_error_kw"] = working["error_kw"].abs()
    working["site_type"] = np.where(working["has_solar"].astype(bool), "solar", "non_solar")
    working["light_regime"] = np.where(working["is_daylight"].astype(bool), "daylight", "night")
    working["horizon_bucket"] = pd.cut(
        working["step"].astype(int),
        bins=[0, 16, 32, np.inf],
        labels=["early", "middle", "late"],
        include_lowest=True,
    ).astype(str)

    peak_threshold = working.groupby(["site_id", "fold"])["actual_kw_import"].transform(lambda s: s.quantile(0.90))
    working["actual_peak_regime"] = np.where(
        working["actual_kw_import"].astype(float) >= peak_threshold,
        "actual_peak",
        "non_peak",
    )

    return (
        working.groupby(["site_id", "site_type", "light_regime", "horizon_bucket", "actual_peak_regime"], as_index=False)
        .agg(
            rows=("error_kw", "size"),
            mean_error_kw=("error_kw", "mean"),
            mean_abs_error_kw=("abs_error_kw", "mean"),
            max_abs_error_kw=("abs_error_kw", "max"),
        )
        .sort_values(["mean_abs_error_kw"], ascending=False)
        .reset_index(drop=True)
    )


def summarize_rolling_candidate_error_diagnostics(
    predictions: pd.DataFrame,
    forecast_columns: dict[str, str],
) -> pd.DataFrame:
    required = {"site_id", "fold", "step", "actual_kw_import", "has_solar", "is_daylight"}
    missing = sorted(required - set(predictions.columns))
    if missing:
        raise ValueError(f"Candidate diagnostic predictions missing columns: {missing}")

    rows: list[pd.DataFrame] = []
    for model_name, column_name in forecast_columns.items():
        if column_name not in predictions.columns:
            raise ValueError(f"Candidate diagnostic predictions missing forecast column: {column_name}")
        working = predictions.copy()
        working["enhanced_kw_import"] = working[column_name].astype(float)
        summary = summarize_rolling_error_diagnostics(working)
        summary.insert(0, "model", model_name)
        rows.append(summary)

    if not rows:
        return pd.DataFrame(
            columns=[
                "model",
                "site_id",
                "site_type",
                "light_regime",
                "horizon_bucket",
                "actual_peak_regime",
                "rows",
                "mean_error_kw",
                "mean_abs_error_kw",
                "max_abs_error_kw",
            ]
        )

    return (
        pd.concat(rows, ignore_index=True)
        .sort_values(["mean_abs_error_kw"], ascending=False)
        .reset_index(drop=True)
    )


def summarize_prediction_errors(
    predictions: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    working = predictions.copy()
    working["abs_error_kw"] = working["error_kw"].abs()
    summary = (
        working.groupby(group_columns, as_index=False)
        .agg(
            rows=("error_kw", "size"),
            mean_abs_error_kw=("abs_error_kw", "mean"),
            mean_signed_error_kw=("error_kw", "mean"),
        )
        .sort_values(group_columns)
        .reset_index(drop=True)
    )
    return summary


def summarize_model_metrics(
    metrics: pd.DataFrame,
    group_columns: list[str],
    metric_columns: list[str] | None = None,
) -> pd.DataFrame:
    selected_columns = metric_columns or FORECAST_METRIC_COLUMNS
    aggregations = {column: (column, "mean") for column in selected_columns if column in metrics.columns}
    if not aggregations:
        raise ValueError("No metric columns were available for summarization")

    summary = (
        metrics.groupby(group_columns, as_index=False)
        .agg(**aggregations)
        .sort_values(group_columns)
        .reset_index(drop=True)
    )
    return summary


def peak_priority_objective(metrics: dict[str, float], horizon: int = 48) -> float:
    peak_recall = float(metrics.get("peak_recall", 0.0))
    peak_precision = float(metrics.get("peak_precision", 0.0))
    md_peak_rank = float(metrics.get("md_peak_rank", horizon))
    peak_time_error = float(metrics.get("peak_time_error_intervals", horizon))
    md_abs_error = float(metrics.get("md_abs_error_kw", 0.0))
    rmse = float(metrics.get("rmse_kw", 0.0))
    wape = float(metrics.get("wape_pct", 0.0))

    if not np.isfinite(md_peak_rank):
        md_peak_rank = float(horizon)

    return float(
        1000.0 * (1.0 - peak_recall)
        + 120.0 * max(0.0, 0.35 - peak_precision)
        + 8.0 * md_peak_rank
        + 5.0 * peak_time_error
        + 0.25 * md_abs_error
        + 0.08 * rmse
        + 0.05 * wape
    )


def forecast_value_objective(metrics: dict[str, float], horizon: int = 48) -> float:
    rmse = float(metrics.get("rmse_kw", metrics.get("rmse", 0.0)))
    md_abs_error = float(metrics.get("md_abs_error_kw", metrics.get("md_abs_error", 0.0)))
    mean_error_abs = float(metrics.get("mean_error_abs", 0.0))
    cumulative_error_abs = float(metrics.get("cumulative_error_abs", 0.0))
    drift_slope_abs = float(metrics.get("drift_slope_abs", 0.0))

    return float(
        0.55 * rmse
        + 0.20 * md_abs_error
        + 0.10 * mean_error_abs
        + 0.10 * (cumulative_error_abs / float(max(horizon, 1)))
        + 0.05 * (drift_slope_abs * float(max(horizon, 1)))
    )


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


def fit_regime_calibration(
    model: Pipeline,
    site_train_frame: pd.DataFrame,
    feature_columns: list[str],
    window: int = 336,
    min_rows_per_regime: int = 48,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> dict[object, tuple[float, float]]:
    default_calibration = fit_site_calibration(
        model,
        site_train_frame,
        feature_columns,
        window=window,
        normalize_targets=normalize_targets,
        site_scale=site_scale,
    )

    working_frame = normalize_site_frame(site_train_frame, site_scale)[0] if normalize_targets else site_train_frame.copy()
    prepared, _ = add_enhanced_features(working_frame)
    if prepared.empty:
        return {"default": default_calibration}

    calibration_rows = prepared.tail(window).copy()
    calibration_rows["light_regime"] = np.where(calibration_rows["daylight"].astype(bool), "daylight", "night")
    calibration_rows["period_type"] = np.where(calibration_rows["is_weekend"].astype(bool), "weekend", "weekday")
    calibration_rows["x_raw"] = model.predict(calibration_rows[feature_columns]).astype(float)
    calibration_rows["y_true"] = calibration_rows["kw_import"].to_numpy(dtype=float)

    regime_calibration: dict[object, tuple[float, float]] = {"default": default_calibration}
    for regime_key, regime_rows in calibration_rows.groupby(["light_regime", "period_type"], sort=True):
        if len(regime_rows) < min_rows_per_regime:
            continue
        x_raw = regime_rows["x_raw"].to_numpy(dtype=float)
        y_true = regime_rows["y_true"].to_numpy(dtype=float)
        if len(x_raw) < 2 or len(np.unique(x_raw)) < 2:
            continue

        calibrator = LinearRegression()
        calibrator.fit(x_raw.reshape(-1, 1), y_true)
        raw_intercept = float(calibrator.intercept_)
        raw_slope = float(calibrator.coef_[0])

        shrink = 0.60
        slope = shrink * 1.0 + (1.0 - shrink) * raw_slope
        intercept = (1.0 - shrink) * raw_intercept

        y_std = float(np.std(y_true))
        if y_std > 0:
            max_abs_intercept = 0.15 * y_std
            intercept = float(np.clip(intercept, -max_abs_intercept, max_abs_intercept))

        slope = float(np.clip(slope, 0.90, 1.10))
        regime_calibration[regime_key] = (intercept, slope)

    return regime_calibration


def fit_horizon_residual_adjustment(
    model: Pipeline,
    site_train_frame: pd.DataFrame,
    feature_columns: list[str],
    horizon: int = 48,
    blend_weight: float | dict[object, float] = 0.70,
    use_calibration_in_inner: bool = True,
    use_regime_calibration_in_inner: bool = True,
    horizon_correction_bucket_size: int = 8,
    max_validation_folds: int = 4,
    min_samples_per_bucket: int = 2,
    shrinkage: float = 4.0,
    max_adjustment_ratio: float = 0.25,
    inner_solar_daylight_anchor: float = 0.15,
    inner_max_step_change_ratio: float = 0.16,
    inner_horizon_blend_floor: float = 0.20,
    inner_horizon_blend_decay: float = 0.25,
    inner_solar_daytime_extra_decay: float = 0.05,
    inner_solar_daytime_floor_ratio: float = 0.78,
    inner_solar_daytime_floor_enabled: bool = True,
    inner_solar_daytime_up_ratio: float = 0.55,
    inner_solar_monday_step_up_bonus: float = 0.20,
    inner_solar_daytime_down_ratio: float = 0.18,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> dict[object, float]:
    if horizon_correction_bucket_size <= 0:
        raise ValueError("horizon_correction_bucket_size must be positive")

    if len(site_train_frame) <= horizon + 336:
        return {"default": 0.0}

    cutoffs = _validation_cutoffs(len(site_train_frame), horizon=horizon, max_folds=max_validation_folds)
    if not cutoffs:
        return {"default": 0.0}

    inferred_scale = (
        site_scale_from_frame(site_train_frame) if normalize_targets and site_scale is None else site_scale
    )
    output_scale = float(inferred_scale if inferred_scale is not None else 1.0)
    if output_scale <= 0 or not np.isfinite(output_scale):
        output_scale = 1.0

    normalized_frame = normalize_site_frame(site_train_frame, output_scale)[0] if normalize_targets else site_train_frame
    normalized_series = normalized_frame["kw_import"].astype(float)
    positive = normalized_series[normalized_series > 0]
    baseline_scale = float(np.nanmedian(positive.to_numpy())) if not positive.empty else float(np.nanmedian(normalized_series.to_numpy()))
    if not np.isfinite(baseline_scale) or baseline_scale <= 0:
        baseline_scale = 1.0
    max_abs_adjustment = float(max(0.02, max_adjustment_ratio * baseline_scale))

    bucket_errors: dict[int, list[float]] = defaultdict(list)
    regime_bucket_errors: dict[tuple[object, int], list[float]] = defaultdict(list)

    for cutoff in cutoffs:
        inner_train = site_train_frame.iloc[:cutoff].copy()
        inner_slice = site_train_frame.iloc[cutoff : cutoff + horizon].copy()
        inner_actual = inner_slice["kw_import"].to_numpy(dtype=float)

        if use_calibration_in_inner:
            if use_regime_calibration_in_inner:
                inner_calibration: tuple[float, float] | dict[object, tuple[float, float]] = fit_regime_calibration(
                    model,
                    inner_train,
                    feature_columns,
                    normalize_targets=normalize_targets,
                    site_scale=output_scale,
                )
            else:
                inner_calibration = fit_site_calibration(
                    model,
                    inner_train,
                    feature_columns,
                    normalize_targets=normalize_targets,
                    site_scale=output_scale,
                )
        else:
            inner_calibration = {"default": (0.0, 1.0)} if isinstance(blend_weight, dict) else (0.0, 1.0)

        inner_forecast = forecast_with_enhanced_model(
            model=model,
            feature_columns=feature_columns,
            target_frame=inner_train,
            horizon=horizon,
            blend_weight=blend_weight,
            calibration=inner_calibration,
            residual_correction=0.0,
            residual_correction_bucket_size=horizon_correction_bucket_size,
            solar_daylight_anchor=inner_solar_daylight_anchor,
            max_step_change_ratio=inner_max_step_change_ratio,
            horizon_blend_floor=inner_horizon_blend_floor,
            horizon_blend_decay=inner_horizon_blend_decay,
            solar_daytime_extra_decay=inner_solar_daytime_extra_decay,
            solar_daytime_floor_ratio=inner_solar_daytime_floor_ratio,
            solar_daytime_floor_enabled=inner_solar_daytime_floor_enabled,
            solar_daytime_up_ratio=inner_solar_daytime_up_ratio,
            solar_monday_step_up_bonus=inner_solar_monday_step_up_bonus,
            solar_daytime_down_ratio=inner_solar_daytime_down_ratio,
            normalize_targets=normalize_targets,
            site_scale=output_scale,
        )
        errors = (inner_actual - inner_forecast["forecast_kw_import"].to_numpy(dtype=float)) / output_scale

        for step_index, (ts, error) in enumerate(zip(inner_slice["interval_end"], errors), start=1):
            bucket_key = (step_index - 1) // horizon_correction_bucket_size
            regime_key = _regime_key(pd.Timestamp(ts))
            bucket_errors[bucket_key].append(float(error))
            regime_bucket_errors[(regime_key, bucket_key)].append(float(error))

    def _shrunken_adjustment(values: list[float]) -> float:
        mean_value = float(np.mean(values))
        shrink_factor = float(len(values)) / float(len(values) + max(shrinkage, 0.0))
        return float(np.clip(mean_value * shrink_factor, -max_abs_adjustment, max_abs_adjustment))

    residual_adjustment: dict[object, float] = {"default": 0.0}
    for bucket_key, values in bucket_errors.items():
        if len(values) < min_samples_per_bucket:
            continue
        residual_adjustment[bucket_key] = _shrunken_adjustment(values)

    for key, values in regime_bucket_errors.items():
        if len(values) < min_samples_per_bucket:
            continue
        residual_adjustment[key] = _shrunken_adjustment(values)

    return residual_adjustment


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
    blend_weight: float | dict[object, float] = 0.70,
    calibration: tuple[float, float] | dict[object, tuple[float, float]] = (0.0, 1.0),
    max_step_change_ratio: float = 0.16,
    solar_daylight_anchor: float = 0.15,
    horizon_blend_floor: float = 0.20,
    horizon_blend_decay: float = 0.25,
    solar_daytime_extra_decay: float = 0.05,
    solar_daytime_floor_ratio: float = 0.78,
    solar_daytime_floor_enabled: bool = True,
    solar_daytime_up_ratio: float = 0.55,
    solar_monday_step_up_bonus: float = 0.20,
    solar_daytime_down_ratio: float = 0.18,
    residual_correction: float | dict[object, float] = 0.0,
    residual_correction_bucket_size: int = 8,
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

    rows: list[dict[str, object]] = []
    for step in range(1, horizon + 1):
        next_end = last_end + pd.Timedelta(minutes=30 * step)
        regime_key = _regime_key(next_end)
        anchor_info = seasonal_anchor_components(history, next_end, has_solar=has_solar)
        is_daylight = bool(anchor_info["is_daylight"])
        is_weekday_daylight = bool(anchor_info["is_weekday_daylight"])
        is_monday = bool(anchor_info["is_monday"])

        feature_row = enhanced_feature_row(history, next_end, has_solar)
        feature_frame = pd.DataFrame([feature_row], columns=feature_columns)

        ridge_pred = max(float(model.predict(feature_frame)[0]), 0.0)
        seasonal_pred = float(anchor_info["anchor"])
        floor_reference = float(max(anchor_info["floor_reference"], seasonal_pred))

        progress = float(step - 1) / float(max(horizon - 1, 1))
        base_blend_weight = (
            float(blend_weight.get(regime_key, blend_weight.get("default", 0.70)))
            if isinstance(blend_weight, dict)
            else float(blend_weight)
        )
        effective_blend = float(
            np.clip(base_blend_weight * (1.0 - horizon_blend_decay * progress), horizon_blend_floor, 1.0)
        )

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

        offset, scale = (
            calibration.get(regime_key, calibration.get("default", (0.0, 1.0)))
            if isinstance(calibration, dict)
            else calibration
        )
        calibrated_pred = max(offset + scale * blended_pred, 0.0)
        bucket_key = (step - 1) // max(residual_correction_bucket_size, 1)
        residual_adjustment = (
            float(
                residual_correction.get(
                    (regime_key, bucket_key),
                    residual_correction.get(bucket_key, residual_correction.get("default", 0.0)),
                )
            )
            if isinstance(residual_correction, dict)
            else float(residual_correction)
        )
        residual_adjusted_pred = max(calibrated_pred + residual_adjustment, 0.0)

        lower_guard, upper_guard = _prediction_guardrails(
            history,
            seasonal_floor=floor_reference if has_solar else None,
            is_weekday_daylight=is_weekday_daylight if has_solar else False,
            is_monday=is_monday if has_solar else False,
        )
        prev = float(history[-1])

        if has_solar and is_weekday_daylight:
            reference_level = max(prev, seasonal_pred, floor_reference, 1.0e-6)
            up_ratio = float(np.clip(solar_daytime_up_ratio + (solar_monday_step_up_bonus if is_monday else 0.0), 0.10, 1.20))
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

        guarded_pred = float(np.clip(residual_adjusted_pred, step_low, step_high))
        final_pred = float(np.clip(guarded_pred, lower_guard, upper_guard))

        if has_solar and is_weekday_daylight and solar_daytime_floor_enabled and solar_daytime_floor_ratio > 0:
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
                "residual_adjustment": residual_adjustment * output_scale,
                "effective_blend_weight": effective_blend,
                "guardrail_lower": lower_guard * output_scale,
                "guardrail_upper": upper_guard * output_scale,
            }
        )

    forecast = pd.DataFrame(rows)
    max_forecast = float(forecast["forecast_kw_import"].max()) if not forecast.empty else 0.0
    forecast["peak_risk_score"] = forecast["forecast_kw_import"] / max_forecast if max_forecast > 0 else 0.0
    threshold = forecast["forecast_kw_import"].quantile(0.9) if not forecast.empty else 0.0
    forecast["is_predicted_peak"] = forecast["forecast_kw_import"] >= threshold
    return forecast


def _validate_peak_overlay_features(feature_columns: Iterable[str]) -> list[str]:
    selected = [str(column) for column in feature_columns]
    leaked = sorted({column.lower() for column in selected} & FORECAST_LEAKAGE_COLUMNS)
    if leaked:
        raise ValueError(f"Peak overlay feature set contains leakage columns: {leaked}")
    if not selected:
        raise ValueError("Peak overlay requires at least one forecast-safe feature column")
    return selected


def fit_peak_risk_overlay(
    prepared_frame: pd.DataFrame,
    feature_columns: Iterable[str],
    peak_quantile: float = 0.90,
) -> PeakRiskOverlay:
    safe_feature_columns = _validate_peak_overlay_features(feature_columns)
    missing_columns = [column for column in safe_feature_columns if column not in prepared_frame.columns]
    if missing_columns:
        raise ValueError(f"Peak overlay feature columns missing from frame: {missing_columns}")
    if "kw_import" not in prepared_frame.columns:
        raise ValueError("Peak overlay training frame must contain 'kw_import' as the target")

    working = prepared_frame.dropna(subset=safe_feature_columns + ["kw_import"]).copy()
    if working.empty:
        return PeakRiskOverlay(
            model=None,
            feature_columns=safe_feature_columns,
            peak_quantile=peak_quantile,
            threshold_kw=float("nan"),
            constant_probability=0.0,
        )

    threshold_kw = float(working["kw_import"].quantile(peak_quantile))
    target = (working["kw_import"].astype(float) >= threshold_kw).astype(int)
    positive_rate = float(target.mean())

    if target.nunique() < 2:
        return PeakRiskOverlay(
            model=None,
            feature_columns=safe_feature_columns,
            peak_quantile=peak_quantile,
            threshold_kw=threshold_kw,
            constant_probability=positive_rate,
        )

    classifier = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=1000,
                    random_state=42,
                ),
            ),
        ]
    )
    classifier.fit(working[safe_feature_columns], target)
    return PeakRiskOverlay(
        model=classifier,
        feature_columns=safe_feature_columns,
        peak_quantile=peak_quantile,
        threshold_kw=threshold_kw,
    )


def predict_peak_risk_overlay(overlay: PeakRiskOverlay, features: pd.DataFrame) -> np.ndarray:
    if overlay.model is None:
        probability = float(overlay.constant_probability or 0.0)
        return np.full(len(features), probability, dtype=float)
    return overlay.model.predict_proba(features[overlay.feature_columns])[:, 1].astype(float)


def smooth_peak_scores(scores: np.ndarray | pd.Series, window: int = 1) -> np.ndarray:
    score_array = np.asarray(scores, dtype=float)
    smoothing_window = max(int(window), 1)
    if smoothing_window == 1 or len(score_array) == 0:
        return score_array.copy()

    return (
        pd.Series(score_array)
        .rolling(window=smoothing_window, min_periods=1, center=True)
        .mean()
        .to_numpy(dtype=float)
    )


def apply_peak_risk_overlay(
    forecast: pd.DataFrame,
    overlay: PeakRiskOverlay,
    target_frame: pd.DataFrame,
    policy: PeakAlertPolicy | None = None,
) -> pd.DataFrame:
    enriched = forecast.copy()
    if enriched.empty:
        enriched["peak_risk_overlay_score"] = []
        return enriched

    ordered = target_frame.sort_values("interval_end").reset_index(drop=True)
    history = ordered["kw_import"].astype(float).tolist()
    has_solar = bool(ordered["has_solar"].iloc[0])
    alert_policy = policy or peak_alert_policy_for_site(has_solar)
    feature_rows: list[dict[str, float]] = []

    for _, row in enriched.sort_values("interval_end").iterrows():
        next_end = pd.Timestamp(row["interval_end"])
        feature_rows.append(enhanced_feature_row(history, next_end, has_solar))
        history.append(float(row["forecast_kw_import"]))

    feature_frame = pd.DataFrame(feature_rows)
    overlay_scores = predict_peak_risk_overlay(overlay, feature_frame)
    enriched = enriched.sort_values("interval_end").reset_index(drop=True)
    enriched["peak_risk_overlay_score"] = overlay_scores

    overlay_weight = float(np.clip(alert_policy.overlay_weight, 0.0, 1.0))
    if "peak_risk_score" in enriched.columns:
        value_score = enriched["peak_risk_score"].astype(float).to_numpy()
        combined_score = (1.0 - overlay_weight) * value_score + overlay_weight * overlay_scores
    else:
        combined_score = overlay_scores

    smoothed_score = smooth_peak_scores(combined_score, window=alert_policy.score_smoothing_window)
    enriched["peak_risk_score"] = combined_score
    enriched["peak_risk_smoothed_score"] = smoothed_score

    threshold = float(np.quantile(smoothed_score, alert_policy.alert_quantile))
    enriched["is_predicted_peak"] = smoothed_score >= threshold
    return enriched


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
    use_calibration_in_inner: bool = True,
    inner_solar_daylight_anchor: float = 0.15,
    inner_max_step_change_ratio: float = 0.16,
    inner_horizon_blend_floor: float = 0.20,
    inner_horizon_blend_decay: float = 0.25,
    inner_solar_daytime_extra_decay: float = 0.05,
    inner_solar_daytime_floor_ratio: float = 0.78,
    inner_solar_daytime_floor_enabled: bool = True,
    inner_solar_daytime_up_ratio: float = 0.55,
    inner_solar_monday_step_up_bonus: float = 0.20,
    inner_solar_daytime_down_ratio: float = 0.18,
    normalize_targets: bool = True,
    site_scale: float | None = None,
) -> tuple[float, pd.DataFrame]:
    default_table = pd.DataFrame(
        {
            "blend_weight": [0.65],
            "rmse": [np.nan],
            "md_abs_error": [np.nan],
            "mean_error_abs": [np.nan],
            "cumulative_error_abs": [np.nan],
            "drift_slope_abs": [np.nan],
            "peak_recall": [np.nan],
            "peak_precision": [np.nan],
            "peak_time_error_intervals": [np.nan],
            "md_peak_rank": [np.nan],
            "objective": [np.nan],
        }
    )
    if candidates is None:
        candidates = np.linspace(0.20, 0.75, 8)

    if len(site_train_frame) <= horizon + 336:
        return 0.65, default_table

    cutoffs = _validation_cutoffs(len(site_train_frame), horizon=horizon)
    if not cutoffs:
        return 0.65, default_table

    inferred_scale = site_scale_from_frame(site_train_frame) if normalize_targets and site_scale is None else site_scale

    fold_contexts = []
    for cutoff in cutoffs:
        inner_train = site_train_frame.iloc[:cutoff].copy()
        inner_actual = site_train_frame.iloc[cutoff : cutoff + horizon]["kw_import"].to_numpy()
        calibration = (
            fit_site_calibration(
                model,
                inner_train,
                feature_columns,
                normalize_targets=normalize_targets,
                site_scale=inferred_scale,
            )
            if use_calibration_in_inner
            else (0.0, 1.0)
        )
        fold_contexts.append(
            {
                "inner_train": inner_train,
                "inner_actual": inner_actual,
                "calibration": calibration,
            }
        )

    rows = []
    for weight in candidates:
        fold_rmses: list[float] = []
        fold_md_errors: list[float] = []
        fold_mean_errors: list[float] = []
        fold_cumulative_errors: list[float] = []
        fold_drift_slopes: list[float] = []
        fold_peak_recalls: list[float] = []
        fold_peak_precisions: list[float] = []
        fold_peak_time_errors: list[float] = []
        fold_md_peak_ranks: list[float] = []
        fold_objectives: list[float] = []

        for fold_context in fold_contexts:
            pred = forecast_with_enhanced_model(
                model=model,
                feature_columns=feature_columns,
                target_frame=fold_context["inner_train"],
                horizon=horizon,
                blend_weight=float(weight),
                calibration=fold_context["calibration"],
                solar_daylight_anchor=inner_solar_daylight_anchor,
                max_step_change_ratio=inner_max_step_change_ratio,
                horizon_blend_floor=inner_horizon_blend_floor,
                horizon_blend_decay=inner_horizon_blend_decay,
                solar_daytime_extra_decay=inner_solar_daytime_extra_decay,
                solar_daytime_floor_ratio=inner_solar_daytime_floor_ratio,
                solar_daytime_floor_enabled=inner_solar_daytime_floor_enabled,
                solar_daytime_up_ratio=inner_solar_daytime_up_ratio,
                solar_monday_step_up_bonus=inner_solar_monday_step_up_bonus,
                solar_daytime_down_ratio=inner_solar_daytime_down_ratio,
                normalize_targets=normalize_targets,
                site_scale=inferred_scale,
            )["forecast_kw_import"].to_numpy()

            inner_actual = fold_context["inner_actual"]
            errors = pred - inner_actual
            metrics = evaluate_forecast(inner_actual, pred)
            rmse = float(metrics["rmse_kw"])
            md_abs_error = float(metrics["md_abs_error_kw"])
            mean_error_abs = float(abs(np.mean(errors)))
            cumulative_error_abs = float(abs(np.sum(errors)))
            drift_slope_abs = (
                float(abs(np.polyfit(np.arange(len(errors)), errors, 1)[0])) if len(errors) > 1 else 0.0
            )
            fold_rmses.append(rmse)
            fold_md_errors.append(md_abs_error)
            fold_mean_errors.append(mean_error_abs)
            fold_cumulative_errors.append(cumulative_error_abs)
            fold_drift_slopes.append(drift_slope_abs)
            fold_peak_recalls.append(float(metrics["peak_recall"]))
            fold_peak_precisions.append(float(metrics["peak_precision"]))
            fold_peak_time_errors.append(float(metrics["peak_time_error_intervals"]))
            fold_md_peak_ranks.append(float(metrics["md_peak_rank"]))
            fold_objectives.append(peak_priority_objective(metrics, horizon=horizon))

        mean_rmse = float(np.mean(fold_rmses))
        mean_md = float(np.mean(fold_md_errors))
        mean_bias = float(np.mean(fold_mean_errors))
        mean_cumulative_error = float(np.mean(fold_cumulative_errors))
        mean_drift = float(np.mean(fold_drift_slopes))
        mean_peak_recall = float(np.mean(fold_peak_recalls))
        mean_peak_precision = float(np.mean(fold_peak_precisions))
        mean_peak_time_error = float(np.mean(fold_peak_time_errors))
        mean_md_peak_rank = float(np.mean(fold_md_peak_ranks))
        objective = forecast_value_objective(
            {
                "rmse_kw": mean_rmse,
                "md_abs_error_kw": mean_md,
                "mean_error_abs": mean_bias,
                "cumulative_error_abs": mean_cumulative_error,
                "drift_slope_abs": mean_drift,
            },
            horizon=horizon,
        )
        rows.append(
            {
                "blend_weight": float(weight),
                "rmse": mean_rmse,
                "md_abs_error": mean_md,
                "mean_error_abs": mean_bias,
                "cumulative_error_abs": mean_cumulative_error,
                "drift_slope_abs": mean_drift,
                "peak_recall": mean_peak_recall,
                "peak_precision": mean_peak_precision,
                "peak_time_error_intervals": mean_peak_time_error,
                "md_peak_rank": mean_md_peak_rank,
                "objective": objective,
            }
        )

    table = pd.DataFrame(rows).sort_values(["objective", "rmse"]).reset_index(drop=True)
    best_weight = float(table.iloc[0]["blend_weight"])
    return best_weight, table


def select_regime_blend_weight(
    model: Pipeline,
    site_train_frame: pd.DataFrame,
    feature_columns: list[str],
    horizon: int = 48,
    candidates: Iterable[float] | None = None,
    use_calibration_in_inner: bool = True,
    normalize_targets: bool = True,
    site_scale: float | None = None,
    default_weight: float | None = None,
    **inner_kwargs: float,
) -> tuple[dict[object, float], dict[object, pd.DataFrame]]:
    global_weight, global_table = select_blend_weight(
        model,
        site_train_frame,
        feature_columns,
        horizon=horizon,
        candidates=candidates,
        use_calibration_in_inner=use_calibration_in_inner,
        normalize_targets=normalize_targets,
        site_scale=site_scale,
        **inner_kwargs,
    )
    inferred_default = float(global_weight if default_weight is None else default_weight)

    if len(site_train_frame) <= horizon + 336:
        return {"default": inferred_default}, {"default": global_table}

    cutoffs = _validation_cutoffs(len(site_train_frame), horizon=horizon)
    if not cutoffs:
        return {"default": inferred_default}, {"default": global_table}

    inferred_scale = site_scale_from_frame(site_train_frame) if normalize_targets and site_scale is None else site_scale

    fold_contexts = []
    for cutoff in cutoffs:
        inner_train = site_train_frame.iloc[:cutoff].copy()
        inner_slice = site_train_frame.iloc[cutoff : cutoff + horizon].copy()
        inner_actual = inner_slice["kw_import"].to_numpy()
        regime_calibration = (
            fit_regime_calibration(
                model,
                inner_train,
                feature_columns,
                normalize_targets=normalize_targets,
                site_scale=inferred_scale,
            )
            if use_calibration_in_inner
            else {"default": (0.0, 1.0)}
        )
        inner_regimes = [_regime_key(pd.Timestamp(ts)) for ts in inner_slice["interval_end"]]
        fold_contexts.append(
            {
                "inner_train": inner_train,
                "inner_actual": inner_actual,
                "inner_regimes": inner_regimes,
                "calibration": regime_calibration,
            }
        )

    regime_weight_map: dict[object, float] = {"default": inferred_default}
    regime_tables: dict[object, pd.DataFrame] = {"default": global_table}
    regime_keys = sorted({_regime_key(pd.Timestamp(ts)) for ts in site_train_frame["interval_end"]})

    for regime_key in regime_keys:
        rows = []
        candidate_weights = candidates if candidates is not None else np.linspace(0.20, 0.75, 8)
        for weight in candidate_weights:
            fold_rmses: list[float] = []
            fold_md_errors: list[float] = []

            for fold_context in fold_contexts:
                regime_blend = {"default": inferred_default, regime_key: float(weight)}
                pred = forecast_with_enhanced_model(
                    model=model,
                    feature_columns=feature_columns,
                    target_frame=fold_context["inner_train"],
                    horizon=horizon,
                    blend_weight=regime_blend,
                    calibration=fold_context["calibration"],
                    normalize_targets=normalize_targets,
                    site_scale=inferred_scale,
                    **{
                        "solar_daylight_anchor": inner_kwargs.get("inner_solar_daylight_anchor", 0.15),
                        "max_step_change_ratio": inner_kwargs.get("inner_max_step_change_ratio", 0.16),
                        "horizon_blend_floor": inner_kwargs.get("inner_horizon_blend_floor", 0.20),
                        "horizon_blend_decay": inner_kwargs.get("inner_horizon_blend_decay", 0.25),
                        "solar_daytime_extra_decay": inner_kwargs.get("inner_solar_daytime_extra_decay", 0.05),
                        "solar_daytime_floor_ratio": inner_kwargs.get("inner_solar_daytime_floor_ratio", 0.78),
                        "solar_daytime_floor_enabled": inner_kwargs.get("inner_solar_daytime_floor_enabled", True),
                        "solar_daytime_up_ratio": inner_kwargs.get("inner_solar_daytime_up_ratio", 0.55),
                        "solar_monday_step_up_bonus": inner_kwargs.get("inner_solar_monday_step_up_bonus", 0.20),
                        "solar_daytime_down_ratio": inner_kwargs.get("inner_solar_daytime_down_ratio", 0.18),
                    },
                )["forecast_kw_import"].to_numpy()

                inner_actual = fold_context["inner_actual"]
                mask = np.array([current_regime == regime_key for current_regime in fold_context["inner_regimes"]], dtype=bool)
                if not np.any(mask):
                    continue

                regime_actual = inner_actual[mask]
                regime_pred = pred[mask]
                rmse = float(np.sqrt(mean_squared_error(regime_actual, regime_pred)))
                md_abs_error = float(abs(np.max(regime_actual) - np.max(regime_pred)))
                fold_rmses.append(rmse)
                fold_md_errors.append(md_abs_error)

            if not fold_rmses:
                continue

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

        if not rows:
            continue

        table = pd.DataFrame(rows).sort_values(["objective", "rmse"]).reset_index(drop=True)
        regime_weight_map[regime_key] = float(table.iloc[0]["blend_weight"])
        regime_tables[regime_key] = table

    return regime_weight_map, regime_tables


def build_cutoffs(
    frame_length: int,
    min_train: int = 48 * 14,
    horizon: int = 48,
    step: int = 48,
    max_folds: int = 10,
) -> list[int]:
    cutoffs = []
    cutoff = min_train
    while cutoff + horizon <= frame_length:
        cutoffs.append(cutoff)
        cutoff += step

    if len(cutoffs) > max_folds:
        cutoffs = cutoffs[-max_folds:]
    return cutoffs
