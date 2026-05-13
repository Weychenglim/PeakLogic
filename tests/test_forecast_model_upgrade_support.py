from __future__ import annotations

from pathlib import Path
import unittest

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = [
    ROOT / "1. Load Profile (With Solar Installed) SoL.xlsx",
    ROOT / "4. Load Profile (With Solar) Mi2.xlsx",
]
CANONICAL_COLUMNS = [
    "site_id",
    "interval_start",
    "interval_end",
    "kw_import",
    "kw_export",
    "kvar_import",
    "kvar_export",
    "has_solar",
    "existing_pv_kwp",
    "source_file",
    "source_sheet",
    "is_imputed",
]
POWER_COLUMNS = ["kw_import", "kw_export", "kvar_import", "kvar_export"]


def regularize_to_30min(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.sort_values("interval_end").drop_duplicates("interval_end", keep="last").copy()
    ordered = ordered.set_index("interval_end")
    full_index = pd.date_range(ordered.index.min(), ordered.index.max(), freq="30min")
    regular = ordered.reindex(full_index)
    regular.index.name = "interval_end"

    site_id = str(frame["site_id"].iloc[0])
    has_solar = bool(frame["has_solar"].iloc[0])
    source_file = str(frame["source_file"].iloc[0])
    existing_pv_candidates = frame["existing_pv_kwp"].dropna()
    existing_pv_kwp = float(existing_pv_candidates.iloc[0]) if not existing_pv_candidates.empty else np.nan

    regular["site_id"] = site_id
    regular["has_solar"] = has_solar
    regular["existing_pv_kwp"] = existing_pv_kwp
    regular["source_file"] = source_file
    regular["source_sheet"] = regular["source_sheet"].fillna("imputed")
    regular["interval_start"] = regular.index - pd.Timedelta(minutes=30)

    was_missing = regular["kw_import"].isna()
    for col in POWER_COLUMNS:
        series = pd.to_numeric(regular[col], errors="coerce")
        series = series.interpolate(method="time", limit=4, limit_direction="both")
        median = float(np.nanmedian(series.to_numpy()))
        if np.isnan(median):
            median = 0.0
        regular[col] = series.fillna(median).clip(lower=0.0)

    regular["is_imputed"] = was_missing
    regular = regular.reset_index()
    return regular[CANONICAL_COLUMNS]


def synthetic_site_frame(
    site_id: str,
    has_solar: bool,
    periods: int = 900,
    start: str = "2025-01-06 00:30:00",
) -> pd.DataFrame:
    interval_end = pd.date_range(start=start, periods=periods, freq="30min")
    hour = interval_end.hour + interval_end.minute / 60.0
    dayofweek = interval_end.dayofweek
    daily = 120.0 + 25.0 * np.sin(2 * np.pi * hour / 24.0)
    weekly = np.where(dayofweek < 5, 20.0, -10.0)
    solar_shape = (
        35.0
        * np.clip(np.sin(np.pi * np.clip((hour - 6.0) / 12.0, 0.0, 1.0)), 0.0, None)
        if has_solar
        else 0.0
    )
    kw_import = np.maximum(daily + weekly - solar_shape, 5.0)

    return pd.DataFrame(
        {
            "site_id": site_id,
            "interval_start": interval_end - pd.Timedelta(minutes=30),
            "interval_end": interval_end,
            "kw_import": kw_import.astype(float),
            "kw_export": np.zeros(periods, dtype=float),
            "kvar_import": np.zeros(periods, dtype=float),
            "kvar_export": np.zeros(periods, dtype=float),
            "has_solar": bool(has_solar),
            "existing_pv_kwp": np.full(periods, 100.0 if has_solar else 0.0, dtype=float),
            "source_file": f"{site_id}.xlsx",
            "source_sheet": "synthetic",
            "is_imputed": np.zeros(periods, dtype=bool),
        }
    )


class ForecastModelUpgradeSupportTests(unittest.TestCase):
    def test_peak_alert_policy_supports_site_type_thresholds(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            peak_alert_policy_for_site,
        )

        solar_policy = peak_alert_policy_for_site(has_solar=True)
        nonsolar_policy = peak_alert_policy_for_site(has_solar=False)

        self.assertIsInstance(solar_policy, PeakAlertPolicy)
        self.assertIsInstance(nonsolar_policy, PeakAlertPolicy)
        self.assertGreaterEqual(solar_policy.alert_quantile, 0.70)
        self.assertLessEqual(solar_policy.alert_quantile, 0.90)
        self.assertGreaterEqual(nonsolar_policy.alert_quantile, 0.70)
        self.assertLessEqual(nonsolar_policy.alert_quantile, 0.90)
        self.assertEqual(solar_policy.match_window_intervals, 2)
        self.assertEqual(nonsolar_policy.match_window_intervals, 2)

    def test_smooth_peak_scores_reduces_isolated_spikes(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import smooth_peak_scores

        scores = np.array([0.10, 0.10, 0.95, 0.10, 0.10, 0.80, 0.82, 0.81])
        smoothed = smooth_peak_scores(scores, window=3)

        self.assertLess(smoothed[2], scores[2])
        self.assertGreater(smoothed[6], 0.75)
        self.assertEqual(len(smoothed), len(scores))

    def test_apply_peak_risk_overlay_policy_does_not_change_forecast_values(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            add_enhanced_features,
            apply_peak_risk_overlay,
            fit_peak_risk_overlay,
        )

        frame = synthetic_site_frame("overlay_policy", has_solar=False, periods=950)
        train_frame = frame.iloc[:-48].copy()
        prepared, feature_columns = add_enhanced_features(train_frame)
        overlay = fit_peak_risk_overlay(prepared, feature_columns)
        forecast = pd.DataFrame(
            {
                "site_id": ["overlay_policy"] * 6,
                "interval_end": pd.date_range(
                    train_frame["interval_end"].iloc[-1] + pd.Timedelta(minutes=30),
                    periods=6,
                    freq="30min",
                ),
                "forecast_kw_import": [100.0, 120.0, 140.0, 160.0, 180.0, 200.0],
                "peak_risk_score": [0.10, 0.20, 0.90, 0.30, 0.85, 0.40],
            }
        )

        enriched = apply_peak_risk_overlay(
            forecast,
            overlay,
            train_frame,
            policy=PeakAlertPolicy(alert_quantile=0.80, score_smoothing_window=3),
        )

        self.assertTrue(np.allclose(enriched["forecast_kw_import"], forecast["forecast_kw_import"]))
        self.assertIn("peak_risk_overlay_score", enriched.columns)
        self.assertIn("peak_risk_smoothed_score", enriched.columns)

    def test_compare_peak_alert_policies_scores_recall_precision_tradeoff(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            PeakAlertPolicy,
            compare_peak_alert_policies,
        )

        actual = np.array([100.0, 500.0, 120.0, 480.0, 130.0, 460.0, 140.0, 150.0, 160.0, 170.0])
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 300.0, 120.0, 470.0, 130.0, 350.0, 140.0, 150.0, 160.0, 170.0],
                "peak_risk_overlay_score": [0.01, 0.99, 0.02, 0.98, 0.03, 0.70, 0.04, 0.69, 0.06, 0.07],
            }
        )
        policies = {
            "strict": PeakAlertPolicy(alert_quantile=0.90),
            "catch_more": PeakAlertPolicy(alert_quantile=0.60),
        }

        table = compare_peak_alert_policies(actual, forecast, policies, actual_peak_quantile=0.70)

        self.assertEqual(set(table["policy"]), {"strict", "catch_more"})
        strict_recall = float(table.loc[table["policy"] == "strict", "peak_recall"].iloc[0])
        catch_more_recall = float(table.loc[table["policy"] == "catch_more", "peak_recall"].iloc[0])
        self.assertGreater(catch_more_recall, strict_recall)
        self.assertIn("alert_quantile", table.columns)
        self.assertIn("peak_false_positive_count", table.columns)

    def test_enhanced_features_include_ramp_and_peak_approach_signals(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import add_enhanced_features

        frame = synthetic_site_frame("ramp_features", has_solar=False, periods=950)
        prepared, feature_columns = add_enhanced_features(frame)

        expected = {
            "recent_slope_4",
            "recent_slope_8",
            "recent_acceleration_4",
            "gap_to_rolling_max_48",
            "rolling_max_ratio_48",
            "ramp_to_tariff_peak_interaction",
            "solar_ramp_to_daylight_interaction",
        }

        self.assertTrue(expected.issubset(set(feature_columns)))
        self.assertFalse(prepared[list(expected)].isna().any().any())

    def test_md_peak_calibration_adjusts_magnitude_without_changing_timing(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            apply_md_peak_calibration,
            fit_md_peak_calibration,
        )

        actual_peaks = np.array([400.0, 420.0, 410.0, 430.0])
        predicted_peaks = np.array([320.0, 335.0, 330.0, 340.0])
        correction = fit_md_peak_calibration(actual_peaks, predicted_peaks)
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 200.0, 340.0, 150.0],
                "peak_risk_score": [0.10, 0.20, 0.90, 0.30],
            }
        )

        corrected = apply_md_peak_calibration(forecast, correction)

        self.assertGreater(corrected["forecast_kw_import"].max(), forecast["forecast_kw_import"].max())
        self.assertEqual(int(corrected["forecast_kw_import"].idxmax()), int(forecast["forecast_kw_import"].idxmax()))
        self.assertIn("md_calibrated_kw_import", corrected.columns)

    def test_late_horizon_peak_envelope_lifts_only_late_high_risk_slots(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            apply_late_horizon_peak_uplift,
            fit_late_horizon_peak_envelope,
        )

        history_end = pd.Timestamp("2025-01-22 00:00:00")
        history = pd.DataFrame(
            {
                "interval_end": pd.date_range(end=history_end, periods=21 * 48, freq="30min"),
            }
        )
        history["kw_import"] = np.where(history["interval_end"].dt.hour == 22, 420.0, 140.0)

        forecast = pd.DataFrame(
            {
                "interval_end": pd.date_range(history_end + pd.Timedelta(minutes=30), periods=48, freq="30min"),
                "forecast_kw_import": [160.0] * 48,
                "peak_risk_overlay_score": [0.10] * 48,
            }
        )
        forecast.loc[44, "peak_risk_overlay_score"] = 0.99

        envelope = fit_late_horizon_peak_envelope(history, envelope_quantile=0.90)
        uplifted = apply_late_horizon_peak_uplift(
            forecast,
            envelope,
            start_step=33,
            score_quantile=0.80,
            floor_ratio=0.90,
            max_uplift_kw=260.0,
        )

        self.assertIn("late_peak_uplift_kw_import", uplifted.columns)
        self.assertEqual(float(uplifted.loc[10, "late_peak_uplift_kw_import"]), 160.0)
        self.assertGreater(float(uplifted.loc[44, "late_peak_uplift_kw_import"]), 300.0)
        self.assertEqual(float(uplifted.loc[44, "late_peak_uplift_kw_import"]), float(uplifted["late_peak_uplift_kw_import"].max()))

    def test_late_horizon_peak_uplift_is_capped_and_forecast_safe(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            LateHorizonPeakEnvelope,
            apply_late_horizon_peak_uplift,
        )

        forecast = pd.DataFrame(
            {
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=48, freq="30min"),
                "forecast_kw_import": [100.0] * 48,
                "peak_risk_overlay_score": [0.10] * 47 + [0.99],
            }
        )
        envelope = LateHorizonPeakEnvelope(slot_floors_kw={}, half_hour_floors_kw={}, global_floor_kw=500.0)

        uplifted = apply_late_horizon_peak_uplift(
            forecast,
            envelope,
            start_step=33,
            score_quantile=0.80,
            floor_ratio=1.0,
            max_uplift_kw=75.0,
        )

        self.assertEqual(float(uplifted.loc[47, "late_peak_uplift_kw_import"]), 175.0)
        self.assertTrue(np.allclose(uplifted.loc[:31, "late_peak_uplift_kw_import"], 100.0))
        self.assertTrue(np.allclose(forecast["forecast_kw_import"], 100.0))

    def test_late_horizon_peak_uplift_uses_site_peak_floor_for_nonsolar_night(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            LateHorizonPeakEnvelope,
            apply_late_horizon_peak_uplift,
        )

        forecast = pd.DataFrame(
            {
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=48, freq="30min"),
                "forecast_kw_import": [700.0] * 48,
                "peak_risk_overlay_score": [0.10] * 47 + [0.99],
            }
        )
        forecast.loc[47, "interval_end"] = pd.Timestamp("2025-01-02 22:30:00")
        envelope = LateHorizonPeakEnvelope(
            slot_floors_kw={(3, 22, 30): 650.0},
            half_hour_floors_kw={(22, 30): 650.0},
            global_floor_kw=640.0,
            site_peak_floor_kw=1200.0,
        )

        uplifted = apply_late_horizon_peak_uplift(
            forecast,
            envelope,
            start_step=33,
            score_quantile=0.80,
            floor_ratio=0.90,
            max_uplift_kw=250.0,
            has_solar=False,
            use_site_peak_floor_for_nonsolar_night=True,
        )

        self.assertEqual(float(uplifted.loc[47, "late_peak_uplift_kw_import"]), 950.0)
        self.assertEqual(float(uplifted.loc[47, "late_peak_envelope_floor_kw"]), 1080.0)

    def test_lightgbm_quantile_dependency_is_available(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import require_lightgbm

        module = require_lightgbm()

        self.assertTrue(hasattr(module, "LGBMRegressor"))
        self.assertTrue(hasattr(module, "LGBMClassifier"))

    def test_build_direct_horizon_training_rows_uses_future_steps_without_target_leakage(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            build_direct_horizon_training_rows,
        )

        frame = synthetic_site_frame("direct_rows", has_solar=False, periods=900)
        rows, feature_columns = build_direct_horizon_training_rows([frame], horizon=8)

        self.assertFalse(rows.empty)
        self.assertIn("target_kw_import", rows.columns)
        self.assertIn("horizon_step", rows.columns)
        self.assertIn("horizon_step", feature_columns)
        self.assertNotIn("kw_import", feature_columns)
        self.assertNotIn("target_kw_import", feature_columns)
        self.assertEqual(int(rows["horizon_step"].min()), 1)
        self.assertEqual(int(rows["horizon_step"].max()), 8)

    def test_build_direct_horizon_quantile_rows_has_future_targets_and_no_leakage(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            build_direct_horizon_quantile_rows,
        )

        frame = synthetic_site_frame("quantile_rows", has_solar=True, periods=900)
        rows, feature_columns = build_direct_horizon_quantile_rows([frame], horizon=8)

        self.assertFalse(rows.empty)
        self.assertIn("target_kw_import", rows.columns)
        self.assertIn("is_md_risk_interval", rows.columns)
        self.assertIn("horizon_step", feature_columns)
        self.assertIn("target_is_daylight", feature_columns)
        self.assertNotIn("kw_import", feature_columns)
        self.assertNotIn("target_kw_import", feature_columns)
        self.assertEqual(int(rows["horizon_step"].min()), 1)
        self.assertEqual(int(rows["horizon_step"].max()), 8)

    def test_direct_horizon_boosted_forecast_returns_horizon_rows(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            fit_direct_horizon_boosted_model,
            forecast_with_direct_horizon_boosted_model,
        )

        frame = synthetic_site_frame("direct_hgb", has_solar=False, periods=950)
        train_frame = frame.iloc[:-48].copy()
        model = fit_direct_horizon_boosted_model([train_frame], horizon=12, max_iter=20)
        forecast = forecast_with_direct_horizon_boosted_model(model, train_frame, horizon=12)

        self.assertEqual(len(forecast), 12)
        self.assertIn("forecast_kw_import", forecast.columns)
        self.assertIn("horizon_step", forecast.columns)
        self.assertTrue(np.isfinite(forecast["forecast_kw_import"]).all())
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())

    def test_direct_lightgbm_quantile_forecast_returns_monotonic_quantiles(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            fit_direct_horizon_lightgbm_quantile_model,
            forecast_with_direct_horizon_lightgbm_quantile_model,
        )

        frame = synthetic_site_frame("quantile_lgbm", has_solar=True, periods=950)
        train_frame = frame.iloc[:-48].copy()
        model = fit_direct_horizon_lightgbm_quantile_model([train_frame], horizon=12, n_estimators=30)
        forecast = forecast_with_direct_horizon_lightgbm_quantile_model(model, train_frame, horizon=12)

        self.assertEqual(len(forecast), 12)
        self.assertIn("forecast_p50_kw_import", forecast.columns)
        self.assertIn("forecast_p80_kw_import", forecast.columns)
        self.assertIn("forecast_p90_kw_import", forecast.columns)
        self.assertTrue((forecast["forecast_p80_kw_import"] >= forecast["forecast_p50_kw_import"]).all())
        self.assertTrue((forecast["forecast_p90_kw_import"] >= forecast["forecast_p80_kw_import"]).all())

    def test_summarize_rolling_error_diagnostics_groups_horizon_and_peak_regimes(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import summarize_rolling_error_diagnostics

        predictions = pd.DataFrame(
            {
                "site_id": ["A"] * 6,
                "fold": [1] * 6,
                "step": [1, 2, 10, 11, 30, 31],
                "actual_kw_import": [100.0, 120.0, 300.0, 320.0, 150.0, 140.0],
                "enhanced_kw_import": [110.0, 130.0, 260.0, 270.0, 170.0, 160.0],
                "has_solar": [False] * 6,
                "is_daylight": [False, False, True, True, True, False],
            }
        )

        summary = summarize_rolling_error_diagnostics(predictions)

        self.assertIn("horizon_bucket", summary.columns)
        self.assertIn("actual_peak_regime", summary.columns)
        self.assertIn("mean_abs_error_kw", summary.columns)
        self.assertTrue({"early", "middle", "late"}.intersection(set(summary["horizon_bucket"])))

    def test_summarize_rolling_candidate_error_diagnostics_compares_models(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            summarize_rolling_candidate_error_diagnostics,
        )

        predictions = pd.DataFrame(
            {
                "site_id": ["E"] * 4,
                "fold": [1] * 4,
                "step": [33, 34, 35, 36],
                "actual_kw_import": [400.0, 420.0, 100.0, 110.0],
                "enhanced_kw_import": [250.0, 260.0, 100.0, 110.0],
                "uplift_kw_import": [360.0, 380.0, 100.0, 110.0],
                "has_solar": [False] * 4,
                "is_daylight": [False] * 4,
            }
        )

        summary = summarize_rolling_candidate_error_diagnostics(
            predictions,
            {"enhanced": "enhanced_kw_import", "uplift": "uplift_kw_import"},
        )

        enhanced_peak = summary.loc[
            (summary["model"] == "enhanced") & (summary["actual_peak_regime"] == "actual_peak")
        ].iloc[0]
        uplift_peak = summary.loc[
            (summary["model"] == "uplift") & (summary["actual_peak_regime"] == "actual_peak")
        ].iloc[0]
        self.assertLess(abs(float(uplift_peak["mean_error_kw"])), abs(float(enhanced_peak["mean_error_kw"])))
        self.assertIn("model", summary.columns)

    def test_confirm_peak_alerts_requires_risk_and_context_confirmation(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import confirm_peak_alerts

        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 180.0, 210.0, 120.0, 205.0],
                "peak_risk_overlay_score": [0.95, 0.92, 0.91, 0.20, 0.89],
                "ridge_component": [100.0, 180.0, 210.0, 120.0, 205.0],
                "seasonal_component": [100.0, 170.0, 205.0, 150.0, 190.0],
            }
        )

        confirmed = confirm_peak_alerts(forecast, alert_quantile=0.60, value_quantile=0.70)

        self.assertIn("confirmed_peak_score", confirmed.columns)
        self.assertIn("is_confirmed_peak_alert", confirmed.columns)
        self.assertLess(int(confirmed["is_confirmed_peak_alert"].sum()), 4)
        self.assertTrue(bool(confirmed.loc[2, "is_confirmed_peak_alert"]))
        self.assertLess(float(confirmed.loc[0, "confirmed_peak_score"]), 0.0)

    def test_rank_alert_episodes_groups_nearby_alerts(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import rank_alert_episodes

        forecast = pd.DataFrame(
            {
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=8, freq="30min"),
                "is_confirmed_peak_alert": [False, True, True, False, False, True, True, False],
                "confirmed_peak_score": [0.0, 0.7, 0.9, 0.0, 0.0, 0.6, 0.8, 0.0],
                "forecast_kw_import": [100.0, 180.0, 220.0, 120.0, 130.0, 190.0, 210.0, 140.0],
            }
        )

        episodes = rank_alert_episodes(forecast)

        self.assertEqual(len(episodes), 2)
        self.assertGreaterEqual(float(episodes.loc[0, "episode_score"]), float(episodes.loc[1, "episode_score"]))
        self.assertEqual(int(episodes.loc[0, "alert_count"]), 2)

    def test_confirmed_alert_quantile_matches_confirmed_alert_share(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import confirmed_alert_quantile

        confirmed = pd.Series([False, False, True, False, True])

        self.assertAlmostEqual(confirmed_alert_quantile(confirmed), 0.60)
        self.assertAlmostEqual(confirmed_alert_quantile(pd.Series([False, False])), 1.0)

    def test_mixed_training_defaults_to_global_model_and_segmented_training_requires_threshold(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            SegmentedRidgeModel,
            fit_global_enhanced_ridge,
        )

        solar_a = synthetic_site_frame("solar_a", has_solar=True)
        solar_b = synthetic_site_frame("solar_b", has_solar=True, start="2025-02-03 00:30:00")
        non_solar_a = synthetic_site_frame("non_solar_a", has_solar=False, start="2025-03-03 00:30:00")
        non_solar_b = synthetic_site_frame("non_solar_b", has_solar=False, start="2025-04-07 00:30:00")

        global_default = fit_global_enhanced_ridge(
            [solar_a, non_solar_a],
            n_splits=2,
            normalize_targets=True,
        )
        self.assertNotIsInstance(global_default.model, SegmentedRidgeModel)
        self.assertIsInstance(global_default.alpha, float)

        threshold_fallback = fit_global_enhanced_ridge(
            [solar_a, solar_b, non_solar_a],
            n_splits=2,
            normalize_targets=True,
            enable_segmented_training=True,
            segmented_min_sites_per_segment=2,
        )
        self.assertNotIsInstance(threshold_fallback.model, SegmentedRidgeModel)
        self.assertIsInstance(threshold_fallback.alpha, float)

        segmented = fit_global_enhanced_ridge(
            [solar_a, solar_b, non_solar_a, non_solar_b],
            n_splits=2,
            normalize_targets=True,
            enable_segmented_training=True,
            segmented_min_sites_per_segment=2,
        )
        self.assertIsInstance(segmented.model, SegmentedRidgeModel)
        self.assertIsInstance(segmented.alpha, dict)
        self.assertEqual(set(segmented.alpha.keys()), {"solar", "non_solar"})

    def test_solar_daytime_floor_and_step_up_controls_can_soften_predictions(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            add_enhanced_features,
            forecast_with_enhanced_model,
        )

        class ConstantModel:
            def __init__(self, value: float) -> None:
                self.value = float(value)

            def predict(self, features: pd.DataFrame) -> np.ndarray:
                return np.full(len(features), self.value, dtype=float)

        solar_frame = synthetic_site_frame("solar_test", has_solar=True, periods=1100)

        monday_noon_idx = next(
            idx
            for idx, ts in enumerate(solar_frame["interval_end"])
            if idx > 700 and ts.dayofweek == 0 and ts.hour == 11 and ts.minute == 30
        )
        train_frame = solar_frame.iloc[: monday_noon_idx + 1].copy()
        _, feature_columns = add_enhanced_features(train_frame)

        strict_floor = forecast_with_enhanced_model(
            model=ConstantModel(0.0),
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=1,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            horizon_blend_floor=1.0,
            solar_daytime_floor_ratio=0.82,
            solar_daytime_floor_enabled=True,
            normalize_targets=False,
            site_scale=1.0,
        )
        soft_floor = forecast_with_enhanced_model(
            model=ConstantModel(0.0),
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=1,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            horizon_blend_floor=1.0,
            solar_daytime_floor_ratio=0.82,
            solar_daytime_floor_enabled=False,
            normalize_targets=False,
            site_scale=1.0,
        )
        self.assertGreater(
            float(strict_floor["forecast_kw_import"].iloc[0]),
            float(soft_floor["forecast_kw_import"].iloc[0]),
        )

        strict_step = forecast_with_enhanced_model(
            model=ConstantModel(500.0),
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=1,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            horizon_blend_floor=1.0,
            solar_daytime_up_ratio=0.60,
            solar_monday_step_up_bonus=0.20,
            normalize_targets=False,
            site_scale=1.0,
        )
        soft_step = forecast_with_enhanced_model(
            model=ConstantModel(500.0),
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=1,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            horizon_blend_floor=1.0,
            solar_daytime_up_ratio=0.40,
            solar_monday_step_up_bonus=0.05,
            normalize_targets=False,
            site_scale=1.0,
        )
        self.assertGreater(
            float(strict_step["forecast_kw_import"].iloc[0]),
            float(soft_step["forecast_kw_import"].iloc[0]),
        )

    def test_site_evaluation_settings_and_prediction_summary_are_shared_helpers(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            site_evaluation_settings,
            summarize_prediction_errors,
        )

        solar_settings = site_evaluation_settings(has_solar=True)
        nonsolar_settings = site_evaluation_settings(has_solar=False)

        self.assertEqual(solar_settings["alpha_grid"], [3.0, 10.0, 30.0, 100.0])
        self.assertEqual(len(solar_settings["blend_candidates"]), 6)
        self.assertIsNone(nonsolar_settings["alpha_grid"])
        self.assertEqual(len(nonsolar_settings["blend_candidates"]), 6)
        self.assertIn("solar_daylight_anchor", solar_settings["forecast_kwargs"])
        self.assertIn("inner_solar_daylight_anchor", solar_settings["inner_forecast_kwargs"])

        predictions = pd.DataFrame(
            {
                "site_id": ["A", "A", "B"],
                "error_kw": [-10.0, 20.0, 5.0],
                "is_daylight": [True, True, False],
            }
        )
        summary = summarize_prediction_errors(predictions, group_columns=["site_id", "is_daylight"])

        self.assertEqual(
            list(summary.columns),
            ["site_id", "is_daylight", "rows", "mean_abs_error_kw", "mean_signed_error_kw"],
        )
        self.assertEqual(int(summary.loc[0, "rows"]), 2)
        self.assertAlmostEqual(float(summary.loc[0, "mean_abs_error_kw"]), 15.0)
        self.assertAlmostEqual(float(summary.loc[0, "mean_signed_error_kw"]), 5.0)

    def test_non_solar_anchor_damps_large_weekly_disagreement(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import seasonal_anchor_components

        history = [700.0] * 672
        history[-48] = 700.0
        history[-336] = 1220.0
        history[-672] = 1180.0

        components = seasonal_anchor_components(
            history,
            pd.Timestamp("2025-05-30 12:00:00"),
            has_solar=False,
        )

        self.assertAlmostEqual(float(components["prev_day"]), 700.0)
        self.assertAlmostEqual(float(components["prev_week_raw"]), 1220.0)
        self.assertLessEqual(float(components["weekly_weight"]), 0.15)
        self.assertLessEqual(float(components["prev_week"]), 805.0)
        self.assertLess(float(components["anchor"]), 760.0)

    def test_evaluate_forecast_reports_normalized_and_peak_timing_metrics(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import evaluate_forecast

        actual = np.array([100.0, 200.0, 150.0, 300.0])
        predicted = np.array([110.0, 180.0, 140.0, 270.0])

        metrics = evaluate_forecast(actual, predicted)

        self.assertAlmostEqual(metrics["mae_kw"], 17.5)
        self.assertAlmostEqual(metrics["rmse_kw"], float(np.sqrt(375.0)))
        self.assertAlmostEqual(metrics["mean_error_kw"], -12.5)
        self.assertAlmostEqual(metrics["wape_pct"], 100.0 * 70.0 / 750.0)
        self.assertGreater(metrics["smape_pct"], 0.0)
        self.assertAlmostEqual(metrics["nrmse_by_median_pct"], metrics["rmse_kw"] / 175.0 * 100.0)
        self.assertAlmostEqual(metrics["nrmse_by_peak_pct"], metrics["rmse_kw"] / 300.0 * 100.0)
        self.assertEqual(metrics["peak_time_error_intervals"], 0.0)
        self.assertAlmostEqual(metrics["peak_f1"], 1.0)
        self.assertEqual(metrics["peak_false_negative_count"], 0.0)
        self.assertEqual(metrics["peak_false_positive_count"], 0.0)
        self.assertAlmostEqual(metrics["peak_capture_rate_at_k"], 1.0)
        self.assertEqual(metrics["md_peak_rank"], 1.0)

    def test_evaluate_forecast_can_rank_peaks_with_overlay_scores(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import evaluate_forecast

        actual = np.array([100.0, 500.0, 120.0, 450.0, 130.0])
        conservative_prediction = np.array([100.0, 300.0, 120.0, 350.0, 130.0])
        overlay_score = np.array([0.05, 0.95, 0.10, 0.90, 0.20])

        metrics = evaluate_forecast(
            actual,
            conservative_prediction,
            peak_quantile=0.6,
            peak_score=overlay_score,
        )

        self.assertEqual(metrics["peak_false_negative_count"], 0.0)
        self.assertEqual(metrics["peak_false_positive_count"], 0.0)
        self.assertAlmostEqual(metrics["peak_recall"], 1.0)
        self.assertAlmostEqual(metrics["peak_f1"], 1.0)
        self.assertEqual(metrics["md_peak_rank"], 1.0)

    def test_evaluate_forecast_lower_alert_quantile_catches_more_peaks(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import evaluate_forecast

        actual = np.array([100.0, 500.0, 120.0, 480.0, 130.0, 460.0, 140.0, 150.0, 160.0, 170.0])
        predicted = np.array([100.0, 300.0, 120.0, 470.0, 130.0, 350.0, 140.0, 150.0, 160.0, 170.0])
        peak_score = np.array([0.01, 0.99, 0.02, 0.98, 0.03, 0.70, 0.04, 0.69, 0.06, 0.07])

        strict_metrics = evaluate_forecast(
            actual,
            predicted,
            peak_quantile=0.70,
            peak_score=peak_score,
            predicted_peak_quantile=0.90,
        )
        catch_more_metrics = evaluate_forecast(
            actual,
            predicted,
            peak_quantile=0.70,
            peak_score=peak_score,
            predicted_peak_quantile=0.60,
        )

        self.assertGreater(catch_more_metrics["peak_recall"], strict_metrics["peak_recall"])
        self.assertGreater(catch_more_metrics["peak_false_positive_count"], strict_metrics["peak_false_positive_count"])

    def test_evaluate_forecast_window_scoring_credits_nearby_peak_alerts(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import evaluate_forecast

        actual = np.array([100.0, 500.0, 100.0, 100.0, 450.0, 100.0])
        predicted = np.array([100.0, 100.0, 490.0, 100.0, 100.0, 440.0])

        exact_metrics = evaluate_forecast(actual, predicted, peak_quantile=0.70)
        window_metrics = evaluate_forecast(actual, predicted, peak_quantile=0.70, peak_match_window=1)

        self.assertEqual(exact_metrics["peak_recall"], 0.0)
        self.assertEqual(window_metrics["peak_recall"], 1.0)
        self.assertEqual(window_metrics["peak_false_negative_count"], 0.0)

    def test_component_evaluation_uses_overlay_alert_quantile_for_peak_priority_row(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import evaluate_forecast_components

        actual = np.array([100.0, 500.0, 120.0, 480.0, 130.0, 460.0, 140.0, 150.0, 160.0, 170.0])
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [100.0, 300.0, 120.0, 470.0, 130.0, 350.0, 140.0, 150.0, 160.0, 170.0],
                "ridge_component": [100.0] * 10,
                "seasonal_component": [100.0] * 10,
                "peak_risk_overlay_score": [0.01, 0.99, 0.02, 0.98, 0.03, 0.70, 0.04, 0.69, 0.06, 0.07],
            }
        )

        strict = evaluate_forecast_components(actual, forecast, peak_quantile=0.70, overlay_alert_quantile=0.90)
        tuned = evaluate_forecast_components(actual, forecast, peak_quantile=0.70, overlay_alert_quantile=0.60)
        strict_peak = strict.loc[strict["model"] == "enhanced_peak_priority", "peak_recall"].iloc[0]
        tuned_peak = tuned.loc[tuned["model"] == "enhanced_peak_priority", "peak_recall"].iloc[0]

        self.assertGreater(tuned_peak, strict_peak)

    def test_peak_priority_objective_prefers_recall_over_lower_rmse(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import peak_priority_objective

        misses_md_peak = {
            "rmse_kw": 20.0,
            "wape_pct": 5.0,
            "md_abs_error_kw": 120.0,
            "peak_recall": 0.0,
            "peak_precision": 0.0,
            "peak_time_error_intervals": 8.0,
            "md_peak_rank": 6.0,
        }
        catches_md_peak = {
            "rmse_kw": 35.0,
            "wape_pct": 8.0,
            "md_abs_error_kw": 20.0,
            "peak_recall": 1.0,
            "peak_precision": 0.5,
            "peak_time_error_intervals": 1.0,
            "md_peak_rank": 1.0,
        }

        self.assertLess(
            peak_priority_objective(catches_md_peak),
            peak_priority_objective(misses_md_peak),
        )

    def test_forecast_value_objective_keeps_blend_selection_value_safe(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import forecast_value_objective

        value_stable_but_lower_recall = {
            "rmse_kw": 20.0,
            "md_abs_error_kw": 10.0,
            "mean_error_abs": 5.0,
            "cumulative_error_abs": 96.0,
            "drift_slope_abs": 0.2,
            "peak_recall": 0.0,
        }
        peak_heavy_but_value_worse = {
            "rmse_kw": 60.0,
            "md_abs_error_kw": 150.0,
            "mean_error_abs": 40.0,
            "cumulative_error_abs": 960.0,
            "drift_slope_abs": 2.0,
            "peak_recall": 1.0,
        }

        self.assertLess(
            forecast_value_objective(value_stable_but_lower_recall),
            forecast_value_objective(peak_heavy_but_value_worse),
        )

    def test_peak_overlay_rejects_leakage_columns_and_uses_forecast_safe_features(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            FORECAST_LEAKAGE_COLUMNS,
            add_enhanced_features,
            fit_peak_risk_overlay,
        )

        frame = synthetic_site_frame("overlay", has_solar=False, periods=950)
        prepared, feature_columns = add_enhanced_features(frame)

        with self.assertRaisesRegex(ValueError, "leakage"):
            fit_peak_risk_overlay(prepared, feature_columns + ["kw_import"])

        overlay = fit_peak_risk_overlay(prepared, feature_columns)

        self.assertTrue(set(overlay.feature_columns).issubset(set(feature_columns)))
        self.assertFalse(set(overlay.feature_columns) & FORECAST_LEAKAGE_COLUMNS)

    def test_evaluate_forecast_components_and_summary_compare_baselines(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            evaluate_forecast_components,
            summarize_model_metrics,
        )

        actual = np.array([100.0, 200.0, 150.0, 300.0])
        forecast = pd.DataFrame(
            {
                "forecast_kw_import": [110.0, 180.0, 140.0, 270.0],
                "ridge_component": [95.0, 190.0, 145.0, 260.0],
                "seasonal_component": [120.0, 210.0, 160.0, 310.0],
            }
        )

        component_metrics = evaluate_forecast_components(actual, forecast)

        self.assertEqual(
            set(component_metrics["model"]),
            {"enhanced", "ridge_only", "seasonal"},
        )

        summarized = summarize_model_metrics(
            pd.DataFrame(
                {
                    "site_id": ["A", "A", "A"],
                    **component_metrics.to_dict(orient="list"),
                }
            ),
            group_columns=["site_id", "model"],
        )
        self.assertIn("wape_pct", summarized.columns)
        self.assertIn("peak_time_error_intervals", summarized.columns)
        self.assertEqual(len(summarized), 3)

    def test_select_blend_weight_reports_bias_and_drift_terms(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            add_enhanced_features,
            select_blend_weight,
        )

        class ConstantModel:
            def __init__(self, value: float) -> None:
                self.value = float(value)

            def predict(self, features: pd.DataFrame) -> np.ndarray:
                return np.full(len(features), self.value, dtype=float)

        frame = synthetic_site_frame("bias_terms", has_solar=False, periods=950)
        _, feature_columns = add_enhanced_features(frame)

        _, table = select_blend_weight(
            model=ConstantModel(100.0),
            site_train_frame=frame,
            feature_columns=feature_columns,
            horizon=48,
            candidates=[1.0],
            use_calibration_in_inner=False,
            inner_horizon_blend_floor=1.0,
            inner_max_step_change_ratio=1.0,
            normalize_targets=False,
            site_scale=1.0,
        )

        self.assertIn("mean_error_abs", table.columns)
        self.assertIn("cumulative_error_abs", table.columns)
        self.assertIn("drift_slope_abs", table.columns)
        self.assertTrue(np.isfinite(float(table.loc[0, "objective"])))

    def test_horizon_residual_correction_can_reduce_recent_recursive_bias(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            add_enhanced_features,
            fit_horizon_residual_adjustment,
            forecast_with_enhanced_model,
        )

        class ConstantModel:
            def __init__(self, value: float) -> None:
                self.value = float(value)

            def predict(self, features: pd.DataFrame) -> np.ndarray:
                return np.full(len(features), self.value, dtype=float)

        frame = synthetic_site_frame("residual_profile", has_solar=False, periods=950)
        train_frame = frame.iloc[:-48].copy()
        actual = frame.iloc[-48:]["kw_import"].to_numpy()
        _, feature_columns = add_enhanced_features(train_frame)
        model = ConstantModel(100.0)

        base_forecast = forecast_with_enhanced_model(
            model=model,
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=48,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            horizon_blend_floor=1.0,
            max_step_change_ratio=1.0,
            normalize_targets=False,
            site_scale=1.0,
        )
        residual_correction = fit_horizon_residual_adjustment(
            model=model,
            site_train_frame=train_frame,
            feature_columns=feature_columns,
            horizon=48,
            blend_weight=1.0,
            use_calibration_in_inner=False,
            horizon_correction_bucket_size=8,
            inner_horizon_blend_floor=1.0,
            inner_max_step_change_ratio=1.0,
            normalize_targets=False,
            site_scale=1.0,
        )
        corrected_forecast = forecast_with_enhanced_model(
            model=model,
            feature_columns=feature_columns,
            target_frame=train_frame,
            horizon=48,
            blend_weight=1.0,
            calibration=(0.0, 1.0),
            residual_correction=residual_correction,
            residual_correction_bucket_size=8,
            horizon_blend_floor=1.0,
            max_step_change_ratio=1.0,
            normalize_targets=False,
            site_scale=1.0,
        )

        base_rmse = float(np.sqrt(np.mean(np.square(base_forecast["forecast_kw_import"].to_numpy() - actual))))
        corrected_rmse = float(
            np.sqrt(np.mean(np.square(corrected_forecast["forecast_kw_import"].to_numpy() - actual)))
        )

        self.assertTrue(any(key != "default" for key in residual_correction))
        self.assertLess(corrected_rmse, base_rmse)

    def test_latest_fold_spot_checks_preserve_sol_and_mi2_behavior(self) -> None:
        from notebooks.model_upgrade_inspection.forecast_model_upgrade_support import (
            build_cutoffs,
            fit_global_enhanced_ridge,
            fit_site_calibration,
            forecast_with_enhanced_model,
            select_blend_weight,
            site_evaluation_settings,
            site_scale_from_frame,
        )
        from trex_energy.ingestion import load_site_workbook

        results: dict[str, dict[str, float]] = {}
        for path in DATA_FILES:
            frame, metadata = load_site_workbook(path)
            ordered = regularize_to_30min(frame).sort_values("interval_end").reset_index(drop=True)
            cutoff = build_cutoffs(len(ordered), horizon=48)[-1]
            train_frame = ordered.iloc[:cutoff].copy()
            actual_slice = ordered.iloc[cutoff : cutoff + 48].copy()
            actual = actual_slice["kw_import"].to_numpy()
            settings = site_evaluation_settings(has_solar=bool(ordered["has_solar"].iloc[0]))
            target_scale = site_scale_from_frame(train_frame)

            enhanced = fit_global_enhanced_ridge(
                [train_frame],
                alpha_grid=settings["alpha_grid"],
                n_splits=3,
                normalize_targets=True,
            )
            calibration = fit_site_calibration(
                enhanced.model,
                train_frame,
                enhanced.feature_columns,
                window=336,
                normalize_targets=enhanced.normalize_targets,
                site_scale=target_scale,
            )
            blend_weight, _ = select_blend_weight(
                enhanced.model,
                train_frame,
                enhanced.feature_columns,
                horizon=48,
                candidates=settings["blend_candidates"],
                use_calibration_in_inner=True,
                normalize_targets=enhanced.normalize_targets,
                site_scale=target_scale,
                **settings["inner_forecast_kwargs"],
            )
            forecast = forecast_with_enhanced_model(
                model=enhanced.model,
                feature_columns=enhanced.feature_columns,
                target_frame=train_frame,
                horizon=48,
                blend_weight=blend_weight,
                calibration=calibration,
                normalize_targets=enhanced.normalize_targets,
                site_scale=target_scale,
                **settings["forecast_kwargs"],
            )
            predicted = forecast["forecast_kw_import"].to_numpy()
            errors = predicted - actual
            is_daylight = (
                (actual_slice["interval_end"].dt.hour >= 6)
                & (actual_slice["interval_end"].dt.hour < 18)
            ).to_numpy()

            results[metadata.site_id] = {
                "rmse_kw": float(np.sqrt(np.mean(np.square(errors)))),
                "md_abs_error_kw": float(abs(np.max(actual) - np.max(predicted))),
                "drift_slope_kw_per_step": float(np.polyfit(np.arange(len(errors)), errors, 1)[0]),
                "daylight_mean_error_kw": float(errors[is_daylight].mean()),
            }

        sol_result = next(value for key, value in results.items() if "SoL" in key)
        mi2_result = next(value for key, value in results.items() if "Mi2" in key)

        self.assertLess(sol_result["rmse_kw"], 60.0)
        self.assertLess(abs(sol_result["drift_slope_kw_per_step"]), 5.0)
        self.assertGreater(sol_result["daylight_mean_error_kw"], -80.0)

        self.assertLess(mi2_result["md_abs_error_kw"], 40.0)
        self.assertLess(abs(mi2_result["drift_slope_kw_per_step"]), 8.0)


if __name__ == "__main__":
    unittest.main()
