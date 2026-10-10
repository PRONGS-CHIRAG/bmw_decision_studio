"""Shared test helpers: a scripted stand-in for the OpenAI client (no network)."""

import re

from bmw_feedback.agents.contracts import JudgmentLLM, JudgmentsLLM
from bmw_feedback.agents.llm import LLMError


class FakeLLM:
    """Returns scripted answers per role; callables get the prompt. Embeddings are unavailable."""

    def __init__(self, script=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.models = {"retriever": "fake-luna", "explainer": "fake-terra", "verifier": "fake-luna",
                       "embedding": "fake-embed"}
        self.calls = []

    def parse(self, role, instructions, input_text, schema):
        self.calls.append((role, input_text))
        item = self.script[role].pop(0)
        if isinstance(item, Exception):
            raise item
        out = item(input_text) if callable(item) else item
        assert isinstance(out, schema)
        return out

    def embed(self, texts, model=None):
        raise LLMError("embeddings are not available in tests")

    def check_models(self, refresh=False):
        return {"roles": {r: {"model": m, "available": True} for r, m in self.models.items()}}


def judge_all(supported=True, unsupported_text=None):
    def run(prompt):
        out = []
        for cid, text in re.findall(r"claim_id: (\S+)\nclaim: (.*)", prompt):
            ok = supported and not (unsupported_text and unsupported_text in text)
            out.append(JudgmentLLM(claim_id=cid, verdict="supported" if ok else "unsupported",
                                   reason="scripted"))
        return JudgmentsLLM(judgments=out)
    return run
