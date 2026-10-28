# HomeLabStats: notes for contributors and AI assistants

Self-hosted Linux server dashboard. Python (FastAPI + psutil + Docker SDK) backend in `app/main.py`,
self-updater in `app/updater.py`, single-file vanilla JS frontend in `app/static/index.html`.
GitHub Pages site in `docs/` (landing page + a live demo running on simulated data from `app/static/demo.js`).

## Release rules (do this for EVERY change pushed to main)

Installed copies update themselves from `main` using `app/VERSION` and `CHANGELOG.md`, so:

1. **Bump `app/VERSION`** using semver: patch for fixes, minor for new features, major for breaking config changes.
2. **Add a `CHANGELOG.md` entry** at the top: `## [x.y.z] - YYYY-MM-DD` with `### Added`, `### Changed`, `### Fixed`
   or `### Removed` subsections. Write entries for users, not developers. The Updates tab renders this file.
3. If the frontend or `demo.js` changed, run `./scripts/build-pages.sh` so `docs/demo/` matches the app.
   Re-take the screenshots in `docs/img/` if the UI looks different.
4. If you add a setting, document it in `README.md`, the config table in `docs/index.html`, `.env.example`
   and the installer's env file in `install.sh`.
5. Never require edits to tracked files for configuration. User settings live in `.env` (Docker) or
   `/etc/homelabstats.env` (systemd) so `git merge --ff-only` updates never conflict.
6. Keep `main` deployable: updates are a fast-forward of `main`, followed by `pip install -r requirements.txt`
   when it changed, then a process restart.

## Style
- No em dashes in any user-facing text or docs.
- Dark theme with cyan accent (`#22d3ee`), violet secondary (`#a78bfa`), monospace for numbers.
- Frontend has no build step and no external CDN dependencies (it must work on an offline LAN).

## Test locally
```bash
pip install -r requirements.txt
DATA_DIR=./data PORT=8090 python -m app.main     # real data
# open http://localhost:8090/?demo for simulated data
```
