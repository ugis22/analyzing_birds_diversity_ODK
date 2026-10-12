import hashlib
import re

import numpy as np
import pandas as pd
import pytest

from common.config import load_config
from common.geo import (
    axis_deviation_from_ns,
    bearing_deg,
    haversine_m,
    project_on_line,
)
from common.paths import VEG_ENTITIES, VEG_EXPORTS
from vegetation import checks, report
from vegetation.checks import FLAG_COLUMNS, run_checks
from vegetation.model import build_model
from vegetation.summaries import (
    chao2,
    field_completeness,
    rarefaction_curve,
)

CONFIG = "veg_qaqc_checks.yaml"


@pytest.fixture(scope="module")
def model():
    return build_model()


@pytest.fixture(scope="module")
def flags(model):
    return run_checks(model)


def _plots_flagged(flags, check_id):
    return set(flags.loc[flags.check_id == check_id, "plot_name"])


# Geometry helpers.


def test_geometry_helpers():
    # One ten thousandth of a degree of latitude is about 11.1 m.
    assert haversine_m(0, 37, 1e-4, 37) == pytest.approx(11.12, abs=0.05)
    assert bearing_deg(0, 37, 1e-4, 37) == pytest.approx(0, abs=1e-6)
    assert bearing_deg(0, 37, 0, 37.001) == pytest.approx(90, abs=1e-6)
    devs = axis_deviation_from_ns(np.array([0, 90, 170, 200]))
    assert devs.tolist() == [0, 90, 10, 20]


def test_project_on_line():
    # The line goes due north and the point lies to its east.
    along, offset = project_on_line(0.0, 37.0001, 0.0, 37.0, 0.0005, 37.0)
    assert along == pytest.approx(0, abs=0.01)
    assert offset == pytest.approx(11.13, abs=0.05)


# Joined tables.


def test_model_row_counts(model):
    assert len(model["surveys"]) == 32
    assert len(model["quadrats"]) == 640
    assert len(model["plots"]) == 51
    rec = model["species_records"]
    assert (rec["source"] == "additional_species").sum() == 1296


def test_every_quadrat_and_record_is_joined(model):
    q, s = model["quadrats"], model["surveys"]
    assert q["survey_key"].isin(s["survey_key"]).all()
    rec = model["species_records"]
    assert rec["quadrat_key"].isin(q["quadrat_key"]).all()


# Check registry.


def test_config_and_code_list_the_same_checks():
    ids = [c["id"] for c in load_config(CONFIG)["checks"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == set(checks.REGISTRY)


def test_flags_have_the_expected_columns_and_values(flags):
    assert list(flags.columns) == FLAG_COLUMNS
    assert set(flags["severity"]) <= {"error", "warning", "info"}
    levels = {"project", "plot", "survey", "quadrat", "record"}
    assert set(flags["level"]) <= levels


def test_known_issues_are_flagged(flags):
    rejected = {"SavMon_LW_Plot_18", "SavMon_LW_Plot_21"}
    assert _plots_flagged(flags, "S01") == rejected
    assert _plots_flagged(flags, "S02") == rejected
    assert _plots_flagged(flags, "S10") == {"SavMon_LW_Plot_46"}
    assert _plots_flagged(flags, "P01") == {"SavMon_LW_Plot_23"}
    assert _plots_flagged(flags, "P04") == {"SavMon_LW_Plot_14"}
    d01 = flags.loc[flags.check_id == "D01", "message"].iloc[0]
    assert "shrubland" in d01
    assert (flags.check_id == "R04").any()


def test_all_transects_fail_the_north_south_rule(model, flags):
    with_line = model["plots"]["bearing_a_b_deg"].notna().sum()
    assert (flags.check_id == "P06").sum() == with_line == 30


def test_form_summary_mismatch_count(flags):
    assert (flags.check_id == "S13").sum() == 23


def test_checks_are_silent_on_clean_quadrats(model):
    m = {
        k: (v.copy() if isinstance(v, pd.DataFrame) else v)
        for k, v in model.items()
    }
    q = m["quadrats"]
    q.loc[:, "accuracy"] = 2.0
    q.loc[:, "offset_m"] = 2.0
    q.loc[:, "quadrat_image"] = "x.jpg"
    params = load_config(CONFIG)["params"]
    for cid in ["Q01", "Q03", "Q04"]:
        assert len(checks.REGISTRY[cid](m, params)) == 0

    # Break one quadrat: low accuracy and no photo.
    q.loc[q.index[0], "accuracy"] = 9.0
    q.loc[q.index[0], "quadrat_image"] = np.nan
    assert len(checks.REGISTRY["Q03"](m, params)) == 1
    assert len(checks.REGISTRY["Q01"](m, params)) == 1


def test_raw_files_are_not_modified(model):
    # The pipeline only reads files, so the hashes must not change.
    files = sorted(VEG_EXPORTS.glob("*.csv")) + sorted(
        VEG_ENTITIES.glob("*.csv")
    )

    def digests():
        return {f: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}

    before = digests()
    run_checks(build_model())
    assert digests() == before


# Richness statistics.


def _toy_incidence():
    # Three units, four taxa. Taxon d is never found.
    return pd.DataFrame(
        [[1, 1, 0, 0], [1, 0, 1, 0], [1, 0, 0, 0]], columns=list("abcd")
    )


def test_rarefaction_end_points():
    inc = _toy_incidence()
    curve = rarefaction_curve(inc)
    first = curve["expected_richness"].iloc[0]
    last = curve["expected_richness"].iloc[-1]
    assert first == pytest.approx(inc.sum(axis=1).mean())
    assert last == pytest.approx(3)


def test_chao2_without_doubletons():
    # Q1 = 2 (taxa b and c), Q2 = 0, T = 3.
    c = chao2(_toy_incidence())
    assert c["S_obs"] == 3
    assert c["chao2"] == pytest.approx(3 + (2 / 3) * 2 * 1 / 2)


def test_chao2_with_doubletons():
    # Taxon a in 3 units, b in 2, c in 1: Q1 = 1, Q2 = 1, T = 3, U = 6.
    inc = pd.DataFrame([[1, 1, 1], [1, 1, 0], [1, 0, 0]], columns=list("abc"))
    c = chao2(inc)
    assert c["chao2"] == pytest.approx(3)
    expected_cov = 1 - 1 / 6 * (2 * 1 / (2 * 1 + 2 * 1))
    assert c["coverage"] == pytest.approx(expected_cov)


def test_field_completeness_is_full(model):
    fc = field_completeness(model)
    assert (fc["completeness"] == 1).all()


# Report.


def test_report_fills_every_placeholder(model, flags):
    from vegetation import cli

    res = cli.run()
    template = report.TEMPLATE.read_text(encoding="utf-8")
    needed = set(re.findall(r"\{\{(\w+)\}\}", template))
    assert needed <= set(report.tables(res))
