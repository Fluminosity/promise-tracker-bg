"""Run the update.

    python pipeline/run_all.py            # everything, judged by the configured backend (ollama / openai)
    python pipeline/run_all.py prepare    # fetch + write data/work/tasks.json for an external judge (Hermes agent)
    python pipeline/run_all.py apply      # read data/work/answers.json, apply guards + verdict rules, rebuild site
    python pipeline/run_all.py --no-ai    # only fetch headlines and rebuild the site

Every step is isolated, so a failing news feed or an unreachable model never prevents the site from rebuilding.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build  # noqa: E402
import discover  # noqa: E402
import external  # noqa: E402
import fetch  # noqa: E402
import judge  # noqa: E402
import match  # noqa: E402
import verdict  # noqa: E402
from common import (DATA, LOGS, backend, ensure_ollama, load_json, log,  # noqa: E402
                    now_iso, save_json, today)


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, s):
        for st in self.streams:
            st.write(s)

    def flush(self):
        for st in self.streams:
            st.flush()


def step(report: dict, name: str, fn):
    t0 = time.time()
    try:
        report[name] = {"ok": True, **(fn() or {})}
    except Exception as e:  # noqa: BLE001
        log(f"STEP {name} FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    report[name]["seconds"] = round(time.time() - t0, 1)


def _matcher(cfg: dict):
    return match.make(cfg["models"], load_json(DATA / "promises.json", []), load_json(DATA / "news.json", {"items": []})["items"])


def do_prepare(cfg: dict) -> dict:
    m = _matcher(cfg)
    external.write_tasks(judge.prepare(m, cfg["limits"], cfg["thresholds"]), discover.prepare(cfg["limits"]))
    return {"matcher": m.kind}


def do_apply(cfg: dict, report: dict) -> None:
    tasks, answers = external.load_tasks(), external.load_answers()
    if not (answers.get("judge") or answers.get("discover")):
        log("apply: no answers found in data/work/answers.json - nothing to apply")
        report["apply"] = {"ok": False, "error": "no answers file"}
        return
    label = "external-agent"
    m = _matcher(cfg)
    step(report, "judge", lambda: judge.apply_answers(answers.get("judge", {}), tasks["judge"]["tasks"], cfg["thresholds"], label))
    step(report, "verdict", lambda: verdict.run(cfg["thresholds"], label))
    step(report, "discover", lambda: discover.apply_answers(answers.get("discover", {}), cfg["limits"], cfg["thresholds"], m, label))
    external.archive()


def main() -> None:
    LOGS.mkdir(exist_ok=True)
    logfile = (LOGS / f"run-{today()}.log").open("a", encoding="utf-8")
    sys.stdout = Tee(sys.__stdout__, logfile)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mode = args[0] if args else "all"
    log(f"=== update started ({mode}) ===")

    cfg = load_json(DATA / "sources.json")
    chat = backend()["chat"]
    report: dict = {"started": now_iso(), "mode": mode, "chat_backend": chat}
    use_ai = "--no-ai" not in sys.argv

    if mode == "apply":
        do_apply(cfg, report)
    else:
        step(report, "fetch", fetch.run)
        if mode == "prepare" or (mode == "all" and chat == "external"):
            step(report, "prepare", lambda: do_prepare(cfg))
            log("external judge: now let the agent write data/work/answers.json, then run: python pipeline/run_all.py apply")
        elif use_ai and (chat == "openai" or ensure_ollama()):
            m = _matcher(cfg)
            label = cfg["models"]["chat"]
            step(report, "judge", lambda: judge.run(cfg["models"], cfg["limits"], cfg["thresholds"], m))
            step(report, "verdict", lambda: verdict.run(cfg["thresholds"], label))
            step(report, "discover", lambda: discover.run(cfg["models"], cfg["limits"], cfg["thresholds"], m))
        else:
            log("AI steps skipped (--no-ai given or Ollama unavailable)")
            report["ai"] = "skipped"
    report["finished"] = now_iso()
    step(report, "build", lambda: build.run(cfg["models"], report))
    save_json(DATA / "run_report.json", report)
    log("=== update finished ===")


if __name__ == "__main__":
    main()
