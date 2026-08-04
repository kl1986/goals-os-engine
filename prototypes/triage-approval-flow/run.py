#!/usr/bin/env python3
"""PROTOTYPE — throwaway TUI. Drive the Triage approval flow by hand.

Run:  ./venv/bin/python prototypes/triage-approval-flow/run.py

Thin shell over gestures.py, which holds the actual model and states the
question. This file owns the one thing that cannot be pure: a scratch Brain in
a temp dir, so the `x` key runs the *real* execute_plan against real files.
Wiped on quit. Nothing here touches your Vault.
"""

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import execute  # noqa: E402
import gestures  # noqa: E402

B, D, R = "\x1b[1m", "\x1b[2m", "\x1b[0m"
GRN, YEL, RED, CYN = "\x1b[32m", "\x1b[33m", "\x1b[31m", "\x1b[36m"

PLAN = """---
type: triage-plan
source: email
date: 2026-07-28
status: pending
---

# Triage Plan — email — 2026-07-28

## discard

- [ ] **1** → `discard` · Pass A · High · a1b2c3d4
    LinkedIn Job Alerts · "Credit Manager, Fraud at Revolut"
    [[inbox/raw/email/0001-linkedin.md]]

- [ ] **2** → `discard` · Pass A · High · a1b2c3d4
    Currys · "Payday treat — 15% off sitewide"
    [[inbox/raw/email/0002-currys.md]]

- [ ] **3** → `discard` · Pass A · High · a1b2c3d4
    Trainline · "Thinking of going to Glasgow Central?"
    [[inbox/raw/email/0003-trainline.md]]

## unmatched

- [ ] **4** → `unmatched` · Pass B · — · —
    Monzo · "Open your Monzo pension"
    [[inbox/raw/email/0004-monzo.md]]

## areas/ho-lee-fook/_inbox.md

- [ ] **5** → `areas/ho-lee-fook/_inbox.md` · Pass B · Medium · —
    Buyer at Sainsbury's wants a meeting date
    [[inbox/raw/email/0005-buyer.md]]
"""


class Session:
    """Scratch Brain + Plan text. The only stateful thing in the prototype."""

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="PROTOTYPE-wipe-me-"))
        self.text = PLAN
        self.log = ["started — scratch Brain at " + str(self.root)]
        self._seed()

    def _seed(self):
        for d in ("inbox/raw/email", "inbox/triage", "archive/inbox/email",
                  "archive/triage", "log", "config", "areas/ho-lee-fook"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        (self.root / "areas/ho-lee-fook/_inbox.md").write_text("# Inbox\n")
        (self.root / "config/routine-state.md").write_text(
            "| Routine | Last run |\n|---|---|\n| Execute | never |\n"
            "| Triage | never |\n"
        )

    def captures(self):
        """Re-materialise every capture a Row still points at, so Execute has
        real files to move. Cheap enough to redo each run."""
        for row in execute.parse_plan_rows(self.text):
            cap = row["capture"]
            if not cap:
                continue
            p = self.root / cap
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists():
                p.write_text(f"---\nid: {p.stem}\n---\n\n# {p.stem}\n\nbody\n")

    def run_execute(self):
        self.captures()
        plan = self.root / "inbox/triage/2026-07-28-email.md"
        plan.write_text(self.text)
        try:
            res = execute.execute_plan(self.root, plan)
        except execute.ExecuteError as e:
            self.log.append(f"{RED}Execute REFUSED the whole Plan{R} — {e}")
            self.log.append(f"{D}  Plan on disk unchanged; nothing filed or logged.{R}")
            return
        landing = plan if plan.exists() else res.get("archived_to")
        if landing and Path(landing).exists():
            self.text = Path(landing).read_text()
        self.log.append(
            f"{GRN}Execute ran{R} — filed {len(res['filed'])}, "
            f"discarded {len(res['discarded'])}, errors {len(res['errors'])}"
            + (f" {D}(plan archived — all Rows spent){R}" if res["plan_executed"] else "")
        )
        for err in res["errors"]:
            self.log.append(f"{YEL}  ! {err}{R}")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def render(s: Session):
    print("\033[2J\033[H", end="")
    st = gestures.derive(s.text)

    print(f"{B}Triage approval flow — PROTOTYPE{R} "
          f"{D}(throwaway; scratch Brain, wiped on quit){R}\n")

    for line in s.text.splitlines():
        if line.startswith("---") or line.startswith("type:") or \
           line.startswith("source:") or line.startswith("date:") or \
           line.startswith("status:"):
            continue
        if line.startswith("## "):
            print(f"{CYN}{B}{line}{R}")
        elif execute.ROW_RE.match(line):
            m = execute.ROW_RE.match(line)
            col = GRN if m.group("tick") == "[x]" else ""
            if m.group("marker"):
                col = D
            print(f"{col}{line}{R}")
        elif line.strip():
            print(f"{D}{line}{R}")
        else:
            print()

    print(f"\n{B}What each consumer sees{R}")
    prob = st["problems"]
    print(f"  {B}Execute{R}    would act on rows {st['execute_would_act_on'] or '—'}"
          + (f"   {RED}REFUSES: {len(prob)} malformed{R}" if prob else ""))
    for p in prob:
        print(f"    {RED}{p}{R}")
    print(f"  {B}Nudge{R}      {len(st['nudge_awaiting_pass_b'])} awaiting Pass B, "
          f"{len(st['nudge_awaiting_execute'])} awaiting Execute")
    print(f"  {B}Dashboard{R}  {st['dashboard_ticked']} ticked, "
          f"{st['dashboard_pending']} pending")
    print(f"  {D}rows parsed: {len(st['rows'])}   groups: "
          f"{', '.join(st['groups']) or '—'}{R}")

    print(f"\n{B}Log{R}")
    for line in s.log[-4:]:
        print(f"  {D}·{R} {line}")

    print(f"\n{B}Gestures{R} {D}(a thumb on a phone){R}")
    print(f"  {B}t{R} {D}tap checkbox{R}    {B}T{R} {D}tap a whole run{R}      "
          f"{B}d{R} {D}retype destination{R}  {B}c{R} {D}clear destination{R}")
    print(f"  {B}h{R} {D}rename heading{R}  {B}i{R} {D}auto-indent a Row{R}    "
          f"{B}k{R} {D}delete capture line{R}  {B}n{R} {D}overnight capture{R}")
    print(f"  {B}g{R} {D}regroup{R}         {B}x{R} {D}run Execute (real){R}   "
          f"{B}r{R} {D}reset{R}               {B}q{R} {D}quit{R}")
    print(f"\n{D}Try: T discard → x   ·   c 5 → x   ·   h discard→keep → g   "
          f"·   k 1 → i 2 → x{R}")


def ask(prompt):
    try:
        return input(f"  {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def main():
    s = Session()
    while True:
        render(s)
        try:
            key = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not key:
            continue
        k, rest = key[0], key[1:].strip()

        if k == "q":
            break
        elif k == "r":
            s.text = PLAN
            s.log.append("reset to the starting Plan")
        elif k == "t":
            n = rest or ask("row number")
            s.text = gestures.tap_checkbox(s.text, n)
            s.log.append(f"tapped checkbox on row {n}")
        elif k == "T":
            h = rest or ask("heading (e.g. discard)")
            s.text = gestures.tap_run(s.text, h)
            s.log.append(f"tapped the whole run under '## {h}'")
        elif k == "d":
            n = rest or ask("row number")
            dest = ask("new destination")
            s.text = gestures.retype_destination(s.text, n, dest)
            s.log.append(f"retyped row {n}'s destination to '{dest}' "
                         f"{D}(in place — no block moved){R}")
        elif k == "c":
            n = rest or ask("row number")
            s.text = gestures.clear_destination(s.text, n)
            s.log.append(f"{YEL}cleared row {n}'s destination{R} "
                         f"{D}— mid-edit, autosaved{R}")
        elif k == "h":
            old = rest or ask("existing heading")
            new = ask("rename to")
            s.text = gestures.edit_heading(s.text, old, new)
            s.log.append(f"renamed heading '{old}' → '{new}' "
                         f"{D}(watch it revert on the next write){R}")
        elif k == "i":
            n = rest or ask("row number")
            s.text = gestures.autoindent_row(s.text, n)
            s.log.append(f"auto-indented row {n}")
        elif k == "k":
            n = rest or ask("row number")
            s.text = gestures.delete_capture_line(s.text, n)
            s.log.append(f"{YEL}deleted row {n}'s capture line{R}")
        elif k == "n":
            dest = rest or ask("destination for the new capture") or "discard"
            s.text = gestures.new_capture_arrives(
                s.text, dest, "Overnight arrival — something new")
            s.log.append(f"overnight: a capture arrived, routed to '{dest}'")
        elif k == "g":
            s.text = gestures.regroup(s.text)
            s.log.append("regrouped — headings regenerated from Row destinations")
        elif k == "x":
            s.run_execute()

    s.cleanup()
    print("\nScratch Brain wiped. Nothing outside it was touched.\n")


if __name__ == "__main__":
    main()
