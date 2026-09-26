"""Common problem interface + frozen-instance handling (hash-checked, read-only)."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import INSTANCE_DIR
from ..harness.contract import EvalOutcome
from ..harness.package import Program, split_program


@dataclass
class ProblemSpec:
    name: str
    title: str
    description: str                              # what the mutator (and AlphaEvolve problem_description) sees
    required_functions: tuple[str, ...]
    seed_path: Path
    null_path: Path
    evaluate: Callable[..., EvalOutcome]          # evaluate(program_src, fold="train") -> EvalOutcome
    descriptor: Callable[[EvalOutcome], tuple[int, int]]
    descriptor_names: tuple[str, str]
    folds: tuple[str, ...] = ("train", "holdout")
    unit: str = "JPY M"
    notes: dict = field(default_factory=dict)
    version: str = "v1"
    holdout_fold: str = "holdout"          # tariff moved to "holdout2" after holdout 1 informed evaluator v3

    @property
    def seed_src(self) -> str:
        return self.seed_path.read_text()

    @property
    def null_src(self) -> str:
        return self.null_path.read_text()

    @property
    def seed_program(self) -> Program:
        return split_program(self.seed_src)

    @property
    def baseline_lock_path(self) -> Path:
        return self.seed_path.parent / "baseline_lock.json"


class InstanceError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path() -> Path:
    return INSTANCE_DIR / "manifest.json"


def load_manifest() -> dict:
    p = manifest_path()
    if not p.exists():
        raise InstanceError(f"{p} missing: run `python data/generate.py` first")
    return json.loads(p.read_text())


_CACHE: dict[str, tuple[float, str, dict]] = {}


def load_instance(name: str) -> tuple[dict, str]:
    """Load a frozen instance and verify its content SHA-256 against the manifest on EVERY call.

    The content hash (sorted array names, dtype, shape, bytes) is recomputed from the arrays actually used, so a
    tampered or silently regenerated file is refused. Arrays are marked read-only so evaluator code cannot mutate
    the cached instance between candidates. Returns (arrays, sha256).
    """
    from ..sim.npz import content_sha256, load_npz

    man = load_manifest()
    if name not in man["instances"]:
        raise InstanceError(f"instance {name!r} not in manifest")
    entry = man["instances"][name]
    path = INSTANCE_DIR / entry["file"]
    if not path.exists():
        raise InstanceError(f"{path} missing: run `python data/generate.py` (instances are regenerated deterministically)")
    mtime = path.stat().st_mtime
    cached = _CACHE.get(name)
    if cached and cached[0] == mtime:
        arrays = cached[2]
    else:
        arrays = load_npz(path)
        for a in arrays.values():
            a.setflags(write=False)
    digest = content_sha256(arrays)
    if digest != entry["sha256"]:
        raise InstanceError(f"instance {name} hash mismatch: content {digest[:12]} != manifest {entry['sha256'][:12]} "
                            "(tampered or regenerated without re-locking)")
    _CACHE[name] = (mtime, digest, arrays)
    return arrays, digest


def make_read_only(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
