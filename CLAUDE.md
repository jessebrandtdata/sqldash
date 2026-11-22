# sqldash

Spec: `specs:sqldash/specs/2026-11-21-sqldash-design.md`. Plan: `specs:sqldash/plans/2026-11-21-sqldash-v1.md`.

## Layout

- `serve [host] [port]` runs `python3 -m sqldash.server` (default 127.0.0.1:8096).
- `sqldash/` is the stdlib server: `server.py` (routes, static `dist/`, `main`), `checker.py` (syntax check: pglast for `postgres`, sqlglot for `mysql`, `redshift`, `athena`), `summary.py` (Claude), `judge.py` (Jev), `caps.py`, `dialects.py`, `errors.py`, `envfile.py` (key file loader), `theme.py`, `words.py`.
- `web/` is the Svelte source (`src/`, `tests/*.test.js`, `scripts/source-hash.js`, `public/docs/`); `dist/` is its build, committed.
- `web/e2e/smoke.mjs` is a headless-browser smoke test; `web/e2e/fake_server.py` is its stand-in for the two paid services.
- `scripts/build_pgdocs.py` builds `pg17.json`; `scripts/check_links.py` checks doc links with plain `curl`.
- `tests/` is pytest. `check` is the merge gate; `deploy-hook` is the box's install step.

## Commands

- `./check`: no network; SKIP lines name a missing dep; runs pytest, `node --test`, `source-hash.js check`.
- `./deploy-hook`: pip-installs `requirements.txt` for the host user.
- Smoke (host only, not in `check`; never downloads a browser): `cd web && LD_LIBRARY_PATH=$HOME/dev/bullets/web/tests/.libs/usr/lib/x86_64-linux-gnu node e2e/smoke.mjs`. It uses the browser cached on the box.
- Link check (host only, not in `check`): `python3 scripts/check_links.py`.
- Keys load from `~/.config/sqldash/env` or `SQLDASH_ENV`: `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`; `SQLDASH_SUMMARY_MODEL` overrides the summary model.
- Every request needs a `Host` the server answers to: loopback names for a loopback bind, any IP literal and `localhost` for `0.0.0.0` or `::`, else exactly the bound host. `SQLDASH_ALLOWED_HOSTS` (comma-separated names, read in `main`) adds more. POSTs must be `application/json`, and an `Origin` header must equal `Host`; otherwise 403 `forbidden` or 400 `bad_request`, before any service runs.

## Rules

- Rebuild and commit `dist/` after any `web/` edit (`web/scripts/source-hash.js` fails `check` on drift).
- Model-facing strings live only in `sqldash/words.py`, copied verbatim from the spec.
- No AI call without a click; no key in the page, the repo, a response or a log.
- Route and static names never contain `stat`, `track`, `collect`, `pixel`, `beacon`, `analytics`, `pageview` or `ads`.
- Only `scripts/build_pgdocs.py` produces `pg17.json`; its text is never hand-written.
- The SQL box is changed only by the user's keyboard.
- `checker.py`, `summary.py` and `judge.py` import their third-party package inside the function that uses it, so `import sqldash.server` works on a box without them; test modules `pytest.importorskip` each dep.
- AI calls refuse SQL over 50,000 characters; never truncate.
- No person's name in source: docs say "the user" and "the maintainer" (`tests/test_identity.py`).
- Code comments say what the line does.
- Work in `~/dev/sqldash`, never `~/apps/`; features land on `dev` by PR.

## Dependencies

Runtime (a new one is the maintainer's decision):

- `pglast>=7,<8`: the exact `postgres` syntax check, PostgreSQL 17 grammar (pglast 8 is PostgreSQL 18).
- `sqlglot>=30.33,<31`: approximate syntax check for `mysql`, `redshift`, `athena`; it is not used for `postgres`.
- `anthropic>=1,<2`: the plain-English summary call.
- `typesafe-sdk>=0.7.5,<0.8`: the Jev agreement check.

Build (`web/package.json`, exact pins): `vite`, `svelte`, `@sveltejs/vite-plugin-svelte`, `codemirror` with `@codemirror/{commands,lang-sql,language,lint,state,view}`, `@lezer/highlight`; smoke only: `playwright-core`, pinned to the version whose browser is cached on the box.

Test: `pytest`; Node's built-in `node --test` (no packages).
