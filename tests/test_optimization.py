from pathlib import Path
import math
import unittest

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = [
    ROOT / "1. Load Profile (With Solar Installed) SoL.xlsx",
    ROOT / "2. Load Profile (No Solar) E.xlsx",
    ROOT / "3. Load Profile (No Solar) SuN.xlsx",
    ROOT / "4. Load Profile (With Solar) Mi2.xlsx",
]


class TariffTests(unittest.TestCase):
    def test_bill_calculation_separates_md_and_energy_charges(self) -> None:
        from trex_energy.tariff import TariffConfig, calculate_bill_components

        frame = pd.DataFrame(
            {
                "interval_start": [pd.Timestamp("2025-01-01 00:00:00"), pd.Timestamp("2025-01-01 00:30:00")],
                "interval_end": [pd.Timestamp("2025-01-01 00:30:00"), pd.Timestamp("2025-01-01 01:00:00")],
                "kw_import": [100.0, 200.0],
            }
        )
        config = TariffConfig(md_rate_rm_per_kw=10.0, offpeak_energy_rate_rm_per_kwh=0.5, peak_energy_rate_rm_per_kwh=1.0)

        bill = calculate_bill_components(frame, config)

        self.assertAlmostEqual(bill.md_kw, 200.0)
        self.assertAlmostEqual(bill.md_cost_rm, 2000.0)
        self.assertAlmostEqual(bill.energy_kwh, 150.0)
        self.assertGreater(bill.total_cost_rm, bill.md_cost_rm)

    def test_bill_calculation_charges_md_once_per_planning_month(self) -> None:
        from trex_energy.tariff import TariffConfig, calculate_bill_components

        frame = pd.DataFrame(
            {
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=4, freq="30min"),
                "kw_import": [100.0, 300.0, 200.0, 500.0],
            }
        )
        config = TariffConfig(
            md_rate_rm_per_kw=10.0,
            offpeak_energy_rate_rm_per_kwh=0.0,
            peak_energy_rate_rm_per_kwh=0.0,
            md_period_intervals=2,
        )

        bill = calculate_bill_components(frame, config)

        self.assertAlmostEqual(bill.md_kw, 500.0)
        self.assertAlmostEqual(bill.md_cost_rm, 8000.0)


class OptimizationTests(unittest.TestCase):
    def test_scenario_search_returns_best_savings_candidate(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        target_frame = frames[0]
        forecast = forecast_next_intervals(frames=frames, target_frame=target_frame, horizon=48)

        config = OptimizationConfig(
            flexible_load_fraction=0.15,
            shift_window_intervals=4,
            battery_kw_options=[0.0, 100.0],
            battery_kwh_options=[0.0, 200.0],
            solar_kwp_options=[0.0, 100.0],
        )
        result = evaluate_site_scenarios(forecast, config)

        self.assertGreaterEqual(len(result.scenario_summary), 3)
        self.assertIn("savings_rm", result.scenario_summary.columns)
        self.assertIn("payback_months", result.scenario_summary.columns)
        self.assertLessEqual(result.best_scenario["bill_after_rm"], result.best_scenario["bill_before_rm"])
        self.assertLessEqual(result.best_scenario["md_after"], result.best_scenario["md_before"])

    def test_optimized_profile_stays_non_negative(self) -> None:
        from trex_energy.forecasting import forecast_next_intervals
        from trex_energy.ingestion import load_site_workbook
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios

        frames = [load_site_workbook(path)[0] for path in DATA_FILES]
        forecast = forecast_next_intervals(frames=frames, target_frame=frames[1], horizon=48)
        result = evaluate_site_scenarios(forecast, OptimizationConfig())

        self.assertTrue((result.optimized_schedule["optimized_kw_import"] >= 0).all())
        self.assertTrue((result.optimized_schedule["battery_discharge_kw"] >= 0).all())
        self.assertTrue((result.optimized_schedule["solar_offset_kw"] >= 0).all())

    def test_clear_sky_solar_profile_uses_sine_curve(self) -> None:
        from trex_energy.optimization import clear_sky_sine_solar_factor

        self.assertAlmostEqual(clear_sky_sine_solar_factor(pd.Timestamp("2025-01-01 06:00:00")), 0.0)
        self.assertAlmostEqual(clear_sky_sine_solar_factor(pd.Timestamp("2025-01-01 12:00:00")), 1.0)
        self.assertAlmostEqual(clear_sky_sine_solar_factor(pd.Timestamp("2025-01-01 18:00:00")), 0.0)
        self.assertAlmostEqual(
            clear_sky_sine_solar_factor(pd.Timestamp("2025-01-01 09:00:00")),
            math.sqrt(0.5),
            places=6,
        )

    def test_optimization_can_use_md_risk_envelope_for_monthly_planning(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 4,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=4, freq="30min"),
                "forecast_kw_import": [100.0, 100.0, 100.0, 100.0],
                "md_risk_envelope_kw": [100.0, 400.0, 100.0, 600.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.0,
            battery_kw_options=[0.0],
            battery_kwh_options=[0.0],
            solar_kwp_options=[0.0],
            use_md_risk_envelope=True,
            tariff=TariffConfig(
                md_rate_rm_per_kw=10.0,
                offpeak_energy_rate_rm_per_kwh=0.0,
                peak_energy_rate_rm_per_kwh=0.0,
                md_period_intervals=2,
            ),
        )

        result = evaluate_site_scenarios(frame, config)

        self.assertAlmostEqual(float(result.best_scenario["md_before"]), 600.0)
        self.assertAlmostEqual(float(result.best_scenario["bill_before_rm"]), 10000.0)

    def test_optimization_keeps_grid_import_billing_when_gross_forecast_exists(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["solar_site"] * 4,
                "interval_start": pd.date_range("2025-01-01 11:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 11:30:00", periods=4, freq="30min"),
                "forecast_gross_load_kw": [200.0, 240.0, 240.0, 200.0],
                "forecast_kw_import": [100.0, 140.0, 140.0, 100.0],
                "estimated_existing_solar_kw": [100.0, 100.0, 100.0, 100.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.0,
            battery_kw_options=[0.0],
            battery_kwh_options=[0.0],
            solar_kwp_options=[0.0],
            base_solar_kwp=0.0,
            tariff=TariffConfig(
                md_rate_rm_per_kw=10.0,
                offpeak_energy_rate_rm_per_kwh=0.0,
                peak_energy_rate_rm_per_kwh=0.0,
            ),
        )

        result = evaluate_site_scenarios(frame, config)

        self.assertAlmostEqual(float(result.best_scenario["md_before"]), 140.0)
        self.assertTrue("gross_load_kw" in result.optimized_schedule.columns)
        self.assertTrue("existing_solar_offset_kw" in result.optimized_schedule.columns)
        pd.testing.assert_series_equal(
            result.optimized_schedule["baseline_kw_import"],
            frame["forecast_kw_import"],
            check_names=False,
        )

    def test_optimization_can_select_p90_or_p95_md_risk_basis(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 4,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=4, freq="30min"),
                "forecast_kw_import": [100.0, 100.0, 100.0, 100.0],
                "calibrated_p90_md_risk_kw": [100.0, 300.0, 100.0, 500.0],
                "md_risk_envelope_kw": [100.0, 400.0, 100.0, 700.0],
            }
        )
        common = {
            "flexible_load_fraction": 0.0,
            "battery_kw_options": [0.0],
            "battery_kwh_options": [0.0],
            "solar_kwp_options": [0.0],
            "tariff": TariffConfig(
                md_rate_rm_per_kw=10.0,
                offpeak_energy_rate_rm_per_kwh=0.0,
                peak_energy_rate_rm_per_kwh=0.0,
                md_period_intervals=2,
            ),
        }

        p90 = evaluate_site_scenarios(frame, OptimizationConfig(md_risk_basis="p90", **common))
        p95 = evaluate_site_scenarios(frame, OptimizationConfig(md_risk_basis="p95", **common))

        self.assertAlmostEqual(float(p90.best_scenario["md_before"]), 500.0)
        self.assertAlmostEqual(float(p95.best_scenario["md_before"]), 700.0)
        self.assertEqual(p90.best_scenario["risk_basis"], "p90")
        self.assertEqual(p95.best_scenario["risk_basis"], "p95")

    def test_risk_basis_tradeoff_returns_best_rows_for_requested_bases(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_risk_basis_tradeoff
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 4,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=4, freq="30min"),
                "forecast_kw_import": [100.0, 100.0, 100.0, 100.0],
                "calibrated_p90_md_risk_kw": [100.0, 300.0, 100.0, 500.0],
                "md_risk_envelope_kw": [100.0, 400.0, 100.0, 700.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.0,
            battery_kw_options=[0.0],
            battery_kwh_options=[0.0],
            solar_kwp_options=[0.0],
            tariff=TariffConfig(
                md_rate_rm_per_kw=10.0,
                offpeak_energy_rate_rm_per_kwh=0.0,
                peak_energy_rate_rm_per_kwh=0.0,
                md_period_intervals=2,
            ),
        )

        tradeoff = evaluate_risk_basis_tradeoff(frame, config, risk_bases=("p90", "p95"))

        self.assertEqual(tradeoff["risk_basis"].tolist(), ["p90", "p95"])
        self.assertEqual(tradeoff["md_before"].tolist(), [500.0, 700.0])

    def test_assumption_sensitivity_returns_single_analysis_rows(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_assumption_sensitivity
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 8,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=8, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=8, freq="30min"),
                "forecast_kw_import": [100.0, 220.0, 140.0, 280.0, 150.0, 260.0, 130.0, 210.0],
                "md_risk_envelope_kw": [120.0, 260.0, 150.0, 320.0, 180.0, 300.0, 160.0, 250.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.1,
            battery_kw_options=[0.0, 100.0],
            battery_kwh_options=[0.0, 200.0],
            solar_kwp_options=[0.0, 100.0],
            use_md_risk_envelope=True,
            tariff=TariffConfig(md_rate_rm_per_kw=10.0, peak_energy_rate_rm_per_kwh=0.5, offpeak_energy_rate_rm_per_kwh=0.3),
        )

        sensitivity = evaluate_assumption_sensitivity(frame, config)

        self.assertIn("sensitivity_id", sensitivity.columns)
        self.assertIn("savings_rm", sensitivity.columns)
        self.assertIn("payback_months", sensitivity.columns)
        self.assertIn("md_rate_plus_10", sensitivity["sensitivity_id"].tolist())
        self.assertIn("battery_capex_plus_10", sensitivity["sensitivity_id"].tolist())
        self.assertIn("solar_capex_minus_10", sensitivity["sensitivity_id"].tolist())
        self.assertEqual(sensitivity["scope"].unique().tolist(), ["active_analysis"])

    def test_multi_month_scenario_reports_monthly_and_annualized_finance(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 8,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=8, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=8, freq="30min"),
                "forecast_kw_import": [100.0, 100.0, 1000.0, 100.0, 100.0, 100.0, 1000.0, 100.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.0,
            battery_kw_options=[100.0],
            battery_kwh_options=[200.0],
            solar_kwp_options=[0.0],
            battery_capex_rm_per_kw=10.0,
            battery_capex_rm_per_kwh=0.0,
            savings_period_months=2,
            tariff=TariffConfig(
                md_rate_rm_per_kw=10.0,
                offpeak_energy_rate_rm_per_kwh=0.0,
                peak_energy_rate_rm_per_kwh=0.0,
                md_period_intervals=4,
            ),
        )

        result = evaluate_site_scenarios(frame, config)
        best = result.best_scenario
        savings = float(best["savings_rm"])
        expected_monthly_savings = savings / 2.0

        self.assertGreater(savings, 0.0)
        self.assertAlmostEqual(float(best["monthly_savings_rm"]), expected_monthly_savings)
        self.assertAlmostEqual(float(best["annual_savings_rm"]), expected_monthly_savings * 12.0)
        self.assertAlmostEqual(float(best["capex_rm"]), 1000.0)
        self.assertAlmostEqual(float(best["payback_months"]), 1000.0 / expected_monthly_savings)
        self.assertNotAlmostEqual(float(best["payback_months"]), 1000.0 / savings)
        self.assertEqual(best["savings_period_months"], 2)

    def test_scenario_search_excludes_invalid_battery_power_without_storage(self) -> None:
        from trex_energy.optimization import OptimizationConfig, evaluate_site_scenarios
        from trex_energy.tariff import TariffConfig

        frame = pd.DataFrame(
            {
                "site_id": ["planning_site"] * 4,
                "interval_start": pd.date_range("2025-01-01 00:00:00", periods=4, freq="30min"),
                "interval_end": pd.date_range("2025-01-01 00:30:00", periods=4, freq="30min"),
                "forecast_kw_import": [100.0, 400.0, 100.0, 400.0],
            }
        )
        config = OptimizationConfig(
            flexible_load_fraction=0.0,
            battery_kw_options=[0.0, 100.0],
            battery_kwh_options=[0.0, 200.0],
            solar_kwp_options=[0.0],
            tariff=TariffConfig(md_rate_rm_per_kw=10.0, offpeak_energy_rate_rm_per_kwh=0.0, peak_energy_rate_rm_per_kwh=0.0),
        )

        result = evaluate_site_scenarios(frame, config)
        invalid_rows = result.scenario_summary[
            (result.scenario_summary["battery_kw"] > 0) & (result.scenario_summary["battery_kwh"] <= 0)
        ]

        self.assertTrue(invalid_rows.empty)


if __name__ == "__main__":
    unittest.main()
