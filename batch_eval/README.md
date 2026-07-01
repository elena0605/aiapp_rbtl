# Batch chat evaluation

Run the same questions the UI sends to `POST /api/chat`, systematically across keywords.

## Setup

1. Start the backend (and Neo4j):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d backend
```

2. Edit `input/campaign.md`:
   - **Keywords** — one bullet per theme
   - **Questions** — templates with `[keyword]` placeholder

## Run

```bash
# Preview substituted questions (no API calls)
python batch_eval/run_batch.py --dry-run

# Full batch (uses username `batch` by default — separate Mongo history from manual chat)
python batch_eval/run_batch.py

# Single keyword or question
python batch_eval/run_batch.py --keyword vaping
python batch_eval/run_batch.py --question 2 --force

# Custom backend URL (override user only if needed)
python batch_eval/run_batch.py --base-url http://localhost:8001 --username bojan
```

## Output layout

```
batch_eval/output/
  _index.md                 # summary table of all runs
  vaping/
    question1.md
    question1.json          # full API response for scripting
    question2.md
    ...
  gaming/
    ...
```

Re-run with `--force` to overwrite. Without `--force`, existing files are skipped.

**Keyword vs folder slug:** `--keyword` must match the exact text in `campaign.md` (e.g. `"meal preping"`, `"hate speech"`), not the output folder slug (`meal-preping`, `hate-speech`). Quote multi-word keywords in the shell.

## Theme merge (Phase 2)

After batch runs finish, merge related keywords into theme-level totals **without new API calls**.

1. Edit `input/themes.yaml` — group keywords under theme keys (strings must match `campaign.md` exactly).
2. Run:

```bash
# Preview all themes × Q1–Q7
python batch_eval/merge_themes.py --dry-run

# Write merged JSON + markdown + themes/_index.md
python batch_eval/merge_themes.py

# Single theme or question
python batch_eval/merge_themes.py --theme violence
python batch_eval/merge_themes.py --question 5
```

### Output layout

```
batch_eval/output/themes/
  _index.md                              # summary table
  violence/
    question5_merged.json                # unioned IDs + unique counts
    question5_merged.md
  online_hate_and_bullying/
  food/
```

### Merge rules (never sum per-keyword counts)

| Q# | Type | Dedupe by |
| --- | --- | --- |
| Q4, Q6 | Influencers | Union `youtube_channel_ids` + `tiktok_usernames` from `candidate_keys` |
| Q5, Q7 | Video counts | Union `video_ids` |
| Q1–Q3 | Examples | Union `results[].video_id`, keep top 20 by score |

Each merged JSON includes `per_keyword_reported_counts`, `unique_total`, and an `overlap_note` showing what naive summing would have produced vs deduped union.

## Recommendations

1. **Use `--output-mode both`** (default) so markdown summaries and structured fields (route, trace, timings) are both saved in JSON.
2. **Add `--delay 1`** if you hit OpenAI/Langfuse rate limits on large batches.
3. **Keep hybrid questions in the campaign** to verify `route_type`, `tool_name`, and Stage 2 Cypher per keyword — check `_index.md` first, then individual MD files.
4. **Do not commit `output/`** — results depend on DB state and model stochasticity; regenerate locally.
5. **Separate “routing smoke tests” from “quality evals”** — short count questions are fast; hybrid + popularity questions can take 1–3 minutes each (timeout default 300s).
6. **Optional next steps** (not implemented yet):
   - assert expected `route_type` / `tool_name` in campaign MD (fail batch on mismatch)
   - CSV export from `_index.md` / JSON for spreadsheets
   - `--no-history` flag so each question is routed without prior batch context

## Chat history (Mongo)

The script calls the same `/api/chat` endpoint as the UI. Messages are saved to Mongo under the
request username. **Default is `batch`**, so tester accounts (`bojan`, `roel`, etc.) stay clean
in the chat UI. Batch history appears only if you log in as `batch` (not on the login dropdown
today — script-only).

Restart the backend after pulling this change so the allowlist reloads:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --force-recreate backend
```

## Allowed usernames

`bojan`, `roel`, `famke`, `scarlett`, `batch` (default for this script).
