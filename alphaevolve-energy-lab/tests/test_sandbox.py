"""The sandbox denies I/O, network, look-ahead reads and runaway resources; it only ever returns decisions."""
import pytest

from energy_lab.config import INSTANCE_DIR
from energy_lab.harness.sandbox import SandboxError, SandboxLimits, SandboxSession

FAST = SandboxLimits(wall_s=20, call_timeout_s=5, cpu_s=15, mem_mb=512)


def run(src, arg=None):
    with SandboxSession(src, FAST) as sb:
        return sb.call("f", arg if arg is not None else {"a": 1})


def test_ok_round_trip_and_shared_inputs():
    src = "import numpy as np\ndef f(x, m):\n    return {'y': float(np.sqrt(x['a'])) + m['k']}\n"
    with SandboxSession(src, FAST) as sb:
        sb.put("m", {"k": 2})
        assert sb.map("f", [{"a": 4}, {"a": 9}], shared=("m",)) == [{"y": 4.0}, {"y": 5.0}]


@pytest.mark.parametrize("name,src,needle", [
    ("import_socket", "import socket\ndef f(x):\n    return 1\n", "import of 'socket' denied"),
    ("import_os", "import os\ndef f(x):\n    return 1\n", "import of 'os' denied"),
    ("import_subprocess", "import subprocess\ndef f(x):\n    return 1\n", "denied"),
    ("write_file", "def f(x):\n    open('lab_escape.txt', 'w').write('x')\n", "writing files denied"),
])
def test_denials(name, src, needle):
    with pytest.raises(SandboxError) as e:
        run(src)
    assert needle in str(e.value)


def test_socket_denied_even_if_import_guard_is_bypassed():
    # Reassigning __name__ at module level defeats the import hook; the socket patch must still deny.
    src = "__name__ = 'evil'\nimport socket\ndef f(x):\n    socket.socket()\n"
    with pytest.raises(SandboxError) as e:
        run(src)
    assert "network access" in str(e.value)


def test_sqlite_denied_even_if_import_guard_is_bypassed():
    src = "__name__ = 'evil'\nimport sqlite3\ndef f(x):\n    sqlite3.connect(':memory:')\n"
    with pytest.raises(SandboxError) as e:
        run(src)
    assert "sqlite3.connect denied" in str(e.value)


def test_no_look_ahead_read_of_frozen_instance():
    target = next(INSTANCE_DIR.glob("*.npz"))
    src = f"def f(x):\n    return open({str(target)!r}, 'rb').read(10).hex()\n"
    with pytest.raises(SandboxError) as e:
        run(src)
    assert "reading outside the Python installation denied" in str(e.value)


def test_inputs_are_read_only():
    with pytest.raises(SandboxError) as e:
        run("def f(x):\n    x['a'] = 2\n")
    assert "does not support item assignment" in str(e.value)


def test_wall_clock_limit():
    with pytest.raises(SandboxError) as e:
        run("def f(x):\n    while True:\n        pass\n")
    assert e.value.etype == "Timeout"


def test_memory_limit():
    with pytest.raises(SandboxError) as e:
        run("import numpy as np\ndef f(x):\n    a = np.ones(200_000_000)\n    return float(a.sum())\n")
    assert "memory limit" in str(e.value)


def test_crash_at_import_is_reported():
    with pytest.raises(SandboxError) as e:
        run("raise RuntimeError('boom')\n")
    assert "boom" in str(e.value)


def test_non_json_result_is_rejected():
    with pytest.raises(SandboxError) as e:
        run("def f(x):\n    return object()\n")
    assert "non-JSON" in str(e.value)
