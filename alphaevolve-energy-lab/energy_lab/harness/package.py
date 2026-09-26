"""EVOLVE-BLOCK packaging: only the marked policy block evolves; the scaffolding around it is fixed.

A program is ``prefix + START + block + END + suffix``. ``check_scaffolding`` proves a candidate kept
the seed's prefix/suffix byte-for-byte, and ``static_check`` rejects blocks that reach for I/O,
introspection or nondeterminism before anything executes (the sandbox denies these again at runtime;
the static pass exists so the next generation gets a precise insight instead of a stack trace).
"""
from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

START = "# EVOLVE-BLOCK-START"
END = "# EVOLVE-BLOCK-END"

ALLOWED_IMPORTS = {"math", "numpy", "statistics", "itertools", "functools", "collections", "heapq",
                   "bisect", "dataclasses", "typing", "operator", "copy"}
DENIED_NAMES = {"eval", "exec", "compile", "open", "__import__", "globals", "locals", "vars", "getattr",
                "setattr", "delattr", "input", "breakpoint", "memoryview", "help", "exit", "quit"}
DENIED_ATTRS = {"random", "now", "today", "utcnow", "time_ns", "perf_counter", "system", "popen", "load", "save",
                "savez", "tofile", "fromfile", "loadtxt", "genfromtxt", "memmap", "ctypeslib", "lib"}


class PackagingError(ValueError):
    pass


@dataclass(frozen=True)
class Program:
    prefix: str
    block: str
    suffix: str

    @property
    def source(self) -> str:
        return assemble(self.prefix, self.block, self.suffix)

    @property
    def block_sha(self) -> str:
        return hashlib.sha256(self.block.encode()).hexdigest()[:16]


def split_program(src: str) -> Program:
    if src.count(START) != 1 or src.count(END) != 1:
        raise PackagingError(f"program must contain exactly one '{START}' and one '{END}' marker")
    i, j = src.index(START), src.index(END)
    if j < i:
        raise PackagingError("EVOLVE-BLOCK-END appears before EVOLVE-BLOCK-START")
    head_end = src.index("\n", i) + 1          # block starts on the line after the START marker
    tail_start = src.rindex("\n", 0, j) + 1    # block ends before the END marker line
    return Program(prefix=src[:head_end], block=src[head_end:tail_start], suffix=src[tail_start:])


def assemble(prefix: str, block: str, suffix: str) -> str:
    if not block.endswith("\n"):
        block += "\n"
    return prefix + block + suffix


def check_scaffolding(seed: Program, cand: Program) -> str | None:
    """Return an error string if anything outside the EVOLVE-BLOCK differs from the seed."""
    if cand.prefix != seed.prefix:
        return "code before EVOLVE-BLOCK-START was modified (scaffolding is fixed)"
    if cand.suffix != seed.suffix:
        return "code after EVOLVE-BLOCK-END was modified (scaffolding is fixed)"
    return None


def static_check(program: Program, required_functions: tuple[str, ...]) -> list[str]:
    """AST scan of the evolve block (plus a parse of the whole program). Returns a list of problems."""
    problems: list[str] = []
    try:
        ast.parse(program.source)
    except SyntaxError as e:
        return [f"SyntaxError: {e.msg} (line {e.lineno})"]
    try:
        tree = ast.parse(program.block)
    except SyntaxError as e:  # block must parse on its own (it is top-level code)
        return [f"SyntaxError in EVOLVE-BLOCK: {e.msg} (block line {e.lineno})"]
    defined = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for fn in required_functions:
        if fn not in defined:
            problems.append(f"required function '{fn}' is not defined at top level of the EVOLVE-BLOCK")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_IMPORTS:
                    problems.append(f"import of '{a.name}' is not allowed (allowed: {sorted(ALLOWED_IMPORTS)})")
        elif isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if node.level or mod not in ALLOWED_IMPORTS:
                problems.append(f"import from '{node.module}' is not allowed")
        elif isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            problems.append(f"dunder name '{node.id}' is not allowed in the policy block")
        elif isinstance(node, ast.Name) and node.id in DENIED_NAMES:
            problems.append(f"use of '{node.id}' is not allowed in the policy block (no I/O or introspection)")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                problems.append(f"dunder attribute access '.{node.attr}' is not allowed")
            elif node.attr in DENIED_ATTRS:
                problems.append(f"attribute '.{node.attr}' is not allowed (nondeterminism or file I/O)")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            problems.append("global/nonlocal state is not allowed: the policy must be a pure function of its inputs")
        elif isinstance(node, (ast.AsyncFunctionDef, ast.Await)):
            problems.append("async code is not allowed in the policy block")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.Lambda)):
            for d in list(node.args.defaults) + [x for x in node.args.kw_defaults if x is not None]:
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    problems.append("mutable default argument is not allowed (it would carry state between calls)")
    # Module-level mutable state that functions could use as memory across calls breaks determinism.
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            val = n.value
            if isinstance(val, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp)) or (
                isinstance(val, ast.Call) and getattr(val.func, "id", "") in {"list", "dict", "set", "defaultdict"}
            ):
                tgt = ast.unparse(n.targets[0] if isinstance(n, ast.Assign) else n.target)
                problems.append(f"module-level mutable container '{tgt}' is not allowed (use tuples or constants)")
    seen, out = set(), []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
