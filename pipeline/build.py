"""Step 5 - bundle everything the website needs into site/data.js."""
from __future__ import annotations

import json
from collections import Counter

import bundle
from common import DATA, SITE, backend, load_json, log, now_iso, today

STATUSES = ["kept", "partial", "in_progress", "broken", "reversed", "no_power", "too_early", "unclear"]


def run(models: dict | None = None, report: dict | None = None) -> dict:
    people = load_json(DATA / "politicians.json")
    promises = load_json(DATA / "promises.json", [])
    news = load_json(DATA / "news.json", {"updated": None, "items": []})

    order = {p["id"]: n for n, p in enumerate(people)}
    promises.sort(key=lambda p: (order.get(p["politician"], 99), p["origin"] != "seed", -(int((p.get("said_on") or "0")[:4] or 0))))

    for p in people:
        mine = [x for x in promises if x["politician"] == p["id"]]
        c = Counter(x["status"] for x in mine)
        p["counts"] = {s: c.get(s, 0) for s in STATUSES}
        p["promise_count"] = len(mine)

    for pr in promises:
        pr["overdue"] = bool(pr.get("due") and pr["due"] < today() and pr["status"] in ("in_progress", "unclear", "too_early"))

    auto_ev = [e for pr in promises for e in pr["evidence"] if e.get("origin") == "auto"]
    data = {
        "generated": now_iso(),
        "last_fetch": news.get("updated"),
        "models": models or {},
        "backend": backend()["chat"],
        # Only models that actually produced evidence - a configured-but-failing judge must not be advertised.
        "judge_models": sorted({e["model"] for p in promises for e in p["evidence"] if e.get("origin") == "auto" and e.get("model")}),
        "politicians": people,
        "promises": promises,
        "stats": {
            "news_items": len(news["items"]),
            "auto_evidence": len(auto_ev),
            "auto_promises": sum(1 for p in promises if p["origin"] == "auto"),
            "status_changes": sum(len(p["status_history"]) for p in promises),
        },
        "last_run": report or {},
    }
    js = "window.SITE_DATA = " + json.dumps(data, ensure_ascii=False).replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + ";\n"
    (SITE / "data.js").write_text(js, encoding="utf-8")
    log(f"build: wrote site/data.js ({len(promises)} promises, {len(auto_ev)} auto-evidence items)")
    bundle.run()
    return data["stats"]


if __name__ == "__main__":
    run()
