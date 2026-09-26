"""Deterministic .npz writing and content hashing.

np.savez stamps zip entries with the current time, so two byte-identical datasets produce different files.
Instances are written with fixed zip timestamps and hashed by CONTENT (sorted array names, dtype, shape, bytes),
so regenerating the gitignored cache reproduces the recorded SHA-256 and the baseline lock holds.
"""
from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np


def _c(a) -> np.ndarray:
    """C-contiguous view/copy that keeps 0-d arrays 0-d (np.ascontiguousarray promotes them to 1-d)."""
    a = np.asarray(a)
    return a if a.flags.c_contiguous else a.copy(order="C")


def content_sha256(arrays: dict[str, np.ndarray]) -> str:
    h = hashlib.sha256()
    for name in sorted(arrays):
        a = _c(arrays[name])
        h.update(name.encode())
        h.update(a.dtype.str.encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def save_npz(path: Path, arrays: dict[str, np.ndarray]) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.chmod(0o644)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(arrays):
            buf = io.BytesIO()
            np.lib.format.write_array(buf, _c(arrays[name]), allow_pickle=False)
            info = zipfile.ZipInfo(f"{name}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, buf.getvalue())
    return content_sha256(arrays)


def load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}
