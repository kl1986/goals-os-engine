#!/usr/bin/env python3
"""Parse a Brain's `config/schedules.md` — the sole source of truth for timing.

Implements protocols/schedules.md. One row is a **Schedule**: when a Routine
or a standalone script runs, both trigger and timing. A Schedule has a
**kind** — *fixed-interval* (fires on a clock) or *poll* (an event-trigger
realised as a frequent check).

Two consumers read this module, and nothing else parses the table:

- `scripts/heartbeat.py` (layer 1) — cadence for due-checking. Per ADR-0030
  cadence left the Engine's `protocols/routines.md` manifest entirely and
  lives here.
- `scripts/sync_schedules.py` (layer 2, the Scheduler Adapter) — renders the
  Managed `.plist` per enabled row.

Pure Python, zero LLM calls. Validation is whole-table and fails loudly:
`parse_schedules` raises `ScheduleError` listing every bad row, so no caller
can ever act on a half-valid table.
"""

import re
import shlex
from pathlib import Path

KIND_FIXED = "fixed-interval"
KIND_POLL = "poll"
KINDS = (KIND_FIXED, KIND_POLL)

# Cadence words a fixed-interval Timing cell may use in place of a clock time.
# A word-only row is heartbeat-checkable but renders no Job (no clock to fire on).
CADENCE_DAYS = {
    "hourly": 1 / 24,
    "daily": 1,
    "weekly": 7,
    "fortnightly": 14,
    "monthly": 30,
    "quarterly": 90,
}

# launchd's StartCalendarInterval Weekday numbering: 0 = Sunday.
WEEKDAYS = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
WEEKDAY_ORDER = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

INTERVAL_UNITS = {"s": 1, "m": 60, "h": 3600}

NONE_CELLS = {"", "—", "-", "–", "none", "n/a"}

REQUIRED_COLUMNS = ("Label", "Routine", "Command", "Kind", "Timing", "Enabled", "Log", "Env", "Options")

_CLOCK_RE = re.compile(r"^(?:(?P<days>[A-Za-z,\-]+)\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})$")
_INTERVAL_RE = re.compile(r"^(?P<n>\d+)\s*(?P<unit>[smh])$", re.IGNORECASE)


class ScheduleError(Exception):
    """One or more rows in a schedules table are malformed.

    Carries every problem found, not just the first — the whole table is
    validated before any caller writes anything to the filesystem.
    """

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("Invalid config/schedules.md:\n" + "\n".join(f"  - {p}" for p in self.problems))


class Schedule:
    """One parsed row. Attributes are the plist-ready, validated form."""

    def __init__(self, label, routine, command, kind, timing, enabled, stdout, stderr,
                 env, working_dir, run_at_load, calendar, interval_seconds,
                 cadence_days, checkable, line_no):
        self.label = label
        self.routine = routine              # Routine name, or None for a standalone Job
        self.command = command              # list[str] -> ProgramArguments, or [] for no Job
        self.kind = kind
        self.timing = timing                # the raw cell, for diagnostics
        self.enabled = enabled
        self.stdout = stdout
        self.stderr = stderr
        self.env = env                      # dict[str, str]
        self.working_dir = working_dir
        self.run_at_load = run_at_load      # True / False / None (omit the key)
        self.calendar = calendar            # list[dict] for fixed-interval clock rows
        self.interval_seconds = interval_seconds  # int for poll rows
        self.cadence_days = cadence_days    # float or None
        self.checkable = checkable          # heartbeat-checkable?
        self.line_no = line_no

    @property
    def renders_job(self) -> bool:
        """Does this row realise a launchd Job?

        Only if it is enabled, names a command, and carries firing detail —
        a cadence-word-only row (e.g. `weekly`) exists purely so Heartbeat
        can due-check a Routine no launchd job drives.
        """
        if not (self.enabled and self.command):
            return False
        return bool(self.calendar) if self.kind == KIND_FIXED else self.interval_seconds is not None

    def __repr__(self):
        return f"<Schedule {self.label} {self.kind} {self.timing!r}>"


def _blank(cell: str) -> bool:
    return cell.strip().lower() in NONE_CELLS


def _strip_code(cell: str) -> str:
    cell = cell.strip()
    if len(cell) > 1 and cell.startswith("`") and cell.endswith("`"):
        cell = cell[1:-1].strip()
    return cell


def _expand(token: str) -> str:
    return str(Path(token).expanduser()) if token.startswith("~") else token


def parse_table(text: str, header_must_contain: str = "Label") -> list:
    """Parse the first markdown table whose header contains `header_must_contain`.

    Same idiom as `heartbeat.parse_table`, but skips prose tables in the
    schema's own header comments — `config/schedules.md` documents itself
    above the data, so "the first table in the file" is not good enough.
    Rows carry a `_line` key so validation errors can name the line.
    """
    lines = text.splitlines()
    header = None
    header_idx = None
    for i, line in enumerate(lines):
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header_must_contain in cells:
            header, header_idx = cells, i
            break
    if header is None:
        return []

    rows = []
    for i in range(header_idx + 2, len(lines)):  # skip header + --- separator
        line = lines[i]
        if not line.strip().startswith("|"):
            if rows:
                break  # table ended
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            continue  # a separator row
        row = dict(zip(header, cells))
        row["_line"] = i + 1
        if len(cells) != len(header):
            row["_arity"] = (len(cells), len(header))
        rows.append(row)
    return rows


def _parse_command(cell: str, problems, line_no):
    if _blank(cell):
        return []
    try:
        args = shlex.split(_strip_code(cell))
    except ValueError as exc:
        problems.append(f"line {line_no}: Command is not shell-parseable ({exc})")
        return []
    if not args:
        problems.append(f"line {line_no}: Command is empty after parsing")
    return [_expand(a) for a in args]


def _parse_logs(cell: str, problems, line_no):
    if _blank(cell):
        return None, None
    parts = [p.strip() for p in _strip_code(cell).split(";") if p.strip()]
    if len(parts) == 1:
        path = _expand(_strip_code(parts[0]))
        return path, path
    if len(parts) == 2:
        return _expand(_strip_code(parts[0])), _expand(_strip_code(parts[1]))
    problems.append(f"line {line_no}: Log takes one path (both streams) or `out ; err`, got {len(parts)}")
    return None, None


def _parse_kv(cell: str, problems, line_no, what):
    if _blank(cell):
        return {}
    out = {}
    for pair in _strip_code(cell).split(";"):
        pair = _strip_code(pair)
        if not pair:
            continue
        if "=" not in pair:
            problems.append(f"line {line_no}: {what} entry {pair!r} is not KEY=value")
            continue
        key, value = pair.split("=", 1)
        out[key.strip()] = _expand(value.strip())
    return out


def _parse_weekdays(spec: str, problems, line_no):
    """Expand `Mon-Fri`, `Sun`, `Mon,Wed` into launchd Weekday integers."""
    days = []
    for part in spec.split(","):
        part = part.strip().lower()
        if "-" in part:
            start, _, end = part.partition("-")
            if start not in WEEKDAYS or end not in WEEKDAYS:
                problems.append(f"line {line_no}: unknown day range {part!r} in Timing")
                return []
            i, j = WEEKDAY_ORDER.index(start), WEEKDAY_ORDER.index(end)
            span = WEEKDAY_ORDER[i:j + 1] if i <= j else WEEKDAY_ORDER[i:] + WEEKDAY_ORDER[:j + 1]
            days.extend(span)
        elif part in WEEKDAYS:
            days.append(part)
        else:
            problems.append(f"line {line_no}: unknown day {part!r} in Timing")
            return []
    seen, ordered = set(), []
    for d in days:
        if d not in seen:
            seen.add(d)
            ordered.append(d)
    return [WEEKDAYS[d] for d in ordered]


def _parse_timing(kind, cell, problems, line_no):
    """-> (calendar, interval_seconds, cadence_days, checkable)"""
    cell = _strip_code(cell)

    if kind == KIND_POLL:
        # Poll rows are event-triggers: excluded from due-checking by design.
        if _blank(cell):
            return [], None, None, False
        m = _INTERVAL_RE.match(cell)
        if not m:
            problems.append(f"line {line_no}: poll Timing must be an interval like `900s`, `15m`, `1h`, got {cell!r}")
            return [], None, None, False
        return [], int(m.group("n")) * INTERVAL_UNITS[m.group("unit").lower()], None, False

    # fixed-interval
    if _blank(cell):
        problems.append(f"line {line_no}: fixed-interval Timing is required (a clock time or a cadence word)")
        return [], None, None, False

    word = cell.lower()
    if word in CADENCE_DAYS:
        return [], None, CADENCE_DAYS[word], True

    m = _CLOCK_RE.match(cell)
    if not m:
        problems.append(
            f"line {line_no}: fixed-interval Timing must be `HH:MM`, `<days> HH:MM`, "
            f"or one of {', '.join(sorted(CADENCE_DAYS))} — got {cell!r}"
        )
        return [], None, None, False

    hour, minute = int(m.group("hour")), int(m.group("minute"))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        problems.append(f"line {line_no}: Timing {cell!r} is not a valid 24h clock time")
        return [], None, None, False

    days = _parse_weekdays(m.group("days"), problems, line_no) if m.group("days") else []
    if m.group("days") and not days:
        return [], None, None, False

    if days:
        calendar = [{"Weekday": d, "Hour": hour, "Minute": minute} for d in days]
        cadence = 7 / len(days)
    else:
        calendar = [{"Hour": hour, "Minute": minute}]
        cadence = CADENCE_DAYS["daily"]
    return calendar, None, cadence, True


def parse_row(row: dict) -> tuple:
    """Validate one table row. Returns (Schedule|None, problems)."""
    problems = []
    line_no = row.get("_line", "?")

    if "_arity" in row:
        got, want = row["_arity"]
        problems.append(f"line {line_no}: row has {got} cells, expected {want}")
        return None, problems

    missing = [c for c in REQUIRED_COLUMNS if c not in row]
    if missing:
        problems.append(f"line {line_no}: missing column(s): {', '.join(missing)}")
        return None, problems

    label = _strip_code(row["Label"])
    if not label:
        problems.append(f"line {line_no}: Label is required")
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", label):
        problems.append(f"line {line_no}: Label {label!r} must be a reverse-DNS-safe token")

    kind = _strip_code(row["Kind"]).lower()
    if kind not in KINDS:
        problems.append(f"line {line_no}: Kind must be one of {', '.join(KINDS)}, got {kind!r}")
        kind = None

    enabled_cell = _strip_code(row["Enabled"]).lower()
    if enabled_cell in ("yes", "true", "y"):
        enabled = True
    elif enabled_cell in ("no", "false", "n"):
        enabled = False
    else:
        problems.append(f"line {line_no}: Enabled must be yes or no, got {enabled_cell!r}")
        enabled = False

    routine = None if _blank(row["Routine"]) else _strip_code(row["Routine"])
    command = _parse_command(row["Command"], problems, line_no)
    stdout, stderr = _parse_logs(row["Log"], problems, line_no)
    env = _parse_kv(row["Env"], problems, line_no, "Env")

    options = _parse_kv(row["Options"], problems, line_no, "Options")
    working_dir = options.pop("cwd", None)
    run_at_load = None
    if "run-at-load" in options:
        raw = options.pop("run-at-load").lower()
        if raw in ("true", "yes"):
            run_at_load = True
        elif raw in ("false", "no"):
            run_at_load = False
        else:
            problems.append(f"line {line_no}: Options run-at-load must be true or false, got {raw!r}")
    for unknown in options:
        problems.append(f"line {line_no}: unknown Options key {unknown!r} (supported: cwd, run-at-load)")

    calendar, interval_seconds, cadence_days, checkable = ([], None, None, False)
    if kind:
        calendar, interval_seconds, cadence_days, checkable = _parse_timing(
            kind, row["Timing"], problems, line_no
        )

    if command and enabled and kind == KIND_POLL and interval_seconds is None:
        problems.append(f"line {line_no}: an enabled poll row with a Command needs a poll interval in Timing")
    if command and enabled and kind == KIND_FIXED and not calendar:
        problems.append(
            f"line {line_no}: an enabled fixed-interval row with a Command needs a clock time in Timing "
            f"(a cadence word alone declares cadence only, and renders no job)"
        )

    if problems:
        return None, problems

    return Schedule(
        label=label, routine=routine, command=command, kind=kind,
        timing=_strip_code(row["Timing"]), enabled=enabled, stdout=stdout, stderr=stderr,
        env=env, working_dir=working_dir, run_at_load=run_at_load, calendar=calendar,
        interval_seconds=interval_seconds, cadence_days=cadence_days, checkable=checkable,
        line_no=line_no,
    ), []


def parse_schedules_text(text: str) -> list:
    rows = parse_table(text)
    schedules, problems = [], []
    for row in rows:
        sched, row_problems = parse_row(row)
        problems.extend(row_problems)
        if sched:
            schedules.append(sched)

    seen = {}
    for s in schedules:
        if s.label in seen:
            problems.append(f"line {s.line_no}: duplicate Label {s.label!r} (first seen line {seen[s.label]})")
        else:
            seen[s.label] = s.line_no

    if problems:
        raise ScheduleError(problems)
    return schedules


def schedules_path(brain_path: Path) -> Path:
    return Path(brain_path) / "config" / "schedules.md"


def parse_schedules(path: Path) -> list:
    """Parse a schedules table file. Raises ScheduleError on any bad row."""
    path = Path(path)
    if not path.exists():
        raise ScheduleError([f"{path} does not exist"])
    return parse_schedules_text(path.read_text())


def cadence_by_routine(schedules: list) -> dict:
    """Routine name -> {cadence_days, checkable} — what Heartbeat due-checks on.

    Standalone Jobs (no Routine) are skipped: they have a Schedule but no
    Routine to be overdue. Poll rows land here with `checkable: False` so the
    caller can tell "event-triggered by declaration" from "not declared".
    A disabled row is skipped entirely — `Enabled: no` switches a Schedule
    off for Heartbeat as well as for launchd.
    """
    out = {}
    for s in schedules:
        if not s.routine or not s.enabled:
            continue
        out[s.routine] = {"cadence_days": s.cadence_days, "checkable": s.checkable}
    return out
