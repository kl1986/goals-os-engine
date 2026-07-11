# Routines are declarative manifest entries triggered by layered due-checking

The Engine ships a Routine manifest (name, protocol, cadence, risk tier); last-run state lives in the Brain. Triggering is layered so the same manifest degrades gracefully: (1) heartbeat — every session start checks for overdue routines and nudges or auto-runs them per their autonomy level; (2) the Adapter may bind real schedulers (cron/launchd, runtime cloud schedules) for true away-from-keyboard firing; (3) every routine stays manually invocable. Decided 11/07/2026.

**Rejected:** hard cron wiring at install (deterministic but fragile across laptop sleep/multiple machines, and front-loads setup friction); manual-first with scheduling as a plugin (fails the AFK north star in the core product).
