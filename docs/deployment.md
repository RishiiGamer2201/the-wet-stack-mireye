# Deployment

Frontend on **Vercel**, backend on **Render**, running in the same deterministic
demo mode as a local checkout — **no external credentials are required**.

> **Read §5 before showing this to anyone who might mistake it for production.**
> Render's filesystem is ephemeral: the database and every uploaded file are
> destroyed on each deploy and restart, and the demo re-seeds itself. That is a
> deliberate choice for a hackathon demo, not a persistence strategy.

---

## 1. Shape of the deployment

```
Browser ──► Vercel (static bundle, apps/web/dist)
                │  fetch(VITE_API_BASE_URL + "/api/...")
                ▼
           Render (uvicorn, apps/api)  ──►  SQLite + in-memory graph on an ephemeral disk
```

The browser talks only to the Render API. Every credential (Mireye, Supabase,
Neo4j, Gemini, LangSmith) lives in the Render environment and never reaches the bundle.
There is no serverless function and no Vercel rewrite proxying `/api` — the API
origin is compiled into the bundle from one environment variable, and CORS on the
API names the Vercel origin explicitly.

## 2. Pinned toolchain

| Runtime | Pin | Where |
| --- | --- | --- |
| Python | 3.13.4 | `apps/api/.python-version`, and `PYTHON_VERSION` in `render.yaml` |
| Node | ≥ 20 (22 recommended) | `apps/web/package.json` `engines.node`, `apps/web/.nvmrc` |

`pyproject.toml` declares `requires-python = ">=3.11"`; 3.13 is the line the test
suite is verified on.

## 3. Backend — Render

`render.yaml` lives at the **repository root** because that is the only place
Render's Blueprint detection looks. (`infra/render.yaml` is now just a pointer.)

### Steps

1. Push the repository to GitHub.
2. Render dashboard → **New → Blueprint** → select the repo. Render reads
   `render.yaml` and proposes the `wetstack-mireye-api` service.
3. Leave every `sync: false` variable blank for a demo deployment. Do **not**
   set `CORS_ORIGINS` yet — you do not know the Vercel URL.
4. **Apply**. Wait for the first deploy, then note the service URL, e.g.
   `https://wetstack-mireye-api.onrender.com`.
5. Check it: `curl https://<service>.onrender.com/api/health` → `{"status":"ok",...}`.
6. Deploy the frontend (§4), then come back and set `CORS_ORIGINS` to the Vercel
   origin and let the service restart.

### What the Blueprint sets

| Setting | Value | Why |
| --- | --- | --- |
| `rootDir` | `apps/api` | the Python project |
| `buildCommand` | `pip install --upgrade pip && pip install .` | non-editable install; needs the packaging fix already in `pyproject.toml` |
| `startCommand` | `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --no-access-log` | production server |
| `healthCheckPath` | `/api/health` | cheap liveness probe, no store access |
| `plan` | `starter` | stays warm; see §5 for the `free` trade-off |
| `autoDeploy` | `false` | a demo should not redeploy (and wipe its data) on every push |

**`--workers 1` is mandatory, not a default.** The impact-graph store is
in-process memory and the SQLite store holds one guarded connection, so a second
worker would answer from a different graph depending on which process took the
request. Scaling out requires Neo4j and Postgres first.

`--no-access-log` avoids duplicating the structured request log the app already
emits. `--proxy-headers` plus `FORWARDED_ALLOW_IPS=*` makes the app see the real
scheme and client behind Render's TLS-terminating proxy.

### Health checks

| Endpoint | Use | Cost |
| --- | --- | --- |
| `/api/health` | Render's liveness probe | static, no I/O |
| `/api/ready` | readiness / diagnostics | touches the store and every adapter, reports which is in use and whether the demo data is seeded |

## 4. Frontend — Vercel

`apps/web/vercel.json` is already correct: Vite framework preset, `dist` output,
SPA rewrite (the app has no client-side router, so the rewrite exists so a
refresh on any path still serves the app), and `X-Content-Type-Options` /
`Referrer-Policy` headers.

### Steps

1. Vercel → **Add New → Project** → import the repo.
2. **Root Directory: `apps/web`.** Everything else is detected from
   `vercel.json`; leave the build command and output directory alone.
3. **Settings → Environment Variables**, for *Production* **and** *Preview*:

   ```
   VITE_API_BASE_URL = https://wetstack-mireye-api.onrender.com
   ```

   No trailing slash. This is a build-time value: changing it requires a
   redeploy, not just a restart.
4. **Deploy.** Note the production URL, e.g. `https://wetstack-mireye.vercel.app`.
5. Go back to Render and set `CORS_ORIGINS` to exactly that origin.

### The build refuses to ship a broken API origin

`vite.config.ts` fails a production build when `VITE_API_BASE_URL`:

* points at `localhost`, `127.0.0.1`, `0.0.0.0` or `[::1]` — a local address in a
  deployed bundle is broken for every user and unfixable without a rebuild;
* is not `https://` — the Vercel page is HTTPS, so anything else is blocked as
  mixed content.

If it is unset the build still succeeds (local verification and CI need that) but
prints a warning, and the running app reports *"This build has no API origin
configured"* instead of silently 404-ing against the static host.

### Preview deployments

Each Vercel preview gets its own `*.vercel.app` origin, so it is **not** in
`CORS_ORIGINS` and its API calls will be refused. Either add the preview origin
to `CORS_ORIGINS`, or accept that only production talks to the API. There is no
wildcard option — the API rejects `*` rather than honouring it.

## 5. Ephemeral filesystem — what resets, and what that means

Render's disk is **ephemeral**. Every deploy, every restart, every crash-restart,
and (on `free`) every wake from idle gives the service a brand-new empty disk.

| What | Where | Survives a redeploy? |
| --- | --- | --- |
| SQLite database (projects, sites, evidence, gaps, investigations) | `$DATA_DIR/wetstack.db` | **No** |
| Uploaded PDFs | `$DATA_DIR/uploads/` | **No** |
| Generated synthetic sample PDFs | `sample_data/` | **No** — regenerated at seed |
| Impact graph | process memory | **No** — rebuilt from the stored analysis on request |
| Mireye response cache | SQLite `cache` table | **No** |
| Everything in `render.yaml` / the dashboard | Render config | Yes |

**The demo self-heals.** On startup with an empty store the API seeds the
synthetic project (5 sites, 3 documents, 3 change cases, 7 assumptions). It is
idempotent by construction: only an empty store is seeded, and the seed runs with
`reset=False`, so a restart can neither wipe nor duplicate existing data.
Verified by deleting `DATA_DIR` and restarting — a fresh project id appears and
`/api/ready` reports `seeded: yes`.

**In practice this means:** anything a viewer does — uploading a PDF, confirming a
requirement, overriding a site value, resolving a gap — is gone after the next
deploy. For a demo that is fine, and the "Reseed demo" button makes it explicit.

**This is not production persistence, and nothing here should be read as
claiming otherwise.** For real durability:

1. Provision Postgres (Render Postgres or Supabase) and set `DATABASE_URL`. That
   also switches retrieval to pgvector.
2. Set **`SEED_ON_STARTUP=false`**. The application warns loudly if you leave it
   on with a `DATABASE_URL` set, because synthetic engineering data must never be
   written into a real database.
3. Provision Neo4j (Aura) and set `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD`
   so the impact graph outlives the process.
4. Move uploads to object storage (S3/Supabase Storage); a Render persistent disk
   would also work but pins the service to one instance.

Attaching a Render **persistent disk** is a middle ground: it survives restarts
but not a service delete, and it forces single-instance deployment — which this
build already requires anyway.

## 6. Uploads

Uploaded files are constrained twice, on purpose:

* `safe_filename()` reduces the client-supplied name to its final path segment
  and strips anything outside `[A-Za-z0-9._ -]`, so `../../../x.pdf` becomes
  `x.pdf`;
* the router then resolves the destination and refuses to write it if its parent
  is not exactly the upload directory.

Only `application/pdf` is accepted, up to `MAX_UPLOAD_BYTES` (25 MB default), and
a file whose text cannot be extracted is deleted rather than kept. Nothing is
executed or served back from the upload directory.

**Uploads are ephemeral** (§5) and are stored unencrypted on the container's
disk. Do not upload anything confidential to a demo deployment.

## 7. Environment variables

### Render (backend)

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `CORS_ORIGINS` | **yes** | dev origins | Comma-separated exact origins. `*` is dropped, not honoured. Must include the Vercel production origin. |
| `ENVIRONMENT` | no | `local` | `production` enables the stricter startup warnings. Set by the Blueprint. |
| `PYTHON_VERSION` | no | — | `3.13.4`. Set by the Blueprint. |
| `DATA_DIR` | no | `apps/api/var` | `/tmp/wetstack` on Render. Ephemeral either way. |
| `SEED_ON_STARTUP` | no | `true` | Seeds only an empty store. **Set `false` with a real `DATABASE_URL`.** |
| `LOG_LEVEL` | no | `INFO` | |
| `FORWARDED_ALLOW_IPS` | no | — | `*` behind Render's proxy. |
| `MAX_UPLOAD_BYTES` | no | 26214400 | |
| `DATABASE_URL` | no | — | Postgres/Supabase; also enables pgvector. |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | no | — | Persistent impact graph. |
| `MIREYE_BASE_URL` / `MIREYE_API_KEY` | no | — | Live physical-world data; without them the labelled mock is used. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | no | — | Explanations and planning only; never a calculation. |
| `LANGSMITH_API_KEY` / `LANGSMITH_PROJECT` | no | — | Opt-in agent tracing; nothing is sent when unset. |

Every optional variable left unset keeps a deterministic local adapter, and the
UI keeps showing the amber **Demo mode** banner naming exactly what is simulated.

### Vercel (frontend)

| Variable | Required | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | **yes** for any deployed build | The Render origin, `https://`, no trailing slash. Build-time; a change needs a redeploy. |

Only `VITE_`-prefixed values reach the browser, and by design none of them is a
secret. `.env.production.example` in each app documents the full set.

## 8. Smoke testing a deployment

`scripts/smoke_test.py` is stdlib-only, so it runs anywhere Python does.

```bash
# backend only
python scripts/smoke_test.py --api https://wetstack-mireye-api.onrender.com

# backend + CORS from the real frontend origin
python scripts/smoke_test.py \
  --api    https://wetstack-mireye-api.onrender.com \
  --origin https://wetstack-mireye.vercel.app

# the built bundle: no secret, localhost URL, Windows path or CORS wildcard
npm --prefix apps/web run build
python scripts/smoke_test.py --skip-api --bundle apps/web/dist \
  --expect-base https://wetstack-mireye-api.onrender.com
```

It asserts health and readiness, that every adapter is named, that the demo data
is seeded, that all three change cases reach their expected decision states, that
re-running an analysis is idempotent (no gap inflation, same stale set), that the
impact graph is served, that CORS admits the real origin and refuses an unknown
one, and that the bundle is clean. It exits non-zero on the first failure.

Against a `free`-plan service the first call may take ~50 s while the instance
wakes; the script's 60 s timeout covers one cold start.

## 9. Rollback

Render: **Deploys** tab → pick the previous deploy → *Redeploy*.
Vercel: **Deployments** → previous build → *Promote to Production*.

Both are config/artifact rollbacks. Neither restores data, because there is none
to restore (§5).
