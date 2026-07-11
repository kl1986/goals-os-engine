# Risk-tiered autonomy graduation: silence approves internal actions, never outward ones

Action types graduate from confirm-first to autonomous based on validated feedback in the Action Log, and every action type carries a risk tier that determines what counts as validation. **Internal & reversible** actions (filing, tagging, drafting): unreviewed entries older than the review window count as approval — autonomy grows organically without review effort. **Outward-facing or hard-to-reverse** actions (sending, deleting, spending, messaging people): graduate only on explicit validation; silence never counts. A correction instantly demotes the action type in either tier. Thresholds and window are Brain-config policy. Decided 11/07/2026.

**Rejected:** uniform silence-as-approval (accepts autonomy-by-inattention over e.g. external email); undo-window softening for outward actions (machinery that delays rather than gates the failure mode); explicit-only graduation everywhere (the AFK curve then depends entirely on user review discipline).

**Amended 11/07/2026 (adversarial review):** graduation additionally requires **temporal spread** — the qualifying validated actions must span a minimum number of distinct days/sessions (Brain config), so a burst of correlated actions stemming from one wrong premise in a single window can never graduate an action type on its own.
