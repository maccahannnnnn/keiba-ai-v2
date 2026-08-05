# KeibaAI Ver1.0 Freeze

Freeze date: 2026-07-19

Version name: KeibaAI Ver1.0

## Project Purpose

KeibaAI is an explainable horse-racing analysis system. It reads TARGET/JRA-style race data, links entry and horse-history data, evaluates each horse through multiple transparent evaluators, produces race-level decisions, stores prediction and review snapshots, and supports later comparison against official results.

Ver1.0 is frozen as the reproducible baseline before Ver1.1 development. This freeze is a reference point for future comparison, regression checks, and review-based improvement.

## Development Philosophy

- Keep the prediction pipeline explainable.
- Preserve the separation between scoring, decision, review, learning storage, and reporting.
- Do not let review or learning modules automatically rewrite scores, Knowledge, CSV files, or decisions.
- Treat TrackBias and MeetingBias as distinct layers.
- Keep MeetingBias explain-only at Ver1.0.
- Prefer additive diagnostics and reports over hidden score changes.

## System Structure

Major directories:

- `analyzer/`: legacy analysis and reporting components.
- `archive/`: prediction archive storage and search foundation.
- `dashboard/`: dashboard-facing data generation layer.
- `data/`: templates, sample files, analysis inputs, official results, and generated feature files.
- `docs/`: architecture, design notes, and this Ver1.0 freeze record.
- `engine/`: core output, decision, confidence, explain, review, learning, and MeetingBias engines.
- `evaluation/`: TARGET adapters, trial runners, race-shape, result comparison, and evaluator orchestration.
- `evaluators/`: shared evaluators for course shape, lap, score weight, and track bias.
- `importer/`: TARGET/JRA CSV import and normalization.
- `knowledge/`: course, bloodline, pace, track-bias, race-level, and meeting-bias Knowledge.
- `learning/`: statistics and learning-history summarization/export.
- `review/`: self-review layer.
- `reports/`: generated runtime reports.

## Completed Features

- TARGET entry CSV import, including headered formats and headerless fixed-column formats.
- TARGET horse-history CSV import.
- Entry/history horse-name linking.
- RaceContext construction.
- RaceStructure generation.
- RacePace prediction.
- RaceShape evaluation with Ver0.91a front/escape relaxation.
- CourseShape evaluation.
- TrackCondition evaluation.
- TrackBias manual input and neutral handling.
- TrackBias result comparison tools.
- FinalScore integration.
- Impact evaluation.
- DecisionEngine with TrackBias BUY guard and top-score PASS rescue to CAUTION.
- RaceDecisionEngine with PLAY promotion guard.
- ConfidenceEngine.
- ExplainEngine with separated RaceShape / TrackBias / MeetingBias layers.
- FinalOutputFormatter.
- TrialReportExporter.
- ReviewRecorder.
- ResultImporter and TARGET Result Adapter.
- ReviewEngine.
- ImprovementAdvisor.
- LearningDatabase.
- LearningEngine storage and statistics foundation.
- StatisticsEngine / StatisticsResult / StatisticsExporter.
- PredictionArchive.
- DashboardCore.
- RaceFileLocator data-layout support.

## MeetingBias Current Position

MeetingBias is present as an explain-only layer.

- Knowledge exists under `knowledge/meeting_bias/`.
- MeetingBiasEngine selects Knowledge by racecourse, surface, distance category, and meeting stage.
- Current `score_impact` is fixed to `none`.
- MeetingBias is not connected to FinalScore.
- MeetingBias is not connected to Decision.
- MeetingBias is not connected to TrackBias scoring.
- MeetingBias is displayed as a separate explanation layer so that race-specific RaceShape and meeting-wide tendencies can coexist.

## Explain Structure

Ver1.0 Explain separates the following layers:

- Race Structure: race conditions and key evaluation points.
- Race Shape: this race's expected pace, running styles, and formation.
- Track Bias: same-day track tendency, inside/outside and front/closer bias.
- Meeting Bias: meeting-wide and course-wide tendency, including surface and distance category.
- CourseShape, Lap, Weight, strengths, weaknesses, risks, and consistency diagnostics remain separate supporting explanations.

This separation is intended to reduce apparent contradictions such as:

- RaceShape: very fast pace may help closers.
- MeetingBias: small-turn dirt may still have a front/stalk meeting tendency.
- TrackBias: neutral when no manual or same-day bias is supplied.

## Decision Improvement History

- TrackBias BUY Promotion Guard was added to prevent TrackBias-only promotions from turning non-BUY horses into BUY without meaningful ranking improvement.
- Neutral-time BUY horses are protected from TrackBias Guard suppression.
- RaceDecision PLAY Guard was added to avoid PLAY promotion driven only by TrackBias-sensitive BUYs.
- Top-score PASS rescue was added so high-ranked, high-score PASS horses can remain CAUTION instead of being dropped solely by accumulated risk/conflict.
- Ver0.91c Decision diagnostics added risk/conflict details and traces without changing decisions.
- Ver0.92 and Ver0.93 review cycles checked Risk/Conflict and escape/front double-penalty behavior.

The Ver1.0 freeze keeps existing BUY thresholds, PASS thresholds, FinalScore, RaceShape, Impact, RaceDecision, and Confidence logic unchanged from the current completed state.

## Review Results

Freeze baseline values:

- Review target: 38 complete races.
- Target horse rows: 532.
- MeetingBias display rate: 100%.
- Major Explain contradictions: 0.
- MeetingBias `score_impact`: `none`.
- FinalScore changed by MeetingBias: no.
- Decision changed by MeetingBias: no.

Explain consistency review:

- A/B/C/D review target: 38 races.
- A complete consistency: 5.
- B mostly consistent: 21.
- C minor tension: 12.
- D major contradiction: 0.
- Turf consistency: 24/24 A or B.
- Dirt consistency: 2/14 A or B, with minor RaceShape vs MeetingBias tension concentrated around very-fast small-turn dirt races.

## Protected Areas

The following are protected as Ver1.0 baseline behavior unless a later version explicitly changes them:

- Analyzer behavior.
- TARGET CSV specifications.
- Importer behavior.
- Knowledge structure and existing Knowledge values.
- FinalScore formula.
- RaceShape scoring and pace classification.
- ImpactEvaluator behavior.
- DecisionEngine BUY/PASS/CAUTION thresholds.
- RaceDecisionEngine thresholds.
- ConfidenceEngine behavior.
- TrackBiasEvaluator scoring.
- MeetingBias score isolation.
- Self Review storage-only behavior.
- Review and Learning storage-only behavior.
- `main.py` basic flow.

## Known Limitations

- Meeting stage currently often defaults to `middle` when the race context does not supply a concrete meeting stage.
- MeetingBias is not yet score-aware and cannot adjust predictions.
- TrackBias remains neutral unless manual or explicit bias data is supplied.
- Same-day track trend auto-detection is not implemented.
- MeetingBias and RaceShape can intentionally point in different directions because they describe different layers.
- Bloodline profiles remain incomplete for some sires and broodmare sires.
- Top5 ranking and Decision can still diverge when risk/conflict is high.
- Official result comparison depends on available result files and successful horse-name matching.

## Ver1.1 Candidates

- Add explicit meeting-stage input or derivation.
- Improve MeetingBias wording for dirt 1700m and very-fast pace coexistence.
- Add same-day TrackBias auto-calculation as a separate, reviewable module.
- Expand bloodline Knowledge coverage.
- Continue Decision diagnostics on Top5 PASS good performers.
- Improve result-review aggregation and recurring regression reports.
- Add non-scoring consistency checks between RaceShape, TrackBias, and MeetingBias.

## Ver1.0 Operation Rules

- Use TARGET entry and horse-history CSV pairs under `data/analysis/`.
- Keep official result files under `data/results/` using RaceFileLocator-compatible names.
- Run `TargetTrialAdapter.run()` for race-level prediction.
- Use `manual_track_bias=None` or neutral unless a human explicitly supplies TrackBias.
- Treat MeetingBias as explanation only.
- Do not update Knowledge from review results automatically.
- Do not rewrite CSV files during analysis or review.
- Use ReviewEngine and TrackBiasResultComparator for post-race review.
- Use this freeze file and `docs/keibaai_v1_0_file_manifest.txt` as the Ver1.0 baseline reference.
