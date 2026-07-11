# One unified, append-only Action Log as the audit and learning substrate

Every agent action — regardless of which agent took it — appends a structured entry (actor, trigger, input link, action, confidence, outcome, empty feedback slot) to a single Action Log in the Brain, stored as daily markdown files. User feedback is written into the entry's feedback slot; the learning loop reads only validated feedback to update rules and graduate action types toward autonomy. Git supplies the diff-level trail underneath. Decided 11/07/2026.

**Rejected:** per-agent logs rolled up to a dashboard (v1's pattern — locality, but auditability becomes convention not guarantee, and learning must crawl N surfaces); git-as-audit via structured commits (perfect diffs, unusable from Obsidian/mobile).

**Amended 11/07/2026 (adversarial review):** concurrent multi-agent writes to one daily file are a real conflict risk. The log stays markdown (a database as primary store would break the text-substrate principle), but if concurrency materialises the write pattern shards to **one file per actor per day**, merged into the review surface by script. Entries remain strictly append-only either way.
