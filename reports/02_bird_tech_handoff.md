# Birds: from BirdNET predictions to observations

**Handoff for the Tech team, NS Analytics platform**

This document explains how we turn BirdNET predictions into observations, which decisions we made, and what the platform needs so the method runs automatically after each upload. The ML pipeline (SD card upload to BirdNET predictions) already works. Everything here starts after the predictions are saved.

The Python code in `src/birds/` is the reference implementation. If this document and the code disagree, the code is correct, and we will fix the document.

The full results, with more detail on each decision, are in [`01_bird_observations.md`](01_bird_observations.md).


## 1. Summary

1. BirdNET gives each detection a confidence score between 0 and 1. The score is **not** a probability. A score of 0.8 does not mean an 80% chance that the bird is really there.
2. Ornithologists listened to a sample of clips and marked each one as correct (1) or incorrect (0).
3. For each species we use these answers to learn the link between the score and the chance that the prediction is correct.
4. For each species we find the lowest score where this chance is at least **0.99**. This is the **threshold**.
5. A prediction becomes an **observation** when its score is at or above the threshold. If an ornithologist checked that exact clip, their answer is used instead.

Result on this dataset: **20,751 of 29,491 predictions are observations.**


## 2. The data

<table>
<tr><th>File</th><th>Content</th></tr>
<tr><td><code>birdnet_predictions.csv</code></td><td>29,491 predictions from 1,696 recordings, 43 recorders, 20 June to 12 July 2023. Four species.</td></tr>
<tr><td><code>validation_results.csv</code></td><td>551 clips checked by ornithologists. Each row has the species, the score and the outcome (1 correct, 0 incorrect).</td></tr>
</table>

The four species:

<table>
<tr><th>Short name</th><th>Scientific name</th><th>Predictions</th><th>Validated</th><th>Correct</th></tr>
<tr><td>Nightjar</td><td><i>Caprimulgus poliocephalus</i></td><td>10,187</td><td>150</td><td>117</td></tr>
<tr><td>Oriole</td><td><i>Oriolus larvatus</i></td><td>18,054</td><td>150</td><td>150</td></tr>
<tr><td>Firefinch</td><td><i>Lagonosticta senegala</i></td><td>235</td><td>101</td><td>6</td></tr>
<tr><td>Plover</td><td><i>Charadrius tricollaris</i></td><td>1,015</td><td>148</td><td>147</td></tr>
</table>

The validated clips are not a random sample of the predictions. About 30% have a score below 0.2 and about 40% have a score of 0.8 or more. This is good for fitting the curve, because it covers both ends of the score range. But it means the share of correct clips in the validation file is **not** the precision of all predictions.


## 3. How we derive observations from predictions

### Step 1. Link each validated clip to its prediction

The validation file name has the form `<score>_<n>_<recording>.wav`. It gives the recording, the species and the score rounded to 3 decimals. It does **not** give the prediction id (the Raven `selection` number).

We link a validated clip to a prediction only when exactly **one** prediction of that species in that recording has the same rounded score. We never guess.

<table>
<tr><th>Link result</th><th>Clips</th><th>What it means</th></tr>
<tr><td>unique</td><td>204</td><td>Linked to exactly one prediction.</td></tr>
<tr><td>recording not in predictions</td><td>288</td><td>The recording is not in the predictions file we received.</td></tr>
<tr><td>ambiguous</td><td>45</td><td>More than one prediction has the same rounded score.</td></tr>
<tr><td>no matching score</td><td>14</td><td>The recording is there, but no prediction has that score.</td></tr>
</table>

Clips that are not linked are still used to fit the curve, because the curve only needs the score and the outcome. They just cannot label a specific prediction.

Two clips were exported and checked twice. We count each one only once.

### Step 2. Fit a curve for each species

For each species we fit a logistic regression:

```
log odds of (prediction is correct) = b0 + b1 * logit(score)
```

`logit(score)` is `log(score / (1 minus score))`. We use it because BirdNET scores are very close together near 1, and this scale spreads them out. This is the method of Wood & Kahl (2024). Scores are first limited to the range 0.0001 to 0.9999, so the logit is always finite.

We use **Firth logistic regression**, not the plain logistic regression (GLM) used in the paper. Section 4 explains why.

### Step 3. Find the threshold

The threshold is the **lowest score from which the fitted chance of being correct stays at or above 0.99**, up to the highest validated score.

We only search **inside the range of validated scores**. Outside this range nobody has listened to clips, so the curve has no data to support it.

The search gives one of three results:

<table>
<tr><th>Status</th><th>Meaning</th></tr>
<tr><td><code>ok</code></td><td>The curve crosses 0.99 inside the validated range. The threshold is the crossing point.</td></tr>
<tr><td><code>floored_at_min_validated</code></td><td>The curve is above 0.99 everywhere. The threshold is the lowest validated score. This is flagged for review.</td></tr>
<tr><td><code>not_reached_in_validated_range</code></td><td>The curve never reaches 0.99 inside the validated range. The species has no threshold.</td></tr>
</table>

### Step 4. Label every prediction

Each prediction gets a status. The first rule that applies wins:

1. An ornithologist checked this exact clip and said **correct**: `validated_correct`. This is an observation.
2. An ornithologist checked this exact clip and said **incorrect**: `validated_incorrect`. This is not an observation.
3. The species has no threshold: `no_threshold_for_species`. This is not an observation.
4. The score is at or above the threshold: `above_threshold`. This is an observation.
5. Otherwise: `below_threshold`. This is not an observation.

If two checks of the same clip disagree, we ignore both and use the threshold.

The new column `observation` contains the species name when the prediction is an observation, and is empty otherwise.

### Step 5. Measure the uncertainty

For each threshold we also report:

1. **Bootstrap range.** We resample the validated clips 1,000 times, refit, and report the range that holds 95% of the thresholds.
2. **Careful threshold.** The lowest score where the lower edge of the 95% band of the curve reaches 0.99.
3. **Direct check.** The share of validated clips above the threshold that are correct, with a 95% lower bound.


## 4. Decisions and reasons

1. **Firth logistic regression for every species.** The plain GLM has no solution when all validated clips are correct (Oriole). It is also too confident when there is only one error (Plover). Firth adds a small correction that always gives a solution. When the data are good, it gives almost the same result as the GLM (Nightjar). One method for all species means no special cases in the platform.
2. **Target of 0.99.** This is the Natural State definition of an observation: we are 99% sure the prediction is correct, according to the fitted curve.
3. **No extrapolation.** The threshold must be inside the validated score range. For Firefinch the curve reaches 0.99 only at a score of 0.999, but the highest validated score is 0.907. We do not trust the curve there, so Firefinch has no threshold.
4. **Flat curve.** For Oriole all 150 clips are correct, so the curve is flat and above 0.99. We set the threshold to the lowest validated score (0.104) and flag it.
5. **Human answers win.** A checked clip uses the ornithologist answer, not the threshold. We only use links that are certain.
6. **Duplicate checks count once.** Otherwise one clip would count twice in the curve.
7. **Point estimate as the main result.** We use the fitted curve directly, as the definition asks. The uncertainty is published next to it, so users can see how stable each threshold is.


## 5. Results on this dataset

<table>
<tr><th>Species</th><th>Threshold</th><th>Status</th><th>Bootstrap 95% range</th><th>Observations</th></tr>
<tr><td>Nightjar</td><td>0.709</td><td>ok</td><td>0.50 to 0.87</td><td>2,963 of 10,187</td></tr>
<tr><td>Oriole</td><td>0.104</td><td>floored</td><td>0.104 to 0.106</td><td>17,646 of 18,054</td></tr>
<tr><td>Firefinch</td><td>none</td><td>not reached</td><td>none</td><td>1 of 235 (one clip checked as correct)</td></tr>
<tr><td>Plover</td><td>0.833</td><td>ok</td><td>0.10 to 0.96</td><td>141 of 1,015</td></tr>
<tr><td><b>Total</b></td><td></td><td></td><td></td><td><b>20,751 of 29,491</b></td></tr>
</table>

![Validated clips and fitted curves for each species](figures/birds_threshold_curves.png)

*Each panel shows the validated clips (green correct, red incorrect), the Firth curve with its 95% band, the plain GLM curve (dashed), the 0.99 target (dotted) and the threshold (vertical line).*

![Score distribution of all predictions with the threshold](figures/birds_score_distributions.png)

*Score distribution of all predictions for each species. The vertical line is the threshold.*

### What the results tell us

1. **Nightjar** has a clear curve and many errors at low scores. Its threshold is the best supported of the four, but the bootstrap range (0.50 to 0.87) shows there is still uncertainty.
2. **Oriole** has no errors in 150 checks. The model says nearly all predictions are correct. But 150 correct checks are not enough to prove 0.99 directly: we would need **299 correct checks in a row**. More validation is recommended.
3. **Firefinch** is almost always wrong (6 of 101 correct). BirdNET does not identify this species well here. No observations except the one clip an ornithologist confirmed.
4. **Plover** has only one error in 148 checks, so the threshold is very uncertain (bootstrap range 0.10 to 0.96, and 14% of the resamples find no threshold). The plain GLM would give 0.260 and about five times more observations. More validation at middle scores is recommended.

### Check without validations

The species have different daily activity. If many false predictions passed the thresholds, we would see observations at unexpected hours. We do not:

<table>
<tr><th>Species</th><th>Share of observations at night (20:00 to 04:59)</th></tr>
<tr><td>Nightjar (active at dusk and night)</td><td>77%</td></tr>
<tr><td>Oriole (active by day)</td><td>2%</td></tr>
<tr><td>Plover</td><td>23%</td></tr>
</table>

![Observations by hour of the day](figures/birds_observations_by_hour.png)


## 6. What the platform needs

### 6.1 Overview

```
BirdNET predictions saved (already working)
        |
        v
[Job A] Label new predictions with the active thresholds
        |
        v
Observations available to users and reports

Ornithologists check clips
        |
        v
[Job B] Choose clips to validate          [Job C] Refit thresholds
        (sampling plan)                           (new version, needs approval)
                                                  |
                                                  v
                                          [Job D] Label all predictions again
```

How this fits the current NS Analytics stack:

<table>
<tr><th>Part</th><th>Proposal</th></tr>
<tr><td>Storage</td><td>PostgreSQL tables in section 6.2. Thresholds are versioned and never overwritten.</td></tr>
<tr><td>Jobs</td><td>Python 3.13 workers, one Docker Compose service. Jobs are put on a Redis queue.</td></tr>
<tr><td>Trigger for Job A</td><td>The ML pipeline adds a message to the Redis queue when a batch of predictions is saved.</td></tr>
<tr><td>Trigger for Job C</td><td>A message when new validations are saved, plus a monthly scheduled run.</td></tr>
<tr><td>Figures</td><td>Curve figures saved to Azure Blob Storage, linked from the threshold row.</td></tr>
<tr><td>Approval</td><td>A page in NS Analytics (React) that shows a new threshold next to the active one.</td></tr>
<tr><td>Code</td><td>The modules in <code>src/birds/</code> move into the platform repository on GitHub, with the tests in section 6.11 in CI.</td></tr>
</table>

The reference code reads CSV files from the repository folders. On the platform, the same functions should receive data read from PostgreSQL. The model code (`firth.py`, `thresholds.py`, `labeling.py`) does not read files, so it can be reused as it is.

### 6.2 Tables

The column names below are a proposal. The Tech team can adapt them to the existing schema.

**predictions** (already exists; these fields are required)

```sql
prediction_id     BIGINT PRIMARY KEY,
project_id        BIGINT,
recorder_id       TEXT,
recording_id      BIGINT,
species_code      TEXT,
confidence        DOUBLE PRECISION,
clip_start        TIMESTAMP,
birdnet_version   TEXT
```

**validations** (one row for each check by an ornithologist)

```sql
validation_id     BIGINT PRIMARY KEY,
prediction_id     BIGINT REFERENCES predictions,
species_code      TEXT,
confidence        DOUBLE PRECISION,
outcome           SMALLINT,
validator_id      TEXT,
validated_at      TIMESTAMP
```

The most important change: **store the `prediction_id` with every validated clip.** In this dataset 347 of 551 clips could not be linked to a prediction because the file name has no id. With the id, every check can label its prediction.

**species_thresholds** (one row for each species, project and version)

```sql
threshold_id                 BIGINT PRIMARY KEY,
project_id                   BIGINT,
species_code                 TEXT,
birdnet_version              TEXT,
target_precision             DOUBLE PRECISION,
b0                           DOUBLE PRECISION,
b1                           DOUBLE PRECISION,
threshold                    DOUBLE PRECISION,
threshold_status             TEXT,
validated_conf_min           DOUBLE PRECISION,
validated_conf_max           DOUBLE PRECISION,
n_validated                  INTEGER,
n_correct                    INTEGER,
bootstrap_ci_low             DOUBLE PRECISION,
bootstrap_ci_high            DOUBLE PRECISION,
conservative_threshold       DOUBLE PRECISION,
notes                        TEXT,
code_version                 TEXT,
created_at                   TIMESTAMP,
approved_by                  TEXT,
is_active                    BOOLEAN
```

Old versions are never deleted. Only one row for each project, species and BirdNET version is active.

**observations** (one row for each prediction, or new columns on `predictions`)

```sql
prediction_id        BIGINT PRIMARY KEY REFERENCES predictions,
threshold_id         BIGINT REFERENCES species_thresholds,
observation          TEXT,
observation_status   TEXT,
decision_source      TEXT,
p_correct            DOUBLE PRECISION,
validated_outcome    SMALLINT,
labelled_at          TIMESTAMP
```

`decision_source` is `human_validation`, `probabilistic_threshold` or `none`. `p_correct` is the fitted chance that the prediction is correct, useful for later models.

### 6.3 Job A: label new predictions

**When:** each time a batch of predictions is saved.

**What:** apply the rules of section 3, step 4, with the active threshold. It is a simple join and can run in SQL:

```sql
CREATE VIEW validation_consensus AS
SELECT prediction_id, MIN(outcome) AS outcome
FROM validations
GROUP BY prediction_id
HAVING MIN(outcome) = MAX(outcome);

SELECT
    p.prediction_id,
    t.threshold_id,
    v.outcome AS validated_outcome,
    CASE
        WHEN v.outcome = 1 THEN 'validated_correct'
        WHEN v.outcome = 0 THEN 'validated_incorrect'
        WHEN t.threshold IS NULL THEN 'no_threshold_for_species'
        WHEN p.confidence >= t.threshold THEN 'above_threshold'
        ELSE 'below_threshold'
    END AS observation_status
FROM predictions p
LEFT JOIN species_thresholds t
    ON t.project_id = p.project_id
    AND t.species_code = p.species_code
    AND t.birdnet_version = p.birdnet_version
    AND t.is_active
LEFT JOIN validation_consensus v
    ON v.prediction_id = p.prediction_id;
```

`observation` is the species name when the status is `validated_correct` or `above_threshold`, and empty otherwise.

A species with no active threshold gives no observations. This is on purpose: we do not publish observations we cannot support.

### 6.4 Job B: choose clips to validate

**When:** after a new upload, for each species that has predictions but not enough validations.

**What:** a sample of clips for the ornithologists, spread over the score range:

1. Split the scores into 10 groups of equal width on the logit scale, inside the range of the predictions.
2. Take the same number of clips from each group, chosen at random. About 15 clips for each group gives 150 clips for each species.
3. Spread the sample over recorders and dates, so one recorder does not dominate.
4. Save the `prediction_id` with each clip.

The sample must cover the middle scores too, not only the lowest and highest. In this dataset the middle scores have few checks, which makes the Plover threshold uncertain.

### 6.5 Job C: refit thresholds

**When:** when new validations arrive for a species, or on a fixed schedule (for example, monthly).

**What:**

1. Take all validations for the project, species and BirdNET version. Remove repeated checks of the same clip.
2. If there are fewer than 30 validations, do not fit. Status `insufficient_validations`.
3. Fit the Firth logistic regression (`src/birds/firth.py`).
4. Find the threshold (`src/birds/thresholds.py`, function `threshold_in_range`).
5. Compute the uncertainty (1,000 bootstrap samples, fixed seed).
6. Save a **new** row in `species_thresholds` with `is_active = false`.

The whole fit takes about one minute for four species on a laptop, so it can run as a normal background job.

**A person must approve a new threshold** before it becomes active. A new threshold can change the number of observations a lot (for Plover the GLM and Firth differ by a factor of five). The approval screen should show: old and new threshold, the curve figure, the bootstrap range, and how many observations would change.

### 6.6 Job D: label again after a change

When a new threshold is approved, run Job A again for all predictions of that project, species and BirdNET version. Keep the `threshold_id` on each observation, so every result can be traced to the threshold that produced it.

### 6.7 Settings

These are in `config/bird_thresholds.yaml` and should be platform settings:

<table>
<tr><th>Setting</th><th>Value</th><th>Meaning</th></tr>
<tr><td><code>target_precision</code></td><td>0.99</td><td>Required chance that an observation is correct.</td></tr>
<tr><td><code>logit_clip</code></td><td>0.0001</td><td>Scores are limited to 0.0001 to 0.9999 before the logit.</td></tr>
<tr><td><code>min_validations</code></td><td>30</td><td>Fewer validations: no threshold.</td></tr>
<tr><td><code>min_negatives_for_curve</code></td><td>0</td><td>A species with no incorrect clips still gets a curve.</td></tr>
<tr><td><code>ci_level</code></td><td>0.95</td><td>Level for the band and the bootstrap range.</td></tr>
<tr><td><code>bootstrap.n</code>, <code>bootstrap.seed</code></td><td>1000, 20240101</td><td>Number of resamples and random seed.</td></tr>
</table>

The platform should also store the **minimum score used when BirdNET was run** (0.1 in this dataset). Predictions and validation samples only exist above this value, so a threshold close to it (Oriole, 0.104) means that almost every prediction is an observation. If the minimum changes, thresholds must be checked again.

### 6.8 Scope of a threshold

A threshold is valid for **one species, one BirdNET version and one project** (or one region with similar habitat and recorders).

1. **New BirdNET version:** scores change, so thresholds must be fitted again with new validations.
2. **New project or region:** background noise and similar species change, so the same score can mean something different. Start with no threshold and validate.
3. **New species:** no observations until it has enough validations.

### 6.9 Special cases

<table>
<tr><th>Case</th><th>What to do</th></tr>
<tr><td>All validated clips are correct</td><td>Threshold at the lowest validated score, status <code>floored_at_min_validated</code>, alert for more validation.</td></tr>
<tr><td>Curve never reaches 0.99</td><td>No threshold, status <code>not_reached_in_validated_range</code>. Only checked clips can be observations.</td></tr>
<tr><td>Two checks of one clip disagree</td><td>No human label for that clip. Use the threshold.</td></tr>
<tr><td>Firth fit does not converge</td><td>The reference code adds a note. The platform should not activate this threshold and should alert the data team.</td></tr>
<tr><td>Prediction score above the highest validated score</td><td>Normal. If the threshold exists, the prediction is above it.</td></tr>
</table>

### 6.10 Monitoring

Show these on a dashboard for each project and species, and alert when they change a lot:

1. Number of predictions and observations by week.
2. Share of predictions that are observations.
3. Number of validations, and the date of the last threshold fit.
4. Species with no threshold or with a flagged status.
5. Share of observations by hour of the day, compared with the known activity of the species.
6. For each new threshold: how many observations it adds or removes.

### 6.11 How to test the port

Run the platform version on the two files of this dataset. It should give:

1. The thresholds in section 5 (within 0.001).
2. 20,751 observations out of 29,491 predictions.
3. The same `observation_status` for every row as `outputs/birds/birdnet_predictions_with_observations.csv`.

The reference outputs are in `outputs/birds/`. To produce them again, install the package from the repository root and run the module `birds.cli`, as described in the README.

We ran the reference code on Python 3.13, the platform version. It gives the same thresholds and the same `observation_status` for every row. Note: the reference code finds the data through the repository folders, so it must be installed in editable mode. On the platform this does not matter, because the data come from PostgreSQL.


## 7. For the Biometrics team (R)

The Biometrics team works in R. The same model and threshold in R:

```r
library(logistf)

fit = logistf(outcome ~ qlogis(score), data = validations)
coef(fit)
```

`qlogis` is the logit. The threshold is the score `s` where `b0 + b1 × qlogis(s)` equals `qlogis(0.99)`. This gives the crossing point only. The reference code also limits the threshold to the checked score range (section 3, step 3).


## 8. Suggested work items

These can become Jira tickets:

1. Add `prediction_id` to the clips sent to ornithologists, and save it with each answer.
2. Create the tables `validations`, `species_thresholds` and `observations` in PostgreSQL.
3. Port the reference code into a worker service, and add the tests in section 6.11.
4. Job A: label new predictions when a batch is saved.
5. Job B: create validation samples for species without enough checks.
6. Job C and Job D: refit thresholds, save new versions, label again after approval.
7. Approval page for new thresholds.
8. Monitoring dashboard (section 6.10).


## 9. Open questions

1. Should thresholds be shared across projects in the same region, or always fitted for each project?
2. Who approves a new threshold: the Biometrics team or the project lead?
3. Should users also see predictions below the threshold (marked as not confirmed), or only observations?
4. How many validations can the ornithologists do for each new project? This sets the size of the sample in Job B.


## 10. Files

<table>
<tr><th>Path</th><th>Content</th></tr>
<tr><td><code>src/birds/data.py</code></td><td>Load the files and link validated clips to predictions.</td></tr>
<tr><td><code>src/birds/firth.py</code></td><td>Firth logistic regression.</td></tr>
<tr><td><code>src/birds/thresholds.py</code></td><td>Curve fit, threshold search, uncertainty.</td></tr>
<tr><td><code>src/birds/labeling.py</code></td><td>Rules that turn predictions into observations.</td></tr>
<tr><td><code>src/birds/cli.py</code></td><td>Runs the whole process and writes the outputs.</td></tr>
<tr><td><code>config/bird_thresholds.yaml</code></td><td>Settings.</td></tr>
<tr><td><code>notebooks/01_birds_thresholds.ipynb</code></td><td>Analysis with all tables and figures.</td></tr>
<tr><td><code>outputs/birds/</code></td><td>Thresholds, links and labelled predictions.</td></tr>
<tr><td><code>reports/01_bird_observations.md</code></td><td>Results and decisions for question 1.</td></tr>
</table>
