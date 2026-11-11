# Release and update plan

Status: proposal, November 2026. Describes how SciView will be distributed to
non-expert users with standard Pixi and conda tooling, while developers keep
the source checkout. Phases are independent; stop after any of them.

## Where we are

- Install today means a Git checkout plus Pixi. The per-OS launchers install
  Pixi on consent, run `pixi install`, offer a Git fast-forward update, register
  shortcuts after a one-time prompt, and start the app.
- Updates exist only for Git checkouts. A downloaded archive never updates.
- The code is not installable as a package. `main.py` and `tabs/` sit outside
  `src/`, and assets, fonts, and `pyproject.toml` are located relative to the
  repository root. `launchers.py` already looks for `sciview.stable_app.main`
  first, so an installed layout was anticipated.
- A PyInstaller experiment was evaluated and removed. It produced a 1.4 GB
  bundle with hundreds of unresolved optional imports and would have added a
  three-platform build pipeline to maintain. Build outputs are now ignored.

## Goal

Non-expert users install, start, and update SciView without Git, a checkout,
or shell knowledge. Developers keep `pixi run launch-app` in a checkout. Both
run the same package, so one fix serves both. SciView owns no installer,
updater, or shortcut code of its own.

## Approach: conda package installed with `pixi global`

| Need | Standard tool | Replaces |
| --- | --- | --- |
| Build a package from the repo | `pixi build` (rattler-build) in CI on a tag | New |
| Host versions | Public channel on prefix.dev; GitHub Releases as mirror | Git as distribution |
| Install for a user | `pixi global install sciview` | `pixi install` in a checkout, venv fallback |
| Shortcuts, icons, taskbar grouping | menuinst JSON in the package, applied by `pixi global shortcut` | Both shortcut scripts |
| Update | `pixi global update sciview` | Git fast-forward prompt and restart |
| Offline bundle or GUI installer, if ever needed | `pixi-pack` or conda `constructor`, fed by the same package | New |

Verified on this machine: Pixi 0.75 provides `pixi build` and
`pixi global shortcut`; `scitoolsscianalysis`, `bluesky-tiled-plugins`, and
`menuinst` are on conda-forge. `pyqtdarktheme` is PyPI only and is the one
dependency that must go (see phase 1).

### User experience

1. Install Pixi once from its official installer (MSI on Windows, one-line
   command on macOS and Linux).
2. Run one command, or double-click a short bootstrap script that runs it.
   SciView appears in the Start menu, Applications, or the application menu
   with its icon.
3. Update from a SciView menu item or one command. No branch, no checkout.

### Developer experience

Unchanged: clone, `pixi run launch-app`, Git updates through the existing
launchers. The launcher conveniences built in November 2026 (shortcut prompt,
restart after update, first-time banner) remain for checkouts and are not
developed further.

## Phases

### Phase 0: housekeeping (done or half a day)

- PyInstaller outputs removed; `build/`, `dist/`, `*.spec` ignored; `pixi.lock`
  restored to match `pixi.toml`.
- Commit the launcher work from this session.
- Fix the indentation of the new Unix steps in `installation.yml`.

### Phase 1: make the package installable (three to five days)

This is the real work and pays off regardless of distribution.

- Move `main.py` to `src/sciview/stable_app/main.py` and `tabs/` into the
  package. Keep a thin `main.py` at the root for one release so existing
  checkouts keep working.
- Locate assets and fonts with `importlib.resources`; read version and
  `app_id` with `importlib.metadata`. Remove every "repository root" path.
- Add `[project.gui-scripts] sciview = "sciview.launchers:main"` so the
  package provides a command for menuinst to launch.
- Drop `pyqtdarktheme`. The app already falls back to its own styling when the
  import fails; confirm appearance in both themes, then remove the dependency.
- Validate with `pip install .` into a scratch environment, run
  `python -m sciview.launchers`, and run the test suite from outside the repo.

### Phase 2: package and shortcuts (one to two days)

- Add a `[package]` section and `pixi build` backend to `pixi.toml`, or a
  `recipe.yaml`, that builds a noarch Python conda package from the project.
- Add menuinst JSON (`Menu/sciview.json`) with the icon files already in the
  repo, the `sciview` command, and the AppUserModelID from `pyproject.toml`.
- Prove it locally: build, `pixi global install` from the built package, check
  the shortcut and taskbar grouping on Windows and the bundle on macOS, then
  `pixi global uninstall`.

### Phase 3: release workflow (one day)

- GitHub Actions on tag `v*`: check the tag equals the project version, build
  the package, run the installation smoke test from the package rather than
  the checkout, upload to the prefix.dev channel and attach to the GitHub
  Release.
- Bootstrap scripts, one per platform, each about ten lines: install Pixi if
  missing, then `pixi global install` with the channel. No other logic.
- README: a "Download" section for users and a "Develop" section for the
  checkout. Replace the current launcher-centred text.

### Phase 4: in-app update (half a day)

In an installed environment the Update menu runs `pixi global update sciview`
and asks the user to restart. In a checkout it keeps the Git behaviour. Mode is
detected by the presence of `.git` next to the package, which the installed
layout never has. New strings go in the message catalog per
`docs/LOCALIZATION.md`.

### Later, only on request

- `pixi-pack` offline bundle for facilities without internet.
- conda `constructor` GUI installer for sites that forbid command lines.
- Code signing if SmartScreen or Gatekeeper friction becomes a support burden.

## Validation

- Phase 1: existing pytest suite plus an install-from-wheel check in CI.
- Phase 2: manual check of shortcuts on each OS once; menuinst is the
  maintained component, not SciView.
- Phase 3: the installation workflow installs from the built package on
  Windows, macOS, and the RHEL container exactly as it installs from the
  checkout today.
- Keep exploratory probes local and uncommitted per the test instructions.

## Risks

- Channel hosting. prefix.dev public channels are free; GitHub Releases is the
  mirror if that changes. The package is small, so either is fine.
- Pixi global shortcuts are a recent feature. Phase 2 proves them on all three
  platforms before anything is published.
- Users still install Pixi first. The bootstrap script hides this, and Pixi's
  own installers are maintained upstream.
- Moving `main.py` and `tabs/` touches many imports. Do it in one commit with
  the test suite as the gate, and keep the root shim for one release.

## Decisions needed

1. Confirm the `pixi global` approach and shelve PyInstaller for good.
2. Channel name on prefix.dev and whether to mirror packages to GitHub Releases.
3. Agree to drop `pyqtdarktheme` in favour of the existing fallback styling.
4. First tag. `v0.1.0` matches `pyproject.toml` today.
