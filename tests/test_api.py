from __future__ import annotations

from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from api import app


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_endpoint_reports_ok(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_bundled_sites_endpoint_lists_current_workbooks(self) -> None:
        response = self.client.get("/api/bundled-sites")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertGreaterEqual(len(payload["sites"]), 4)
        first = payload["sites"][0]
        self.assertIn("site_id", first)
        self.assertIn("source_file", first)
        self.assertIn("has_solar", first)

    def test_api_allows_local_vite_origins_for_cors(self) -> None:
        response = self.client.get(
            "/api/bundled-sites",
            headers={"Origin": "http://localhost:5173"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_bundled_analysis_returns_real_forecast_and_optimization_payload(self) -> None:
        sites = self.client.get("/api/bundled-sites").json()["sites"]

        response = self.client.post(
            "/api/analyze/bundled",
            json={
                "source_file": sites[0]["source_file"],
                "months": 2,
                "md_rate_rm_per_kw": 88.5,
                "peak_energy_rate_rm_per_kwh": 0.51,
                "offpeak_energy_rate_rm_per_kwh": 0.37,
                "battery_capex_rm_per_kw": 1200.0,
                "battery_capex_rm_per_kwh": 800.0,
                "solar_capex_rm_per_kwp": 3000.0,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metadata"]["source_file"], sites[0]["source_file"])
        self.assertGreater(payload["validation"]["row_count"], 0)
        self.assertGreater(payload["profile"]["peak_kw_import"], 0)
        self.assertGreater(len(payload["load_history"]), 0)
        self.assertIn("kw_import", payload["load_history"][0])
        self.assertGreater(len(payload["forecast"]["points"]), 0)
        self.assertGreater(len(payload["optimization"]["scenarios"]), 0)
        self.assertIn("executive_summary", payload)
        self.assertIn("explanation", payload["optimization"])
        self.assertIn("sensitivity", payload["optimization"])
        self.assertIn("what_changed", payload["optimization"]["explanation"])
        self.assertIn("planning_basis_label", payload["optimization"]["explanation"])
        self.assertGreaterEqual(len(payload["optimization"]["sensitivity"]), 7)
        self.assertEqual(payload["assumptions"]["planning_months"], 2)
        self.assertAlmostEqual(payload["assumptions"]["md_rate_rm_per_kw"], 88.5)
        self.assertAlmostEqual(payload["assumptions"]["peak_energy_rate_rm_per_kwh"], 0.51)
        self.assertAlmostEqual(payload["assumptions"]["battery_capex_rm_per_kw"], 1200.0)
        first_point = payload["forecast"]["points"][0]
        self.assertIn("peak_risk_overlay_score", first_point)
        self.assertIn("is_peak_risk_overlay", first_point)
        self.assertIn("forecast_gross_load_kw", first_point)
        self.assertIn("estimated_existing_solar_kw", first_point)
        self.assertIn("forecast_basis", first_point)
        self.assertEqual(first_point["planning_method"], "md_ensemble_gradient_boosting")

    def test_bundled_analysis_uses_md_ensemble_forecast_by_default(self) -> None:
        response = self.client.post(
            "/api/analyze/bundled",
            json={
                "source_file": "2. Load Profile (No Solar) E.xlsx",
                "months": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["forecast"]["points"][0]["planning_method"],
            "md_ensemble_gradient_boosting",
        )

    def test_bundled_site_four_uses_site_one_solar_capacity_fallback(self) -> None:
        response = self.client.post(
            "/api/analyze/bundled",
            json={
                "source_file": "4. Load Profile (With Solar) Mi2.xlsx",
                "months": 1,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertAlmostEqual(payload["assumptions"]["existing_pv_kwp"], 944.880)
        daylight_points = [
            point
            for point in payload["forecast"]["preview"]
            if point["estimated_existing_solar_kw"] > 0
        ]
        self.assertGreater(len(daylight_points), 0)
        self.assertTrue(
            all(point["forecast_gross_load_kw"] >= point["forecast_kw_import"] for point in daylight_points)
        )

    def test_upload_analysis_accepts_workbook_file(self) -> None:
        workbook = Path("2. Load Profile (No Solar) E.xlsx")

        with workbook.open("rb") as handle:
            response = self.client.post(
                "/api/analyze/upload",
                files={
                    "file": (
                        workbook.name,
                        handle,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                data={"months": "1", "active_power_unit": "auto"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["metadata"]["source_file"], workbook.name)
        self.assertGreater(payload["validation"]["row_count"], 0)
        self.assertGreater(len(payload["normalized_preview"]), 0)


if __name__ == "__main__":
    unittest.main()
