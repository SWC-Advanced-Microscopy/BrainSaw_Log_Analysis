# BakingTray log analysis: details

Supplement to [README.md](README.md).
Sections: [corpus](#corpus), [deduplication](#deduplication), [restarts](#restarts), [validation](#validation), [tables](#tables), [running](#running).


## Corpus

The logs had accumulated in four overlapping storage locations: a November 2024 snapshot, a later sync of the same tree, a fresh sync, and a recovered archive that was the only source for two labs (`murray` and `histology`).
`MERGED_LOGS` is their union, keeping one copy per relative path; every same-path collision was checked to be byte-identical first.
The four source trees no longer exist, so `MERGED_LOGS` is now the only copy.

An acquisition log looks like this:

```
2022/01/13 18:21:34 -- STARTING NEW ACQUISITION
Using BakingTray version 94d365b3eebc7086a2b53e8b62b2e863ff66b28a
2022/01/13 18:21:34 -- STARTING section number 1 (1 of 357) at z=27.0500 in directory F:\...
2022/01/13 18:22:48 -- acquired 108 tile positions in 1 mins 14 secs
2022/01/13 18:24:00 -- FINISHED section number 1, section completed in 2 mins 25 secs
```

Co-imaged samples share one byte-identical log, copied into each sample's directory.
Section durations are worded seven ways over the ten years, and tile positions were not logged before 2017.


## Deduplication

Stage 01 reduces 10,917 recipe files to 7,090 samples, applying these rules in order.
Choosing each directory's recipe before removing copies across directories matters: done the other way round, a directory could lose its original recipe as a copy of another directory's and keep a false start instead.

| Step | Recipes |
|---|---:|
| Backup copies in `logfiles*/` ignored | 10,917 → 10,816 |
| One per sample directory: the one matching the directory's log (drops restart and false-start recipes) | → 10,098 |
| Identical content and sample name in another directory | → 7,202 |
| Same microscope, sample name and run (log start), content differing | → 7,186 |
| Uncropped recipe in the directory above the per-sample directories | → 7,146 |
| The run with fewer samples, of each of the 22 pairs resumed into a new directory | → 7,101 |
| Test runs: five or fewer sections in total (7 runs, listed in `test_runs.csv`) | → 7,090 |

Content alone cannot identify a duplicate.
In 82 of 1,676 multi-sample acquisitions the name inside the recipe was not updated on cropping, so the samples' recipe files are byte-identical; hashing alone would merge 333 distinct samples.
Acquisition logs are deduplicated the same way, leaving 7,184.

Every discarded recipe is listed, with the one kept, in `resume_recipes.csv` or `unsplit_recipes.csv`.
The resumed pairs are in `new_directory_resumes.csv`, with the reason each qualifies.
Twelve start at the depth where the first run would have cut its next section (e.g. `ML159_…_JK_2_B` stopped at z = 24.0528 mm and `…_JK_2_C` began there 54 h later).
The other ten are matched by name: two continue the section numbering, eight follow a first run of 1–64 sections.
Related names the rule keeps apart (a whole brain re-imaged) all had first runs of 93 sections or more.
Where the first attempt was never cropped and the resumed run was, the resumed run's samples are counted (e.g. `AF_PCA_19_20_22_25`: four brains, not one).


## Restarts

Stage 03 found 311 restarts: 289 in the logs and 22 between runs resumed into a new directory.
100 came after five or fewer sections and are set aside in `setup_restarts.csv`.
An earlier rule, which looked for a cluster of header lines away from the top of the file, missed 63 restarts within about ten lines of the opening header; all were setup restarts.

| Category | Restarts | Unplanned |
|---|---:|---|
| User abort | 53 | no |
| Stopped normally (`FINISHED AND COMPLETED`) | 29 | no |
| Stopped normally (`Found no tissue`) | 5 | no |
| Laser fault | 39 | yes |
| Unexplained | 85 | yes |

Laser faults ran from January 2018 to 19 December 2025, in 26 acquisitions, peaking at 12 in 2019 and 9 in 2021.

Unexplained stops, by downtime before the restart:

| Downtime | Restarts |
|---|---:|
| < 30 min | 31 |
| 30–60 min | 14 |
| 1–6 h | 14 |
| 6–24 h | 22 |
| > 24 h | 4 |

The median is 51 min.
The long gaps, with no error text, suggest a hung process, an uncaught dropped connection or a reboot rather than one software bug.
Unexplained stops follow each lab's share of the workload (`mrsic_flogel`: 55% of them, 59% of samples).

The per-year rates in the figure use the 3,245 acquisitions that have a log; the overall restart rate uses all 3,251.
Averaged over the yearly values for 2020–2026 there is one unplanned restart per 34 acquisitions and per 470 imaging hours; pooled over those years, one per 31 and per 418 h.


## Validation

Each key quantity is re-derived by a route the pipeline does not use; the checks and their plots are in [validation.md](validation.md).


## Tables

All in `raw/derived_data/`, written by the pipeline and never edited by hand.
Paths are stored relative, as `MERGED_LOGS/<lab>/...`; `paths.abs_log` resolves them.

| File | One row per | Rows | Contents |
|---|---|---:|---|
| `fig_samples_dated.csv` | sample | 7,090 | lab, acquisition key, path, date |
| `fig_acq_resolution.csv` | acquisition | 3,251 | XY pixel size and band |
| `acquisition_metrics.csv` | logged acquisition | 3,245 | imaging and wall-clock time, tiles, sections, starts |
| `fig_failures.csv` | restart per log file | 431 | `event_key` (211 restarts), `acq_key` (180 acquisitions), category, downtime |
| `fig_per_year.csv` | year | 11 | acquisitions, hours, tiles, restarts by category, rates |
| `acq_timing_index.csv` | acquisition | 3,243 | settings, brains, depth and hours; unfiltered |
| `acq_timing_sections.csv.gz` | section | 874,156 | cumulative time and tiles against depth |
| `fig_timing_cohort.csv` | acquisition | 632 | timing-figure cohort, averaging capped |
| `fig_timing_averaging.csv` | acquisition | 791 | the same, averaging uncapped |

Intermediate and audit tables: `unique_recipes.txt`, `unique_acqlogs.txt`, `duplicate_groups.csv`, `resume_recipes.csv`, `unsplit_recipes.csv`, `new_directory_resumes.csv`, `test_runs.csv` (01); `sample_acquisition_groups.csv` (02); `restart_events_full.csv`, `setup_restarts.csv` (03); `acquisition_metrics_per_logfile.csv` (05).

Acquisition keys name the microscope and start time, in two formats that do not join directly:
`brainsaw|220726_114752` (recipe start time; sample and resolution tables) and
`brainsaw|2016/11/04 18:44:17` (log start time; all log-derived tables).
A run resumed into a new directory takes the key of the run it resumed.


## Running

`write_derived_data.py` runs stages 01–08 as separate processes, checks that the logs are unpacked first, and stops at the first failure.
Options: `--from NN` resumes at a stage, `--with-diagnostics` adds stage 04, `--list` prints the stages, `--quiet` hides their output.
Each stage can also be run by hand, in order.

Stages 01–08 need Python 3.9+ and the standard library only; the figure scripts and stage 09 need `numpy` and `matplotlib`.
`acquisition_timing.py` does not use `raw/figure_style.py`, so the two figures can change independently.
