import numpy as np
import pandas as pd
import pytest
from scipy.special import expit, logit

from birds import cli
from birds.data import (
    link_validations,
    load_predictions,
    load_validations,
    parse_validation_filename,
)
from birds.firth import _penalized_loglik, firth_logit
from birds.labeling import label_predictions
from birds.thresholds import (
    SpeciesFit,
    clopper_pearson_lower,
    fit_species,
    solve_threshold,
    threshold_in_range,
)
from common.config import load_config


@pytest.fixture(scope="module")
def pipeline():
    # The bootstrap only changes the uncertainty columns, so it is skipped
    # to keep the test fast.
    return cli.run(bootstrap=False)


# Firth logistic regression.


def test_firth_intercept_only_closed_form():
    # With only an intercept, the Firth estimate of a proportion is
    # (k + 0.5) / (n + 1).
    y = np.ones(150)
    res = firth_logit(np.ones((150, 1)), y)
    assert expit(res.coef[0]) == pytest.approx(150.5 / 151, rel=1e-8)


def test_firth_is_stationary_point_of_penalised_likelihood():
    rng = np.random.default_rng(0)
    x = rng.normal(size=80)
    y = (rng.random(80) < expit(0.5 + 1.5 * x)).astype(float)
    design = np.column_stack([np.ones_like(x), x])
    res = firth_logit(design, y)
    eps = 1e-5
    for j in range(2):
        d = np.zeros(2)
        d[j] = eps
        up = _penalized_loglik(design, y, res.coef + d)[1]
        down = _penalized_loglik(design, y, res.coef - d)[1]
        assert abs((up - down) / (2 * eps)) < 1e-4


def test_firth_finite_under_perfect_separation():
    x = np.array([-2, -1, -0.5, 0.5, 1, 2.0])
    y = np.array([0, 0, 0, 1, 1, 1.0])
    res = firth_logit(np.column_stack([np.ones_like(x), x]), y)
    assert np.all(np.isfinite(res.coef))
    assert res.coef[1] > 0
    assert res.converged


# Thresholds.


def test_threshold_round_trip():
    b0, b1 = 2.9, 1.9
    c = solve_threshold(b0, b1, 0.99)
    assert expit(b0 + b1 * logit(c)) == pytest.approx(0.99)
    assert np.isnan(solve_threshold(b0, -0.1, 0.99))


def test_threshold_in_range_matches_closed_form():
    b0, b1 = 2.9, 1.9
    c = solve_threshold(b0, b1, 0.99)
    assert threshold_in_range(b0, b1, 0.1, 1.0, 0.99) == pytest.approx(
        c, abs=1e-3
    )


def test_threshold_in_range_does_not_extrapolate():
    # The crossing is above the highest validated score: no threshold.
    b0, b1 = 2.9, 1.9
    c = solve_threshold(b0, b1, 0.99)
    assert np.isnan(threshold_in_range(b0, b1, 0.1, c - 0.05, 0.99))


def test_flat_curve_is_floored_at_lowest_validated_score():
    assert threshold_in_range(6.0, 0.0, 0.2, 0.9, 0.99) == pytest.approx(0.2)


def test_clopper_pearson_all_correct():
    # With n correct out of n, the lower bound is 0.05 ** (1 / n).
    assert clopper_pearson_lower(150, 150) == pytest.approx(
        0.05 ** (1 / 150), rel=1e-6
    )
    assert clopper_pearson_lower(0, 0) == 0.0


def test_insufficient_validations_gives_no_threshold():
    cfg = load_config("bird_thresholds.yaml")
    df = pd.DataFrame({"confidence": [0.2, 0.5, 0.9], "outcome": [0, 1, 1]})
    fit = fit_species(df, "x", cfg)
    assert fit.status == "insufficient_validations"
    assert np.isnan(fit.threshold)


# Linking validations to predictions.


def test_parse_validation_filename():
    d = parse_validation_filename("0.107_4_RBS21_20230630_190000.wav")
    assert d == {
        "name_conf": 0.107,
        "name_n": 4,
        "file_stem": "RBS21_20230630_190000",
    }


def test_parse_bad_filename_gives_missing_values():
    d = parse_validation_filename("not_a_clip.mp3")
    assert d["file_stem"] is None
    assert np.isnan(d["name_conf"])


def test_links_on_real_data_are_one_to_one():
    pred, val = load_predictions(), load_validations()
    links = link_validations(pred, val)
    assert len(links) == len(val)
    linked = links[
        (links.link_status == "unique") & ~links.is_duplicate_review
    ]
    key = ["file_stem", "common_name", "selection"]
    assert not linked.duplicated(key).any()
    assert links["is_duplicate_review"].sum() == 2


# Labelling rules.


def _toy_inputs(outcomes):
    """Return toy predictions, thresholds, fits and links for one species.

    `outcomes` maps a selection id to the list of human answers for it.
    """
    pred = pd.DataFrame(
        {
            "file_stem": "rec",
            "common_name": ["A", "A", "A", "A", "B"],
            "selection": [1, 2, 3, 4, 5],
            "confidence": [0.9, 0.3, 0.9, 0.3, 0.9],
        }
    )
    table = pd.DataFrame(
        {
            "common_name": ["A"],
            "threshold": [0.5],
            "threshold_status": ["ok"],
        }
    )
    fit = SpeciesFit(
        "A", 100, 90, 0.1, 1.0, 0.0, 1.0, np.eye(2), 0.5, 0.5, "ok"
    )
    rows = [
        {
            "file_stem": "rec",
            "common_name": "A",
            "selection": sel,
            "outcome": o,
            "link_status": "unique",
        }
        for sel, answers in outcomes.items()
        for o in answers
    ]
    return pred, table, {"A": fit}, pd.DataFrame(rows)


def test_labelling_precedence():
    # Selection 3 is above the threshold but checked as incorrect.
    # Selection 4 is below the threshold but checked as correct.
    pred, table, fits, links = _toy_inputs({3: [0], 4: [1]})
    out = label_predictions(pred, table, fits, links).set_index("selection")
    assert out.loc[1, "observation_status"] == "above_threshold"
    assert out.loc[2, "observation_status"] == "below_threshold"
    assert out.loc[3, "observation_status"] == "validated_incorrect"
    assert out.loc[4, "observation_status"] == "validated_correct"
    assert out.loc[5, "observation_status"] == "no_threshold_for_species"
    assert out["observation"].notna().tolist() == [
        True,
        False,
        False,
        True,
        False,
    ]


def test_disagreeing_reviews_are_ignored():
    pred, table, fits, links = _toy_inputs({4: [0, 1]})
    out = label_predictions(pred, table, fits, links).set_index("selection")
    assert np.isnan(out.loc[4, "validated_outcome"])
    assert out.loc[4, "observation_status"] == "below_threshold"


# Whole pipeline on the challenge data.


def test_pipeline_reference_results(pipeline):
    thr = pipeline["table"].set_index("common_name")["threshold"]
    assert thr["Abyssinian Nightjar"] == pytest.approx(0.709, abs=1e-3)
    assert thr["Three-banded Plover"] == pytest.approx(0.833, abs=1e-3)
    assert thr["African Black-headed Oriole"] == pytest.approx(0.104)
    assert np.isnan(thr["Red-billed Firefinch"])
    lab = pipeline["labelled"]
    assert len(lab) == 29491
    assert lab["observation"].notna().sum() == 20751
