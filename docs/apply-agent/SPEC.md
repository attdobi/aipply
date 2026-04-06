# Apply Agent Spec

## Goal

Define a safer Apply Agent workflow for Aipply that prefers **shadow mode first**:

- collect candidate jobs
- filter aggressively for quality and policy fit
- enrich job details
- prepare tailored materials
- produce a reviewed execution plan
- require explicit operator opt-in before any live submission path

This spec is directional architecture for the in-repo Apply Agent effort.

## Design Principles

1. **Shadow mode is the default operating posture**
   - scan, filter, enrich, and draft artifacts without final submission
   - log every decision and rejection reason
   - make review easy before any live action
2. **Safe-first over max-throughput**
   - prefer skipping ambiguous jobs to low-quality or risky submissions
   - avoid unattended loops that can spam ATS systems or apply to junk roles
3. **Deterministic early filtering**
   - cheap policy checks run before deeper fetch/generation work where possible
   - reasons should be structured and testable
4. **Live mode is explicit, narrow, and supervised**
   - only enabled by a deliberate operator decision
   - final submit remains a separately guarded step

## Proposed Phases

### Phase 0 — Config + Guardrails

Inputs:
- search config
- exclusion config
- apply-policy config (optional overrides)
- candidate profile and base documents

Responsibilities:
- load config
- establish run mode (`shadow`, later optional `live`)
- initialize tracker/logging
- fail closed on missing critical config

### Phase 1 — Discovery

Responsibilities:
- search LinkedIn / source sites using configured keywords and locations
- deduplicate raw results by stable identifiers / URLs
- preserve basic metadata needed for later review

Outputs:
- raw candidate job list

### Phase 2 — Policy Filtering

Responsibilities:
- apply deterministic title/company quality filters
- reject obvious recruiting, staffing, consulting, hourly, temp, or similar low-signal jobs
- log stable reasons for every blocked job

Outputs:
- policy-approved candidate list
- skip logs for blocked jobs

### Phase 3 — Detail Enrichment

Responsibilities:
- fetch full job description only for policy-approved jobs
- normalize description and metadata for downstream generation
- tolerate fetch failures with clear fallback logging

Outputs:
- enriched job records

### Phase 4 — Asset Preparation

Responsibilities:
- tailor resume
- generate cover letter / supporting docs
- store artifacts in per-job output folders

Outputs:
- tailored resume
- cover letter
- execution metadata for review

### Phase 5 — Review Package (Shadow Mode)

Responsibilities:
- record what would happen for each approved job
- surface reasons, artifacts, and target URLs for operator review
- stop before final submission

Outputs:
- tracker entries / reports
- reviewable bundle for operator approval

### Phase 6 — Optional Live Mode

Responsibilities:
- only run when explicitly enabled
- use the reviewed package as input
- preserve screenshots, statuses, and failure notes
- keep submission supervised and auditable

Outputs:
- explicit apply results
- final tracker/report updates

## Current Minimal Scaffolding

The current repo work for this phase adds:

- `src/apply_policy.py` for deterministic company/title policy evaluation
- pre-detail policy filtering in `scripts/run_cycle.py`
- tests covering policy decisions and run-cycle integration

This is intentionally modest scaffolding, not a full autonomous agent loop.

## Non-Goals for This Iteration

- no autonomous forever-loop apply engine
- no hidden background final-submit behavior
- no “spray and pray” multi-site automation
- no opaque LLM-only gating for first-pass policy decisions
