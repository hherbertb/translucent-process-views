"""Check that the paper's prose and its generated numbers agree.

The failure this guards against is the one that reached the submitted PDF: the
evaluation prose quoted numbers from one run while the tables came from another.
Now every quoted number is a macro from ``tables/numbers.tex`` (evaluation) or
``tables/numbers_properties.tex`` (kappa's own properties), so the two cannot
disagree -- provided every macro the prose uses is actually defined, and the
definitions did not come from a ``--quick`` smoke run.

Usage::

    venv/Scripts/python evaluation/check_paper_numbers.py \
        "paper_final/ICPM_2026__Translucent_Variants(4)"

Exit code 0 = consistent, 1 = problems found.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

MACRO_FILES = ("tables/numbers.tex", "tables/numbers_properties.tex",
               "tables/numbers_semireal.tex")

# Prefixes used by the generated macros.  Anything matching one of these in the
# prose is expected to be defined by a generated file.
PREFIXES = (
    "kap", "var", "tvar", "glob", "attr", "case", "tc", "cost", "det", "loop",
    "tie", "hidden", "realised", "addShare", "numbers", "worst", "sr",
)

DEFINE_RE = re.compile(r"\\newcommand\{\\([A-Za-z]+)\}")
# Generated macros are camelCase: the prefix is always followed by an upper-case
# letter.  Requiring that keeps LaTeX built-ins whose names happen to start with
# a prefix -- \kappa, \varepsilon, \varphi -- out of the results.
USE_RE = re.compile(r"\\(" + "|".join(PREFIXES) + r")([A-Z][A-Za-z]*)")


def defined_macros(project: Path) -> tuple[set[str], list[str]]:
    found: set[str] = set()
    missing_files: list[str] = []
    for rel in MACRO_FILES:
        p = project / rel
        if not p.exists():
            missing_files.append(rel)
            continue
        found |= set(DEFINE_RE.findall(p.read_text(encoding="utf-8")))
    return found, missing_files


def used_macros(project: Path) -> dict[str, list[str]]:
    """macro name -> the section files that use it."""
    uses: dict[str, list[str]] = {}
    for p in sorted((project / "sections").glob("*.tex")):
        text = p.read_text(encoding="utf-8")
        # strip comments so a commented-out macro is not counted
        text = "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())
        for prefix, rest in USE_RE.findall(text):
            uses.setdefault(prefix + rest, []).append(p.name)
    return uses


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="the LaTeX project directory")
    a = ap.parse_args()
    project = Path(a.project)
    if not (project / "main.tex").exists():
        print(f"error: {project} does not look like the LaTeX project", file=sys.stderr)
        return 1

    have, missing_files = defined_macros(project)
    uses = used_macros(project)
    problems = 0

    for rel in missing_files:
        print(f"MISSING FILE  {rel} -- run run_evaluation.py / run_properties.py "
              f"with --paper-out {project / 'tables'}")
        problems += 1

    undefined = sorted(m for m in uses if m not in have)
    for m in undefined:
        print(f"UNDEFINED     \\{m}  (used in {', '.join(sorted(set(uses[m])))})")
    problems += len(undefined)

    unused = sorted(m for m in have if m not in uses and not m.startswith("numbers"))
    if unused:
        print(f"note: {len(unused)} generated macro(s) not quoted in the prose "
              f"(harmless): {', '.join(unused[:8])}"
              + (" ..." if len(unused) > 8 else ""))

    quick = (project / "tables" / "numbers.tex")
    if quick.exists() and re.search(r"\\newcommand\{\\numbersAreQuickRun\}\{yes\}",
                                    quick.read_text(encoding="utf-8")):
        print("PLACEHOLDER   tables/numbers.tex came from a --quick run and is "
              "NOT paper-grade; re-run run_evaluation.py --full --paper-out")
        problems += 1

    if problems:
        print(f"\n{problems} problem(s) found.")
        return 1
    print(f"OK: {len(uses)} quoted numbers, all defined by a full run.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
