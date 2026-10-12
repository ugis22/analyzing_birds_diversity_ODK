# Herbaceous vegetation: data quality report

**Project:** Savanna Monitoring Pilot, area Lewa (LW), baseline 2026
**Surveys:** {{DATE_FIRST}} to {{DATE_LAST}}, {{N_SUBMISSIONS}} submissions by {{N_RECORDERS}} recorders ({{RECORDERS}})

This report answers vegetation question 1 of the brief: a data quality report with (a) a survey level summary, (b) a plot level summary, (c) an assessment of sampling effort and (d) a map of transect locations.

**No data were changed.** As the brief asks, every problem is **flagged, not fixed**. The numbers and tables in this report are produced by the code (the module `vegetation.report`), so they always match the data.

The handoff for the Tech team is in [`04_vegetation_tech_handoff.md`](04_vegetation_tech_handoff.md). The analysis is in [`notebooks/02_vegetation_qaqc.ipynb`](../notebooks/02_vegetation_qaqc.ipynb).


## Main findings

1. **One stratum was never sampled.** The design has {{N_PLANNED}} prescribed locations. {{N_REGISTERED}} were registered and {{N_SURVEYED}} were surveyed. None of the {{N_UNSAMPLED_LOCATIONS}} locations in the stratum **{{UNSAMPLED_STRATA}}** was registered, so the results describe the savanna only.
2. **Transects do not follow the north/south rule.** The SOP asks for transects along the north/south axis. {{N_NOT_NS}} of {{N_TRANSECTS}} registered transects are more than 20 degrees away from it; their bearings go from {{BEARING_MIN}} to {{BEARING_MAX}} degrees, so they run roughly east to west.
3. **Registered transect geometry is often not plausible.** {{N_LENGTH_OFF}} transects are not close to 50 m long (from {{LEN_MIN}} to {{LEN_MAX}} m), and in {{N_NOT_STRAIGHT}} the midpoint is not on the line from A to B. In {{N_OFF_LINE}} surveys the quadrats lie more than 10 m away from the registered line.
4. **Many taxa are not identified.** {{N_UNKNOWN_TAXA}} of {{N_TAXA}} taxa ({{UNKNOWN_SHARE}}) are unidentified morphospecies (`herb_xxx`). {{SHARE_FREE_RECORDS}} of all records come from the additional species section (typed names and unknown placeholders), not from the species list. Typed names have spelling problems and duplicates. So the richness numbers are an upper limit.
5. **Twenty quadrats do not find all species in a plot.** The median sample coverage in a plot is {{PLOT_COV_MEDIAN}}. The last 5 quadrats still add {{GAIN_LAST_5}} taxa on average.
6. **The form summary is wrong.** The number of "quadrats with species" saved by the form differs from the records in {{N_QWS_WRONG}} submissions.
7. **Field completeness is very good.** Every quadrat has a photo and a GPS point, and every GPS point is accurate to 5 m or better.


## How the data were processed

### Steps

1. **Load.** Read the 4 ODK exports and the 11 entity lists as delivered.
2. **Clean.** Give short names to the columns and parse times (UTC), numbers and lists. No value is changed or removed.
3. **Join.** Link the tables:

<table>
<tr><th>From</th><th>To</th><th>Key</th></tr>
<tr><td>survey</td><td>quadrat</td><td><code>KEY</code> to <code>PARENT_KEY</code></td></tr>
<tr><td>quadrat</td><td>additional species</td><td><code>KEY</code> to <code>PARENT_KEY</code></td></tr>
<tr><td>survey</td><td>vegplot entity</td><td><code>selected_plot_uuid</code> to <code>__id</code></td></tr>
<tr><td>vegplot entity</td><td>centroid and registration</td><td><code>plot_uuid</code> to centroid <code>__id</code></td></tr>
<tr><td>quadrat</td><td>species list</td><td>each id in <code>selected_herb_species_uuids</code></td></tr>
<tr><td>additional species</td><td>species_extra and species_extra_ids</td><td>placeholder entity id and number</td></tr>
</table>

4. **Place quadrats on the transect.** Each quadrat GPS point is projected onto the registered line from A to B. This gives the distance along the line and the distance to the side.
5. **Check.** Run {{N_CHECKS}} checks, defined in `config/veg_qaqc_checks.yaml`. Each check gives a list of flags.
6. **Summarise.** Count flags and compute richness and coverage.

### Flags

Each flag has a severity:

<table>
<tr><th>Severity</th><th>Meaning</th><th>Flags</th></tr>
<tr><td>error</td><td>Must be solved, or accepted on purpose, before the data are used.</td><td>{{N_ERROR}}</td></tr>
<tr><td>warning</td><td>A person should look at it. The data may be fine.</td><td>{{N_WARNING}}</td></tr>
<tr><td>info</td><td>Context for the reviewer. Never blocks the data.</td><td>{{N_INFO}}</td></tr>
</table>

In total there are **{{N_FLAGS}} flags**. The status of a survey or plot is **Error** if it has at least one error, **Warning** if it has at least one warning, and **OK** otherwise.

### Analysis set

The summaries use all surveys that were **not rejected** in review. {{N_REJECTED}} submissions were rejected; both are second surveys of a plot that was surveyed twice on the same day. Each placeholder morphospecies counts as one taxon. Later identifications are shown next to the data, not applied.

### A note on species names

The SOP asks for typed names as `Genus_species`, with an underscore. In the exported data the names use a space (`Genus species`), the same as the species list. The checks compare names in this stored form.


## a. Survey level summary

Status of the surveys in the analysis set: **OK {{N_SURVEYS_OK}}, Warning {{N_SURVEYS_WARN}}, Error {{N_SURVEYS_ERR}}**. The table also shows the 2 rejected submissions.

How to read some columns:

1. **quadrats with species (form):** the number computed from the records, and in brackets the number saved by the form. They should be equal.
2. **taxa:** number of different taxa in the survey, counting each unknown placeholder as one taxon.
3. **distance from line (m):** median side distance of the 20 quadrats from the registered transect line. The belt is 2.5 m on each side, so values much larger than 2.5 m mean that the survey was not done on the registered line, or the registered line is wrong.

{{SURVEY_TABLE}}

### Errors

All errors are listed below. Most are quadrats where the form says "additional species present" but no species was added.

{{ERROR_TABLE}}

### Most common warnings

1. **Position:** quadrats far from the registered line (Q04), beyond the ends (Q05) or far from both neighbours (Q06). Plots 05, 07, 13 and 27 are the clearest cases (S18).
2. **Form summary:** the saved number of quadrats with species is wrong (S13).
3. **Names:** typed names that are not in the canonical form (R05), the same name under several placeholders (R08), and identifications that say a record is a duplicate or should be excluded (R10).


## b. Plot level summary

The table shows the {{N_REGISTERED}} registered plots. Diversity uses the accepted survey of each plot.

How to read some columns:

1. **Chao2:** estimate of the total number of taxa in the plot, including those the 20 quadrats missed.
2. **coverage:** sample coverage. A value of 0.88 means that, in a new quadrat, about 12% of the species records would be taxa not yet found in the plot.
3. **Hill N1:** effective number of common taxa, from quadrat frequencies.
4. **unknown share:** share of the taxa that are unidentified placeholders.

{{PLOT_TABLE}}

Notes:

1. Plot 23 was registered as **not viable** ("On private property"). Backup plot 46 was surveyed instead, as the SOP asks.
2. The midpoint of plot 14 is 34 m from the prescribed centroid. The SOP allows at most 25 m.
3. Plot 19 has a registered transect of only 23 m.
4. Richness goes from {{RICH_MIN}} to {{RICH_MAX}} taxa, with a mean of {{RICH_MEAN}}.


## c. Assessment of sampling effort

### Design coverage

{{COVERAGE_TABLE}}

All primary savanna locations except one (not viable) were registered and surveyed. The **{{UNSAMPLED_STRATA}}** stratum has no registered plot. This is the largest gap in the data: the project cannot report on this stratum.

### Field completeness

{{COMPLETENESS_TABLE}}

### Effort by day and recorder

{{EFFORT_TABLE}}

### Are 20 quadrats enough?

![Species accumulation inside plots and across plots](figures/veg_species_accumulation.png)

1. **Inside a plot:** on average, the first 10 quadrats find {{SHARE_AT_10}} of the taxa found by all 20, and the last 5 quadrats still add {{GAIN_LAST_5}} taxa. The curves do not flatten.
2. **Coverage:** the median plot coverage is {{PLOT_COV_MEDIAN}} (lowest {{PLOT_COV_MIN}}). {{N_COV_BELOW_090}} plots are below 0.90.
3. **Chao2:** in {{N_CHAO_GAP}} plots the Chao2 estimate is more than 1.5 times the observed richness.
4. **Across plots:** {{N_TAXA}} taxa were observed and Chao2 estimates {{CHAO2}}. {{Q1}} taxa were found in only one plot.

**Conclusion:** 20 quadrats give a fair but incomplete picture of each plot. The data support comparisons of frequent species between plots. Richness of single plots should be reported with its coverage, or compared at the same coverage.

### Identification quality

{{N_UNKNOWN_TAXA}} of {{N_TAXA}} taxa ({{UNKNOWN_SHARE}}) are unidentified morphospecies. The most frequent taxa:

{{TOP_TAXA_TABLE}}

Some frequent species, such as *Tephrosia purpurea*, are not on the species list, and three of the most frequent taxa are still unidentified. Updating the species list and identifying the placeholders would improve the data more than any other single action.


## d. Map of transect locations

### Overview

![Map of all prescribed locations](figures/veg_map_overview.png)

*Each point is a prescribed location (centroid). Colour shows the state. Squares are backup locations. Rings mark the stratum that was never registered.*

An interactive map with satellite images, registered transects and every quadrat is in [`figures/veg_map_interactive.html`](figures/veg_map_interactive.html). Download it and open it in a browser.

### Plot details

![Four plots in detail](figures/veg_map_plot_details.png)

*Each panel is drawn in metres around the prescribed centroid. The blue line is the registered transect with its 5 m belt. The dashed circle is the 25 m limit for the midpoint. The dotted line is the north/south direction asked for by the SOP. Points are quadrats; red ones have a position flag.*

1. **Plot 16:** quadrats follow the registered line well. It still runs east to west.
2. **Plot 05:** the quadrats are 21 m (median) from the registered line. Either the survey was done elsewhere, or the line was registered wrongly.
3. **Plot 19:** the registered transect is only 23 m long, and several quadrats are far from it.
4. **Plot 14:** the midpoint is 34 m from the centroid, beyond the 25 m limit.

### Transect direction

![Histogram of transect directions](figures/veg_transect_bearings.png)

All registered transects run between {{BEARING_MIN}} and {{BEARING_MAX}} degrees, far from the north/south axis. Because this is true for every plot, it is most likely a systematic difference in the field method, not a GPS error. It should be discussed with the field team before the next survey.

In {{N_WALK_ORDER}} surveys, quadrats 1 to 10 move away from endpoint A and quadrats 11 to 20 come back. The SOP places two quadrats at each 5 m mark, one on each side. This does not change the data much, but it is a different method.


## Appendix

### Flags by level and severity

{{LEVEL_TABLE}}

### All checks

{{CHECK_TABLE}}

### Outputs

All tables are in `outputs/vegetation/`:

<table>
<tr><th>File</th><th>Content</th></tr>
<tr><td><code>qa_flags.csv</code></td><td>One row for each flag.</td></tr>
<tr><td><code>survey_summary.csv</code>, <code>plot_summary.csv</code></td><td>Tables a and b.</td></tr>
<tr><td><code>design_coverage.csv</code>, <code>field_completeness.csv</code>, <code>daily_effort.csv</code>, <code>taxon_frequency.csv</code></td><td>Tables for section c.</td></tr>
<tr><td><code>clean_plots.csv</code>, <code>clean_surveys.csv</code>, <code>clean_quadrats.csv</code>, <code>clean_species_records.csv</code></td><td>Clean, joined tables, with the values as recorded.</td></tr>
<tr><td><code>catalogue.csv</code></td><td>List of checks.</td></tr>
</table>
