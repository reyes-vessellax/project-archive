# Updating the download engine (slskd)

DigMart ships **slskd** unmodified, renamed `DigMart Engine`. We never change its code. When the slskd
team publishes a release we have to move to (a security fix, a network change that stops old versions
working, or a bug that affects our users), follow these steps.

## The rule for version numbers

An engine-only update is a **patch release**: the last number goes up by one and nothing else changes
(1.0.1 → 1.0.2). It carries no new DigMart features and no DigMart bug fixes. If other work is waiting
on the branch, ship the engine update first, on its own, so it can be traced and rolled back by itself.

## Steps

1. **Read the slskd release notes** for every version between ours and the new one:
   <https://github.com/slskd/slskd/releases>. Look for changes to the API (`/api/v0/...`), the config file
   (`slskd.yml`) and the licence.
2. **Change the version in one place:** `ENGINE_VERSION` in `app/config.py`.
   The CI builds (Windows and both macOS chips) and the local build script read it from there.
3. **Update the three places that print it for people:** the thanks comment at the top of
   `app/core/slskd_manager.py`, and the version in the table and paragraph at the bottom of `README.md`.
   (`tests/test_engine_version.py` fails if any of them is out of step.)
4. **Bump DigMart's patch number:** `APP_VERSION` in `app/config.py` and `version` in `pyproject.toml`.
5. **Add a CHANGELOG entry**, for example:
   `## 1.0.2 — engine update` / `- Download engine updated to slskd X.Y.Z (required by the network). No other changes.`
6. **Test:** `python -m pytest -q`, then a real build. In the built app: sign-in, a search with results, a
   download, a preview, and Settings → Advanced → Connection → Test again.
7. **Release** the usual way. The app's own updater delivers it; users do nothing.

## What must stay true (licence)

- The engine is shipped **unmodified**; only the file name changes.
- Its `LICENSE` file stays next to it (`vendor/engine/LICENSE`).
- The README inside the app (`README.txt`) and the repository README name slskd, its version and licence,
  and link to the source for **that exact version**. Both are generated from, or checked against,
  `ENGINE_VERSION`.
- DigMart's own terms never restrict what a user may do with slskd under the AGPL.

If a new slskd release changes its licence, stop and ask before shipping it.
