"""Hand-off files for an external judge (e.g. a Hermes agent): tasks go out, answers come back.

The agent never edits promises.json itself. It only writes data/work/answers.json; `run_all.py apply`
then validates every answer with the same guards as the local models (exact quote, confidence, rules).
"""
from __future__ import annotations

import datetime as dt

from common import DATA, load_json, log, now_iso, save_json

WORK = DATA / "work"
TASKS = WORK / "tasks.json"
ANSWERS = WORK / "answers.json"

HOW_TO = (
    "You are the judge for a Bulgarian political promise tracker. Do not browse the web and do not use outside knowledge: "
    "judge ONLY the text in each task. For every entry of judge.tasks follow judge.instructions and answer "
    '{"relation": ..., "quote": ..., "confidence": ...}. For every entry of discover.tasks follow discover.instructions and answer '
    "with the discover.answer_keys object. Copy `quote` EXACTLY (character for character) from the headline/summary in the task. "
    "Write ONE JSON file at data/work/answers.json shaped "
    '{"judge": {"<task key>": {...}}, "discover": {"<task key>": {...}}} - answer every task '
    '(use relation "unrelated" / is_promise false when nothing applies). Then run: python pipeline/run_all.py apply'
)


def write_tasks(judge: dict, discover: dict) -> None:
    save_json(TASKS, {"created": now_iso(), "how_to": HOW_TO, "answers_file": "data/work/answers.json", "judge": judge, "discover": discover})
    log(f"external: wrote {len(judge['tasks'])} judge task(s) and {len(discover['tasks'])} discover task(s) to {TASKS}")


def load_tasks() -> dict:
    return load_json(TASKS, {"judge": {"tasks": []}, "discover": {"tasks": []}})


def load_answers() -> dict:
    return load_json(ANSWERS, {"judge": {}, "discover": {}})


def archive() -> None:
    if ANSWERS.exists():
        ANSWERS.rename(WORK / f"answers-{dt.datetime.now():%Y%m%d-%H%M}.done.json")
    TASKS.unlink(missing_ok=True)
