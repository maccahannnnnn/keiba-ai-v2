# PL+Jockey Decision Addendum — Human interpretation note v1

Human decision: `APPROVE_PLJ_ADDENDUM_STEP1_COMPLETION_V1`.

This note interprets, but does not edit or re-freeze, `KeibaAI_PL_Jockey_Prospective_Decision_Addendum_v1.md` (SHA256 `841b1b76df873d4e106b34af17fac2b1b644fdf98018d07e3b8ba34a4159787e`). The parent PL+Jockey protocol remains unchanged.

`ELIGIBLE_RACE` means one unique race in the frozen Current authority where `current_k > 0` **and** the PL+Jockey PRE has the same race and `candidate_k == current_k` with matching selected-slot count. Count from the frozen per-race Current/PL+Jockey identities, not from an artifact's possibly broad `eligible_race_count` (which may mean all processed races). A race failing identity is a STOP, not an excluded race to make the gate pass. Count each eligible race once per eligible date.

For the new Positive Decision Gate, dates eligible for credit must have a pre-first-start, Result-blind freeze after the addendum freeze and must not be designated Development, Diagnostic B, or another reference-only role. 2026-10-31 and 2026-11-01 are `PRE_ADDENDUM_OBSERVATION`, regardless of their existing PL+Jockey prospective status. No date on or before the addendum freeze calendar date can receive new-gate credit.

At the first crossing of both 12 dates and 60 eligible races, record `FIRST_CHECKPOINT_DECIDED=YES` exactly once. At the first crossing of both 24 dates and 120 eligible races, record `FINAL_CHECKPOINT_DECIDED=YES` exactly once. Once final `INCONCLUSIVE_CLOSE` is recorded, later dates cannot change it to ACCEPT or REJECT. Parent SUSPEND retains priority. This is stateful enforcement outside the frozen pure decision helper.

The diagnostic `SIMPLE_SMALLEST_FIELD_FIRST` remains the frozen horse-number fallback `FIELD_SIZE_ONLY_REFERENCE`. The added `SMALLEST_FIELD_FIRST_SAME_SCORER` is a distinct, non-evidential reference using the same within-race ranking score as the compared method. Neither is a BUY or Production authority.
