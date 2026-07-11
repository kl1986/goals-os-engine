# Three-repo topology: Engine / Library / Brain, with all user state in the Brain

The product splits into three repos: **Engine** (protocols, schemas, adapters — zero user data), **Library** (optional plugins/skills), and **Brain** (the user's private repo: knowledge base plus ALL operational state — agent memories, routing rules, audit logs, goals, config overrides). Users clone a Brain Template. Decided 11/07/2026.

The deciding boundary question was where user-specific machine state lives: it goes in the Brain, so Engine upgrades can never clobber learnings, and backing up one private repo captures a user's whole life. **Rejected:** a fourth state repo (4 repos to manage, breaks the one-private-repo story); state gitignored inside the Engine (traps learnings in an upgradeable repo).
