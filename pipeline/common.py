"""Shared helpers for the promise-tracker pipeline.

Only the standard library plus numpy; AI calls go to a local Ollama server.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
SITE = ROOT / "site"
LOGS = ROOT / "logs"

OLLAMA = os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434")
_LAST_CALL = [0.0]
UA = "Mozilla/5.0 (compatible; PromiseTracker/0.1; hobby project)"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def load_json(path: Path, default=None):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def today() -> str:
    return dt.date.today().isoformat()


def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def http_get(url: str, timeout: int = 25) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


_QUOTES = re.compile(r"[\"'“”„‘’«»‹›`´]")


def norm(s: str) -> str:
    """Loose normalisation used to check that a quote really appears in a text."""
    s = _QUOTES.sub("", s or "").casefold()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def mentions(text: str, aliases: list[str]) -> bool:
    for a in aliases:
        if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", text, flags=re.IGNORECASE | re.UNICODE):
            return True
    return False


# ---------------------------------------------------------------- Ollama ----

def ollama_up() -> bool:
    try:
        http_get(f"{OLLAMA}/api/tags", timeout=3)
        return True
    except Exception:
        return False


def ensure_ollama(wait: int = 40) -> bool:
    if ollama_up():
        return True
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
    cmd = [str(exe) if exe.exists() else "ollama", "serve"]
    try:
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0  # DETACHED | NEW_GROUP
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    except Exception as e:  # noqa: BLE001
        log(f"could not launch ollama: {e}")
        return False
    for _ in range(wait):
        time.sleep(1)
        if ollama_up():
            return True
    return False


def _post(path: str, payload: dict, timeout: int) -> dict:
    req = urllib.request.Request(
        f"{OLLAMA}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def backend() -> dict:
    """Which engine judges headlines. Config in sources.json, overridable by env (PT_CHAT_BACKEND / PT_MATCHER).

    chat: "ollama"   local Ollama (default)
          "openai"   any OpenAI-compatible API (JUDGE_BASE_URL, JUDGE_API_KEY, JUDGE_MODEL)
          "external" an agent (e.g. Hermes) reads data/work/tasks.json and writes data/work/answers.json
    matcher: "embeddings" (needs Ollama + bge-m3), "keywords" (no dependencies), or "auto".
    """
    cfg = (load_json(DATA / "sources.json", {}) or {}).get("backend", {})
    return {"chat": os.environ.get("PT_CHAT_BACKEND", cfg.get("chat", "ollama")),
            "matcher": os.environ.get("PT_MATCHER", cfg.get("matcher", "auto"))}


def chat_json(model: str, system: str, user: str, schema: dict, timeout: int = 240) -> dict | None:
    """One deterministic chat call that must return JSON matching `schema`."""
    if backend()["chat"] == "openai":
        return _chat_openai(model, system, user, schema, timeout)
    return _chat_ollama(model, system, user, schema, timeout)


def _chat_openai(model: str, system: str, user: str, schema: dict, timeout: int) -> dict | None:
    base = os.environ.get("JUDGE_BASE_URL", f"{OLLAMA}/v1").rstrip("/")
    key = os.environ.get("JUDGE_API_KEY", "")
    keys = ", ".join(schema.get("properties", {}))
    payload = {
        "model": os.environ.get("JUDGE_MODEL", model),
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": f"{system}\nReturn ONLY a JSON object with exactly these keys: {keys}."},
            {"role": "user", "content": user},
        ],
    }
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
    gap = float(os.environ.get("PT_MIN_INTERVAL", "0"))  # free APIs cap requests per minute
    for attempt in range(4):
        pause = gap - (time.time() - _LAST_CALL[0])
        if pause > 0:
            time.sleep(pause)
        _LAST_CALL[0] = time.time()
        try:
            req = urllib.request.Request(f"{base}/chat/completions", data=json.dumps(payload).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                status, raw = resp.status, resp.read().decode("utf-8", "replace")
            try:
                text = json.loads(raw)["choices"][0]["message"]["content"] or ""
            except (ValueError, KeyError, IndexError, TypeError):
                log(f"  unexpected API reply (HTTP {status}): {raw[:300]!r}")
                return None
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
            try:
                return json.loads(text)
            except ValueError:
                found = re.search(r"\{.*\}", text, flags=re.S)  # tolerate prose around the JSON object
                if found:
                    try:
                        return json.loads(found.group(0))
                    except ValueError:
                        pass
                log(f"  reply was not JSON: {text[:300]!r}")
                return None
        except urllib.error.HTTPError as e:
            retry_after = int(e.headers.get("Retry-After") or 0)
            if e.code in (429, 500, 502, 503) and attempt < 3 and retry_after <= 300:
                delay = min(retry_after or 15 * (attempt + 1), 90)
                log(f"  API busy (HTTP {e.code}), waiting {delay}s")
                time.sleep(delay)
                continue
            log(f"  chat failed: HTTP {e.code} {e.read()[:160].decode('utf-8', 'replace')}")  # long Retry-After = daily cap reached
            return None
        except Exception as e:  # noqa: BLE001
            log(f"  chat failed: {type(e).__name__}: {e}")
            return None
    return None


def effective_chat_model(models: dict) -> str:
    """The model name that actually judged (JUDGE_MODEL overrides the config for the openai backend)."""
    return os.environ.get("JUDGE_MODEL", models["chat"]) if backend()["chat"] == "openai" else models["chat"]


def _chat_ollama(model: str, system: str, user: str, schema: dict, timeout: int) -> dict | None:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "num_ctx": 4096},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        out = _post("/api/chat", payload, timeout)
        return json.loads(out["message"]["content"])
    except Exception as e:  # noqa: BLE001
        log(f"  chat failed: {type(e).__name__}: {e}")
        return None


def embed(model: str, texts: list[str], batch: int = 24) -> np.ndarray:
    """L2-normalised embeddings, one row per text."""
    rows: list[list[float]] = []
    for i in range(0, len(texts), batch):
        out = _post("/api/embed", {"model": model, "input": texts[i : i + batch]}, 300)
        rows.extend(out["embeddings"])
    arr = np.asarray(rows, dtype=np.float32)
    if arr.size == 0:
        return arr.reshape(0, 0)
    arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
    return arr


def item_text(item: dict) -> str:
    return (item["title"] + (". " + item["summary"] if item.get("summary") else "")).strip()
