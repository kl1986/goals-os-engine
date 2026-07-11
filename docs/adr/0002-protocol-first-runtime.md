# Protocol-first system with runtime Adapters, not a bespoke orchestrator

Provider agnosticism is achieved by defining the system as plain-markdown Protocols (schemas, agent charters, routines) plus a thin Adapter per agentic CLI. Claude Code is the reference Adapter/Runtime; Codex/Gemini adapters can follow. Hyper-specialised model choices are declared per-task in a model-routing config rather than baked into protocols. Decided 11/07/2026.

**Considered:** a bespoke orchestrator daemon (maximum control, but rebuilds the tool harness, permissions, and session management that agentic CLIs already provide, and turns install into "run a server"); Claude Code-native with agnosticism deferred (fastest, but makes provider-agnostic an aspiration rather than an architecture).

**Consequences:** every Engine behaviour must be expressible as text a generalist agent can follow; anything requiring hard code (schedulers, fetchers) lives in scripts callable from any runtime.
