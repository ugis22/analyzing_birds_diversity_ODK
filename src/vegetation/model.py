"""Clean, typed and joined tables of the herbaceous survey data.

Clean means: short column names, parsed types (UTC times, numbers, lists)
and resolved joins. No recorded value is changed, removed or corrected.
Anything that cannot be resolved is kept and shows up later as a flag.

Tables, with one row for each:
    plots            prescribed location (centroid), with its registration
    surveys          herbaceous survey submission
    quadrats         quadrat, with its position on the registered transect
    species_records  species recorded in a quadrat, from the species list
                     or from the additional species repeat
"""

import re

import numpy as np
import pandas as pd

from common.geo import (
    axis_deviation_from_ns,
    bearing_deg,
    haversine_m,
    parse_odk_geometry,
    project_on_line,
)
from vegetation.load import load_raw

PLACEHOLDER = re.compile(r"^(herb|wood)_\d{3}$")

SURVEY_COLS = {
    "KEY": "survey_key",
    "plot_selection-selected_plot_uuid": "vegplot_uuid",
    "plot_selection-plot_name": "plot_name",
    "plot_selection-get_plot_status": "plot_status",
    "survey_begin-selected_survey_uuid": "survey_uuid",
    "survey_begin-get_survey_label": "survey_label",
    "survey_begin-replicate": "replicate",
    "survey_begin-target_group": "target_group",
    "field_team_specifics-recorder_uuid": "recorder_uuid",
    "field_team_specifics-recorder_label": "recorder",
    "field_team_specifics-selected_project_team_uuid_multi": "team_uuids",
    "field_team_specifics-selected_transport_type_uuid": "transport_uuid",
    "field_team_specifics-transport_type_label": "transport",
    "survey_begin-start_time": "start_time",
    "survey_end-end_time": "end_time",
    "SubmissionDate": "submission_date",
    "observations-quadrat_repeat_count": "quadrat_repeat_count",
    "survey_end-quadrats_with_species": "quadrats_with_species_reported",
    "survey_end-confirm_submission": "confirm_submission",
    "survey_end-herbaceous_veg_notes": "survey_notes",
    "survey_end-background_geopoint-Latitude": "bg_lat",
    "survey_end-background_geopoint-Longitude": "bg_lon",
    "survey_end-background_geopoint-Accuracy": "bg_accuracy",
    "SubmitterName": "submitter",
    "DeviceID": "device_id",
    "ReviewState": "review_state",
    "Edits": "edits",
    "AttachmentsPresent": "attachments_present",
    "AttachmentsExpected": "attachments_expected",
    "FormVersion": "form_version",
}

QUADRAT_COLS = {
    "KEY": "quadrat_key",
    "PARENT_KEY": "survey_key",
    "quadrat_number": "quadrat_number",
    "herbs_present": "herbs_present",
    "herb_species-all_unknown_unidentifiable": "all_unknown",
    "herb_species-selected_herb_species_uuids": "species_uuids_raw",
    "herb_species-count_herb_species": "count_herb_species",
    "additional_species_present": "additional_species_present",
    "quadrat_image": "quadrat_image",
    "location_quadrat-Latitude": "lat",
    "location_quadrat-Longitude": "lon",
    "location_quadrat-Altitude": "alt",
    "location_quadrat-Accuracy": "accuracy",
    "quadrat_comment": "quadrat_comment",
}

ADDITIONAL_COLS = {
    "KEY": "record_key",
    "PARENT_KEY": "quadrat_key",
    "observation_index": "observation_index",
    "species_entry_mode": "entry_mode",
    "target_extra_name": "target_extra_uuid",
    "select_reuse_unknown": "reuse_unknown_uuid",
    "select_reuse_missing": "reuse_missing_uuid",
    "new_missing_canonical": "new_missing_canonical",
    "validated_name": "validated_name",
    "entity_label_to_write": "entity_label_to_write",
    "macro_images-macro_1": "macro_image_1",
}

REG = "plot_metadata-collect_points-"
REGISTRATION_COLS = {
    "KEY": "registration_key",
    "plot_selection-selected_plot_uuid": "centroid_uuid",
    "plot_selection-plot_name": "reg_plot_name",
    "plot_selection-sample_status": "reg_sample_status",
    "plot_selection-is_plot_viable": "is_viable",
    "plot_selection-plot_establishment_notes": "not_viable_reason",
    "plot_metadata-ecosystem_type_name": "ecosystem_type",
    "plot_metadata-ground_cover": "ground_cover",
    "plot_metadata-disturbance_types": "disturbance_types",
    "plot_metadata-soil_type": "soil_type",
    "field_team_specifics-recorder_label": "reg_recorder",
    "survey_begin-start_time": "reg_start_time",
    "survey_end-end_time": "reg_end_time",
    "survey_end-plot_establishment_notes": "reg_notes",
    "survey_begin-replicate": "reg_replicate",
    REG + "endpoint_a-location_endpoint_a-Latitude": "a_lat",
    REG + "endpoint_a-location_endpoint_a-Longitude": "a_lon",
    REG + "endpoint_a-location_endpoint_a-Accuracy": "a_accuracy",
    REG + "midpoint-location_midpoint-Latitude": "mid_lat",
    REG + "midpoint-location_midpoint-Longitude": "mid_lon",
    REG + "midpoint-location_midpoint-Accuracy": "mid_accuracy",
    REG + "endpoint_b-location_endpoint_b-Latitude": "b_lat",
    REG + "endpoint_b-location_endpoint_b-Longitude": "b_lon",
    REG + "endpoint_b-location_endpoint_b-Accuracy": "b_accuracy",
    "ReviewState": "reg_review_state",
}


def _utc(series: pd.Series) -> pd.Series:
    """Parse ISO 8601 text into UTC timestamps."""
    return pd.to_datetime(series, utc=True, format="ISO8601")


def _split(value) -> list:
    """Split a space separated ODK multi select value into a list."""
    if isinstance(value, str) and value.strip():
        return value.split()
    return []


def build_plots(raw: dict) -> pd.DataFrame:
    """Build one row for each prescribed location.

    Joins the centroid entity, the latest registration and the vegplot
    entity, and adds the geometry of the registered transect.
    """
    cen = raw["ent_centroids"].rename(
        columns={
            "__id": "centroid_uuid",
            "choice_name": "plot_name",
            "sample_status": "design_status",
        }
    )
    geom = pd.DataFrame(
        cen["geometry"].map(parse_odk_geometry).tolist(),
        columns=[
            "centroid_lat",
            "centroid_lon",
            "centroid_alt",
            "centroid_acc",
        ],
    )
    keep = [
        "centroid_uuid",
        "plot_name",
        "design_status",
        "stratum_label",
        "geohash",
    ]
    plots = pd.concat([cen[keep], geom], axis=1)

    reg = raw["registration"][list(REGISTRATION_COLS)].rename(
        columns=REGISTRATION_COLS
    )
    for c in ["reg_start_time", "reg_end_time"]:
        reg[c] = _utc(reg[c])
    n_reg = reg.groupby("centroid_uuid").size().rename("n_registrations")

    # Keep the latest registration of each centroid for the geometry. Extra
    # registrations are reported by check P03.
    reg = reg.sort_values("reg_end_time").drop_duplicates(
        "centroid_uuid", keep="last"
    )

    vp = raw["ent_vegplots"].rename(
        columns={
            "__id": "vegplot_uuid",
            "plot_uuid": "centroid_uuid",
            "is_viable": "vegplot_is_viable",
        }
    )
    n_vp = vp.groupby("centroid_uuid").size().rename("n_vegplot_entities")
    vp = vp.drop_duplicates("centroid_uuid", keep="last")[
        ["centroid_uuid", "vegplot_uuid", "vegplot_is_viable", "survey_uuids"]
    ]

    plots = (
        plots.merge(reg, on="centroid_uuid", how="left")
        .merge(vp, on="centroid_uuid", how="left")
        .merge(n_reg, on="centroid_uuid", how="left")
        .merge(n_vp, on="centroid_uuid", how="left")
    )
    counts = ["n_registrations", "n_vegplot_entities"]
    plots[counts] = plots[counts].fillna(0).astype(int)
    plots["registered"] = plots["n_registrations"] > 0
    plots["plot_number"] = (
        plots["plot_name"].str.extract(r"(\d+)$")[0].astype(int)
    )

    # Lengths, bearing and straightness of the registered transect.
    a = (plots["a_lat"], plots["a_lon"])
    mid = (plots["mid_lat"], plots["mid_lon"])
    b = (plots["b_lat"], plots["b_lon"])
    plots["len_a_mid_m"] = haversine_m(*a, *mid)
    plots["len_mid_b_m"] = haversine_m(*mid, *b)
    plots["len_a_b_m"] = haversine_m(*a, *b)
    plots["bearing_a_b_deg"] = bearing_deg(*a, *b)
    plots["deviation_from_ns_deg"] = axis_deviation_from_ns(
        plots["bearing_a_b_deg"]
    )
    plots["mid_to_centroid_m"] = haversine_m(
        *mid, plots["centroid_lat"], plots["centroid_lon"]
    )
    _, mid_off = project_on_line(*mid, *a, *b)
    plots["mid_offset_from_ab_m"] = np.abs(mid_off)
    return plots.sort_values("plot_number").reset_index(drop=True)


def build_surveys(raw: dict) -> pd.DataFrame:
    """Build one row for each survey submission, with parsed times."""
    s = raw["survey"][list(SURVEY_COLS)].rename(columns=SURVEY_COLS)
    for c in ["start_time", "end_time", "submission_date"]:
        s[c] = _utc(s[c])
    s["duration_min"] = (
        s["end_time"] - s["start_time"]
    ).dt.total_seconds() / 60

    # The survey date is the local date written on the device.
    local_date = raw["survey"]["survey_begin-start_time"].str[:10]
    s["survey_date"] = pd.to_datetime(local_date)
    s["team_uuids"] = s["team_uuids"].map(_split)
    s["review_state"] = s["review_state"].fillna("")
    return s


def build_quadrats(
    raw: dict, plots: pd.DataFrame, surveys: pd.DataFrame
) -> pd.DataFrame:
    """Build one row for each quadrat, placed on the registered transect.

    along_m is the distance from endpoint A along the line. offset_m is
    the side distance from the line. Distances to the previous and next
    quadrat help to find single position errors.
    """
    q = raw["quadrat"][list(QUADRAT_COLS)].rename(columns=QUADRAT_COLS)
    q["species_uuids"] = q["species_uuids_raw"].map(_split)
    q["n_listed_species"] = q["species_uuids"].map(len)
    n_add = raw["additional"].groupby("PARENT_KEY").size()
    q["n_additional_rows"] = q["quadrat_key"].map(n_add).fillna(0).astype(int)

    line_cols = [
        "vegplot_uuid",
        "a_lat",
        "a_lon",
        "mid_lat",
        "mid_lon",
        "b_lat",
        "b_lon",
        "len_a_b_m",
    ]
    geo = surveys[["survey_key", "vegplot_uuid"]].merge(
        plots[line_cols], on="vegplot_uuid", how="left"
    )
    q = q.merge(geo, on="survey_key", how="left")
    along, offset = project_on_line(
        q["lat"], q["lon"], q["a_lat"], q["a_lon"], q["b_lat"], q["b_lon"]
    )
    q["along_m"], q["offset_m"] = along, offset
    q["dist_to_mid_m"] = haversine_m(
        q["lat"], q["lon"], q["mid_lat"], q["mid_lon"]
    )

    q = q.sort_values(["survey_key", "quadrat_number"]).reset_index(drop=True)
    g = q.groupby("survey_key")
    q["dist_prev_m"] = haversine_m(
        q["lat"], q["lon"], g["lat"].shift(1), g["lon"].shift(1)
    )
    q["dist_next_m"] = haversine_m(
        q["lat"], q["lon"], g["lat"].shift(-1), g["lon"].shift(-1)
    )
    return q.drop(
        columns=["a_lat", "a_lon", "mid_lat", "mid_lon", "b_lat", "b_lon"]
    )


def build_species_records(raw: dict, quadrats: pd.DataFrame) -> pd.DataFrame:
    """Build one row for each species recorded in a quadrat.

    Species chosen from the list and species added by hand are put in one
    table with the same columns. Names are kept as recorded. Later
    identifications are added in separate columns, not applied.
    """
    sp = raw["ent_species"].set_index("__id")
    extra = raw["ent_species_extra"].set_index("__id")
    resolved = (
        raw["ent_species_extra_ids"]
        .drop_duplicates("species_number")
        .set_index("species_number")
    )

    # Species selected from the project list.
    listed = (
        quadrats[["quadrat_key", "survey_key", "species_uuids"]]
        .explode("species_uuids")
        .dropna()
        .rename(columns={"species_uuids": "species_uuid"})
    )
    listed["source"] = "species_list"
    listed["entry_mode"] = "list"
    listed["record_key"] = (
        listed["quadrat_key"] + "/species/" + listed["species_uuid"]
    )
    listed["taxon_name"] = listed["species_uuid"].map(sp["label"])
    listed["species_group"] = listed["species_uuid"].map(sp["groups"])
    listed["family"] = listed["species_uuid"].map(sp["family"])

    # Species added in the additional species repeat.
    a = raw["additional"][list(ADDITIONAL_COLS)].rename(
        columns=ADDITIONAL_COLS
    )
    a = a.merge(
        quadrats[["quadrat_key", "survey_key"]], on="quadrat_key", how="left"
    )
    a["source"] = "additional_species"
    a["extra_uuid"] = (
        a["reuse_unknown_uuid"]
        .fillna(a["reuse_missing_uuid"])
        .fillna(a["target_extra_uuid"])
    )
    a["extra_label"] = a["extra_uuid"].map(extra["label"])
    a["extra_index"] = a["extra_uuid"].map(extra["unknown_index"])
    a["extra_reason"] = a["extra_uuid"].map(extra["new_record_reason"])
    a["extra_review_status"] = a["extra_uuid"].map(extra["review_status"])
    a["placeholder_id"] = a["extra_index"].map(
        lambda i: f"herb_{int(i):03d}" if pd.notna(i) else None
    )

    # Name used in the field. A new missing species keeps the typed name.
    # A reused missing species takes the label of its species_extra
    # entity, because the device still shows the placeholder label until
    # the entity is updated after submission. The raw value is kept in
    # recorded_label.
    a["recorded_label"] = a["validated_name"]
    a["taxon_name"] = np.select(
        [a["entry_mode"] == "new_missing", a["entry_mode"] == "reuse_missing"],
        [a["new_missing_canonical"], a["extra_label"]],
        default=a["validated_name"],
    )
    has_name = a["taxon_name"].notna() & (a["taxon_name"] != "0")
    a["taxon_name"] = a["taxon_name"].where(has_name, a["validated_name"])
    a["is_unknown"] = a["entry_mode"].isin(["new_unknown", "reuse_unknown"])

    # Identification made after the survey, reported but not applied.
    a["resolved_name"] = a["placeholder_id"].map(resolved["species_name"])
    a["resolution_note"] = a["placeholder_id"].map(resolved["notes"])

    cols = [
        "record_key",
        "quadrat_key",
        "survey_key",
        "source",
        "entry_mode",
        "taxon_name",
        "species_uuid",
        "species_group",
        "family",
        "extra_uuid",
        "extra_label",
        "placeholder_id",
        "extra_reason",
        "extra_review_status",
        "is_unknown",
        "new_missing_canonical",
        "resolved_name",
        "resolution_note",
        "observation_index",
        "macro_image_1",
        "recorded_label",
    ]
    rec = pd.concat([listed, a], ignore_index=True).reindex(columns=cols)
    rec["is_unknown"] = rec["is_unknown"].fillna(False).astype(bool)
    rec["taxon_key"] = rec["taxon_name"].str.strip().str.lower()
    return rec


def build_model(raw: dict | None = None) -> dict[str, pd.DataFrame]:
    """Build all joined tables from the raw tables.

    Returns a dictionary with the raw tables and the tables plots,
    surveys, quadrats and species_records.
    """
    raw = raw or load_raw()
    plots = build_plots(raw)
    surveys = build_surveys(raw)
    plot_cols = [
        "vegplot_uuid",
        "centroid_uuid",
        "design_status",
        "stratum_label",
        "registered",
        "is_viable",
        "reg_end_time",
    ]
    surveys = surveys.merge(plots[plot_cols], on="vegplot_uuid", how="left")
    quadrats = build_quadrats(raw, plots, surveys)
    records = build_species_records(raw, quadrats)
    return {
        "raw": raw,
        "plots": plots,
        "surveys": surveys,
        "quadrats": quadrats,
        "species_records": records,
    }
