# Обещано и направено (Promised vs Done)

A Bulgarian-language promise tracker for major politicians. Static site + an update pipeline that runs weekly.

```
site/            the website (plain HTML/CSS/JS, no build step) - host this folder anywhere
dist/            promise-tracker.html: the whole site in ONE file (regenerated on every build) - opens by double-click
data/            politicians.json, promises.json (the "database"), sources.json (feeds, thresholds, backend)
pipeline/        fetch -> judge -> verdict -> discover -> build -> bundle
hermes/          WEEKLY_JOB.md: how to run the weekly update on a Hermes cloud agent
```

## Open the prototype

* Double-click `dist/promise-tracker.html` (self-contained, works offline and can be sent to any device), or
* `site/index.html`, or `python -m http.server 8765 --directory site` -> http://localhost:8765

## Update the data (weekly)

```powershell
python pipeline\run_all.py            # fetch + judge with the configured backend + verdicts + rebuild
python pipeline\run_all.py --no-ai    # only fetch headlines and rebuild
python pipeline\run_all.py prepare    # external-agent mode: write data/work/tasks.json
python pipeline\run_all.py apply      # external-agent mode: read data/work/answers.json, apply, rebuild
```

Who judges the headlines (`backend.chat` in `data/sources.json`, or env `PT_CHAT_BACKEND`):

| backend | judge | needs |
|---------|-------|-------|
| `ollama` (default) | local `qwen3:8b` + `bge-m3` matching | Ollama on this PC |
| `openai` | any OpenAI-compatible API (`JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL`) | an API key |
| `external` | an agent such as Hermes reads `tasks.json`, writes `answers.json` | an agent with its own model, see `hermes/WEEKLY_JOB.md` |

`matcher: auto` uses embeddings when Ollama is available and a dependency-free keyword matcher otherwise.

**On GitHub (no PC, no Hermes):** `.github/workflows/weekly.yml` runs the whole update every Monday with the `openai`
backend pointed at the free GitHub Models API (`JUDGE_API_KEY` is the built-in `GITHUB_TOKEN`, no secret to create).
It commits the changed `data/` and `site/data.js` and redeploys Pages. Run it by hand: Actions tab -> "Weekly update" -> Run workflow.
Free-tier limits are low (about 150 requests/day), so it judges at most 100 pairs + 25 discoveries a week and stops
politely if the API says no; unjudged pairs are retried the following week.

Weekly on this PC (Windows): `powershell -ExecutionPolicy Bypass -File .\schedule.ps1` (not needed if Hermes runs it).

## How verdicts are made (no human review)

1. `fetch.py` pulls headlines (RSS + Google News searches). Only title/summary/link/date are stored.
2. `match.py` proposes which headlines may bear on which promise; the judge labels each pair
   (delivers / progress / obstacle / abandoned / reversal / context) and must return an **exact quote**;
   quotes not found in the text are discarded.
3. Guards (`judge.guard`) downgrade rival accusations, same-day repeats and unsupported "reversal"/"abandoned" to context.
4. `verdict.py` changes a status only by fixed rules: >=2 independent publishers (3 for kept/broken/reversed),
   confidence >= 0.75, at most one change per 7 days. The judge never writes a verdict.
5. `discover.py` finds new pledges in headlines; they appear as "automatically discovered / unverified".
6. `build.py` writes `site/data.js` and `dist/promise-tracker.html`.

## Add a politician or promise

Edit `data/politicians.json` / `data/promises.json` (every promise needs `source`, `match_text`, `done_when`).
Keep the same bar for everyone: a quote or paraphrase, a dated source link, and an honest `status_reason`.

## Hosting (free, later)

`site/` is fully static: GitHub Pages, Cloudflare Pages or Netlify all work. Publishing = push/upload `site/`.
