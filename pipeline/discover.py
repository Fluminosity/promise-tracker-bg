"""Step 4 - spot NEW promises in headlines ("Радев: Ще внесем ...").

Discovered promises are stored as origin="auto", status "unclear" and are shown on the site in
their own clearly-labelled section. The promise text is the headline itself, so the judge never
rewrites what a politician said.
"""
from __future__ import annotations

import re

from common import (DATA, chat_json, item_text, load_json, log, mentions, norm,
                    save_json)

PROMISES = DATA / "promises.json"
NEWS = DATA / "news.json"
SEEN = DATA / "discovered.json"

PROMISE_HINT = re.compile(
    r"(обещ|ще\s|гарантир|ангажир|предлага|настоява|ултиматум|няма да\s|твърдо)", re.IGNORECASE | re.UNICODE
)
TOPICS = ["prices", "justice", "corruption", "eu_funds", "eu_nato", "budget", "euro", "tax", "energy",
          "governance", "security", "foreign", "infrastructure", "social", "other"]

SYSTEM = """You review ONE news headline from Bulgaria.
Decide whether it reports a concrete, checkable commitment or pledge made by one of the listed politicians:
something the speaker says they, their party or their government WILL do, adopt, propose, stop or deliver.
It is NOT a promise if it is an opinion, criticism, accusation, a wish, a prediction, a reaction, or something already done.
"speaker" must be the id of the politician who makes the pledge, or "other" if it is anyone else or unclear.
"quote" must be copied EXACTLY from the headline (character for character).
"due" is a deadline as YYYY-MM-DD only if the headline states a specific date or year, otherwise "". Never guess a date.
"duplicate_of" is the id of an EXISTING promise listed below ONLY if the headline restates that exact same commitment. A narrower, more specific pledge (a particular price, product, date or amount) is NOT a duplicate of a broad existing promise - answer "none" for it.
Respond with JSON only."""


def _schema(ids: list[str], promises: list[dict]) -> dict:
    return {
        "type": "object",
        "properties": {
            "is_promise": {"type": "boolean"},
            "speaker": {"type": "string", "enum": ids + ["other"]},
            "topic": {"type": "string", "enum": TOPICS},
            "due": {"type": "string"},
            "duplicate_of": {"type": "string", "enum": [p["id"] for p in promises] + ["none"]},
            "quote": {"type": "string"},
            "confidence": {"type": "number"},
        },
        "required": ["is_promise", "speaker", "topic", "due", "duplicate_of", "quote", "confidence"],
    }


def _context(people: list[dict], promises: list[dict]) -> str:
    names = ", ".join(f"{p['id']} = {p['name']}" for p in people)
    listing = "\n".join(f"- {p['id']}: {p['text'][:90]}" for p in promises[-60:])
    return f"\nTracked politicians: {names}.\nEXISTING PROMISES:\n{listing}"


def _prompt(it: dict) -> str:
    return f"HEADLINE ({it['publisher']}): {item_text(it)}"


def candidates(news: list[dict], seen: set, cap: int = 100) -> list[dict]:
    return [it for it in news if it["id"] not in seen and it.get("politicians") and PROMISE_HINT.search(it["title"])][:cap]


def evaluate(it: dict, res, by_id: dict, promises: list[dict], thresholds: dict, matcher, label: str) -> str:
    """-> 'added' | 'duplicate' | 'skipped'. Mutates `promises`."""
    if not isinstance(res, dict) or not res.get("is_promise") or res.get("speaker") not in by_id:
        return "skipped"
    try:
        conf = float(res.get("confidence") or 0)
    except (TypeError, ValueError):
        return "skipped"
    if conf < thresholds["discover_confidence_min"]:
        return "skipped"
    quote = str(res.get("quote") or "").strip()
    dup = res.get("duplicate_of")
    if dup not in (None, "", "none"):
        # Same pledge again: keep the headline as context evidence instead of a second card.
        target = next((p for p in promises if p["id"] == dup), None)
        if target and not any(e["id"] == f"a-{it['id']}" for e in target["evidence"]):
            target["evidence"].append({
                "id": f"a-{it['id']}", "date": it.get("published"), "title": it["title"], "publisher": it["publisher"],
                "url": it["url"], "relation": "context", "quote": quote, "confidence": round(conf, 2),
                "origin": "auto", "model": label,
            })
        return "duplicate"
    speaker = by_id[res["speaker"]]
    if not mentions(item_text(it), speaker["aliases"]):
        return "skipped"  # attribution must be visible in the text
    if len(norm(quote)) < 12 or norm(quote) not in norm(item_text(it)):
        return "skipped"
    mine = [p["text"] for p in promises if p["politician"] == speaker["id"]]
    if matcher.max_similarity(it["title"], mine) >= thresholds[matcher.dup_key]:
        return "duplicate"
    due = res.get("due") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(res.get("due") or "")) else None
    # A deadline is only trusted if the headline itself names that year and it lies in the future of the article.
    if due and not (due[:4] in item_text(it) and due >= (it.get("published") or "")):
        due = None
    promises.append({
        "id": f"auto-{it['id']}",
        "politician": speaker["id"],
        "text": it["title"],
        "quote": quote,
        "quote_lang": "bg",
        "said_on": it.get("published"),
        "context": "Автоматично открито от заглавие в новините. Не е проверявано ръчно – възможно е да е неточно.",
        "source": {"title": it["title"], "publisher": it["publisher"], "url": it["url"]},
        "topic": res.get("topic") if res.get("topic") in TOPICS else "other",
        "match_text": it["title"],
        "done_when": "The pledged action is reported as actually completed.",
        "due": due,
        "status": "unclear",
        "status_origin": "auto",
        "status_updated": it.get("published"),
        "status_reason": "Автоматично открито обещание – още няма събрани доказателства за изпълнение.",
        "origin": "auto",
        "evidence": [],
        "status_history": [],
    })
    return "added"


def _load():
    people = load_json(DATA / "politicians.json")
    return people, {p["id"]: p for p in people}, load_json(PROMISES, []), load_json(NEWS, {"items": []})["items"], set(load_json(SEEN, []))


def prepare(limits: dict) -> dict:
    """External-judge mode: the task list instead of calling a model."""
    people, _, promises, news, seen = _load()
    cands = candidates(news, seen)
    keys = {"is_promise": "true|false", "speaker": "politician id or other", "topic": "|".join(TOPICS), "due": "YYYY-MM-DD or empty",
            "duplicate_of": "existing promise id or none", "quote": "exact text", "confidence": "0.0-1.0"}
    return {"instructions": SYSTEM + _context(people, promises), "answer_keys": keys,
            "tasks": [{"key": it["id"], "prompt": _prompt(it)} for it in cands]}


def run(models: dict, limits: dict, thresholds: dict, matcher) -> dict:
    people, by_id, promises, news, seen = _load()
    cands = candidates(news, seen)
    log(f"discover: {len(cands)} headlines look like pledges")
    added = 0
    for it in cands:
        if added >= limits["max_new_promises_per_run"]:
            break
        res = chat_json(models["chat"], SYSTEM + _context(people, promises), _prompt(it), _schema(list(by_id), promises))
        if res is None:
            continue  # model error -> retry next run
        seen.add(it["id"])
        if evaluate(it, res, by_id, promises, thresholds, matcher, models["chat"]) == "added":
            added += 1
            log(f"  + {by_id[res['speaker']]['name']}: {it['title'][:90]}")
    save_json(PROMISES, promises)
    save_json(SEEN, sorted(seen))
    log(f"discover: added {added} new promise(s)")
    return {"added": added}


def apply_answers(answers: dict, limits: dict, thresholds: dict, matcher, label: str) -> dict:
    people, by_id, promises, news, seen = _load()
    by_item = {i["id"]: i for i in news}
    added = 0
    for iid, res in answers.items():
        it = by_item.get(iid)
        if it is None:
            continue
        seen.add(iid)
        if added < limits["max_new_promises_per_run"] and evaluate(it, res, by_id, promises, thresholds, matcher, label) == "added":
            added += 1
            log(f"  + {by_id[res['speaker']]['name']}: {it['title'][:90]}")
    save_json(PROMISES, promises)
    save_json(SEEN, sorted(seen))
    log(f"discover: {len(answers)} answers read, added {added} new promise(s)")
    return {"answers": len(answers), "added": added}
