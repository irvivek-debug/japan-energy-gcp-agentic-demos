"""AlphaEvolve-style SEARCH/REPLACE diffs, applied robustly inside the EVOLVE-BLOCK only.

Format the mutator is asked to produce (one or more blocks)::

    <<<<<<< SEARCH
    exact lines from the current EVOLVE-BLOCK
    =======
    replacement lines
    >>>>>>> REPLACE

Matching ladder per hunk: exact substring -> trailing-whitespace-insensitive lines -> indentation-
insensitive lines (replacement re-indented to the matched indentation) -> fuzzy window
(difflib ratio >= 0.92, unique best). A hunk that matches nowhere is reported, never guessed.
If the reply carries no hunks but a fenced python block that defines every required function, it is
treated as a full-block rewrite (AlphaEvolve's full-rewrite mode).
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

_HUNK = re.compile(r"^[ \t]*<{5,9}[ \t]*SEARCH[^\n]*\n(.*?)\n?^[ \t]*={5,9}[ \t]*\n(.*?)\n?^[ \t]*>{5,9}[ \t]*REPLACE", re.S | re.M)
_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


class DiffError(ValueError):
    pass


@dataclass
class DiffReport:
    hunks: int = 0
    applied: int = 0
    methods: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    mode: str = "diff"   # diff | full_rewrite


def parse_hunks(text: str) -> list[tuple[str, str]]:
    return [(s, r) for s, r in _HUNK.findall(text)]


def _indent(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def _apply_one(block: str, search: str, replace: str) -> tuple[str, str] | None:
    if search and block.count(search) == 1:
        return block.replace(search, replace, 1), "exact"
    if search and block.count(search) > 1:
        return None
    b_lines = block.split("\n")
    s_lines = search.split("\n")
    while s_lines and not s_lines[-1].strip():
        s_lines.pop()
    while s_lines and not s_lines[0].strip():
        s_lines.pop(0)
    if not s_lines:
        return None
    n = len(s_lines)
    r_lines = replace.split("\n")

    def splice(i: int, lines: list[str]) -> str:
        return "\n".join(b_lines[:i] + lines + b_lines[i + n:])

    # 2. trailing-whitespace insensitive
    hits = [i for i in range(len(b_lines) - n + 1)
            if [x.rstrip() for x in b_lines[i:i + n]] == [x.rstrip() for x in s_lines]]
    if len(hits) == 1:
        return splice(hits[0], r_lines), "rstrip"
    # 3. indentation insensitive: re-indent replacement by the delta between matched and search indentation
    hits = [i for i in range(len(b_lines) - n + 1)
            if [x.strip() for x in b_lines[i:i + n]] == [x.strip() for x in s_lines]]
    if len(hits) == 1:
        i = hits[0]
        base_b, base_s = _indent(b_lines[i]), _indent(s_lines[0])
        fixed = []
        for ln in r_lines:
            if ln.startswith(base_s):
                fixed.append(base_b + ln[len(base_s):])
            else:
                fixed.append(base_b + ln.lstrip() if ln.strip() else ln)
        return splice(i, fixed), "reindent"
    # 4. fuzzy window
    target = "\n".join(x.strip() for x in s_lines)
    scored = []
    for i in range(len(b_lines) - n + 1):
        cand = "\n".join(x.strip() for x in b_lines[i:i + n])
        scored.append((difflib.SequenceMatcher(None, cand, target).ratio(), i))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 0.92 and (len(scored) == 1 or scored[1][0] < scored[0][0] - 0.02):
        i = scored[0][1]
        base_b, base_s = _indent(b_lines[i]), _indent(s_lines[0])
        fixed = [base_b + ln[len(base_s):] if ln.startswith(base_s) else ln for ln in r_lines]
        return splice(i, fixed), f"fuzzy({scored[0][0]:.2f})"
    return None


def apply_reply(block: str, reply: str, required_functions: tuple[str, ...] = ()) -> tuple[str, DiffReport]:
    """Apply a model reply to an EVOLVE-BLOCK body. Raises DiffError if nothing applicable was found."""
    rep = DiffReport()
    hunks = parse_hunks(reply)
    rep.hunks = len(hunks)
    if not hunks:
        for body in _FENCE.findall(reply):
            body = body.replace("# EVOLVE-BLOCK-START", "").replace("# EVOLVE-BLOCK-END", "")
            if required_functions and all(re.search(rf"^def {f}\(", body, re.M) for f in required_functions):
                rep.mode, rep.applied = "full_rewrite", 1
                return body.strip("\n") + "\n", rep
        raise DiffError("reply contained no SEARCH/REPLACE hunks and no full rewrite of the EVOLVE-BLOCK")
    new = block
    for k, (s, r) in enumerate(hunks, 1):
        if "EVOLVE-BLOCK" in s or "EVOLVE-BLOCK" in r:
            rep.failures.append(f"hunk {k}: touches EVOLVE-BLOCK markers (only the block body may change)")
            continue
        res = _apply_one(new, s, r)
        if res is None:
            first = next((ln.strip() for ln in s.split("\n") if ln.strip()), "")[:80]
            rep.failures.append(f"hunk {k}: SEARCH text not found uniquely (starts: {first!r})")
            continue
        new, how = res
        rep.applied += 1
        rep.methods.append(how)
    if rep.applied == 0:
        raise DiffError("; ".join(rep.failures) or "no hunk applied")
    if new == block:
        raise DiffError("hunks applied but the EVOLVE-BLOCK is unchanged")
    return (new if new.endswith("\n") else new + "\n"), rep


def unified(a: str, b: str, a_name: str = "parent", b_name: str = "child", context: int = 3) -> str:
    return "".join(difflib.unified_diff(a.splitlines(True), b.splitlines(True), a_name, b_name, n=context))


def diff_stats(a: str, b: str) -> dict:
    added = removed = 0
    for ln in difflib.ndiff(a.splitlines(), b.splitlines()):
        if ln.startswith("+ "):
            added += 1
        elif ln.startswith("- "):
            removed += 1
    return {"lines_added": added, "lines_removed": removed}
