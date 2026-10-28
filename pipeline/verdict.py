"""Step 3 - turn collected evidence into verdicts using fixed, conservative rules.

The language model is NOT allowed to set a verdict. A status only changes when
several independent publishers agree, and never more than once a week.
"""
from __future__ import annotations

import datetime as dt

from common import DATA, load_json, log, save_json, today

PROMISES = DATA / "promises.json"
COOLDOWN_DAYS = 7


def _pubs(evidence: list[dict], relation: str) -> list[str]:
    return sorted({e["publisher"] for e in evidence if e["relation"] == relation})


def propose(promise: dict, thr: dict) -> tuple[str | None, str]:
    need = thr["verdict_min_publishers"]
    strong = thr.get("verdict_min_publishers_strong", need)  # kept / broken / reversed are the claims that hurt if wrong
    since = promise.get("said_on") or ""
    ev = [
        e for e in promise["evidence"]
        if e.get("origin") == "auto"
        and e.get("confidence", 0) >= thr["verdict_confidence_min"]
        and (e.get("date") or "") > since  # the pledge day itself is never evidence of delivery
    ]
    d, a, r = _pubs(ev, "delivers"), _pubs(ev, "abandoned"), _pubs(ev, "reversal")
    o, p = _pubs(ev, "obstacle"), _pubs(ev, "progress")
    cur = promise["status"]

    if len(d) >= strong and not a and not r:
        return "kept", f"{len(d)} независими източника ({', '.join(d[:4])}) съобщават, че е изпълнено"
    if len(a) >= strong and not d:
        return "broken", f"{len(a)} независими източника ({', '.join(a[:4])}) съобщават, че е изоставено или нарушено"
    if len(r) >= strong and not d:
        return "reversed", f"{len(r)} независими източника ({', '.join(r[:4])}) съобщават за промяна на позицията"
    if d and (a or o) and len(set(d) | set(a) | set(o)) >= need and cur != "partial":
        return "partial", "има съобщения както за изпълнение, така и за пречки"
    if cur in ("unclear", "too_early") and len(set(p) | set(d)) >= need:
        return "in_progress", f"{len(set(p) | set(d))} независими източника съобщават за конкретни стъпки"
    return None, ""


def run(thresholds: dict, model: str) -> dict:
    promises = load_json(PROMISES, [])
    changed = []
    for pr in promises:
        new, why = propose(pr, thresholds)
        if not new or new == pr["status"]:
            continue
        if pr["status"] == "no_power" and new != "kept":
            continue  # opposition promises stay "no power" unless clearly delivered
        last = pr["status_history"][-1]["date"] if pr["status_history"] else None
        if last and (dt.date.fromisoformat(today()) - dt.date.fromisoformat(last)).days < COOLDOWN_DAYS:
            continue
        reason = (f"Автоматична промяна от {today()}: {why}. Оценката е направена от правила върху "
                  f"данни, извлечени от модела {model}; проверете цитатите.")
        pr["status_history"].append({"date": today(), "from": pr["status"], "to": new, "origin": "auto", "reason": reason})
        pr["status"], pr["status_origin"] = new, "auto"
        pr["status_updated"], pr["status_reason"] = today(), reason
        changed.append((pr["id"], new))
    save_json(PROMISES, promises)
    log(f"verdict: {len(changed)} status change(s) {changed}")
    return {"changed": len(changed)}
