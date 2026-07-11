# Distribution via runtime plugin + Brain Template, not an installer CLI

The Engine ships as a runtime plugin (Claude Code plugin from a marketplace repo as the reference packaging; other runtimes get equivalent packaging via their Adapters). The Library is a second marketplace of optional plugins. The only thing a user clones is a Brain Template. Upgrade = plugin update, structurally incapable of touching the Brain. Decided 11/07/2026.

**Rejected:** a bespoke installer CLI (`brain init/upgrade`) — better migration control but a second product to maintain; git-native clone-and-pull of all three repos — zero tooling but pushes version pinning and schema migrations onto users, and forked engines can never merge upstream again (the failure mode of most distributed vault templates).
