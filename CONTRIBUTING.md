# Contributing

Bug reports, ideas and pull requests are welcome. For anything larger than a fix, open an issue first so we can agree on the shape before you build it.

## Run the checks

From the repository root, with the Herdr desktop app's `herdr-app` on your PATH:

```bash
herdr-app check mods/pm-dash
herdr-app check mods/pm-nav
herdr-app check mods/pm-list
herdr-app check mods/pm-toast
herdr-app check mods/pm-project
node --test mods/pm-dash/model.test.mjs mods/pm-list/model.test.mjs mods/pm-project/model.test.mjs
python3 -m unittest mods/pm-dash/skill/scripts/test_pm.py tests/test_install.py
bash -n install.sh
```

These do not replace trying the change in the desktop app: say in the pull request what you clicked and saw. [RECIPE.md](RECIPE.md) lists the behavior each mod must keep.

## Commits

- [Conventional Commits](https://www.conventionalcommits.org/): `feat(scope): …`, `fix(scope): …`, `docs: …`, `test: …`, `chore: …`.
- The subject says what changes for the user, in plain words. The body says why, when that is not obvious.
- One change per pull request; keep unrelated cleanups out.
- Update the README, [the guide](docs/guide.md) and [CHANGELOG.md](CHANGELOG.md) when behavior changes.

## What we will not merge

- Changes that tie dudu to one coding agent. The manager and the workers must keep working with any agent.
- Writes outside dudu's own files, or changes to a user's settings, without the installer saying so.
- New runtime dependencies for the installer or the scripts: they use Python's standard library only.
- Telemetry or network calls that send a user's data anywhere.
- Large rewrites or reformatting without an issue agreed first.
