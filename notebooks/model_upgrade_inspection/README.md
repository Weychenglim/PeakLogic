# Model Upgrade Inspection Notebook

This folder is isolated from the production package and is meant for experimentation only.

## File
- `forecast_model_upgrade_inspection.ipynb`

## What it covers
- 30-minute interval regularization and conservative imputation
- Enhanced feature engineering for demand forecasting
- Standardized Ridge with alpha tuning (time-based CV)
- Hybrid recursive + seasonal blending
- Site-local calibration layer
- Leave-one-site-out (unseen-site) evaluation
- Rolling-origin evaluation
- Peak-focused metrics and coefficient inspection

## How to use
1. Open the notebook.
2. Run cells from top to bottom.
3. The notebook now pulls shared tuning defaults and error-summary helpers from `forecast_model_upgrade_support.py`, so LOSO and rolling-origin use the same low-risk settings.
4. Review LOSO and rolling-origin tables to compare baseline vs enhanced model.
5. Inspect the weekday-coverage and grouped-error summaries for judge-facing explanation of where the model is stable or weak.
6. Inspect coefficient and prediction charts for model behavior.

## Validation
- Fast notebook structure check: `python -m unittest tests.test_forecast_model_upgrade_notebook`
- Support-layer guardrails including SoL and Mi2 spot checks: `python -m unittest tests.test_forecast_model_upgrade_support`
- Full repo regression pass: `python -m unittest`
- Notebook smoke rerun outside Jupyter: execute cells `0-12` with a small Python runner if you want a top-to-bottom reproducibility check.

## Source Of Truth
- `docs/forecast_model_upgrade_source_of_truth.md`
