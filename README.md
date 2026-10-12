# Natural State: Senior Data Scientist take-home

This repository solves the two challenges:

1. turning BirdNET predictions into observations, using species-specific thresholds (Wood & Kahl 2024)
2. cleaning, joining and QA/QC of herbaceous vegetation ODK data.

Each challenge also has a handoff document for the Tech team, so the approach can run automatically on NS Analytics.

| # | Deliverable                                                                                  | What it answers                                                                                           |
|---|----------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| 1 | [reports/01_bird_observations.md](reports/01_bird_observations.md)                           | Bird Q1: per-species thresholds at pr(correct) = 0.99, and the `observation` field for every clip         |
| 2 | [reports/02_bird_tech_handoff.md](reports/02_bird_tech_handoff.md)                           | Bird Q2: what the Tech team needs to automate it (data model, jobs, SQL, validation sampling, monitoring) |
| 3 | [reports/03_vegetation_data_quality_report.md](reports/03_vegetation_data_quality_report.md) | Vegetation Q1: data quality report (survey level, plot level, sampling effort, map)                       |
| 4 | [reports/04_vegetation_tech_handoff.md](reports/04_vegetation_tech_handoff.md)               | Vegetation Q2: pipeline, check registry, marts and dashboard spec for automated QA/QC                     |

**Notebooks with the analysis behind the reports:**

- [notebooks/01_birds_thresholds.ipynb](notebooks/01_birds_thresholds.ipynb)
- [notebooks/02_vegetation_qaqc.ipynb](notebooks/02_vegetation_qaqc.ipynb)

## Headline results

**Birds**

- [`outputs/birds/birdnet_predictions_with_observations.csv`](outputs/birds/birdnet_predictions_with_observations.csv)
  has all 29,491 rows, with a new `observation` field; 20,751 of them are observations.
- **Thresholds:**

| Species                     | Threshold                                                  |
|-----------------------------|------------------------------------------------------------|
| Abyssinian Nightjar         | 0.709                                                      |
| Three-banded Plover         | 0.833                                                      |
| African Black-headed Oriole | 0.104 (no false positive in 150 validations)               |
| Red-billed Firefinch        | none (6 of 101 validations correct; 0.99 is never reached) |

- **Key decisions:**
    - Firth logistic regression, because the plain GLM fails when there are no false positives;
    - no extrapolation outside the validated score range;
    - human validations override the threshold;
    - uncertainty reported for every threshold.

**Vegetation** (809 flags from 53 configurable checks; no data changed)

- The **shrubland stratum was never sampled**: 11 locations, 0 registered.
- **All 30 transects run east-west**, while the SOP specifies north/south. Registered transect geometry is often
  implausible, and in 4 surveys the quadrats are offset 10 to 21 m from the registered line.
- **46% of taxa are unidentified morphospecies.** Common species are missing from the species list, and typed names have
  misspellings and duplicate placeholders. So richness is an upper bound.
- **20 quadrats do not saturate plot richness:** median sample coverage is 0.88.
- **The form's "quadrats with species" summary is wrong** in 23 of 32 submissions.
- **Field completeness is 100%:** every quadrat has a photo and a GPS point within 5 m.

## Repository layout

```
Data Birds/, Data Vegetation/     raw inputs as provided (PDFs not committed: third-party paper, internal SOPs)
config/                           bird threshold parameters; vegetation QA/QC check registry (YAML)
src/ns/birds/                     data loading and linking, Firth regression, thresholds, labelling, plots, CLI
src/ns/vegetation/                load, joined model, checks, summaries, maps, report renderer, CLI
src/ns/common/                    paths, config, geometry helpers
notebooks/                        executed analysis notebooks
reports/                          the four Markdown deliverables, figures, the report template
outputs/                          generated CSVs (labelled predictions, thresholds, flags, summaries, clean tables)
tests/                            pytest suite (16 tests)
```

## Reproduce

Requires Python 3.11 or later.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
pytest                                   
python -m ns.birds.cli
python -m ns.vegetation.cli
python -m ns.vegetation.report
jupyter nbconvert --to notebook --execute --inplace notebooks/*.ipynb
```

Everything is deterministic: the bootstrap seed is in the config.

## Language choice

Everything is in Python. That makes the handoff to the Tech team (Python/SQL) direct: the reference implementation *is* the specification.

The statistical methods have standard R equivalents for the Biometrics team:

| Python (this repo)           | R equivalent       |
|------------------------------|--------------------|
| Firth regression             | `logistf::logistf` |
| Chao2, coverage, rarefaction | `iNEXT`            |
