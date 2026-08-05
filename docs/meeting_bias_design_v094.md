# KeibaAI Ver0.94 MeetingBias Design

## 1. Purpose

MeetingBias handles meeting-level context that RaceShape and TrackBias should
not own.

MeetingBias covers:

- meeting stage: opening, middle, closing
- course rotation: A / B / C / D
- turf wear
- tendency changes caused by meeting progression
- meeting-level inside/outside, front/closer, speed/stamina hints

TrackBias remains responsible for same-day track tendencies, such as front
remaining, closer-friendly, inside advantage, outside advantage, and current
track condition.

## 2. Data Structure

The initial structure is non-scoring.

```text
meeting_stage
course_rotation
turf_wear
inside_bias
outside_bias
front_bias
closer_bias
speed_bias
stamina_bias
```

Additional metadata:

```text
meeting_bias
meeting_bias_comment
meeting_bias_factors
meeting_bias_flags
meeting_bias_warnings
meeting_bias_source
meeting_bias_ready
score_impact
```

`score_impact` is fixed to `none` in Ver0.94.

## 3. Knowledge Structure

Planned layout:

```text
knowledge/meeting_bias/
  meeting_bias_template.json
  sapporo.json
  hakodate.json
  fukushima.json
  niigata.json
  tokyo.json
  nakayama.json
  chukyo.json
  kyoto.json
  hanshin.json
  kokura.json
```

Ver0.94 adds only the template.  Course files should be added after the manual
input policy is fixed.

## 4. MeetingBiasEngine

New class:

```python
MeetingBiasEngine
```

Primary API:

```python
analyze(race_context=None, meeting_knowledge=None) -> dict
```

This API returns a stable shape for future connection, but does not change any
existing evaluator, score, decision, or confidence output.

## 5. Explain Design

Future ExplainEngine examples:

- Opening turf meeting with low wear. Inside/front hints are available.
- Closing turf meeting with high wear. Outside/closer stamina hints are noted.
- B-course rotation may reduce inner wear and support position advantage.

These comments should be explanatory only until a scoring policy is approved.

## 6. Future Connection Policy

MeetingBias may later provide context to:

- TrackBias: meeting-level hints can complement same-day bias.
- RaceShape: meeting stage can explain why an apparent pace bias may be softened.
- Decision: meeting uncertainty can add caution text, not direct scoring at first.
- ExplainEngine: meeting context can be included in natural language reasons.

Ver0.94 does not connect MeetingBias to these components.

## 7. Non-Goals

Ver0.94 does not implement:

- automatic meeting-day inference
- result-based learning
- score calculation
- FinalScore adjustment
- RaceShape adjustment
- TrackBias adjustment
- Decision / Confidence changes
