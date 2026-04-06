# Apply Agent Safety Constraints

These are the intended hard constraints for Apply Agent behavior.

## Core Constraints

1. **No final submit by default**
   - default behavior is shadow mode
   - scanning, filtering, detail fetch, and document prep are allowed
   - final application submission is not the assumed default path

2. **No unattended apply loop**
   - do not run an always-on or cron-driven live submission loop that can apply without review
   - periodic automation should stay in discovery/shadow mode unless an operator explicitly supervises a live run

3. **Explicit opt-in required for live mode**
   - live mode must be a deliberate operator action
   - the operator should know they are enabling browser-driven submission behavior
   - silent escalation from shadow mode to live mode is not allowed

4. **Prefer skip over risky apply**
   - ambiguous companies, junk listings, and low-confidence matches should be skipped
   - safety and quality beat coverage

5. **Auditability required**
   - blocked jobs should have logged reasons
   - prepared materials and outcomes should be traceable to a specific run
   - failures should be visible rather than silently ignored

## Submission Safety Expectations

Before any future live-mode submit path:

- candidate job has passed deterministic policy filtering
- job details have been reviewed or packaged for review
- generated assets are stored locally
- the operator has intentionally chosen to proceed
- final submission remains observable (status, screenshots, notes)

## What This Means in Practice

Safe-by-default direction:
- run scans
- reject junk early
- prepare materials
- review outputs
- only then consider a supervised live submission step

Unsafe direction to avoid:
- auto-starting a loop
- discovering jobs and immediately submitting without review
- silently applying to recruiting/staffing/temp junk because it matched a keyword
