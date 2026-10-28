"""Step 2 - decide how each headline bears on a promise.

Who judges is configurable (see common.backend): a local Ollama model, any OpenAI-compatible API,
or an external agent that answers a task file. Whoever judges, the same safety rails apply
(there is no human review, so these matter):
  * the judge must return an EXACT quote from the headline/summary; if the quote cannot be found the
    judgement is thrown away;
  * low-confidence judgements are thrown away;
  * deterministic guards downgrade claims, accusations and same-day repeats to "context";
  * the judge never writes a verdict - see verdict.py for the fixed rules.
"""
from __future__ import annotations

import os

import numpy as np

from common import (DATA, chat_json, item_text, load_json, log, mentions, norm,
                    now_iso, save_json)

JUDGED = DATA / "judged.json"          # pair keys already processed
NEWS = DATA / "news.json"
PROMISES = DATA / "promises.json"

RELATIONS = ["delivers", "progress", "obstacle", "abandoned", "reversal", "context", "unrelated"]

SYSTEM = """You are a strict fact-checking assistant for a Bulgarian political promise tracker.
You receive ONE promise made by a politician and ONE news item (headline, sometimes a short summary; Bulgarian or English).
Decide how the news item bears on whether the promise has been kept.

Relations:
- delivers: the item explicitly reports that the promised outcome ITSELF has been achieved, as described in COMPLETE WHEN. Passing a law or adopting a measure that is only a means toward a broader goal is NOT delivery.
- progress: a concrete step toward it (bill introduced, passed a reading, rules adopted, money allocated, talks started, a related measure enacted) but the outcome in COMPLETE WHEN is not yet reached.
- obstacle: the item reports a FACT that blocks or delays the promise (a court ruling, a failed vote, a frozen payment, a missed deadline).
- abandoned: the item reports that the promise-maker or their government refused, dropped or acted against the promise.
- reversal: the item reports that the SAME politician who made the promise publicly took the opposite position.
- context: related background that shows neither delivery nor failure.
- unrelated: the item is not about this promise.

Rules:
- Use ONLY the text given. Never use outside knowledge. If unsure choose context or unrelated.
- An accusation, claim, opinion or criticism voiced by a politician or party (especially a rival) is only "context", never obstacle, abandoned or reversal. Only reported facts and the promise-maker's own actions count.
- A politician repeating, explaining or defending their position is "context", not reversal.
- A statement of intent or a new promise is NOT delivery. When in doubt between delivers and progress, choose progress.
- A headline alone is weak evidence: use confidence 0.7 or lower when it is ambiguous.
- "quote" must be copied EXACTLY, character for character, from the news item text (max 200 characters). Use "" if relation is unrelated.
- "confidence" is 0.0-1.0: how sure you are about the relation.
Respond with JSON only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {"type": "string", "enum": RELATIONS},
        "quote": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["relation", "quote", "confidence"],
}


def build_prompt(promise: dict, who: dict, item: dict) -> str:
    return (
        f"PROMISE by {who['name']} ({promise.get('said_on') or 'date unknown'}):\n{promise['text']}\n"
        f"COMPLETE WHEN: {promise.get('done_when') or 'The pledged action is reported as actually completed.'}\n\n"
        f"NEWS ITEM ({item['publisher']}, {item.get('published') or 'date unknown'}):\n{item_text(item)}"
    )


def quote_ok(quote: str, item: dict) -> bool:
    q = norm(quote)
    return len(q) >= 12 and q in norm(item_text(item))


NEGATIVE = {"obstacle", "abandoned", "reversal"}
# The 8B model readily treats rhetoric as fact, so the strong negative labels need explicit wording.
CUES = {
    "abandoned": ("отказ", "изостав", "отмята", "не изпълн", "нарушав", "наруши", "не спази", "провал", "пренебрег", "abandon", "scrap"),
    "reversal": ("обръща", "обърна", "смяна на позиц", "променя позиц", "промени позиц", "отстъпи", "отстъпва", "отмята", "u-turn", "reverse", "backtrack"),
}


def guard(rel: str, promise: dict, item: dict, people: dict) -> tuple[str, str | None]:
    """Deterministic sanity check on the judge's label -> (relation, reason if it was downgraded)."""
    text = item_text(item)
    maker_id = promise["politician"]
    said, pub = promise.get("said_on") or "", item.get("published") or ""
    if rel in ("delivers", "progress") and said and pub and pub <= said:
        return "context", "публикацията е от деня на самото обещание или по-рано – не доказва изпълнение"
    if rel in NEGATIVE and any(mentions(text, p["aliases"]) for pid, p in people.items() if pid != maker_id):
        return "context", "заглавието е твърдение на/за друг политик, а не установен факт"
    if rel in CUES and not any(c in text.casefold() for c in CUES[rel]):
        return "context", "няма изрични думи, които да потвърждават това отношение"
    return rel, None


def _load():
    news = load_json(NEWS, {"items": []})["items"]
    promises = load_json(PROMISES, [])
    people = {p["id"]: p for p in load_json(DATA / "politicians.json")}
    return news, promises, people, set(load_json(JUDGED, [])), {p["id"]: p for p in promises}


def collect(matcher, news: list[dict], promises: list[dict], judged: set, limits: dict, thresholds: dict) -> list[tuple]:
    """Headline/promise pairs worth reading, best matches first."""
    scores = matcher.scores(promises, news)
    floor = thresholds[matcher.min_key]
    if matcher.kind == "keywords":
        # Word overlap has no calibrated scale, so take the best K headlines for every promise instead.
        top = int(thresholds.get("keyword_top_k", 25))
        chosen = {(n, k) for k in range(scores.shape[1]) for n in np.argsort(-scores[:, k])[:top] if scores[n, k] >= floor}
    else:
        chosen = {(n, k) for n in range(len(news)) for k in np.argsort(-scores[n])[:3] if scores[n, k] >= floor}
    pairs = []
    for n, k in chosen:
        key = f"{promises[k]['id']}|{news[n]['id']}"
        if key not in judged:
            pairs.append((float(scores[n, k]), key, promises[k]["id"], news[n]))
    pairs.sort(key=lambda t: -t[0])
    return pairs[: int(os.environ.get("PT_MAX_PAIRS", limits["max_judgements_per_run"]))]


def settle(promise: dict, item: dict, sim: float, res: dict | None, people: dict, thresholds: dict, label: str) -> bool:
    """Validate one judgement and attach it as evidence. True if attached."""
    if not isinstance(res, dict):
        return False
    rel, quote = res.get("relation"), str(res.get("quote") or "").strip()
    try:
        conf = float(res.get("confidence") or 0)
    except (TypeError, ValueError):
        return False
    if rel not in RELATIONS or rel == "unrelated" or conf < thresholds["evidence_confidence_min"]:
        return False
    if not quote_ok(quote, item):
        return False  # invented or altered quote -> discard
    if any(e.get("id") == f"a-{item['id']}" for e in promise["evidence"]):
        return False
    model_rel = rel
    rel, downgraded = guard(rel, promise, item, people)
    promise["evidence"].append({
        **({"model_relation": model_rel, "guard": downgraded} if downgraded else {}),
        "id": f"a-{item['id']}",
        "date": item.get("published"),
        "title": item["title"],
        "publisher": item["publisher"],
        "url": item["url"],
        "relation": rel,
        "quote": quote,
        "confidence": round(conf, 2),
        "similarity": round(sim, 2),
        "origin": "auto",
        "model": label,
        "added": now_iso(),
    })
    return True


def prepare(matcher, limits: dict, thresholds: dict) -> dict:
    """External-judge mode: the task list instead of calling a model."""
    news, promises, people, judged, by_id = _load()
    pairs = collect(matcher, news, promises, judged, limits, thresholds)
    tasks = [{"key": key, "similarity": round(sim, 2), "prompt": build_prompt(by_id[pid], people[by_id[pid]["politician"]], item)}
             for sim, key, pid, item in pairs]
    return {"instructions": SYSTEM, "answer_keys": {"relation": "|".join(RELATIONS), "quote": "exact text", "confidence": "0.0-1.0"}, "tasks": tasks}


def run(models: dict, limits: dict, thresholds: dict, matcher) -> dict:
    news, promises, people, judged, by_id = _load()
    pairs = collect(matcher, news, promises, judged, limits, thresholds)
    log(f"judge: {len(pairs)} candidate headline/promise pairs to read ({matcher.kind} matcher)")
    attached = 0
    for n, (sim, key, pid, item) in enumerate(pairs, 1):
        promise = by_id[pid]
        res = chat_json(models["chat"], SYSTEM, build_prompt(promise, people[promise["politician"]], item), SCHEMA)
        if res is None:
            continue  # model error -> leave unjudged so it is retried next run
        judged.add(key)
        attached += settle(promise, item, sim, res, people, thresholds, models["chat"])
        if n % 25 == 0:
            log(f"  ...{n}/{len(pairs)} read, {attached} attached")
            save_json(PROMISES, promises)
            save_json(JUDGED, sorted(judged))
    save_json(PROMISES, promises)
    save_json(JUDGED, sorted(judged))
    log(f"judge: attached {attached} evidence items, discarded {len(pairs) - attached}")
    return {"pairs": len(pairs), "attached": attached, "discarded": len(pairs) - attached}


def apply_answers(answers: dict, tasks: list[dict], thresholds: dict, label: str) -> dict:
    news, promises, people, judged, by_id = _load()
    by_item = {i["id"]: i for i in news}
    sims = {t["key"]: t.get("similarity", 0.0) for t in tasks}
    attached = seen = 0
    for key, res in answers.items():
        pid, _, iid = key.partition("|")
        if pid not in by_id or iid not in by_item:
            continue
        seen += 1
        judged.add(key)
        attached += settle(by_id[pid], by_item[iid], sims.get(key, 0.0), res, people, thresholds, label)
    save_json(PROMISES, promises)
    save_json(JUDGED, sorted(judged))
    log(f"judge: {seen} answers read, attached {attached} evidence items")
    return {"answers": seen, "attached": attached}
