"""Parent side of the per-candidate subprocess sandbox.

Every candidate runs in a FRESH child process (``sandbox_child.py``) with a scrubbed environment, an
empty temp cwd, CPU / memory limits, and a wall-clock budget enforced here. The parent sends decision
contexts and receives decisions; all simulation and scoring stays in the trusted parent process.
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHILD = Path(__file__).with_name("sandbox_child.py")


@dataclass(frozen=True)
class SandboxLimits:
    wall_s: float = 90.0        # whole evaluation (all calls) for one candidate
    call_timeout_s: float = 20.0
    cpu_s: int = 80
    mem_mb: int = 1024


class SandboxError(RuntimeError):
    """Candidate-attributable failure (crash, denial, timeout, bad output). Message becomes the insight."""

    def __init__(self, message: str, etype: str = "SandboxError"):
        super().__init__(message)
        self.etype = etype


def _json_default(o: Any):
    import numpy as np

    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o).__name__)


class SandboxSession:
    """Context manager: ``with SandboxSession(src, limits) as sb: sb.call("fn", arg)``."""

    def __init__(self, program_src: str, limits: SandboxLimits | None = None):
        self.src = program_src
        self.limits = limits or SandboxLimits()
        self.proc: subprocess.Popen | None = None
        self._q: queue.Queue = queue.Queue()
        self._t0 = 0.0
        self.calls = 0
        self.stdout_tail = ""
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._errf = None

    # -- lifecycle ---------------------------------------------------------------------------------
    def __enter__(self) -> "SandboxSession":
        self._tmp = tempfile.TemporaryDirectory(prefix="ae_sbx_")
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "VECLIB_MAXIMUM_THREADS": "1", "LANG": "C.UTF-8"}
        self._errf = tempfile.TemporaryFile(mode="w+b")
        self.proc = subprocess.Popen([sys.executable, "-s", "-P", str(CHILD)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self._errf, cwd=self._tmp.name, env=env,
                                     start_new_session=True)
        threading.Thread(target=self._reader, daemon=True).start()
        self._t0 = time.monotonic()
        try:
            hello = self._rpc({"op": "init", "program": self.src, "mem_mb": self.limits.mem_mb,
                               "cpu_s": self.limits.cpu_s}, raw_header=True)
        except BaseException:
            self.close()
            raise
        self.stdout_tail = hello.get("stdout", "")
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.write(b'{"op":"exit"}\n')
                self.proc.stdin.flush()
                self.proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        if self.proc and self.proc.poll() is None:
            self._kill()
        if self._errf:
            self._errf.close()
            self._errf = None
        if self._tmp:
            self._tmp.cleanup()
            self._tmp = None

    def _kill(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:  # noqa: BLE001
            try:
                self.proc.kill()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass

    def _reader(self) -> None:
        for line in self.proc.stdout:
            self._q.put(line)
        self._q.put(None)

    def _stderr_tail(self) -> str:
        if not self._errf:
            return ""
        try:
            self._errf.flush()
            self._errf.seek(0)
            return self._errf.read()[-800:].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return ""

    # -- rpc ---------------------------------------------------------------------------------------
    def _rpc(self, msg: dict, raw_header: bool = False) -> dict:
        if self.proc is None:
            raise SandboxError("sandbox not started")
        elapsed = time.monotonic() - self._t0
        remaining = self.limits.wall_s - elapsed
        if remaining <= 0:
            self._kill()
            raise SandboxError(f"sandbox: wall-clock limit exceeded ({self.limits.wall_s:.0f} s for the evaluation)",
                               "Timeout")
        try:
            self.proc.stdin.write((json.dumps(msg, default=_json_default) + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise self._death_error() from None
        timeout = min(remaining, self.limits.call_timeout_s if not raw_header else max(30.0, remaining))
        try:
            line = self._q.get(timeout=timeout)
        except queue.Empty:
            self._kill()
            what = "call" if not raw_header else "program load"
            raise SandboxError(f"sandbox: {what} exceeded the time limit ({timeout:.0f} s)", "Timeout") from None
        if line is None:
            raise self._death_error()
        self.calls += 1
        try:
            resp = json.loads(line)
        except json.JSONDecodeError:
            raise SandboxError("sandbox: malformed reply from child", "Protocol") from None
        if not resp.get("ok"):
            raise SandboxError(resp.get("error", "unknown error"), resp.get("etype", "Error"))
        return resp

    def _death_error(self) -> SandboxError:
        try:
            self.proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
        rc = self.proc.returncode
        err = self._stderr_tail()
        if "memory limit exceeded" in err or rc in (137, -9) and "memory" in err:
            return SandboxError(f"sandbox: memory limit exceeded ({self.limits.mem_mb} MB)", "MemoryError")
        if rc in (-signal.SIGXCPU, 128 + signal.SIGXCPU, -signal.SIGKILL) and "memory" not in err:
            return SandboxError(f"sandbox: CPU limit exceeded ({self.limits.cpu_s} s) or process killed (rc={rc})",
                                "Timeout")
        return SandboxError(f"sandbox: child exited (rc={rc}). stderr: {err.strip()[-400:]}", "Crash")

    def put(self, key: str, value: Any) -> None:
        self._rpc({"op": "put", "key": key, "value": value})

    def call(self, fn: str, *args: Any, shared: tuple[str, ...] = ()) -> Any:
        return self._rpc({"op": "call", "fn": fn, "args": list(args), "shared": list(shared)})["result"]

    def map(self, fn: str, items: list, shared: tuple[str, ...] = ()) -> list:
        return self._rpc({"op": "map", "fn": fn, "items": items, "shared": list(shared)})["result"]
