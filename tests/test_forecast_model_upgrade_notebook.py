from __future__ import annotations

import json
from functools import lru_cache
import importlib
from pathlib import Path
import sys
from types import ModuleType
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "model_upgrade_inspection" / "forecast_model_upgrade_inspection.ipynb"


def _cell_source(cell: dict[str, object]) -> str:
    return "".join(cell.get("source", []))


@lru_cache(maxsize=1)
def load_notebook_namespace() -> dict[str, object]:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    module_name = "forecast_model_upgrade_notebook_tests"
    module = ModuleType(module_name)
    sys.modules[module_name] = module
    namespace = module.__dict__

    for idx in [2, 3, 4, 6, 7, 8, 12]:
        source = _cell_source(notebook["cells"][idx])
        if idx == 6 and "sample_site_id =" in source:
            source = source.split("sample_site_id =", maxsplit=1)[0]
        if idx == 12 and "rolling_rows = []" in source:
            source = source.split("rolling_rows = []", maxsplit=1)[0]
        exec(compile(source, f"{NOTEBOOK.name}#cell{idx}", "exec"), namespace)

    return namespace


class ForecastModelUpgradeNotebookTests(unittest.TestCase):
    def test_notebook_adds_48_hour_non_sol_comparison_view(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        loso_source = _cell_source(notebook["cells"][11])
        plot_source = _cell_source(notebook["cells"][15])

        self.assertIn("COMPARISON_HORIZON = 96", loso_source)
        self.assertIn('comparison_sites = [site for site in sorted(best_predictions.keys())', plot_source)
        self.assertIn('Enhanced LOSO Forecast (48 Hours)', plot_source)

    def test_notebook_reports_baseline_comparison_tables_and_normalized_metrics(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        import_source = _cell_source(notebook["cells"][8])
        settings_source = _cell_source(notebook["cells"][9])
        loso_source = _cell_source(notebook["cells"][11])
        rolling_source = _cell_source(notebook["cells"][12])
        summary_source = _cell_source(notebook["cells"][13])

        self.assertIn("evaluate_forecast = forecast_support.evaluate_forecast", import_source)
        self.assertIn("evaluate_forecast_components = forecast_support.evaluate_forecast_components", import_source)
        self.assertIn("fit_horizon_residual_adjustment = forecast_support.fit_horizon_residual_adjustment", import_source)
        self.assertIn("summarize_model_metrics = forecast_support.summarize_model_metrics", import_source)
        self.assertIn("ridge_only", loso_source)
        self.assertIn("seasonal", loso_source)
        self.assertIn("wape_pct", rolling_source)
        self.assertIn("LOSO model comparison", summary_source)
        self.assertIn("Rolling model comparison", summary_source)

    def test_notebook_declares_peak_priority_candidate_and_metrics(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        import_source = _cell_source(notebook["cells"][8])
        settings_source = _cell_source(notebook["cells"][9])
        loso_source = _cell_source(notebook["cells"][11])
        rolling_source = _cell_source(notebook["cells"][12])
        summary_source = _cell_source(notebook["cells"][13])

        self.assertIn("fit_peak_risk_overlay = forecast_support.fit_peak_risk_overlay", import_source)
        self.assertIn("apply_peak_risk_overlay = forecast_support.apply_peak_risk_overlay", import_source)
        self.assertIn("enhanced_peak_priority", loso_source)
        self.assertIn("enhanced_peak_priority", rolling_source)
        self.assertIn("PEAK_ALERT_QUANTILE = 0.80", settings_source)
        self.assertIn("PEAK_MATCH_WINDOW = 2", settings_source)
        self.assertIn("overlay_alert_quantile=PEAK_ALERT_QUANTILE", loso_source)
        self.assertIn("peak_match_window=PEAK_MATCH_WINDOW", rolling_source)
        self.assertIn("peak_f1", summary_source)
        self.assertIn("md_peak_rank", summary_source)
        self.assertIn("peak_false_negative_count", summary_source)

    def test_notebook_wires_peak_alert_policy_comparison(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("PeakAlertPolicy = forecast_support.PeakAlertPolicy", all_source)
        self.assertIn("compare_peak_alert_policies = forecast_support.compare_peak_alert_policies", all_source)
        self.assertIn("PEAK_ALERT_POLICIES", all_source)
        self.assertIn("peak_policy_rows", all_source)

    def test_notebook_wires_diagnostics_confirmation_and_episode_candidates(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("summarize_rolling_error_diagnostics = forecast_support.summarize_rolling_error_diagnostics", all_source)
        self.assertIn("confirm_peak_alerts = forecast_support.confirm_peak_alerts", all_source)
        self.assertIn("rank_alert_episodes = forecast_support.rank_alert_episodes", all_source)
        self.assertIn("enhanced_peak_confirmed", all_source)
        self.assertIn("rolling_error_diagnostics", all_source)
        self.assertIn("alert_episode_rows", all_source)

    def test_notebook_wires_late_horizon_peak_uplift_candidate(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("LateHorizonPeakEnvelope = forecast_support.LateHorizonPeakEnvelope", all_source)
        self.assertIn("fit_late_horizon_peak_envelope = forecast_support.fit_late_horizon_peak_envelope", all_source)
        self.assertIn("apply_late_horizon_peak_uplift = forecast_support.apply_late_horizon_peak_uplift", all_source)
        self.assertIn(
            "summarize_rolling_candidate_error_diagnostics = forecast_support.summarize_rolling_candidate_error_diagnostics",
            all_source,
        )
        self.assertIn("LATE_PEAK_UPLIFT_START_STEP = 33", all_source)
        self.assertIn("enhanced_late_peak_uplift", all_source)
        self.assertIn("rolling_candidate_error_diagnostics", all_source)

    def test_notebook_wires_direct_horizon_boosted_candidate(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("fit_direct_horizon_boosted_model = forecast_support.fit_direct_horizon_boosted_model", all_source)
        self.assertIn(
            "forecast_with_direct_horizon_boosted_model = forecast_support.forecast_with_direct_horizon_boosted_model",
            all_source,
        )
        self.assertIn("direct_hgb", all_source)

    def test_notebook_wires_lightgbm_quantile_md_candidate(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn(
            "fit_direct_horizon_lightgbm_quantile_model = forecast_support.fit_direct_horizon_lightgbm_quantile_model",
            all_source,
        )
        self.assertIn(
            "forecast_with_direct_horizon_lightgbm_quantile_model = forecast_support.forecast_with_direct_horizon_lightgbm_quantile_model",
            all_source,
        )
        self.assertIn("direct_lgbm_quantile_p50", all_source)
        self.assertIn("direct_lgbm_quantile_p90", all_source)
        self.assertIn("direct_lgbm_md_risk", all_source)

    def test_notebook_caps_lightgbm_quantile_smoke_candidate_runtime(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("DIRECT_LGBM_N_ESTIMATORS = 10", all_source)
        self.assertIn("DIRECT_LGBM_RECENT_ROWS = 1200", all_source)
        self.assertIn("direct_lgbm_train_frames = [train_frame.tail(DIRECT_LGBM_RECENT_ROWS).copy()]", all_source)

    def test_esum_notebook_is_reference_only_not_active_source_of_truth(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        all_source = "\n".join(_cell_source(cell) for cell in notebook["cells"])

        self.assertIn("ESUM_T_Rex_Model_Building", all_source)
        self.assertIn("reference only", all_source.lower())
        self.assertNotIn("ESUM_T_Rex_Model_Building.ipynb\",", all_source)

    def test_notebook_defaults_to_global_training_and_declares_experiment_variants(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        import_source = _cell_source(notebook["cells"][8])

        self.assertIn("ENABLE_SEGMENTED_TRAINING = False", import_source)
        self.assertIn("SEGMENTED_MIN_SITES_PER_SEGMENT = 2", import_source)
        self.assertIn("EXPERIMENT_VARIANTS", import_source)
        self.assertIn("global_regime_current", import_source)
        self.assertIn("global_regime_softened", import_source)
        self.assertIn("seasonal_anchor_baseline", import_source)

    def test_rolling_loop_uses_softened_solar_variant_and_single_blend_search(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        rolling_source = _cell_source(notebook["cells"][12])

        self.assertIn('active_variant = variant_bundle(settings, "B" if site_has_solar else "A")', rolling_source)
        self.assertIn(
            'pooled_train_frames = [train_frame, *[clean_datasets[other_site] for other_site in site_ids if other_site != site_id]]',
            rolling_source,
        )
        self.assertIn("blend_weight, _ = select_blend_weight(", rolling_source)
        self.assertIn('blend_weight=blend_weight,', rolling_source)
        self.assertNotIn("regime_blend_weight, _ = select_regime_blend_weight(", rolling_source)
        self.assertNotIn('blend_weight=regime_blend_weight,', rolling_source)
        self.assertNotIn("residual_correction = fit_horizon_residual_adjustment(", rolling_source)
        self.assertNotIn("residual_correction=residual_correction,", rolling_source)

    def test_loso_loop_uses_target_solar_flag_without_stale_notebook_state(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        loso_source = _cell_source(notebook["cells"][11])

        self.assertIn('target_has_solar = bool(full_target["has_solar"].iloc[0])', loso_source)
        self.assertIn('active_variant = variant_bundle(settings, "B" if target_has_solar else "A")', loso_source)
        self.assertNotIn('active_variant = variant_bundle(settings, "B" if site_has_solar else "A")', loso_source)
        self.assertNotIn("residual_correction = fit_horizon_residual_adjustment(", loso_source)
        self.assertNotIn("comparison_residual_correction = fit_horizon_residual_adjustment(", loso_source)

    def test_latest_fold_variant_comparison_uses_pooled_training_frames(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        variant_source = _cell_source(notebook["cells"][17])

        self.assertIn(
            'pooled_train_frames = [train_frame, *[clean_datasets[other_site] for other_site in site_ids if other_site != site_id]]',
            variant_source,
        )
        self.assertNotIn('[train_frame]', variant_source)
        self.assertNotIn("residual_correction = fit_horizon_residual_adjustment(", variant_source)

    def test_support_import_cell_reloads_stale_module_state(self) -> None:
        notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
        source = _cell_source(notebook["cells"][8])

        from notebooks.model_upgrade_inspection import forecast_model_upgrade_support as forecast_support

        original_site_evaluation_settings = forecast_support.site_evaluation_settings
        original_summarize_prediction_errors = forecast_support.summarize_prediction_errors
        delattr(forecast_support, "site_evaluation_settings")
        delattr(forecast_support, "summarize_prediction_errors")

        namespace: dict[str, object] = {}
        try:
            exec(compile(source, f"{NOTEBOOK.name}#cell8", "exec"), namespace)
            self.assertIs(namespace["fit_global_enhanced_ridge"], forecast_support.fit_global_enhanced_ridge)
            self.assertIs(namespace["site_evaluation_settings"], forecast_support.site_evaluation_settings)
            self.assertIs(namespace["summarize_prediction_errors"], forecast_support.summarize_prediction_errors)
            self.assertIs(namespace["should_use_segmented_training"], forecast_support.should_use_segmented_training)
        finally:
            importlib.reload(forecast_support)

    def test_enhanced_features_include_weekly_memory_and_regime_columns(self) -> None:
        namespace = load_notebook_namespace()
        add_enhanced_features = namespace["add_enhanced_features"]
        frame = next(iter(namespace["clean_datasets"].values()))

        prepared, feature_columns = add_enhanced_features(frame)

        self.assertFalse(prepared.empty)
        expected_columns = {
            "lag_336",
            "lag_672",
            "is_monday",
            "is_post_weekend",
            "weekday_daylight",
            "same_slot_prev_week_delta",
        }
        self.assertTrue(expected_columns.issubset(feature_columns))
        self.assertTrue(expected_columns.issubset(prepared.columns))

    def test_seasonal_anchor_prediction_prefers_previous_week_for_monday_daylight(self) -> None:
        namespace = load_notebook_namespace()
        self.assertIn("seasonal_anchor_prediction", namespace)

        history = [20.0] * 700
        history[-48] = 100.0
        history[-336] = 500.0
        history[-672] = 450.0

        anchor = namespace["seasonal_anchor_prediction"](
            history=history,
            next_end=pd.Timestamp("2026-03-16 12:00:00"),
        )

        self.assertAlmostEqual(anchor, 420.0, places=6)

    def test_build_cutoffs_defaults_to_daily_spacing(self) -> None:
        namespace = load_notebook_namespace()
        cutoffs = namespace["build_cutoffs"](frame_length=48 * 40, horizon=48)

        self.assertGreaterEqual(len(cutoffs), 10)
        self.assertTrue(all((right - left) == 48 for left, right in zip(cutoffs, cutoffs[1:])))


if __name__ == "__main__":
    unittest.main()
