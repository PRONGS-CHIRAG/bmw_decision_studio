"""OpenAI access for the three agents.

Configuration (environment variables, or a git-ignored `.env` file in the repo root):
    OPENAI_API_KEY             required for the LLM agents and embeddings
    OPENAI_RETRIEVER_MODEL     default gpt-6-luna   (Agent 1: idea -> IdeaSpec)
    OPENAI_EXPLAINER_MODEL     default gpt-6-terra  (Agent 2: facts -> PM explanation)
    OPENAI_VERIFIER_MODEL      default gpt-6-luna   (Agent 3: semantic check of each claim)
    OPENAI_EMBEDDING_MODEL     default text-embedding-3-small (semantic matching of ideas)

A configured model that the account cannot use is reported with the models it can
use; it is never replaced by another model silently.
"""

import os
import threading

import numpy as np
from pydantic import BaseModel

from .. import config

ROLES = ("retriever", "explainer", "verifier", "embedding")
DEFAULT_MODELS = {"retriever": "gpt-6-luna", "explainer": "gpt-6-terra", "verifier": "gpt-6-luna",
                  "embedding": "text-embedding-3-small"}
ENV_VARS = {"retriever": "OPENAI_RETRIEVER_MODEL", "explainer": "OPENAI_EXPLAINER_MODEL",
            "verifier": "OPENAI_VERIFIER_MODEL", "embedding": "OPENAI_EMBEDDING_MODEL"}


class LLMError(RuntimeError):
    """A call to the language model failed or returned nothing usable."""


class LLMUnavailable(LLMError):
    """No API key is configured."""


class ModelUnavailable(LLMError):
    """The configured model is not available to this API key."""


class LLMOutputInvalid(LLMError):
    """The model's structured output did not validate against the requested schema."""

    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.errors = errors


def _dotenv() -> dict:
    path = config.ROOT / ".env"
    out = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
    return out


def setting(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name) or _dotenv().get(name) or default


def model_config() -> dict:
    return {role: setting(ENV_VARS[role], DEFAULT_MODELS[role]) for role in ROLES}


class OpenAILLM:
    """Thin wrapper: structured parsing into Pydantic models, embeddings, model availability."""

    provider = "openai"

    def __init__(self, api_key: str, models: dict | None = None, timeout: float = 180.0):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=timeout, max_retries=2)
        self.models = models or model_config()
        self._available: set | None = None
        self._listing_error: str | None = None
        self._lock = threading.Lock()

    # -------------------------------------------------------------- availability
    def available_models(self, refresh: bool = False) -> set | None:
        """Model ids this key can use, or None if the key may not list models."""
        import openai
        with self._lock:
            if self._available is None or refresh:
                try:
                    self._available = {m.id for m in self.client.models.list()}
                    self._listing_error = None
                except openai.AuthenticationError as e:
                    raise LLMError(f"OpenAI rejected the API key: {_msg(e)}") from e
                except openai.OpenAIError as e:
                    self._available, self._listing_error = None, _msg(e)
            return self._available

    def check_models(self, refresh: bool = False) -> dict:
        avail = self.available_models(refresh)
        roles = {r: {"model": m, "available": None if avail is None else m in avail} for r, m in self.models.items()}
        similar = sorted(m for m in (avail or ()) if m.startswith(("gpt-6", "gpt-5", "text-embedding")))
        return {"roles": roles, "listing_error": self._listing_error, "similar_models": similar[:40]}

    def _model(self, role: str) -> str:
        model = self.models[role]
        avail = self.available_models()
        if avail is not None and model not in avail:
            options = sorted(m for m in avail if m.startswith(("gpt-", "text-embedding")))
            raise ModelUnavailable(f"The {role} model '{model}' is not available to this API key. Set "
                                   f"{ENV_VARS[role]} to one of: {', '.join(options[:30]) or '(none listed)'}")
        return model

    # -------------------------------------------------------------- calls
    def parse(self, role: str, instructions: str, input_text: str, schema: type[BaseModel]) -> BaseModel:
        import openai
        from pydantic import ValidationError
        model = self._model(role)
        try:
            resp = self.client.responses.parse(model=model, instructions=instructions, input=input_text,
                                               text_format=schema, store=False)
        except ValidationError as e:
            errors = [f"{'.'.join(str(x) for x in err['loc']) or 'output'}: {err['msg']}" for err in e.errors()]
            raise LLMOutputInvalid(f"{model} returned output that does not match {schema.__name__}", errors) from e
        except openai.OpenAIError as e:
            raise LLMError(f"{model}: {_msg(e)}") from e
        parsed = resp.output_parsed
        if parsed is None:
            raise LLMError(f"{model} returned no structured output (status {resp.status}, "
                           f"details {resp.incomplete_details})")
        return parsed

    def embed(self, texts: list[str], model: str | None = None) -> np.ndarray:
        import openai
        model = model or self._model("embedding")
        try:
            resp = self.client.embeddings.create(model=model, input=texts)
        except openai.OpenAIError as e:
            raise LLMError(f"{model}: {_msg(e)}") from e
        return np.array([d.embedding for d in resp.data], dtype=float)


def _msg(e: Exception) -> str:
    body = getattr(e, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        return body["error"].get("message") or str(e)
    return str(e)


def from_env() -> OpenAILLM | None:
    key = setting("OPENAI_API_KEY")
    return OpenAILLM(key) if key else None
