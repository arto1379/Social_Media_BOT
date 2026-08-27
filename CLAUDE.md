# Social Media BOT

Self-hosted Flask app that publishes short-form video on a schedule, tracks how each
upload performs, and researches trends — all behind a web UI with bitmask access
control. v1 ships YouTube Shorts; `app/platforms/` is a plugin layer, so a new network
is a new folder, not a rewrite. Python 3.13 (3.11+ supported), Flask, SQLAlchemy,
APScheduler.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Graph-first workflow

**Always consult the graph before reading or grepping source.** The corpus is ~78k
tokens naive; a scoped graph query averages ~4.2k — measured 18.5x reduction
(`graphify benchmark`). Reaching for `Grep`/`Read` first burns time and context on a
question the graph answers in one call.

Start every task with the matching command:

| Task | Run first |
|---|---|
| "How does X work?" / "Where is Y handled?" | `graphify query "how does X work"` |
| "What links A to B?" | `graphify path "A" "B"` |
| "What is this symbol?" | `graphify explain "PlatformAccount"` |
| **"What breaks if I change X?"** | `graphify affected "X"` — reverse traversal, run before every edit |
| "What are the core abstractions?" | `graphify god-nodes` |
| Broad architecture review | read `graphify-out/GRAPH_REPORT.md` |

Then read only the files the graph named. `.claude/settings.json` registers PreToolUse
`hook-guard` hooks on Bash/Grep/Read/Glob that nudge toward this — don't work around them.

### Keeping the graph current

**Every code change must be followed by a graph update.** A stale graph is worse than
no graph: it sends the next session to symbols that moved or no longer exist.

```powershell
graphify update .          # after editing .py/.js/.sh/.ps1 — AST-only, no API cost, seconds
graphify update . --force  # after a refactor that DELETES code (bypasses the shrink guard)
```

Rules:
- Run `graphify update .` before finishing any task that touched code. Not optional.
- Docs and templates (`.md`, `.html`) are **not** covered by `update` — it is AST-only.
  After editing README/CONFIGURE/Jinja templates, run the full `/graphify .` pipeline,
  which re-runs semantic extraction (cached per file, so only changed files cost tokens).
- Renaming or moving a module invalidates node IDs across the graph — use `--force`.
- `graphify hook install` adds post-commit/post-checkout git hooks that rebuild
  automatically. Not currently installed; install it if manual updates get missed.

## Environment

Bare `python` on this Windows machine resolves to the **Microsoft Store stub** and will
fail (documented in [CONFIGURE_LOCAL.md](CONFIGURE_LOCAL.md)). Always use the venv
interpreter explicitly:

```powershell
.venv\Scripts\python.exe -m pytest        # not: python -m pytest
.venv\Scripts\Activate.ps1                # or activate first
```

PowerShell here is **5.1** — no `&&`, no `||`, no ternary, no `??`. Chain with
`A; if ($?) { B }`. Write files with `-Encoding utf8`; a BOM in `.env` breaks config parsing.

`data/`, `media/`, `logs/` must stay outside OneDrive sync in real deployments — sync
locks the SQLite file mid-write.

## Commands

```powershell
# setup
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
Copy-Item .env.example .env               # then fill SECRET_KEY and ENCRYPTION_KEY

# run  (FLASK_APP=wsgi.py, APP_ENV=development)
.venv\Scripts\python.exe run.py           # web UI on http://127.0.0.1:8000
.venv\Scripts\python.exe worker.py        # background scheduler

# tests — 110 tests, none touch the network
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m pytest --cov=app
.venv\Scripts\python.exe -m pytest tests/test_content_service.py -k monetizable

# flask CLI
flask check              # diagnose configuration — run this first when stuck
flask init-db            # schema + built-in roles + default settings
flask create-admin
flask reset-password <user>
flask list-users
flask run-job <job>      # upload_queue | collect_statistics | research_trends | maintenance
flask db upgrade         # apply migrations (alembic.ini lives in migrations/)
```

## Architecture

**Views are thin; behaviour lives in `app/services/`.** That is what lets the scheduler
reuse the exact code path the website uses. A view parses the request, calls one
service, renders. If you find yourself writing a decision in `app/web/`, it belongs in a
service.

```
app/web/*.py        one blueprint per area — auth, dashboard, videos, accounts,
                    stats, trends, users, settings, api; forms.py holds WTForms
app/services/*.py   all the behaviour (content picking, queue, stats, scheduler)
app/models/*.py     one table per file
app/platforms/      base.py = PlatformAdapter contract; registry.py = @register_adapter;
                    youtube/ = the one implementation
app/security/       permissions.py (catalogue), access.py (decorators), crypto.py (Fernet)
```

Architectural hubs, by edge count (`graphify god-nodes`) — changes here ripple widest:
`permission_required()` 53 · `PlatformAccount` 38 · `record()` 33 · `PlatformError` 26 ·
`get_adapter()` 26 · `UploadJob` 25 · `PlatformAdapter` 24 · `User` 23.

### Rules that are load-bearing

- **Scheduler ownership is exclusive.** Web runs `SCHEDULER_ENABLED=0`, worker `1`.
  Three gunicorn workers each running a scheduler publishes the same video three times.
- **The publish gate runs twice.** `Video.blocking_reasons()` is checked at queue time
  *and* immediately before transfer, so approval withdrawn while a job waited still
  stops the upload. It is the single source of truth for the UI banner and the
  suppressed Publish form — don't duplicate its logic in a template.
- **The money rule is a running mix, not a rotation.** `content_service` measures the
  monetisable share of the last 20 automatic uploads; below target (default 80%) the
  next pick must be monetisable. If the preferred class is empty it falls back rather
  than waste the slot.
- **Unverified rights are never published.** Trend research stores topics and keywords
  only — never files. Re-uploading someone else's video is the fastest route to losing
  monetisation, so the licence model is a revenue feature, not red tape.
- **Stats are append-only.** Each collection adds a `StatSnapshot`; never overwrite a
  counter. Aggregations must not sum a video's whole history.
- **Errors are classified, not just raised.** `PlatformRetryableError` gets backoff
  (5/15/45/135 min); anything else fails the job and flags the account.
- **Tokens are encrypted at rest** with Fernet and never rendered. `ENCRYPTION_KEY` is
  the only way back — losing it means reconnecting every channel.

## Conventions

- One concern per file. Every module opens with a docstring saying what it is for **and
  why** — match that when adding modules.
- Permissions are powers of two and **permanent**; add new bits, never renumber.
- `is_admin` short-circuits every permission check by design.
- Guard rails are deliberate: you cannot demote or delete the last administrator, or
  disable your own account. UI-only guards (e.g. `users/index.html`) must be re-checked
  in the POST handler — never trust the template.
- Static assets are self-contained, no CDN. The CSP is strict so the app works on a
  server with no outbound internet.
- Two config surfaces, kept apart: `.env` belongs to the machine (needs restart);
  the Settings page belongs to the operation (applies next background cycle).

## Known graph caveats

- `app/templates/auth/change_password.html` and `app/templates/users/reset_password.html`
  were skipped by graphify's sensitive-filename heuristic — they are **absent from the
  graph**. Read them directly.
- The last build reported 207 dangling-endpoint edges: semantic edges pointing at node
  IDs the AST pass didn't emit (mostly Jinja macros). Those edges were dropped at build
  time, so template→macro links are incomplete.
