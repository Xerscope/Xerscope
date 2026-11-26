"""The one place xerscope talks to a network: the local model served by llama.cpp, and nothing else.

The model is reached at XERSCOPE_LLM_URL (``http://llm:8080`` by default, its name on the silo network
of compose.silo.yaml and compose.gpu.yaml), and a faster one when XERSCOPE_LLM_FAST_URL names it
(``http://llm-fast:8080``, the cascade of compose.gpu.yaml). Only the hosts of ``ALLOWED_HOSTS`` are
accepted: the silo's models, or a loopback address for a server on the same machine. A redirect is
refused and no proxy of the environment is used, so a request can only reach the host named. Each
answer is one JSON object under a flat JSON schema (``response_format``, constrained decoding) with
thinking off; the optional reasoning pass (``think``) runs alone, before it. Every request is
deterministic (temperature 0, a seed) and asks the server to keep its prefix cached.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

URL_VARIABLE = "XERSCOPE_LLM_URL"
FAST_URL_VARIABLE = "XERSCOPE_LLM_FAST_URL"
DEFAULT_URL = "http://llm:8080"
ALLOWED_HOSTS = ("llm", "llm-fast", "127.0.0.1", "::1", "localhost")
TIMEOUT_S = 120  # a file's first question reads the whole instructions; slower with layers in RAM
MAX_TOKENS = 160  # one JSON object: a command, a value, a few conditions
THINK_TOKENS = 512  # the reasoning pass, at "low" effort


class ModelError(RuntimeError):
    """The model could not be asked, or its reply is not the JSON object asked for."""


def model_url() -> str:
    """Return the base URL of the model's server, as XERSCOPE_LLM_URL sets it."""
    return os.environ.get(URL_VARIABLE, "").strip() or DEFAULT_URL


def fast_url() -> str:
    """Return the base URL of the faster model asked first (XERSCOPE_LLM_FAST_URL), "" for none."""
    return os.environ.get(FAST_URL_VARIABLE, "").strip()


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
    """Return the model's reply to ``messages``: one JSON object that ``schema`` constrains, thinking off.

    Raises ``ModelError`` when the URL is not allowed, the server does not answer, or the reply is not
    a JSON object.
    """
    reply = _post(
        url,
        {
            "messages": messages,
            "max_tokens": MAX_TOKENS,
            "response_format": {"type": "json_object", "schema": schema},
            "chat_template_kwargs": {"enable_thinking": False},
        },
    )
    try:
        content = reply["choices"][0]["message"]["content"] or ""
        chosen = json.loads(content, strict=False)  # a raw newline inside a string is still the object
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ModelError("the local model's reply is not the JSON object asked for") from error
    if not isinstance(chosen, dict):
        raise ModelError("the local model's reply is not a JSON object")
    return chosen


def think(messages: list[dict], url: str | None = None) -> str:
    """Return the model's reasoning on ``messages``, thinking on at low effort and no schema.

    The first of two passes: a thinking template and a JSON schema in one request have been reported
    to leave the grammar unenforced in llama.cpp (issue 20345), so the reasoning is asked alone and
    handed to ``complete``. Raises ``ModelError`` as ``complete`` does.
    """
    reply = _post(
        url,
        {
            "messages": messages,
            "max_tokens": THINK_TOKENS,
            "chat_template_kwargs": {"enable_thinking": True, "reasoning_effort": "low"},
        },
    )
    try:
        message = reply["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as error:
        raise ModelError("the local model's reply holds no message") from error
    text = message.get("reasoning_content") or message.get("content") or ""
    return text.replace("<think>", "").replace("</think>", "").strip()


def warm(messages: list[dict], url: str | None = None) -> bool:
    """Have the server read ``messages`` once and keep them cached; True when it answered.

    The instructions are the same for every question on one update: read ahead, the first question
    then reads only itself.
    """
    try:
        _post(url, {"messages": messages, "max_tokens": 1, "chat_template_kwargs": {"enable_thinking": False}})
    except ModelError:
        return False
    return True


def _post(url: str | None, payload: dict) -> dict:
    """Send one chat request, deterministic and cached, to an allowed host; its JSON reply."""
    base = (url or model_url()).rstrip("/")
    if not is_allowed(base):
        raise ModelError(f"{URL_VARIABLE} must name the local model (host one of {', '.join(ALLOWED_HOSTS)})")
    body = {"temperature": 0, "seed": 1, "cache_prompt": True, **payload}
    request = urllib.request.Request(
        f"{base}/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    try:
        with _OPENER.open(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - scheme and host checked above
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        raise ModelError(f"the local model did not answer ({error})") from error
