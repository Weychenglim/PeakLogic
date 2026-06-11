from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = [
    ROOT / "1. Load Profile (With Solar Installed) SoL.xlsx",
    ROOT / "2. Load Profile (No Solar) E.xlsx",
    ROOT / "3. Load Profile (No Solar) SuN.xlsx",
    ROOT / "4. Load Profile (With Solar) Mi2.xlsx",
]


class ReportingTests(unittest.TestCase):
    def test_site_comparison_summary_contains_each_current_dataset(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook
        from trex_energy.optimization import evaluate_site_scenarios
        from trex_energy.reporting import build_site_comparison_summary

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        site_results = []
        for frame in frames:
            forecast = forecast_next_intervals(frames=frames, target_frame=frame, horizon=48)
            optimization = evaluate_site_scenarios(forecast)
            site_results.append((frame, forecast, optimization))

        summary = build_site_comparison_summary(site_results)

        self.assertEqual(len(summary), 4)
        self.assertTrue(
            {
                "site_id",
                "has_solar",
                "baseline_md_kw",
                "optimized_md_kw",
                "savings_rm",
                "best_scenario_id",
            }.issubset(summary.columns)
        )

    def test_export_payloads_return_non_empty_csv_bytes(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook
        from trex_energy.optimization import evaluate_site_scenarios
        from trex_energy.reporting import dataframe_to_csv_bytes

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        forecast = forecast_next_intervals(frames=frames, target_frame=frames[0], horizon=48)
        optimization = evaluate_site_scenarios(forecast)

        payload = dataframe_to_csv_bytes(optimization.scenario_summary)

        self.assertGreater(len(payload), 20)
        self.assertIn(b"scenario_id", payload)

    def test_optimization_explanation_is_judge_facing(self) -> None:
        import pandas as pd

        from trex_energy.reporting import build_optimization_explanation

        best = {
            "risk_basis": "p95",
            "bill_before_rm": 10000.0,
            "bill_after_rm": 7600.0,
            "savings_rm": 2400.0,
            "md_before": 500.0,
            "md_after": 420.0,
            "battery_kw": 100.0,
            "battery_kwh": 200.0,
            "solar_kwp": 50.0,
            "payback_months": 24.0,
        }
        assumptions = {"planning_months": 1, "growth_rate_pct": 0.0, "ev_load_kw": 0.0}
        validation = {"row_count": 2880, "gap_count": 0, "missing_value_count": 0}
        sensitivity = pd.DataFrame(
            [
                {"sensitivity_id": "base", "savings_rm": 2400.0, "payback_months": 24.0},
                {"sensitivity_id": "battery_capex_plus_10", "savings_rm": 2400.0, "payback_months": 26.4},
            ]
        )

        explanation = build_optimization_explanation("planning_site", best, assumptions, validation, sensitivity)

        self.assertEqual(explanation["planning_basis_label"], "Conservative peak-demand planning")
        self.assertIn("what_changed", explanation)
        self.assertIn("why_this_scenario", explanation)
        self.assertIn("savings_sensitivity", explanation)
        self.assertIn("confidence_flags", explanation)
        self.assertTrue(any(flag["level"] == "ok" for flag in explanation["confidence_flags"]))

    def test_decision_explainability_uses_model_outputs(self) -> None:
        import pandas as pd

        from trex_energy.reporting import build_decision_explainability

        forecast = pd.DataFrame(
            [
                {
                    "interval_end": pd.Timestamp("2026-03-03 12:30:00"),
                    "forecast_kw_import": 250.0,
                    "md_risk_envelope_kw": 280.0,
                    "is_peak_risk_overlay": True,
                    "estimated_existing_solar_kw": 0.0,
                },
                {
                    "interval_end": pd.Timestamp("2026-03-03 20:00:00"),
                    "forecast_kw_import": 90.0,
                    "md_risk_envelope_kw": 170.0,
                    "is_peak_risk_overlay": False,
                    "estimated_existing_solar_kw": 0.0,
                },
            ]
        )
        best = {
            "scenario_id": "battery_solar",
            "risk_basis": "p95",
            "md_before": 500.0,
            "md_after": 420.0,
            "peak_reduction_pct": 16.0,
            "battery_kw": 100.0,
            "battery_kwh": 200.0,
            "solar_kwp": 50.0,
            "annual_savings_rm": 36000.0,
            "capex_rm": 280000.0,
            "payback_months": 93.3,
        }
        assumptions = {"planning_months": 1, "md_rate_rm_per_kw": 97.06}
        sensitivity = pd.DataFrame(
            [
                {"sensitivity_id": "base", "annual_savings_rm": 36000.0},
                {"sensitivity_id": "md_rate_plus_10", "annual_savings_rm": 39000.0},
                {"sensitivity_id": "solar_capex_plus_10", "annual_savings_rm": 35000.0},
            ]
        )

        explainability = build_decision_explainability(forecast, best, assumptions, sensitivity)

        self.assertIn("headline", explainability)
        self.assertIn("drivers", explainability)
        self.assertIn("model_factors", explainability)
        self.assertEqual(len(explainability["drivers"]), 3)
        self.assertTrue(any("Mar 3" in item["detail"] for item in explainability["drivers"]))
        self.assertTrue(any("100 kW" in item["value"] for item in explainability["drivers"]))
        self.assertTrue(any("solar" in factor.lower() for factor in explainability["model_factors"]))
        self.assertNotIn("external LLM", explainability["summary"])
        self.assertNotIn("API key", explainability["summary"])


if __name__ == "__main__":
    unittest.main()
