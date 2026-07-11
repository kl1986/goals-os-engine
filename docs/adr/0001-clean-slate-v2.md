# Clean-slate v2 rather than refactoring the existing vault system

The current vault (three-tier agent model, triage pipeline, Tune loop) works but has Kelvin-specific content woven through its system files — agent personas, hard-coded paths, personal goals in operational config. Decided 11/07/2026 to design v2 from scratch for multi-user distribution, porting proven ideas rather than extracting code. The existing vault stays live as the prototype and daily driver during the build; its ADRs and protocols are treated as prior art, not constraints.

**Considered:** extract-and-refactor (lower risk, but the personal/generic entanglement would leak into the product); hybrid spine-and-organs (rejected as an unstable halfway house).
