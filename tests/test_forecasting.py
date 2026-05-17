from pathlib import Path
import unittest

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = [
    ROOT / "1. Load Profile (With Solar Installed) SoL.xlsx",
    ROOT / "2. Load Profile (No Solar) E.xlsx",
    ROOT / "3. Load Profile (No Solar) SuN.xlsx",
    ROOT / "4. Load Profile (With Solar) Mi2.xlsx",
]


class ForecastingTests(unittest.TestCase):
    def _synthetic_planning_frame(self, days: int = 35) -> pd.DataFrame:
        rows = []
        start = pd.Timestamp("2025-01-01 00:00:00")
        for index in range(days * 48):
            interval_end = start + pd.Timedelta(minutes=30 * (index + 1))
            hour = interval_end.hour + interval_end.minute / 60
            is_weekend = interval_end.dayofweek >= 5
            evening_spike = 90.0 if 19 <= hour < 21 and index % (7 * 48) == 0 else 0.0
            rows.append(
                {
                    "site_id": "planning_site",
                    "interval_start": interval_end - pd.Timedelta(minutes=30),
                    "interval_end": interval_end,
                    "kw_import": 100.0 + (35.0 if 8 <= hour < 18 else 0.0) - (10.0 if is_weekend else 0.0) + evening_spike,
                    "kw_export": 0.0,
                    "kvar_import": 0.0,
                    "kvar_export": 0.0,
                    "has_solar": False,
                    "existing_pv_kwp": None,
                    "source_file": "synthetic.xlsx",
                    "source_sheet": "Sheet",
                    "is_imputed": False,
                }
            )
        return pd.DataFrame(rows)

    def test_global_forecast_returns_expected_columns_for_next_48_intervals(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        forecast = forecast_next_intervals(frames=frames, target_frame=frames[0], horizon=48)

        self.assertEqual(len(forecast), 48)
        self.assertTrue(
            {
                "site_id",
                "interval_start",
                "interval_end",
                "forecast_kw_import",
                "peak_risk_score",
                "is_predicted_peak",
            }.issubset(forecast.columns)
        )
        self.assertFalse(forecast["forecast_kw_import"].isna().any())
        self.assertTrue((forecast["forecast_kw_import"] >= 0).all())

    def test_backtest_returns_non_empty_metrics_and_predictions(self) -> None:
        from trex_energy.forecasting import backtest_site_forecast
        from trex_energy.ingestion import load_site_workbook

        frame, _ = load_site_workbook(DATA_FILES[1])
        result = backtest_site_forecast(frame, horizon=48)

        self.assertGreater(result.metrics["mae_kw"], 0.0)
        self.assertGreater(result.metrics["rmse_kw"], 0.0)
        self.assertEqual(len(result.predictions), 48)
        self.assertIn("actual_kw_import", result.predictions.columns)

    def test_monthly_planning_forecast_returns_30_day_blocks_without_recursive_modeling(self) -> None:
        from trex_energy.forecasting import forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=28)

        forecast = forecast_monthly_planning_profile(frame, months=2, growth_rate_pct=10.0, ev_load_kw=25.0)

        self.assertEqual(len(forecast), 2880)
        self.assertEqual(sorted(forecast["planning_month"].unique().tolist()), [1, 2])
        self.assertIn("md_risk_envelope_kw", forecast.columns)
        self.assertTrue((forecast["md_risk_envelope_kw"] >= forecast["forecast_kw_import"]).all())
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertEqual(set(forecast["planning_method"].unique()), {"recent_pattern_simulation"})

    def test_monthly_planning_forecast_returns_probabilistic_envelopes(self) -> None:
        from trex_energy.forecasting import forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=35)

        forecast = forecast_monthly_planning_profile(frame, months=1)

        self.assertTrue(
            {
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "forecast_kw_import",
                "md_risk_envelope_kw",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        pd.testing.assert_series_equal(
            forecast["forecast_kw_import"],
            forecast["p50_forecast_kw"],
            check_names=False,
        )
        self.assertIn("calibrated_p90_md_risk_kw", forecast.columns)
        self.assertIn("calibrated_p95_stress_kw", forecast.columns)
        self.assertTrue((forecast["calibrated_p90_md_risk_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["calibrated_p95_stress_kw"] >= forecast["p95_stress_kw"]).all())
        pd.testing.assert_series_equal(
            forecast["md_risk_envelope_kw"],
            forecast["calibrated_p95_stress_kw"],
            check_names=False,
        )

    def test_monthly_planning_adds_separate_peak_risk_overlay_without_changing_p50(self) -> None:
        from trex_energy.forecasting import forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=35)

        forecast = forecast_monthly_planning_profile(frame, months=1)

        self.assertIn("peak_risk_overlay_score", forecast.columns)
        self.assertIn("is_peak_risk_overlay", forecast.columns)
        self.assertTrue((forecast["peak_risk_overlay_score"] >= 0.0).all())
        self.assertTrue((forecast["peak_risk_overlay_score"] <= 1.0).all())
        self.assertGreater(int(forecast["is_peak_risk_overlay"].sum()), 0)
        pd.testing.assert_series_equal(
            forecast["forecast_kw_import"],
            forecast["p50_forecast_kw"],
            check_names=False,
        )

    def test_long_horizon_model_returns_monthly_planning_contract(self) -> None:
        from trex_energy.forecasting import forecast_long_horizon_model_profile

        target = self._synthetic_planning_frame(days=60)
        reference = self._synthetic_planning_frame(days=60)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.35

        forecast = forecast_long_horizon_model_profile(
            target,
            reference_frames=[reference],
            months=2,
            max_training_rows=300,
        )

        self.assertEqual(len(forecast), 2 * 30 * 48)
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "peak_risk_overlay_score",
                "is_peak_risk_overlay",
                "planning_method",
            }.issubset(forecast.columns)
        )
        self.assertEqual(set(forecast["planning_method"].unique()), {"direct_long_horizon_gradient_boosting"})
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["md_risk_envelope_kw"] == forecast["calibrated_p95_stress_kw"]).all())
        self.assertFalse(forecast["forecast_kw_import"].isna().any())
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())

    def test_long_horizon_model_falls_back_for_short_history(self) -> None:
        from trex_energy.forecasting import forecast_long_horizon_model_profile

        frame = self._synthetic_planning_frame(days=10)

        forecast = forecast_long_horizon_model_profile(frame, months=1)

        self.assertEqual(len(forecast), 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"recent_pattern_simulation"})
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())

    def test_correction_model_returns_monthly_planning_contract_without_fallback(self) -> None:
        from trex_energy.forecasting import forecast_corrected_long_horizon_profile

        target = self._synthetic_planning_frame(days=60)
        reference = self._synthetic_planning_frame(days=60)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.20

        forecast = forecast_corrected_long_horizon_profile(
            target,
            reference_frames=[reference],
            months=2,
            max_training_rows=300,
        )

        self.assertEqual(len(forecast), 2 * 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"baseline_correction_gradient_boosting"})
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "peak_risk_overlay_score",
                "is_peak_risk_overlay",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())

    def test_correction_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_corrected_long_horizon_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_corrected_long_horizon_profile(frame, months=1)

    def test_full_ml_planning_model_returns_monthly_planning_contract_without_fallback(self) -> None:
        from trex_energy.forecasting import forecast_full_ml_planning_profile

        target = self._synthetic_planning_frame(days=75)
        reference = self._synthetic_planning_frame(days=75)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.18

        forecast = forecast_full_ml_planning_profile(
            target,
            reference_frames=[reference],
            months=2,
            max_training_rows=240,
        )

        self.assertEqual(len(forecast), 2 * 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"full_ml_planning_gradient_boosting"})
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "peak_risk_overlay_score",
                "is_peak_risk_overlay",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["md_risk_envelope_kw"] == forecast["calibrated_p95_stress_kw"]).all())

    def test_full_ml_planning_model_changes_p50_path(self) -> None:
        from trex_energy.forecasting import forecast_full_ml_planning_profile, forecast_monthly_planning_profile

        target = self._synthetic_planning_frame(days=75)
        final_month = target["interval_end"] >= target["interval_end"].max() - pd.Timedelta(days=30)
        evening = target["interval_end"].dt.hour.between(18, 22)
        target.loc[final_month & evening, "kw_import"] += 55.0

        baseline = forecast_monthly_planning_profile(target, months=1)
        forecast = forecast_full_ml_planning_profile(target, months=1, max_training_rows=180)

        self.assertFalse(np.allclose(forecast["p50_forecast_kw"], baseline["p50_forecast_kw"]))

    def test_full_ml_planning_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_full_ml_planning_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_full_ml_planning_profile(frame, months=1)

    def test_gated_ml_planning_model_returns_monthly_planning_contract(self) -> None:
        from trex_energy.forecasting import forecast_gated_ml_planning_profile

        target = self._synthetic_planning_frame(days=75)
        reference = self._synthetic_planning_frame(days=75)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.16

        forecast = forecast_gated_ml_planning_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=240,
        )

        self.assertEqual(len(forecast), 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"gated_ml_planning_gradient_boosting"})
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "ml_p50_correction_confidence",
                "ml_p50_correction_applied",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())

    def test_gated_ml_planning_model_limits_p50_corrections_to_confident_intervals(self) -> None:
        from trex_energy.forecasting import forecast_gated_ml_planning_profile

        target = self._synthetic_planning_frame(days=75)
        final_month = target["interval_end"] >= target["interval_end"].max() - pd.Timedelta(days=30)
        evening = target["interval_end"].dt.hour.between(18, 22)
        target.loc[final_month & evening, "kw_import"] += 55.0

        forecast = forecast_gated_ml_planning_profile(target, months=1, max_training_rows=240)

        self.assertTrue((forecast["ml_p50_correction_confidence"] >= 0.0).all())
        self.assertTrue((forecast["ml_p50_correction_confidence"] <= 1.0).all())
        applied_count = int(forecast["ml_p50_correction_applied"].sum())
        self.assertGreater(applied_count, 0)
        self.assertLess(applied_count, len(forecast) // 2)

    def test_gated_ml_planning_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_gated_ml_planning_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_gated_ml_planning_profile(frame, months=1)

    def test_monthly_md_correction_model_returns_monthly_planning_contract(self) -> None:
        from trex_energy.forecasting import forecast_monthly_md_corrected_profile

        target = self._synthetic_planning_frame(days=75)
        reference = self._synthetic_planning_frame(days=75)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.18

        forecast = forecast_monthly_md_corrected_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=240,
        )

        self.assertEqual(len(forecast), 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"monthly_md_correction_gradient_boosting"})
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "ml_monthly_md_target_kw",
                "ml_monthly_md_correction_applied",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["md_risk_envelope_kw"] == forecast["calibrated_p95_stress_kw"]).all())

    def test_monthly_md_correction_model_changes_p50_monthly_md(self) -> None:
        from trex_energy.forecasting import forecast_monthly_md_corrected_profile, forecast_monthly_planning_profile

        target = self._synthetic_planning_frame(days=75)
        final_month = target["interval_end"] >= target["interval_end"].max() - pd.Timedelta(days=30)
        evening = target["interval_end"].dt.hour.between(18, 22)
        target.loc[final_month & evening, "kw_import"] += 75.0

        baseline = forecast_monthly_planning_profile(target, months=1)
        forecast = forecast_monthly_md_corrected_profile(target, months=1, max_training_rows=240)

        self.assertNotAlmostEqual(
            float(forecast["p50_forecast_kw"].max()),
            float(baseline["p50_forecast_kw"].max()),
        )
        self.assertGreater(int(forecast["ml_monthly_md_correction_applied"].sum()), 0)

    def test_monthly_md_correction_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_monthly_md_corrected_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_monthly_md_corrected_profile(frame, months=1)

    def test_md_ensemble_model_returns_monthly_planning_contract(self) -> None:
        from trex_energy.forecasting import forecast_md_ensemble_profile

        target = self._synthetic_planning_frame(days=75)
        reference = self._synthetic_planning_frame(days=75)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.18

        forecast = forecast_md_ensemble_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=240,
        )

        self.assertEqual(len(forecast), 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"md_ensemble_gradient_boosting"})
        self.assertTrue(
            {
                "forecast_kw_import",
                "p50_forecast_kw",
                "p90_md_risk_kw",
                "p95_stress_kw",
                "md_risk_envelope_kw",
                "ml_monthly_md_target_kw",
                "ml_monthly_md_correction_applied",
                "ml_p90_undercoverage_risk",
                "ml_p95_undercoverage_risk",
                "ml_md_peak_timing_score",
            }.issubset(forecast.columns)
        )
        self.assertTrue((forecast["forecast_kw_import"] >= 0.0).all())
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["md_risk_envelope_kw"] == forecast["calibrated_p95_stress_kw"]).all())

    def test_md_ensemble_model_combines_corrected_p50_with_ml_risk_envelopes(self) -> None:
        from trex_energy.forecasting import (
            MonthlyMDCorrectionPolicy,
            forecast_md_ensemble_profile,
            forecast_ml_md_risk_profile,
            forecast_monthly_md_corrected_profile,
            forecast_monthly_planning_profile,
        )

        target = self._synthetic_planning_frame(days=75)
        final_month = target["interval_end"] >= target["interval_end"].max() - pd.Timedelta(days=30)
        evening = target["interval_end"].dt.hour.between(18, 22)
        target.loc[final_month & evening, "kw_import"] += 75.0

        baseline = forecast_monthly_planning_profile(target, months=1)
        correction_policy = MonthlyMDCorrectionPolicy(p50_correction_strength=0.20)
        corrected = forecast_monthly_md_corrected_profile(
            target,
            months=1,
            max_training_rows=240,
            correction_policy=correction_policy,
        )
        risk = forecast_ml_md_risk_profile(target, months=1, max_training_rows=240)
        ensemble = forecast_md_ensemble_profile(
            target,
            months=1,
            max_training_rows=240,
            correction_policy=correction_policy,
        )

        self.assertNotAlmostEqual(
            float(ensemble["p50_forecast_kw"].max()),
            float(baseline["p50_forecast_kw"].max()),
        )
        pd.testing.assert_series_equal(
            ensemble["p50_forecast_kw"],
            corrected["p50_forecast_kw"],
            check_names=False,
        )
        pd.testing.assert_series_equal(
            ensemble["forecast_kw_import"],
            corrected["forecast_kw_import"],
            check_names=False,
        )
        self.assertGreaterEqual(
            float(ensemble["p90_md_risk_kw"].max()),
            float(risk["p90_md_risk_kw"].max()),
        )
        self.assertGreaterEqual(
            float(ensemble["p95_stress_kw"].max()),
            float(risk["p95_stress_kw"].max()),
        )

    def test_md_ensemble_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_md_ensemble_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_md_ensemble_profile(frame, months=1)

    def test_ml_md_risk_model_preserves_p50_forecast_path(self) -> None:
        from trex_energy.forecasting import (
            _localized_risk_envelope,
            forecast_ml_md_risk_profile,
            forecast_monthly_planning_profile,
        )

        target = self._synthetic_planning_frame(days=60)
        reference = self._synthetic_planning_frame(days=60)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.20

        baseline = forecast_monthly_planning_profile(target, months=1)
        forecast = forecast_ml_md_risk_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=300,
        )

        self.assertEqual(len(forecast), 30 * 48)
        self.assertEqual(set(forecast["planning_method"].unique()), {"ml_md_risk_gradient_boosting"})
        pd.testing.assert_series_equal(
            forecast["forecast_kw_import"],
            baseline["forecast_kw_import"],
            check_names=False,
        )
        pd.testing.assert_series_equal(
            forecast["p50_forecast_kw"],
            baseline["p50_forecast_kw"],
            check_names=False,
        )
        self.assertTrue((forecast["p90_md_risk_kw"] >= forecast["p50_forecast_kw"]).all())
        self.assertTrue((forecast["p95_stress_kw"] >= forecast["p90_md_risk_kw"]).all())
        self.assertTrue((forecast["md_risk_envelope_kw"] == forecast["calibrated_p95_stress_kw"]).all())

    def test_ml_md_risk_model_adds_gated_undercoverage_scores(self) -> None:
        from trex_energy.forecasting import forecast_ml_md_risk_profile

        target = self._synthetic_planning_frame(days=60)
        reference = self._synthetic_planning_frame(days=60)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.20

        forecast = forecast_ml_md_risk_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=300,
        )

        self.assertIn("ml_p90_undercoverage_risk", forecast.columns)
        self.assertIn("ml_p95_undercoverage_risk", forecast.columns)
        self.assertTrue((forecast["ml_p90_undercoverage_risk"] >= 0.0).all())
        self.assertTrue((forecast["ml_p90_undercoverage_risk"] <= 1.0).all())
        self.assertTrue((forecast["ml_p95_undercoverage_risk"] >= 0.0).all())
        self.assertTrue((forecast["ml_p95_undercoverage_risk"] <= 1.0).all())

    def test_ml_md_risk_model_adds_peak_timing_localization(self) -> None:
        from trex_energy.forecasting import (
            MdRiskUpliftPolicy,
            _localized_risk_envelope,
            forecast_ml_md_risk_profile,
            forecast_monthly_planning_profile,
        )

        target = self._synthetic_planning_frame(days=60)
        reference = self._synthetic_planning_frame(days=60)
        reference["site_id"] = "reference_site"
        reference["kw_import"] = reference["kw_import"] * 1.20

        baseline = forecast_monthly_planning_profile(target, months=1)
        forecast = forecast_ml_md_risk_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=300,
        )

        self.assertIn("ml_md_peak_timing_score", forecast.columns)
        self.assertTrue((forecast["ml_md_peak_timing_score"] >= 0.0).all())
        self.assertTrue((forecast["ml_md_peak_timing_score"] <= 1.0).all())
        pd.testing.assert_series_equal(
            forecast["forecast_kw_import"],
            baseline["forecast_kw_import"],
            check_names=False,
        )
        localized = _localized_risk_envelope(
            pd.Series([100.0] * 10),
            target_md_kw=150.0,
            timing_scores=pd.Series([0.1, 0.2, 0.1, 0.3, 0.2, 0.95, 0.8, 0.1, 0.2, 0.1]),
        )
        changed = (localized - 100.0).abs() > 1.0e-9
        self.assertGreater(int(changed.sum()), 0)
        self.assertLess(int(changed.sum()), len(localized))
        self.assertGreaterEqual(float(localized.max()), 150.0)

        tighter = forecast_ml_md_risk_profile(
            target,
            reference_frames=[reference],
            months=1,
            max_training_rows=300,
            uplift_policy=MdRiskUpliftPolicy(
                p90_max_ratio=1.01,
                p95_max_ratio=1.01,
                low_risk_max_ratio=1.0,
                timing_active_quantile=0.90,
            ),
        )
        self.assertLessEqual(
            float(tighter["p95_stress_kw"].max()),
            float(forecast["p95_stress_kw"].max()),
        )

    def test_md_risk_features_include_recent_peak_regime_signals(self) -> None:
        from trex_energy.forecasting import _md_risk_model_features, forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=60)
        evening = frame["interval_end"].dt.hour.between(19, 20)
        frame.loc[evening.tail(14 * 48).index.intersection(frame.index[evening]), "kw_import"] += 100.0
        baseline = forecast_monthly_planning_profile(frame, months=1)

        features = _md_risk_model_features(frame, baseline)

        expected = {
            "recent_peak_hour",
            "recent_peak_is_daylight",
            "recent_peak_is_weekend",
            "recent_peak_slot_concentration",
            "recent_7d_max_to_28d_max_ratio",
            "non_solar_night_peak_indicator",
            "solar_daylight_peak_interaction",
        }
        self.assertTrue(expected.issubset(features.keys()))
        for key in expected:
            self.assertTrue(np.isfinite(features[key]))

    def test_ml_md_risk_model_requires_enough_history(self) -> None:
        from trex_energy.forecasting import forecast_ml_md_risk_profile

        frame = self._synthetic_planning_frame(days=12)

        with self.assertRaisesRegex(ValueError, "Not enough history"):
            forecast_ml_md_risk_profile(frame, months=1)

    def test_non_solar_late_night_peak_floor_is_gated_to_night_risk_windows(self) -> None:
        from trex_energy.forecasting import forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=35)
        frame["kw_import"] = 90.0
        night_spike = frame["interval_end"].between(
            pd.Timestamp("2025-02-03 23:00:00"),
            pd.Timestamp("2025-02-03 23:30:00"),
        )
        frame.loc[night_spike, "kw_import"] = 260.0

        forecast = forecast_monthly_planning_profile(frame, months=1)

        self.assertIn("late_night_peak_floor_applied", forecast.columns)
        floor_rows = forecast[forecast["late_night_peak_floor_applied"]]
        self.assertGreater(len(floor_rows), 0)
        floor_hours = floor_rows["interval_end"].dt.hour
        self.assertTrue(((floor_hours >= 18) | (floor_hours < 6)).all())
        self.assertGreaterEqual(float(floor_rows["calibrated_p95_stress_kw"].max()), 260.0)
        pd.testing.assert_series_equal(
            forecast["forecast_kw_import"],
            forecast["p50_forecast_kw"],
            check_names=False,
        )

    def test_monthly_planning_calibrated_p95_uses_recent_observed_md_floor(self) -> None:
        from trex_energy.forecasting import forecast_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=35)
        recent_peak = float(frame["kw_import"].max())

        forecast = forecast_monthly_planning_profile(frame, months=1, md_floor_multiplier=1.03)

        self.assertGreaterEqual(float(forecast["calibrated_p95_stress_kw"].max()), recent_peak * 1.03)
        self.assertGreaterEqual(float(forecast["md_risk_envelope_kw"].max()), recent_peak * 1.03)

    def test_monthly_planning_backtest_reports_md_errors_and_coverage(self) -> None:
        from trex_energy.forecasting import backtest_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=75)
        final_month = frame["interval_end"] >= frame["interval_end"].max() - pd.Timedelta(days=30)
        evening = frame["interval_end"].dt.hour.between(19, 20)
        frame.loc[final_month & evening, "kw_import"] += 80.0

        result = backtest_monthly_planning_profile(frame, train_days=45, horizon_days=30, step_days=15)

        self.assertGreaterEqual(result.metrics["folds"], 1)
        self.assertTrue(
            {
                "actual_md_kw",
                "p50_md_kw",
                "p90_md_kw",
                "p95_md_kw",
                "calibrated_p90_md_kw",
                "calibrated_p95_md_kw",
                "p90_coverage",
                "p95_coverage",
            }.issubset(result.predictions.columns)
        )
        self.assertTrue(
            {
                "p50_md_abs_error_kw",
                "p90_md_abs_error_kw",
                "p95_md_abs_error_kw",
                "p90_coverage_pct",
                "p95_coverage_pct",
            }.issubset(result.metrics)
        )
        self.assertGreaterEqual(result.metrics["p95_coverage_pct"], result.metrics["p90_coverage_pct"])

    def test_monthly_planning_backtest_default_supports_two_month_files(self) -> None:
        from trex_energy.forecasting import backtest_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=60)

        result = backtest_monthly_planning_profile(frame)

        self.assertGreaterEqual(result.metrics["folds"], 1)

    def test_monthly_md_risk_calibrator_raises_undercovered_envelope(self) -> None:
        from trex_energy.forecasting import (
            apply_monthly_md_risk_calibration,
            fit_monthly_md_risk_calibrator,
            forecast_monthly_planning_profile,
        )

        frame = self._synthetic_planning_frame(days=75)
        final_month = frame["interval_end"] >= frame["interval_end"].max() - pd.Timedelta(days=30)
        evening = frame["interval_end"].dt.hour.between(19, 20)
        frame.loc[final_month & evening, "kw_import"] += 220.0

        raw_forecast = forecast_monthly_planning_profile(frame.iloc[:-30 * 48].copy(), months=1)
        calibrator = fit_monthly_md_risk_calibrator(
            frame,
            train_days=45,
            horizon_days=30,
            step_days=15,
        )
        calibrated = apply_monthly_md_risk_calibration(raw_forecast, calibrator)

        self.assertGreaterEqual(calibrator.uplift_factor, 1.0)
        self.assertGreaterEqual(calibrator.training_folds, 1)
        self.assertGreaterEqual(
            float(calibrated["md_risk_envelope_kw"].max()),
            float(raw_forecast["md_risk_envelope_kw"].max()),
        )
        self.assertEqual(
            set(calibrated["md_risk_calibration_method"].unique()),
            {"trained_monthly_md_risk_calibrator"},
        )

    def test_monthly_md_risk_calibrator_does_not_lower_already_conservative_envelope(self) -> None:
        from trex_energy.forecasting import (
            MonthlyMDRiskCalibrator,
            apply_monthly_md_risk_calibration,
            forecast_monthly_planning_profile,
        )

        frame = self._synthetic_planning_frame(days=35)
        raw_forecast = forecast_monthly_planning_profile(frame, months=1)
        neutral_calibrator = MonthlyMDRiskCalibrator(
            uplift_factor=1.0,
            intercept_kw=0.0,
            training_folds=2,
            coverage_before_pct=100.0,
            coverage_after_pct=100.0,
        )

        calibrated = apply_monthly_md_risk_calibration(raw_forecast, neutral_calibrator)

        pd.testing.assert_series_equal(
            calibrated["md_risk_envelope_kw"],
            raw_forecast["md_risk_envelope_kw"],
            check_names=False,
        )
        self.assertIn("md_risk_calibration_uplift_factor", calibrated.columns)

    def test_md_stress_windows_report_7_and_14_day_scores(self) -> None:
        from trex_energy.forecasting import backtest_md_stress_windows

        frame = self._synthetic_planning_frame(days=70)
        final_weeks = frame["interval_end"] >= frame["interval_end"].max() - pd.Timedelta(days=14)
        evening = frame["interval_end"].dt.hour.between(19, 20)
        frame.loc[final_weeks & evening, "kw_import"] += 60.0

        scores = backtest_md_stress_windows(
            frame,
            window_days=(7, 14),
            train_days=21,
            step_days=7,
            max_folds=6,
        )

        self.assertEqual(scores["window_days"].tolist(), [7, 14])
        self.assertTrue(
            {
                "folds",
                "p50_md_abs_error_kw",
                "p90_md_abs_error_kw",
                "p95_md_abs_error_kw",
                "p90_md_bias_kw",
                "p95_md_bias_kw",
                "p90_coverage_pct",
                "p95_coverage_pct",
                "validation_type",
            }.issubset(scores.columns)
        )
        self.assertEqual(set(scores["validation_type"].unique()), {"rolling_stress_window"})
        self.assertTrue((scores["folds"] >= 1).all())

    def test_monthly_backtest_accepts_planner_calibration_parameters(self) -> None:
        from trex_energy.forecasting import backtest_monthly_planning_profile

        frame = self._synthetic_planning_frame(days=70)

        result = backtest_monthly_planning_profile(
            frame,
            train_days=21,
            horizon_days=14,
            step_days=7,
            max_folds=3,
            recent_days=21,
            p90_floor_multiplier=1.08,
        )

        self.assertTrue({"recent_days", "p90_floor_multiplier"}.issubset(result.predictions.columns))
        self.assertEqual(set(result.predictions["recent_days"].unique()), {21})
        self.assertEqual(set(result.predictions["p90_floor_multiplier"].unique()), {1.08})

    def test_adaptive_p90_calibration_returns_candidate_scores_and_best_config(self) -> None:
        from trex_energy.forecasting import (
            evaluate_p90_calibration_candidates,
            fit_adaptive_p90_calibration,
        )

        frame = self._synthetic_planning_frame(days=70)
        final_weeks = frame["interval_end"] >= frame["interval_end"].max() - pd.Timedelta(days=14)
        evening = frame["interval_end"].dt.hour.between(19, 20)
        frame.loc[final_weeks & evening, "kw_import"] += 60.0

        candidates = evaluate_p90_calibration_candidates(
            frame,
            recent_days_options=(21, 28),
            p90_floor_multipliers=(1.0, 1.05),
            stress_window_days=(7, 14),
            train_days=21,
            step_days=7,
            max_folds=4,
            target_coverage_pct=90.0,
        )
        best = fit_adaptive_p90_calibration(
            frame,
            recent_days_options=(21, 28),
            p90_floor_multipliers=(1.0, 1.05),
            stress_window_days=(7, 14),
            train_days=21,
            step_days=7,
            max_folds=4,
            target_coverage_pct=90.0,
        )

        self.assertEqual(len(candidates), 4)
        self.assertTrue(
            {
                "recent_days",
                "p90_floor_multiplier",
                "stress_coverage_pct",
                "stress_md_abs_error_kw",
                "stress_bias_kw",
                "score",
            }.issubset(candidates.columns)
        )
        self.assertIn(best.recent_days, {21, 28})
        self.assertIn(best.p90_floor_multiplier, {1.0, 1.05})
        self.assertGreaterEqual(best.stress_folds, 1)
        self.assertGreaterEqual(best.stress_coverage_pct, 0.0)
        self.assertGreaterEqual(best.stress_md_abs_error_kw, 0.0)

    def test_adaptive_p90_forecast_annotates_selected_calibration(self) -> None:
        from trex_energy.forecasting import forecast_adaptive_p90_planning_profile

        frame = self._synthetic_planning_frame(days=70)

        forecast = forecast_adaptive_p90_planning_profile(
            frame,
            months=1,
            recent_days_options=(21, 28),
            p90_floor_multipliers=(1.0, 1.05),
            max_folds=4,
        )

        self.assertEqual(len(forecast), 1440)
        self.assertIn("adaptive_p90_recent_days", forecast.columns)
        self.assertIn("adaptive_p90_floor_multiplier", forecast.columns)
        self.assertIn("adaptive_p90_stress_coverage_pct", forecast.columns)
        self.assertTrue((forecast["calibrated_p90_md_risk_kw"] >= forecast["p90_md_risk_kw"]).all())


if __name__ == "__main__":
    unittest.main()
