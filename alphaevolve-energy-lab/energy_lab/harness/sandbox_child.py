"""Sandbox child: executes ONE untrusted candidate program and answers decision requests over a pipe.

Launched by harness/sandbox.py as ``python -s -P sandbox_child.py`` with a scrubbed environment, an empty
temporary working directory, and resource limits. This file deliberately imports nothing from the
``energy_lab`` package: the child never sees the evaluator, the frozen instance, or realised data. It
only receives decision contexts (features, forecasts) and returns decisions; the trusted parent
simulates and scores. Forging a reply therefore buys a candidate nothing it could not return anyway.

Denials installed before the candidate executes (defence in depth; production runs this inside the
AlphaEvolve evaluator container):
  * network: socket.socket / create_connection / getaddrinfo -> PermissionError
  * sqlite3.connect -> PermissionError
  * open / io.open / os.open: any write mode denied; reads allowed only under the Python installation
    (lazy stdlib / numpy imports), so the frozen instance and realised data cannot be read (no look-ahead)
  * process / filesystem mutation: os.system, popen, fork, exec*, spawn*, kill, remove, rename, mkdir, ...
  * imports from candidate code limited to an allowlist (math, numpy, statistics, itertools, ...)
  * CPU (RLIMIT_CPU), address space (RLIMIT_AS where the OS supports it) and an RSS watchdog thread
Protocol: newline-delimited JSON on dup'd copies of fd 0/1 (the candidate's print() goes to a buffer).
"""
import builtins
import io
import json
import math  # noqa: F401  (preloaded so candidate imports resolve without file reads)
import os
import resource
import socket
import sqlite3
import subprocess
import sys
import threading
import traceback
import types

import numpy  # noqa: F401  preload
import numpy as _np

ALLOWED_IMPORTS = {"math", "numpy", "statistics", "itertools", "functools", "collections", "heapq", "bisect",
                   "dataclasses", "typing", "operator", "copy"}
for _m in ("statistics", "itertools", "functools", "collections", "heapq", "bisect", "dataclasses", "typing",
           "operator", "copy"):
    __import__(_m)

_proto_in = os.fdopen(os.dup(0), "r", encoding="utf-8")
_proto_out = os.fdopen(os.dup(1), "w", encoding="utf-8")
_captured = io.StringIO()
sys.stdout = _captured
sys.stdin = io.StringIO("")


def _send(obj):
    _proto_out.write(json.dumps(obj, default=_json_default, allow_nan=True) + "\n")
    _proto_out.flush()


def _json_default(o):
    if isinstance(o, _np.integer):
        return int(o)
    if isinstance(o, _np.floating):
        return float(o)
    if isinstance(o, _np.bool_):
        return bool(o)
    if isinstance(o, _np.ndarray):
        return o.tolist()
    if isinstance(o, (types.MappingProxyType,)):
        return dict(o)
    if isinstance(o, tuple):
        return list(o)
    raise TypeError(f"decision contains a non-JSON value of type {type(o).__name__}")


def _freeze(x):
    """Read-only views so a candidate cannot mutate shared inputs between calls."""
    if isinstance(x, dict):
        return types.MappingProxyType({k: _freeze(v) for k, v in x.items()})
    if isinstance(x, list):
        return tuple(_freeze(v) for v in x)
    return x


def _deny(what):
    def _f(*a, **k):
        raise PermissionError(f"sandbox: {what} denied")
    return _f


def _install_guards(mem_mb: int, cpu_s: int):
    # --- resource limits -------------------------------------------------------------------------
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 2))
    except (ValueError, OSError):
        pass
    try:  # enforced on Linux (Cloud Run / containers); macOS refuses, the watchdog below covers it
        resource.setrlimit(resource.RLIMIT_AS, (mem_mb << 20, mem_mb << 20))
    except (ValueError, OSError):
        pass
    scale = 1 if sys.platform == "darwin" else 1024  # ru_maxrss: bytes on macOS, KiB on Linux

    def _watch():
        import time as _t
        while True:
            if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * scale > (mem_mb << 20):
                sys.stderr.write(f"sandbox: memory limit exceeded ({mem_mb} MB)\n")
                sys.stderr.flush()
                os._exit(137)
            _t.sleep(0.05)

    threading.Thread(target=_watch, daemon=True).start()

    # --- network / database ----------------------------------------------------------------------
    socket.socket = _deny("network access (socket)")
    socket.create_connection = _deny("network access (create_connection)")
    socket.getaddrinfo = _deny("network access (getaddrinfo)")
    socket.socketpair = _deny("network access (socketpair)")
    sqlite3.connect = _deny("sqlite3.connect")

    # --- files -------------------------------------------------------------------------------------
    real_open = io.open
    prefixes = tuple(os.path.realpath(p) + os.sep for p in {sys.prefix, sys.base_prefix, sys.exec_prefix})

    def _guarded_open(file, mode="r", *a, **k):
        if isinstance(file, int):
            raise PermissionError("sandbox: opening raw file descriptors denied")
        if any(c in mode for c in "wax+"):
            raise PermissionError(f"sandbox: writing files denied ({file!r}, mode {mode!r})")
        path = os.path.realpath(os.fspath(file))
        if not path.startswith(prefixes):
            raise PermissionError(f"sandbox: reading outside the Python installation denied ({file!r})")
        return real_open(file, mode, *a, **k)

    builtins.open = _guarded_open
    io.open = _guarded_open
    real_os_open = os.open

    def _guarded_os_open(path, flags, *a, **k):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            raise PermissionError("sandbox: writing files denied (os.open)")
        if not os.path.realpath(os.fspath(path)).startswith(prefixes):
            raise PermissionError("sandbox: reading outside the Python installation denied (os.open)")
        return real_os_open(path, flags, *a, **k)

    os.open = _guarded_os_open
    for name in ("system", "popen", "fork", "forkpty", "execv", "execve", "execvp", "execvpe", "execl", "execle",
                 "execlp", "execlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe", "spawnl", "spawnle", "posix_spawn",
                 "posix_spawnp", "kill", "killpg", "remove", "unlink", "rmdir", "removedirs", "rename", "renames",
                 "replace", "mkdir", "makedirs", "chmod", "chown", "symlink", "link", "truncate", "write", "writev",
                 "dup", "dup2", "fdopen", "putenv", "unsetenv", "chdir"):
        if hasattr(os, name):
            setattr(os, name, _deny(f"os.{name}"))
    subprocess.Popen = _deny("subprocess")
    subprocess.run = _deny("subprocess")
    subprocess.call = _deny("subprocess")
    subprocess.check_output = _deny("subprocess")

    # --- imports from candidate code ---------------------------------------------------------------
    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if globals is not None and globals.get("__name__") == "candidate":
            top = name.split(".")[0]
            if level or top not in ALLOWED_IMPORTS:
                raise ImportError(f"sandbox: import of '{name}' denied (allowed: {sorted(ALLOWED_IMPORTS)})")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = _guarded_import


_SRC_LINES = []


def main():
    header = json.loads(_proto_in.readline())
    _SRC_LINES.extend(header["program"].splitlines())
    _install_guards(int(header.get("mem_mb", 1024)), int(header.get("cpu_s", 60)))
    mod = types.ModuleType("candidate")
    mod.__dict__["__name__"] = "candidate"
    try:
        code = compile(header["program"], "candidate.py", "exec")
        exec(code, mod.__dict__)
    except BaseException as e:  # noqa: BLE001  report, never crash silently
        _send({"ok": False, "etype": type(e).__name__, "error": _short_tb(e), "stdout": _captured.getvalue()[-1000:]})
        return
    _send({"ok": True, "stdout": _captured.getvalue()[-1000:]})
    shared = {}
    for line in _proto_in:
        msg = json.loads(line)
        op = msg.get("op")
        try:
            if op == "exit":
                _send({"ok": True})
                return
            if op == "put":
                shared[msg["key"]] = _freeze(msg["value"])
                _send({"ok": True})
                continue
            fn = mod.__dict__.get(msg["fn"])
            if not callable(fn):
                raise NameError(f"function '{msg['fn']}' is not defined by the program")
            if op == "call":
                args = [_freeze(a) for a in msg.get("args", [])]
                args += [shared[k] for k in msg.get("shared", [])]
                _send({"ok": True, "result": fn(*args)})
            elif op == "map":
                extra = [shared[k] for k in msg.get("shared", [])]
                _send({"ok": True, "result": [fn(_freeze(item), *extra) for item in msg["items"]]})
            else:
                raise ValueError(f"unknown op {op}")
        except BaseException as e:  # noqa: BLE001
            try:
                _send({"ok": False, "etype": type(e).__name__, "error": _short_tb(e)})
            except BaseException as e2:  # noqa: BLE001  e.g. non-serialisable result
                _send({"ok": False, "etype": type(e2).__name__, "error": str(e2)[:500]})


def _short_tb(e: BaseException) -> str:
    tb = traceback.extract_tb(e.__traceback__)
    frames = [f for f in tb if f.filename == "candidate.py"][-3:]
    def _src(n):
        return _SRC_LINES[n - 1].strip()[:120] if n and 0 < n <= len(_SRC_LINES) else ""
    where = "; ".join(f"line {f.lineno} in {f.name}: {_src(f.lineno)}" for f in frames)
    return f"{type(e).__name__}: {str(e)[:400]}" + (f" [{where}]" if where else "")


if __name__ == "__main__":
    main()
