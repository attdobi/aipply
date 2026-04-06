# Apply Agent Policy Direction

## Intent

The Apply Agent should bias toward **higher-signal direct roles** and away from low-quality funnels.

## Prefer

- company-site roles
- recognizable ATS-backed application targets
- direct employer listings
- full-time, role-relevant opportunities
- jobs with enough metadata to support review and tailoring

## Avoid / Block by Default

### Company-level signals

- recruiting firms
- staffing agencies
- talent/placement shops
- consulting body shops or generic consulting funnels

### Title-level signals

- hourly roles
- temp / temporary / seasonal roles
- contract-to-hire or similar churn-heavy listings
- recruiter / staffing / talent-acquisition roles when they leak into results
- consulting-heavy role titles when the goal is direct employment

## Policy Strategy

1. **Deterministic first pass**
   - use explicit blocklists with stable reasons
   - keep the initial gate explainable and testable

2. **Configurable over time**
   - allow tuned blocklists per search profile without changing the evaluation contract
   - extend categories carefully to avoid surprising false positives

3. **Log every block**
   - blocked jobs should say why they were skipped
   - reason codes should map back to company/title policy categories

4. **Prefer false negatives over junk submissions**
   - it is acceptable to skip some edge-case jobs if the result is safer, cleaner candidate sets

## Current Scaffolding

`src/apply_policy.py` currently ships with default blocklists for:

- `recruiting_staffing`
- `consulting`
- `hourly_temp`

These defaults are intentionally conservative scaffolding and should evolve with operator feedback.