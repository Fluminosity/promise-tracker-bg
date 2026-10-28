# Weekly update on Hermes (cloud agent)

Goal: the update keeps running while your PC is off. Hermes' built-in cron scheduler starts a fresh agent session once a
week; that agent is the **judge** (its own, stronger model reads the headline/promise pairs), so no GPU and no extra API key.

> I could not test this against your real Hermes install. The Hermes docs describe a built-in cron scheduler driven by the
> gateway daemon (`/cron add` in chat, or `hermes cron create` on the CLI). Check the exact flags in the docs of the
> version you run, and make sure the gateway is running (otherwise cron jobs do not fire).

## One-time setup on the Hermes machine

1. Put this folder on the machine (`git clone <your repo>` once you host it, or copy it) - call the path `<PATH>`.
2. `pip install -r requirements.txt` (only `numpy`).
3. Python 3.10+ with internet access (the fetch step reads RSS and Google News).

## The cron job

Schedule: weekly, e.g. Monday 07:30. Cron sessions start fresh, so the prompt must be self-contained. Paste this prompt:

```text
You maintain the Bulgarian promise tracker in <PATH>. Do exactly this, in order:
1. cd <PATH>. Set environment variables PT_CHAT_BACKEND=external, PT_MATCHER=keywords, PT_MAX_PAIRS=150.
   Run: python pipeline/run_all.py prepare
2. Open data/work/tasks.json and follow its "how_to" field exactly. Judge every task in judge.tasks with judge.instructions
   and every task in discover.tasks with discover.instructions. Use ONLY the text inside the tasks: no browsing, no outside
   knowledge, never invent a quote (a quote must be copied character for character from the headline). Write the result to
   data/work/answers.json.
3. Run: python pipeline/run_all.py apply
4. If a git remote named origin exists: git add data site && git commit -m "weekly update" && git push
5. Reply with five lines: new headlines, evidence attached, status changes, new promises, and any error you saw.
Never edit data/promises.json by hand.
```

What each step does:

| Step | Command | Result |
|------|---------|--------|
| prepare | `run_all.py prepare` | fetches ~10 days of headlines, matches them to promises, writes `data/work/tasks.json` (about 150 tasks, ~70 KB) |
| judge | (the agent) | writes `data/work/answers.json` |
| apply | `run_all.py apply` | validates every answer (exact quote, confidence, guards), applies the fixed verdict rules, rebuilds `site/data.js` |

The safety rails are the same as with the local model: an answer whose quote is not literally in the headline is dropped,
claims by rivals are only "context", and a status changes only when 2-3 independent outlets agree.

## Alternative without an agent (plain script job)

Hermes can also run a script on a schedule with no LLM. Then the judge must be an API:

```bash
PT_CHAT_BACKEND=openai JUDGE_BASE_URL=https://<provider>/v1 JUDGE_API_KEY=<key> JUDGE_MODEL=<model> \
  python pipeline/run_all.py
```

Any OpenAI-compatible endpoint works. This costs API credits; the agent route above does not need a key.

## Publishing

The job only changes files. To make the update public you need the free host (GitHub Pages / Cloudflare Pages) fed from
`site/`; with a git remote the agent's step 4 pushes the new data and the host redeploys by itself.
