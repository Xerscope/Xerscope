"""The one place xerscope talks to a network: the local model served by llama.cpp, and nothing else.

The model is reached at XERSCOPE_LLM_URL (``http://llm:8080`` by default, its name on the silo network of
compose.silo.yaml and compose.gpu.yaml). Only the hosts of ``ALLOWED_HOSTS`` are accepted: the silo's
model, or a loopback address for a server on the same machine. A redirect is refused and no proxy of the
environment is used, so a request can only reach the host named. Each request asks for one JSON object
under a flat JSON schema (llama-server ``response_format``, constrained decoding) and turns the model's
thinking off (``chat_template_kwargs``): the model chooses, it does not reason at length.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

URL_VARIABLE = "XERSCOPE_LLM_URL"
DEFAULT_URL = "http://llm:8080"
ALLOWED_HOSTS = ("llm", "127.0.0.1", "::1", "localhost")
TIMEOUT_S = 120  # a file's first question reads the whole instructions; slower with layers in RAM
MAX_TOKENS = 120  # one JSON object of a tool, a field and an argument


class ModelError(RuntimeError):
    """The model could not be asked, or its reply is not the JSON object asked for."""


def model_url() -> str:
    """Return the base URL of the model's server, as XERSCOPE_LLM_URL sets it."""
    return os.environ.get(URL_VARIABLE, "").strip() or DEFAULT_URL


def is_allowed(url: str) -> bool:
    """Tell whether the URL is http(s) and its host (not a userinfo, not a longer name) is allowed."""
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.hostname in ALLOWED_HOSTS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx is an error: the model's server cannot send the request elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ProxyHandler({}): an HTTP(S)_PROXY in the environment must not carry the request to a proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


def complete(messages: list[dict], schema: dict, url: str | None = None) -> dict:
    """Return the model's reply to ``messages``: one JSON object that ``schema`` constrains.

    Raises ``ModelError`` when the URL is not allowed, the server does not answer, or the reply is not
    a JSON object.
    """
    base = (url or model_url()).rstrip("/")
    if not is_allowed(base):
        raise ModelError(f"{URL_VARIABLE} must name the local model (host one of {', '.join(ALLOWED_HOSTS)})")
    payload = {
        "messages": messages,
        "temperature": 0,
        "seed": 1,
        "max_tokens": MAX_TOKENS,
        "response_format": {"type": "json_object", "schema": schema},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{base}/v1/chat/completions", json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    try:
        with _OPENER.open(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - scheme and host checked above
            reply = json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ModelError(f"the local model did not answer ({error})") from error
    try:
        content = reply["choices"][0]["message"]["content"] or ""
        chosen = json.loads(content, strict=False)  # a raw newline inside a string is still the object
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ModelError("the local model's reply is not the JSON object asked for") from error
    if not isinstance(chosen, dict):
        raise ModelError("the local model's reply is not a JSON object")
    return chosen
