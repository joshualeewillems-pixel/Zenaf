"""
Ollama model provider: local generate via Ollama API.
URL, model, and timeout are read from config.py.
"""

import sys
from pathlib import Path

import requests

# Load config from parent (local_ai) so it works from any cwd
_config_dir = Path(__file__).resolve().parent.parent
if str(_config_dir) not in sys.path:
    sys.path.insert(0, str(_config_dir))
import config as _config  # noqa: E402


class OllamaProvider:
    """Local Ollama API. Single method used by Zenaf: generate(prompt) -> response text."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        # Raw kwarg (e.g. profile ollama_base_url); None means caller relied on config default.
        self._base_url_kwarg = base_url
        self.base_url = base_url if base_url is not None else _config.OLLAMA_URL
        self.model = model if model is not None else _config.OLLAMA_MODEL
        self.timeout = timeout if timeout is not None else _config.MODEL_TIMEOUT

    def generate(self, prompt: str, *, timeout: int | None = None) -> str:
        """Send prompt to Ollama; return model response text. Raises on HTTP/API errors."""
        import time as _time
        import json as _json

        from local_ai.perf_trace import perf_mark

        # #region agent log
        _t0 = _time.perf_counter()
        _plen = len(prompt) if prompt else 0
        _log_path = _config_dir.parent / "debug-5581d2.log"
        try:
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({"sessionId": "5581d2", "hypothesisId": "H2,H3", "location": "ollama.py:generate", "message": "generate start", "data": {"prompt_len": _plen, "model": self.model}, "timestamp": int(_time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        _effective_timeout = timeout if timeout is not None else self.timeout
        perf_mark(
            "ollama_generate_before_requests_post",
            url=self.base_url,
            model=self.model,
            prompt_len=_plen,
            timeout=_effective_timeout,
        )
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        r = requests.post(
            self.base_url,
            json=payload,
            timeout=_effective_timeout,
        )
        perf_mark(
            "ollama_generate_after_requests_post_status",
            status_code=r.status_code,
        )
        r.raise_for_status()
        out = r.json()["response"]
        _dur_ms = (_time.perf_counter() - _t0) * 1000
        perf_mark(
            "ollama_generate_complete",
            wall_ms=round(_dur_ms, 2),
            response_len=len(out) if out else 0,
        )
        # #region agent log
        _dur = int(_dur_ms)
        try:
            with open(_log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({"sessionId": "5581d2", "hypothesisId": "H2,H3", "location": "ollama.py:generate", "message": "generate end", "data": {"duration_ms": _dur, "response_len": len(out) if out else 0}, "timestamp": int(_time.time() * 1000)}) + "\n")
        except Exception:
            pass
        # #endregion
        return out
