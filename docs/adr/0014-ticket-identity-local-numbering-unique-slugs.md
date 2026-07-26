# Ticket identity: slug-scoped local numbering, Project/Area slugs must be unique

Ticket IDs are `<slug>-<number>`, where `<slug>` is the owning Project or Area and `<number>` is a counter local to that Project/Area — not a Brain-wide sequence. This keeps IDs small and Jira-like, but only stays unambiguous if Project and Area slugs never collide. `example-project` currently exists as both an Area (agent Steve) and a Project (the app), so the Project is renamed to `example-project` as a precondition, and "Project and Area slugs must be unique across both namespaces" becomes a standing naming rule. Decided 21/07/2026.

Filenames are `<slug>-<number>-<short-desc>.md`, e.g. `example-project-7-fix-onboarding-crash.md` — the slug-number pair is the actual ID; the short description exists for human skimming and `[[wikilink]]` legibility.

**Rejected:** `p-`/`a-` prefix on every ticket ID to disambiguate Area vs Project (cheaper to just keep slugs unique); a single Brain-wide global counter (loses the small, meaningful per-project numbering that's the point of Jira-style keys).
