import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from google.adk.agents import LlmAgent  # noqa: E402

from retail_desk import model_policy as mp  # noqa: E402
from retail_desk.agent import SPECIALISTS  # noqa: E402

CLONES = {s.name: s.clone(update={"mode": "chat", "disallow_transfer_to_parent": True, "disallow_transfer_to_peers": True})
          for s in SPECIALISTS}
root_agent = LlmAgent(name="specialist_bench", model=mp.BALANCED_ID, instruction="Eval bench root; not used directly.",
                      sub_agents=list(CLONES.values()))
