from __future__ import annotations

from pathlib import Path
import os
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from api import app, _load_local_env


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_health_endpoint_reports_ok(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_backend_local_env_loader_preserves_existing_environment(self) -> None:
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                'AI_ASSISTANT_API_KEY="from-file"\n'
                "AI_ASSISTANT_BASE_URL=https://example.test/chat/completions\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"AI_ASSISTANT_API_KEY": "existing"}, clear=False):
                _load_local_env(env_path)

                self.assertEqual(os.environ["AI_ASSISTANT_API_KEY"], "existing")
                self.assertEqual(os.environ["AI_ASSISTANT_BASE_URL"], "https://example.test/chat/completions")

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

    def test_api_allows_vercel_frontend_origins_for_cors(self) -> None:
        response = self.client.get(
            "/api/health",
            headers={"Origin": "https://peak-logic.vercel.app"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], "https://peak-logic.vercel.app")

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
        self.assertIn("explainability", payload["optimization"])
        self.assertIn("sensitivity", payload["optimization"])
        self.assertIn("what_changed", payload["optimization"]["explanation"])
        self.assertIn("planning_basis_label", payload["optimization"]["explanation"])
        self.assertIn("drivers", payload["optimization"]["explainability"])
        self.assertGreaterEqual(len(payload["optimization"]["explainability"]["drivers"]), 3)
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

    def test_assistant_answers_from_dashboard_context_without_judge_script(self) -> None:
        response = self.client.post(
            "/api/assistant",
            json={
                "question": "Why did the optimizer choose this option instead of the cheaper one?",
                "context": {
                    "site_id": "Test Site",
                    "source_file": "test.xlsx",
                    "profile": {"peak_kw_import": 973, "avg_kw_import": 520},
                    "validation": {"gap_count": 0, "missing_value_count": 0},
                    "assumptions": {
                        "planning_months": 1,
                        "md_rate_rm_per_kw": 97.06,
                        "battery_capex_rm_per_kw": 1400,
                        "battery_capex_rm_per_kwh": 900,
                        "solar_capex_rm_per_kwp": 3200,
                    },
                    "optimization": {
                        "best_scenario": {
                            "annual_savings_rm": 882448,
                            "capex_rm": 1140000,
                            "md_after": 832,
                            "payback_months": 15.5,
                        },
                        "scenario_evidence": {
                            "summary": "3 tested scenarios were ranked by recurring savings, demand-charge exposure, investment, and payback efficiency.",
                            "items": [
                                {
                                    "label": "Cheaper options",
                                    "detail": "The strongest lower-investment option saved RM 182,448/yr less and left 23 kW more peak-demand exposure.",
                                },
                                {
                                    "label": "Larger options",
                                    "detail": "The nearest larger option costs RM 260,000 more but adds only RM 7,552/yr.",
                                },
                            ],
                            "sensitivity": [
                                "Re-check MD tariff, battery CAPEX, solar CAPEX before procurement.",
                            ],
                        },
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "grounded")
        self.assertIn("cheaper", payload["answer"].lower())
        self.assertIn("RM 182,448/yr less", payload["answer"])
        self.assertIn("23 kW", payload["answer"])
        self.assertIn("Options Considered", payload["sources"])
        self.assertNotIn("presentation script", payload["answer"].lower())

    def test_assistant_supports_generic_chat_completion_provider_env(self) -> None:
        provider_response = Mock()
        provider_response.raise_for_status.return_value = None
        provider_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Provider answer grounded in the dashboard context.",
                    }
                }
            ]
        }

        with patch.dict(
            os.environ,
            {
                "AI_ASSISTANT_API_KEY": "test-key",
                "AI_ASSISTANT_BASE_URL": "https://api.z.ai/api/coding/paas/v4/chat/completions",
                "AI_ASSISTANT_MODEL": "glm-5.1",
            },
            clear=False,
        ), patch("api.httpx.post", return_value=provider_response) as post:
            response = self.client.post(
                "/api/assistant",
                json={
                    "question": "What is happening in this site?",
                    "context": {
                        "site_id": "Test Site",
                        "profile": {"peak_kw_import": 973, "avg_kw_import": 520},
                        "optimization": {
                            "best_scenario": {
                                "annual_savings_rm": 882448,
                                "capex_rm": 1140000,
                            }
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "provider")
        self.assertEqual(payload["answer"], "Provider answer grounded in the dashboard context.")
        post.assert_called_once()
        request_payload = post.call_args.kwargs["json"]
        self.assertEqual(request_payload["model"], "glm-5.1")
        self.assertIn("messages", request_payload)

    def test_assistant_falls_back_when_generic_provider_fails(self) -> None:
        with patch.dict(
            os.environ,
            {
                "AI_ASSISTANT_API_KEY": "test-key",
                "AI_ASSISTANT_BASE_URL": "https://api.z.ai/api/coding/paas/v4/chat/completions",
                "AI_ASSISTANT_MODEL": "glm-5.1",
            },
            clear=False,
        ), patch("api.httpx.post", side_effect=RuntimeError("provider unavailable")):
            response = self.client.post(
                "/api/assistant",
                json={
                    "question": "What is happening in this site?",
                    "context": {
                        "site_id": "Test Site",
                        "profile": {"peak_kw_import": 973, "avg_kw_import": 520},
                        "optimization": {
                            "best_scenario": {
                                "annual_savings_rm": 882448,
                                "capex_rm": 1140000,
                            }
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["mode"], "grounded")
        self.assertIn("Test Site", payload["answer"])


if __name__ == "__main__":
    unittest.main()
