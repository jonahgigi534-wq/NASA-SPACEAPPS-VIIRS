"""Tests for pipeline/harmonize.py and pipeline/validate.py (models, scores, metrics contract)."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pipeline import harmonize as hz
from pipeline import validate


def _train(n=400, seed=1):
    """Synthetic pairs where Aqua ~= VIIRS / 5 (VIIRS sees ~5x more), with Poisson noise."""
    rng = np.random.default_rng(seed)
    v = rng.integers(1, 300, n)
    m = rng.poisson(v / 5)
    return pd.DataFrame({"region": "texas", "lc_group": "grassland", "daynight": "D",
                         "aqua_n": m, "viirs_n": v})


@pytest.mark.parametrize("method", hz.METHODS)
def test_fitted_models_match_training_totals(method):
    train = _train()
    models = {"global_ratio": hz.global_ratio(train, "aqua_n", "viirs_n"),
              method: hz.fit_method(method, train, "aqua_n", "viirs_n")}
    pred = hz.predict(method, models, train, "viirs_n")
    assert pred.sum() == pytest.approx(train["aqua_n"].sum(), rel=1e-6)
    assert (pred >= 0).all()


def test_quantile_mapping_is_monotone():
    train = _train()
    curve = hz.qm_curve(train["viirs_n"].to_numpy(float), train["aqua_n"].to_numpy(float))
    pred = hz.curve_predict("B_qm", curve, np.arange(0, 600))
    assert (np.diff(pred) >= -1e-9).all()


def test_ols_recovers_known_curve():
    v = np.arange(1, 500, dtype=float)
    a, b = hz.ols_curve(v, np.expm1(0.2 + 0.8 * np.log1p(v)))
    assert a == pytest.approx(0.2, abs=1e-6) and b == pytest.approx(0.8, abs=1e-6)


def test_predict_falls_back_to_region_then_global():
    train = _train()
    models = {"global_ratio": 5.0, "B_ols": {"texas|all|D": hz.fit_group("B_ols", train, "aqua_n", "viirs_n")}}
    assert hz.predict("B_ols", models, train.assign(lc_group="cropland"), "viirs_n").sum() > 0
    other = train.assign(region="amazon")   # no model at all -> global ratio
    assert hz.predict("B_ols", models, other, "viirs_n") == pytest.approx(other["viirs_n"] / 5.0)


def test_scores_perfect_and_biased():
    obs = np.array([10.0, 20.0, 30.0])
    perfect = validate.scores(obs, obs)
    assert perfect["r2"] == 1.0 and perfect["bias_pct"] == 0.0 and perfect["rmse"] == 0.0
    assert validate.scores(obs, obs * 2)["bias_pct"] == pytest.approx(100.0)


METRICS = Path("results/metrics.json")


@pytest.mark.skipif(not METRICS.exists(), reason="run python -m pipeline.validate")
def test_metrics_json_matches_contract_shape():
    m = json.loads(METRICS.read_text())
    assert set(m) == {"winner", "baseline_years", "test_years", "overall", "regions", "notes"}
    for block in [m["overall"], *m["regions"].values()]:
        assert set(block) == {"holdout", "transfer_noaa20"}
        for test in block.values():
            assert set(test) == {"raw_viirs", "global_ratio", "harmonized"}
            for s in test.values():
                assert set(s) == {"r2", "bias_pct", "rmse", "r"}
    assert set(m["regions"]) == {"texas", "amazon", "australia"}
