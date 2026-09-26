"""AlphaEvolve Energy Lab package.

`energy_lab.agent` (the Lab Analyst root_agent) is exposed lazily so that the data generator and the harness can import
the package before the CSV tables exist; `import energy_lab; energy_lab.agent.root_agent` behaves like `from . import agent`.
"""
import importlib


def __getattr__(name):
    if name == "agent":
        return importlib.import_module(".agent", __name__)   # builds STORE + the agent object; no model calls
    raise AttributeError(name)
