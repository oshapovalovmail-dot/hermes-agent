# Paired-window connector decks

Use this recipe when stakeholders want the same connector evidence for “yesterday” and “all time” in one deck.

## Window contract

- **Yesterday:** a complete half-open local-time day, `[D 00:00, D+1 00:00)`. Do not substitute a rolling 24-hour window.
- **All time:** the known release/telemetry start through a minute-aligned current endpoint. If pre-release telemetry is absent, write **“since release”**, not an unqualified lifetime claim.
- Record both windows in the canonical source JSON and on the slides.

## Four-slide structure

1. Yesterday: reliability, totals by group, error concentration.
2. Yesterday: connector rows with totals, normalized read/write, success, errors.
3. Since release: the same reliability layout and denominator.
4. Since release: the same connector table and derived read/write mapping.

Reusing one pair generator prevents layout and semantic drift between periods. Keep write purple, errors red, and state that normalized bars are 100% within each row.

## Verification gates

- Reconcile every connector total against both status and tool splits.
- Reconcile group totals against the overall total for each window independently.
- Reopen the PPTX and assert four slides plus the required headline figures.
- Render through an Office-compatible renderer to PDF and PNG.
- Inspect all four images. Long scope phrases beside KPI cards are a recurring collision point; shorten “all time” to “since release” in the title before shrinking fonts.
- After any title/copy fix, rebuild and re-render; a valid PPTX is not visual proof.

## Evidence hygiene

Persist raw responses separately from the compact source summary. Never include credentials. State that event totals are calls, not unique users, and that read/write is derived from exact observed tool IDs when no native label exists.
