from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_FILES = {
    "sol": ROOT / "1. Load Profile (With Solar Installed) SoL.xlsx",
    "e": ROOT / "2. Load Profile (No Solar) E.xlsx",
    "sun": ROOT / "3. Load Profile (No Solar) SuN.xlsx",
    "mi2": ROOT / "4. Load Profile (With Solar) Mi2.xlsx",
}


class DatasetIngestionTests(unittest.TestCase):
    def test_known_workbooks_normalize_into_canonical_schema(self) -> None:
        from trex_energy.ingestion import load_site_workbook

        required_columns = {
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
        }

        for path in DATA_FILES.values():
            frame, metadata = load_site_workbook(path)
            self.assertTrue(required_columns.issubset(frame.columns), path.name)
            self.assertGreater(len(frame), 2500, path.name)
            self.assertIsInstance(frame["interval_end"].iloc[0], pd.Timestamp, path.name)
            self.assertEqual(metadata.site_id, path.stem)

    def test_sol_workbook_infers_existing_solar_capacity(self) -> None:
        from trex_energy.ingestion import load_site_workbook

        _, metadata = load_site_workbook(DATA_FILES["sol"])

        self.assertTrue(metadata.has_solar)
        self.assertAlmostEqual(metadata.existing_pv_kwp or 0.0, 944.88, places=2)

    def test_e_workbook_derives_interval_start_from_start_end_columns(self) -> None:
        from trex_energy.ingestion import load_site_workbook

        frame, metadata = load_site_workbook(DATA_FILES["e"])

        self.assertFalse(metadata.has_solar)
        first_row = frame.sort_values("interval_end").iloc[0]
        self.assertEqual(first_row["interval_start"], pd.Timestamp("2025-04-01 00:00:00"))
        self.assertEqual(first_row["interval_end"], pd.Timestamp("2025-04-01 00:30:00"))

    def test_workspace_dataset_loader_skips_excel_lock_files(self) -> None:
        from trex_energy.profile import load_workspace_datasets

        calls: list[str] = []

        def fake_load_site_workbook(path: Path):
            calls.append(path.name)
            frame = pd.DataFrame(
                {
                    "site_id": ["demo"],
                    "interval_start": [pd.Timestamp("2025-01-01 00:00:00")],
                    "interval_end": [pd.Timestamp("2025-01-01 00:30:00")],
                    "kw_import": [1.0],
                    "kw_export": [0.0],
                    "kvar_import": [0.0],
                    "kvar_export": [0.0],
                }
            )
            return frame, object()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / "site.xlsx").write_text("placeholder")
            (workspace / "~$site.xlsx").write_text("lock")

            with patch("trex_energy.profile.load_site_workbook", side_effect=fake_load_site_workbook):
                datasets = load_workspace_datasets(workspace)

        self.assertEqual(calls, ["site.xlsx"])
        self.assertEqual(len(datasets), 1)

    def test_interval_energy_columns_are_converted_to_canonical_kw(self) -> None:
        from trex_energy.ingestion import load_site_workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Energy"
        sheet.append(["start_time", "end_time", "kwh_export", "kwh_import", "kvar_export", "kvar_import"])
        sheet.append(
            [
                pd.Timestamp("2025-01-01 00:00:00").to_pydatetime(),
                pd.Timestamp("2025-01-01 00:30:00").to_pydatetime(),
                3.0,
                10.0,
                0.0,
                0.0,
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "energy-per-interval.xlsx"
            workbook.save(path)

            frame, _ = load_site_workbook(path)

        self.assertAlmostEqual(float(frame["kw_import"].iloc[0]), 20.0)
        self.assertAlmostEqual(float(frame["kw_export"].iloc[0]), 6.0)


class DatasetValidationTests(unittest.TestCase):
    def test_validation_reports_gap_counts_by_site(self) -> None:
        from trex_energy.ingestion import load_site_workbook
        from trex_energy.validation import validate_intervals

        expected_gap_behavior = {
            "sol": "has_gaps",
            "e": "no_gaps",
            "sun": "has_gaps",
            "mi2": "no_gaps",
        }

        for key, expectation in expected_gap_behavior.items():
            frame, _ = load_site_workbook(DATA_FILES[key])
            report = validate_intervals(frame)
            if expectation == "has_gaps":
                self.assertGreater(report.gap_count, 0, key)
            else:
                self.assertEqual(report.gap_count, 0, key)


if __name__ == "__main__":
    unittest.main()
