# KeibaAI PhaseG Step1 MeetingBias Architecture Design

## Purpose

MeetingBias is a planned independent evaluation layer for meeting-level bias.
It explains and, in a future approved phase, may score temporary tendencies
created by meeting progression.

This design does not change current evaluators, scores, decisions, Knowledge,
CSV, Explain, Learning, or the official baseline.

## Responsibility

MeetingBias evaluates:

- meeting stage: opening, middle, closing
- meeting day or meeting week
- A/B/C/D course rotation
- accumulated turf wear
- meeting-wide inside or outside tendency
- meeting-wide front or closer tendency
- speed or stamina tendency caused by meeting progression
- durable course-state patterns that persist beyond a single race day

MeetingBias does not evaluate:

- same-day manual track condition input
- individual race pace or field composition
- permanent course geometry
- horse bloodline suitability
- horse ability
- final Decision thresholds
- race-result learning without human review

## Boundary With Existing Layers

### TrackBias

TrackBias describes the same-day racecourse condition:

- today's inside or outside bias
- today's front or closer bias
- current going and visible track tendency
- manual track-bias input

MeetingBias describes accumulated meeting context:

- opening-week freshness
- closing-week wear
- course-rotation recovery
- tendency caused by repeated use of the same course

TrackBias may override MeetingBias in explanation because today's condition is
more immediate. MeetingBias should remain a prior context, not the final
same-day truth.

### CourseKnowledge

CourseKnowledge describes stable course characteristics:

- turn count
- straight length
- hill or flat finish
- common distance-course requirements
- small-turn or large-turn structure

MeetingBias describes temporary changes on top of that stable course:

- the inside rail wearing after repeated use
- B-course rotation improving the inner lane
- closing-week stamina demand
- opening-week speed preservation

### RaceShape

RaceShape describes the current race's expected flow:

- pace pressure
- running-style composition
- expected position advantage
- front collapse or front remaining caused by this field

MeetingBias describes the race environment before field-specific pace is known:

- meeting stage
- surface wear
- lane tendency
- course-rotation state

RaceShape and MeetingBias can point in different directions. For example,
RaceShape may say high pace favors closers while MeetingBias says opening turf
can still support position. The Explain layer should show this as two separate
layers, not as a contradiction.

## Knowledge Structure Options

### Option A: Simple Course JSON

```text
knowledge/meeting_bias/
  hakodate.json
  fukushima.json
  kokura.json
  ...
```

Each file contains:

- course-level notes
- surface_profiles
- distance_category
- meeting_stage
- features
- cautions
- explain

Benefits:

- compatible with the current `MeetingBiasEngine`
- easy to maintain
- easy to review manually
- simple Shadow validation scope

Drawbacks:

- large JSON files as knowledge grows
- harder to version individual course weeks
- course-rotation detail can become dense

### Option B: Course Directory By Meeting Stage

```text
knowledge/meeting_bias/
  hakodate/
    opening.json
    middle.json
    closing.json
    rotation.json
  fukushima/
    opening.json
    middle.json
    closing.json
    rotation.json
```

Benefits:

- clearer separation by meeting stage
- easier targeted Knowledge edits
- good fit for human review and approvals
- Shadow validation can target one file or one stage

Drawbacks:

- requires loader changes
- more files to manage
- migration needed from current JSON layout

### Option C: Rule-Pack Layout

```text
knowledge/meeting_bias/
  rules/
    turf_opening_speed.json
    turf_closing_outer_closer.json
    dirt_1700_meeting_wear.json
  courses/
    hakodate.json
    fukushima.json
```

Benefits:

- reusable patterns across courses
- good for advanced Learning Candidate aggregation
- strong Shadow validation granularity

Drawbacks:

- more abstraction
- higher risk of hidden broad effects
- harder to explain to humans unless tooling is strong

## Recommended Knowledge Architecture

Use Option A for the next implementation phase, with a schema strict enough to
migrate later to Option B.

Recommended shape:

```json
{
  "course": "hakodate",
  "version": "phase_g",
  "score_enabled": false,
  "surface_profiles": {
    "turf": {
      "sprint": {
        "opening": {
          "inside_outside_tendency": "inside",
          "front_closer_tendency": "front",
          "turf_wear": "low",
          "features": [],
          "cautions": [],
          "explain": ""
        }
      }
    },
    "dirt": {
      "middle": {
        "closing": {
          "inside_outside_tendency": "neutral",
          "front_closer_tendency": "stalk",
          "turf_wear": "not_applicable",
          "features": [],
          "cautions": [],
          "explain": ""
        }
      }
    }
  },
  "course_rotation": {
    "A": {},
    "B": {},
    "C": {},
    "D": {}
  }
}
```

## Input Information

Primary inputs:

- racecourse
- race_date
- surface
- distance
- track_condition
- meeting_stage
- meeting_week
- meeting_day
- course_rotation

Optional future inputs:

- turf wear observation
- lane condition observation
- water content
- same-day result trend
- manual meeting-bias override
- official JRA course-use metadata

Fallback policy:

- explicit `meeting_stage` first
- meeting week
- meeting day
- race_date-derived estimate
- `middle` if insufficient

The detector must always return only `opening`, `middle`, or `closing`.

## Evaluator Structure

Future structure:

```text
MeetingBiasEvaluator
  -> MeetingStageDetector
  -> MeetingBiasKnowledgeLoader
  -> MeetingBiasScorer
  -> MeetingBiasExplainBuilder
  -> ShadowValidationFramework
```

Initial scoring output should be isolated:

```text
meeting_bias_score
meeting_bias_score_raw
meeting_bias_score_weighted
meeting_bias_comment
meeting_bias_factors
meeting_bias_warnings
meeting_bias_source
meeting_bias_confidence
score_impact
```

Before approval, `score_impact` remains `none`.

## Explain Structure

Explain should identify MeetingBias as meeting-wide context:

```text
Meeting Bias
- Layer: 開催全体の傾向
- Stage: closing
- Surface/Distance: turf middle
- Course rotation: B
- Summary: 開催終盤で芝の傷みが進み、外差しと持続力に注意。
- Relation: 当日のTrackBiasとは別レイヤーとして参照。
```

Explain must not imply:

- this is the same as today's TrackBias
- this alone predicts race pace
- this changes Decision before scoring approval

## Shadow Validation Policy

MeetingBias must use the PhaseF corrected Shadow Validation Framework.

Comparison layers:

```text
OFFICIAL
ZERO_DELTA_BASELINE
SHADOW
```

Corrected effect:

```text
SHADOW - ZERO_DELTA_BASELINE
```

Required metrics:

- official_to_zero_delta_changes
- official_to_shadow_changes
- zero_delta_to_shadow_changes
- redecision_drift_excluded
- target_corrected_changes
- non_target_corrected_changes
- cross_race_corrected_changes
- FN improvement
- FP creation

Acceptance requires:

- official baseline unchanged
- cross-race corrected changes = 0
- no broad same-race side effects
- improvements explainable by MeetingBias only

## Learning Integration

Learning Candidate records should store:

- meeting_bias_primary_factor
- meeting_bias_secondary_factors
- meeting_stage
- surface
- distance_category
- course_rotation
- candidate_scope
- zero_delta_baseline_enabled
- corrected_shadow_diff_enabled
- root_confidence
- human_review_status

Learning must not auto-edit Knowledge or scores.

## Implementation Order

1. Freeze this design.
2. Add a read-only `MeetingBiasKnowledgeLoader` if needed.
3. Add `MeetingBiasEvaluator` with `score_impact = none`.
4. Generate MeetingBias shadow candidates from reviewed FN/FP cases.
5. Shadow-validate one narrow candidate.
6. Human-review candidate.
7. Only after approval, allow a limited scoring experiment.

## Implementation Cautions

- Do not mix MeetingBias with TrackBias in the same score field.
- Do not infer same-day bias from meeting stage alone.
- Do not let race_date fallback pretend to be official meeting-day metadata.
- Keep surface and distance-category selection explicit.
- Avoid broad course-wide changes without Shadow validation.
- Keep Explain wording layered and non-absolute.

