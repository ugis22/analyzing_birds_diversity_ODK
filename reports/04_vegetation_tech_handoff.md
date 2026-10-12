# Herbaceous vegetation: automatic QA/QC and dashboard

**Handoff for the Tech team, NS Analytics platform**

This document aims to answer what the Tech team needs so that the cleaning, joining and QA/QC run automatically and feed a Vegetation QA/QC dashboard. 

- The Python code in `src/vegetation/` is the reference implementation.
- The results it produces are in [`03_vegetation_data_quality_report.md`](03_vegetation_data_quality_report.md).


## 1. Summary

1. **Never change raw data.** The raw ODK tables are stored as they arrive. Cleaning makes new tables. It does not edit the raw ones.
2. **Clean and join** into four tables: plots, surveys, quadrats and species records.
3. **Run checks.** Each check is a small rule with a stable id. All checks and their limits are listed in one config file.
4. **Save flags.** Every problem becomes one row in a `qa_flags` table. Flags are never used to change data.
5. **Let people review.** A reviewer can accept or dismiss each flag. The decision stays attached to the flag in later runs.
6. **Build summary tables** for the dashboard: surveys, plots, sampling effort and names.

On this dataset the reference code gives **809 flags from 53 checks**: 15 errors, 403 warnings and 391 info.


## 2. Inputs

<table>
<tr><th>Table</th><th>Source</th><th>One row for each</th></tr>
<tr><td><code>herbaceous_veg_survey</code></td><td>ODK form export</td><td>survey submission</td></tr>
<tr><td><code>herbaceous_veg_survey_quadrat_repeat</code></td><td>ODK repeat group</td><td>quadrat</td></tr>
<tr><td><code>herbaceous_veg_survey_additional_species_repeat</code></td><td>ODK repeat group</td><td>species added by hand</td></tr>
<tr><td><code>register_vegetation_plots</code></td><td>ODK form export</td><td>plot registration</td></tr>
<tr><td>Entity lists</td><td>ODK Central</td><td>centroids, vegplots, species, species_extra, species_extra_ids, project_team, transport, surveys, projects, areas, ecosystem_types</td></tr>
</table>

The pipeline needs the ODK system columns too: `KEY`, `PARENT_KEY`, `SubmissionDate`, `ReviewState`, `AttachmentsPresent`, `AttachmentsExpected` and `FormVersion`.


## 3. Processing steps

### Step 1. Clean

Make new tables with short column names and correct types. Do not change any value.

1. Times: parse to UTC. Keep the local date from the device as `survey_date`.
2. Multi select fields (space separated ids): store as arrays.
3. Geopoints: split into latitude, longitude, altitude and accuracy.
4. Empty review state: keep it empty, and show it as "not reviewed".

The column mapping is in `src/vegetation/model.py` (`SURVEY_COLS`, `QUADRAT_COLS`, `ADDITIONAL_COLS`, `REGISTRATION_COLS`).

### Step 2. Join

<table>
<tr><th>From</th><th>To</th><th>Key</th></tr>
<tr><td>survey</td><td>quadrat</td><td><code>KEY</code> to <code>PARENT_KEY</code></td></tr>
<tr><td>quadrat</td><td>additional species</td><td><code>KEY</code> to <code>PARENT_KEY</code></td></tr>
<tr><td>survey</td><td>vegplot entity</td><td><code>selected_plot_uuid</code> to <code>__id</code></td></tr>
<tr><td>vegplot entity</td><td>centroid</td><td><code>plot_uuid</code> to <code>__id</code></td></tr>
<tr><td>registration</td><td>centroid</td><td><code>selected_plot_uuid</code> to <code>__id</code></td></tr>
<tr><td>quadrat</td><td>species list</td><td>each id in <code>selected_herb_species_uuids</code></td></tr>
<tr><td>additional species</td><td>species_extra</td><td>reused or new placeholder entity id</td></tr>
<tr><td>species_extra</td><td>species_extra_ids</td><td>placeholder number (later identification)</td></tr>
</table>

Rules:

1. If a centroid has more than one registration, use the latest for the geometry and raise flag `P03`.
2. Join with a left join, so nothing is lost. Rows that do not find a partner are flagged.
3. Later identifications from `species_extra_ids` are stored in their own column. They are **not** applied to the data.

### Step 3. Add geometry

For each registered plot, compute from the GPS points of endpoint A, midpoint and endpoint B:

1. Length from A to B, and from A and B to the midpoint.
2. Bearing from A to B, and its angle from the north/south axis.
3. Distance from the midpoint to the prescribed centroid.
4. Distance from the midpoint to the line from A to B.

For each quadrat, project its GPS point on the line from A to B: the distance **along** the line from A, and the distance to the **side** of the line. The plots are under 100 m wide, so a flat local projection is accurate enough (`src/common/geo.py`). PostGIS can do the same with `ST_Transform` to a local metric system.

### Step 4. Run the checks

All checks are listed in `config/veg_qaqc_checks.yaml`. For each check the file gives the id, level, severity, name and description. The limits (5 m GPS accuracy, 25 m midpoint shift, and so on) are in the `params` section, so they can change without changing code.

<table>
<tr><th>Group</th><th>Ids</th><th>Examples</th></tr>
<tr><td>Design</td><td>D01, D02</td><td>a stratum with no registered plot</td></tr>
<tr><td>Plot registration</td><td>P01 to P09</td><td>midpoint more than 25 m from centroid; transect not north/south</td></tr>
<tr><td>Survey</td><td>S01 to S19</td><td>rejected submission; wrong number of quadrats; form summary wrong</td></tr>
<tr><td>Quadrat</td><td>Q01 to Q12</td><td>photo missing; quadrat outside the belt</td></tr>
<tr><td>Species record</td><td>R01 to R11</td><td>name not canonical; possible misspelling; unknown not identified</td></tr>
</table>

Severity:

<table>
<tr><th>Severity</th><th>Meaning</th><th>Effect</th></tr>
<tr><td>error</td><td>Must be solved, or accepted on purpose.</td><td>The survey is not ready for analysis until a reviewer acts.</td></tr>
<tr><td>warning</td><td>A person should look at it.</td><td>Shown on the dashboard; does not block.</td></tr>
<tr><td>info</td><td>Context for the reviewer.</td><td>Shown on request.</td></tr>
</table>

Most checks are simple and can run in SQL. Some are easier in Python: geometry (P05 to P07, Q04 to Q06, S18, S19) and name similarity (R07, which uses the `rapidfuzz` library).

### Step 5. Build the summary tables

These are the inputs for the dashboard. They are rebuilt after each run.

<table>
<tr><th>Table</th><th>One row for each</th><th>Main columns</th></tr>
<tr><td><code>mart_survey_summary</code></td><td>survey</td><td>plot, date, recorder, duration, quadrats, quadrats with species (computed and from the form), taxa, unknown taxa, GPS accuracy, distance from line, flag counts, status</td></tr>
<tr><td><code>mart_plot_summary</code></td><td>prescribed location</td><td>stratum, design status, registered, viable, geometry, taxa, Chao2, coverage, Hill N1, most frequent taxon, flag counts, status</td></tr>
<tr><td><code>mart_design_coverage</code></td><td>stratum and design status</td><td>planned, registered, viable, surveyed</td></tr>
<tr><td><code>mart_field_completeness</code></td><td>item</td><td>count, expected, share</td></tr>
<tr><td><code>mart_daily_effort</code></td><td>day and recorder</td><td>surveys, rejected, hours</td></tr>
<tr><td><code>mart_accumulation</code></td><td>plot and number of quadrats</td><td>expected taxa</td></tr>
<tr><td><code>mart_taxon_frequency</code></td><td>taxon</td><td>source, unknown, plots, quadrats</td></tr>
</table>

Status rule: **Error** if the survey or plot has at least one error that is not dismissed, **Warning** if it has a warning, otherwise **OK**.

Analysis set: all surveys not rejected in review. Each placeholder morphospecies counts as one taxon.


## 4. Tables in PostgreSQL

The names below are a proposal only.

### 4.1 Check registry

Loaded from the config file at each run.

```sql
CREATE TABLE qa_checks (
    check_id        TEXT PRIMARY KEY,
    check_name      TEXT NOT NULL,
    level           TEXT NOT NULL,
    severity        TEXT NOT NULL,
    description     TEXT NOT NULL,
    config_version  TEXT NOT NULL
);
```

### 4.2 Flags

```sql
CREATE TABLE qa_flags (
    flag_id         TEXT PRIMARY KEY,
    run_id          BIGINT NOT NULL,
    project_id      BIGINT NOT NULL,
    check_id        TEXT NOT NULL REFERENCES qa_checks,
    level           TEXT NOT NULL,
    severity        TEXT NOT NULL,
    entity_key      TEXT NOT NULL,
    plot_name       TEXT,
    survey_key      TEXT,
    quadrat_number  INTEGER,
    value           TEXT,
    message         TEXT,
    first_seen      TIMESTAMP NOT NULL,
    last_seen       TIMESTAMP NOT NULL,
    is_open         BOOLEAN NOT NULL
);
```

`flag_id` is a hash of `check_id` and `entity_key`. So the same problem keeps the same id in every run. When a problem disappears (for example, a submission is edited), the flag is kept with `is_open = false`.

### 4.3 Reviewer decisions

```sql
CREATE TABLE qa_flag_reviews (
    review_id       BIGSERIAL PRIMARY KEY,
    flag_id         TEXT NOT NULL REFERENCES qa_flags,
    decision        TEXT NOT NULL,
    comment         TEXT,
    reviewer        TEXT NOT NULL,
    reviewed_at     TIMESTAMP NOT NULL
);
```

`decision` is `accepted` (the problem is real and stays visible) or `dismissed` (not a real problem). A dismissed error does not block the survey any more.

### 4.4 Runs

```sql
CREATE TABLE qa_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    project_id      BIGINT NOT NULL,
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    code_version    TEXT NOT NULL,
    config_version  TEXT NOT NULL,
    n_flags         INTEGER,
    status          TEXT NOT NULL
);
```

### 4.5 Example checks in SQL

Survey rejected in review:

```sql
SELECT 'S01' AS check_id, s.survey_key AS entity_key, s.plot_name,
       'rejected' AS value, 'Submission rejected in review' AS message
FROM clean_surveys s
WHERE s.review_state = 'rejected';
```

Survey without 20 quadrats:

```sql
SELECT 'S03' AS check_id, s.survey_key AS entity_key, s.plot_name,
       COUNT(q.quadrat_key)::TEXT AS value,
       'Quadrat count is not 20' AS message
FROM clean_surveys s
LEFT JOIN clean_quadrats q ON q.survey_key = s.survey_key
GROUP BY s.survey_key, s.plot_name, s.quadrat_repeat_count
HAVING COUNT(q.quadrat_key) <> 20 OR s.quadrat_repeat_count <> 20;
```

Form summary differs from the records:

```sql
WITH computed AS (
    SELECT survey_key,
           SUM(CASE WHEN n_listed_species + n_additional_rows > 0
                    THEN 1 ELSE 0 END) AS n_with_species
    FROM clean_quadrats
    GROUP BY survey_key
)
SELECT 'S13' AS check_id, s.survey_key AS entity_key, s.plot_name,
       s.quadrats_with_species_reported || ' vs ' || c.n_with_species AS value,
       'Form summary of quadrats with species differs from the records' AS message
FROM clean_surveys s
JOIN computed c ON c.survey_key = s.survey_key
WHERE s.quadrats_with_species_reported <> c.n_with_species;
```

Limits such as 20 are written here for clarity. In the platform they should come from the `params` section of the config.


## 5. How it runs on NS Analytics

<table>
<tr><th>Part</th><th>Proposal</th></tr>
<tr><td>Trigger</td><td>When new ODK submissions or entity updates for the herbaceous forms arrive, add a message to the Redis queue for that project.</td></tr>
<tr><td>Worker</td><td>A Python 3.13 worker (one Docker Compose service) runs steps 1 to 5 for the whole project. A run takes a few seconds for this dataset.</td></tr>
<tr><td>Full run</td><td>Each run uses all data of the project, not only the new rows. This is simple and safe, because some checks compare surveys with each other (S02) or with entity lists.</td></tr>
<tr><td>Writing</td><td>Write all tables of a run in one database transaction, so the dashboard never shows half a run.</td></tr>
<tr><td>Review state</td><td>ODK Central review changes (approve, reject) also start a run, because they change the analysis set.</td></tr>
<tr><td>Figures</td><td>The interactive map can be built in the browser from the summary tables. Static figures for reports go to Azure Blob Storage.</td></tr>
<tr><td>Report</td><td>The Markdown report can be built with <code>vegetation.report</code> after each run, or on request.</td></tr>
<tr><td>Code</td><td>The modules in <code>src/vegetation/</code> move into the platform repository on GitHub, with the tests in <code>tests/test_vegetation.py</code> in CI.</td></tr>
</table>

The reference code reads CSV files. On the platform the same functions should get the tables from PostgreSQL. Only `load.py` needs to change.


## 6. The dashboard

One dashboard for each project and survey replicate. All pages share filters: date range, recorder, stratum, plot, severity and check.

### Page 1. Overview

<table>
<tr><th>Widget</th><th>Source</th></tr>
<tr><td>Numbers: planned, registered and surveyed plots</td><td><code>mart_design_coverage</code></td></tr>
<tr><td>Numbers: surveys OK, with warnings, with errors</td><td><code>mart_survey_summary</code></td></tr>
<tr><td>Open flags by severity, and how many are reviewed</td><td><code>qa_flags</code>, <code>qa_flag_reviews</code></td></tr>
<tr><td>Bar chart: flags by check</td><td><code>qa_flags</code></td></tr>
<tr><td>Alert box: strata with no registered plot</td><td><code>qa_flags</code> (D01)</td></tr>
</table>

### Page 2. Surveys

A table with one row per survey (`mart_survey_summary`), coloured by status. Clicking a row opens the survey: its quadrats on a small map, its flags, and the photos.

### Page 3. Plots and map

1. Map of all prescribed locations, coloured by state, with the 25 m circle, the registered transect and the quadrats. Quadrats with a position flag are red.
2. Table with one row per plot (`mart_plot_summary`).
3. Chart of transect directions, with the allowed band around north/south.

### Page 4. Flags

A table of all flags with filters. Each row has buttons to **accept** or **dismiss**, with a comment. This writes to `qa_flag_reviews`. This is where the data team works through the problems.

### Page 5. Sampling effort

1. Design coverage table.
2. Field completeness (photos, GPS points, accuracy).
3. Surveys and hours by day and recorder.
4. Species accumulation curves inside plots and across plots, with the coverage of each plot.

### Page 6. Species names

1. Share of taxa that are unknown placeholders, and the list of placeholders still waiting for an identification.
2. Typed names with problems: not canonical, already on the list, possible misspelling, same name under several placeholders.
3. Most frequent taxa that are not on the species list. These are the first to add to the list.

## 7. Files

<table>
<tr><th>Path</th><th>Content</th></tr>
<tr><td><code>src/vegetation/load.py</code></td><td>Read the raw files.</td></tr>
<tr><td><code>src/vegetation/model.py</code></td><td>Clean, join and add geometry.</td></tr>
<tr><td><code>src/vegetation/checks.py</code></td><td>All checks and the runner.</td></tr>
<tr><td><code>config/veg_qaqc_checks.yaml</code></td><td>Check registry and limits.</td></tr>
<tr><td><code>src/vegetation/summaries.py</code></td><td>Summary tables and richness statistics.</td></tr>
<tr><td><code>src/vegetation/mapping.py</code>, <code>plots.py</code></td><td>Maps and figures.</td></tr>
<tr><td><code>src/vegetation/report.py</code>, <code>reports/templates/03_template.md</code></td><td>Build the data quality report.</td></tr>
<tr><td><code>src/vegetation/cli.py</code></td><td>Run everything and write the outputs.</td></tr>
<tr><td><code>notebooks/02_vegetation_qaqc.ipynb</code></td><td>Analysis with all tables and figures.</td></tr>
<tr><td><code>tests/test_vegetation.py</code></td><td>Tests.</td></tr>
</table>
