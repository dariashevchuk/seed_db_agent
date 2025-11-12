# Seed DB Agent

Seed DB Agent is a toolkit for bootstrapping a structured view of Ukrainian volunteer and donation initiatives. It combines three cooperating agents:

- `search_agent`: finds promising websites for a given topic with LLM-generated queries + SerpAPI.
- `fill_bot`: indexes local documents (PDF/DOCX) for a topic, retrieves relevant snippets, and extracts structured org/project facts with an LLM.
- `rag_agent`: Playwright-driven crawler that walks a site, reflects on each page with an LLM, and stores normalized organization and project records.

Together they let you (1) discover candidate organizations, (2) mine supporting docs, and (3) capture structured data in a repeatable way.

---

## Repository Layout

| Path | Description |
| ---- | ----------- |
| `app.py` | Typer CLI entry point for the crawling agent (`rag_agent`). |
| `rag_agent/` | Crawl planner (`models.py`), Playwright fetch loop (`fetch.py`), HTML parsing (`parse.py`), OpenAI helpers (`llm.py`), and JSON storage helpers (`storage.py`). |
| `fill_bot/` | CLI (`cli.py`), document indexer (`ingest.py`), embedding search (`search.py`), and extraction prompt (`llm_extract.py`). |
| `fill_bot/fill_agent/` | On-disk vector indexes (`*_index.json`) plus `extracted.json` with LLM outputs. |
| `artifacts/` | Cached HTML/Markdown snapshots and screenshots produced by the crawler for auditing. |
| `data/` | Persistent outputs: `organizations.json` (and `projects.json` once created). |
| `topics.json` | (Create in repo root) List of topic definitions consumed by both `search_agent` and `fill_bot`. |
| `requirements.txt` | Python dependencies shared by every agent. |
| `todo.md`, `info.md` | Project notes and background context. |

---

## Prerequisites

- Python 3.10+ (Playwright wheels are built for >=3.8; repo developed on 3.10).
- Google Chrome dependencies (Playwright installs Chromium automatically).
- API keys:
  - `OPENAI_API_KEY` – required by every agent (embeddings + chat models). Optional `OPENAI_MODEL` overrides default `gpt-4o-mini`.
  - `SERPAPI_API_KEY` – required by `search_agent/provider.py` to issue Google search requests.
- (Optional) `.env` file if you prefer `python-dotenv` style loading when running scripts manually.

Install system requirements for Playwright once:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

---

## Configuration

| Variable | Used by | Notes |
| -------- | ------- | ----- |
| `OPENAI_API_KEY` | all agents | Mandatory. Set before running any CLI command. |
| `OPENAI_MODEL` | `rag_agent.llm` | Override default `gpt-4o-mini` for reflections/expansions. |
| `SERPAPI_API_KEY` | `search_agent/provider.py` | Enables Google Custom Search through SerpAPI. |
| `LOG_LEVEL` | `rag_agent.logging_setup` | `INFO` by default; use `DEBUG` for crawl tracing. |
| `LOG_TO_FILE` | `rag_agent.logging_setup` | Set to `1` to mirror logs into `data/run.log`. |

Topics file format (stored at `topics.json` by convention):

```json
[
  {
    "id": "uav",
    "name": "Drone programs",
    "description": "Find NGOs funding reconnaissance drones.",
    "solutions": ["UAV procurement", "production support"],
    "terms": ["дронопад", "UAV charity"],
    "must_have": ["дрон", "БПЛА"],
    "must_not": ["job", "career"]
  }
]
```

Fields:
- `terms` feed the vector search in `fill_bot/search.py`.
- `must_have` / `must_not` empower `search_agent/filters.py`.
- `description` + `solutions` provide context for the extraction prompt.

---

## Workflows

### 1. Discover candidate sites (`search_agent`)

> Source files: `search_agent/main.py`, `queries_llm.py`, `provider.py`, `filters.py`

1. Ensure `SERPAPI_API_KEY` and `OPENAI_API_KEY` are set.
2. Run the agent for a topic ID defined in `topics.json`:
   ```bash
   python -m search_agent.main --topic-id uav
   ```
3. What happens:
   - `queries_llm.py` asks OpenAI to expand the topic into diverse Google queries (cached under `.cache_queries/<topic>.json`).
   - `provider.py` executes queries through SerpAPI, caching raw SERP payloads in `search_agent/serp_cache.jsonl`.
   - `filters.py` drops noise (social media, job boards, news) and scores the rest using TLD bias, keyword matches, and heuristic penalties.
   - `main.py` emits the top-ranked URLs (stdout + JSON file) to seed `rag_agent`.

### 2. Extract from local documents (`fill_bot`)

> Source files: `fill_bot/cli.py`, `ingest.py`, `search.py`, `llm_extract.py`

1. Place PDFs/DOCXs for a topic in the repository root.
2. Ensure the topic exists in `topics.json`.
3. Run:
   ```bash
   python fill_bot/cli.py fill uav
   # or: python app.py fill uav  (same Typer command from repo root)
   ```
4. Pipeline:
   - `ingest.build_index` fingerprints each file, extracts full text (PyMuPDF for PDF, `python-docx` for DOCX), splits into 1500-char chunks, and embeds via `text-embedding-3-small`. Results land in `fill_bot/fill_agent/<hash>_index.json`.
   - `search.run_topic_search` embeds each topic term, computes cosine similarity, and keeps the top snippets.
   - `llm_extract.extract_with_llm` feeds the snippets, topic description, and solution hints into `gpt-4o-mini` (JSON mode) to pull `organization` and `project` entities. Outputs append to `fill_bot/fill_agent/extracted.json`.

Use this workflow for structured content you already possess (reports, grant docs, etc.).

### 3. Crawl and structure websites (`rag_agent`)

> Source files: `app.py`, `rag_agent/*.py`

1. Export `OPENAI_API_KEY`.
2. Launch the crawler against a specific URL:
   ```bash
   python app.py run "https://savelife.in.ua/"
   ```
3. Execution details:
   - `rag_agent.fetch.navigate_with_plan` spins up Playwright Chromium headless, keeps a BFS-style frontier, and respects `StopConfig` budgets (default: 40 actions or 120 s, plus plateau detection).
   - Each page is snapshotted (`rag_agent.parse` converts HTML → markdown, extracts JSON-LD, anchors, titles).
   - `rag_agent.llm.reflect_and_extract` summarizes the snapshot, proposes next URLs/actions, and emits structured organization + project data plus candidate follow-up links.
   - `rag_agent.storage.upsert_org/upsert_project` merges results into `data/organizations.json` and `data/projects.json`, expanding short descriptions to ≥600 chars in Ukrainian when needed (`expand_to_ua_description` helper).
   - Artifacts (HTML, Markdown, screenshots, raw API transcripts) persist under `artifacts/` for auditing.

You can tweak the crawl budgets by editing `rag_agent/models.py::StopConfig` or by instantiating a custom config before calling `navigate_with_plan`.

---

## Outputs

- `data/organizations.json` – normalized organization records (id, name, description, website, contact email, timestamps).
- `data/projects.json` – project records linked to `organization_id`, each with long-form Ukrainian summaries and source URLs.
- `artifacts/*.jsonl|*.md|*.png` – debugging breadcrumbs (snapshots, screenshots, LLM prompts/responses).
- `fill_bot/fill_agent/*` – vector indexes per document + `extracted.json` containing the raw LLM extraction log.

These files are append-only; the storage layer performs atomic writes so you can treat them as your working dataset or import them into a database later.

---

## Tips & Troubleshooting

- **Playwright dependencies**: If Chromium launch fails, run `playwright install-deps` (Linux) or consult Playwright docs for OS-specific steps.
- **Rate limits**: Both the search agent and crawling agent rely on OpenAI. Respect your per-minute quota by spacing runs or lowering concurrency.
- **Cache hygiene**: Delete `search_agent/serp_cache.jsonl` or `.cache_queries/<topic>.json` to force fresh SERP/LLM query generation.
- **LLM drift**: If the extraction JSON schema starts drifting, inspect `artifacts/api-*.jsonl` for raw responses and refine prompts.
- **Language preference**: `rag_agent.llm.plan_site_walk` biases toward Ukrainian/English content; adjust `Plan.prefer_languages` if you need other locales.

---

## Next Steps

- Hook `data/organizations.json` and `data/projects.json` into your target database.
- Automate the three agents in a pipeline (search → crawl → document fill) per topic/nightly job.
- Extend `search_agent.filters` with custom allow/deny lists tailored to your domain.
- Add tests around parsing and storage if you plan to evolve the agents further.

