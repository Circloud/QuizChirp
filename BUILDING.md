# Portable builds

Build on the target operating system and architecture with Python 3.14:

```sh
uv sync --locked --group build --python 3.14 --no-install-package openai-codex-cli-bin
uv run --no-sync python -m unittest discover -s tests
uv run --no-sync python tools/build.py
```

The build creates a ZIP and a SHA-256 file in `dist/`. Windows contains a
`QuizChirp` folder; macOS contains a standalone `QuizChirp.app`. End users do
not need Python, uv, or the source checkout. Keep the complete Windows folder.
macOS builds use ad-hoc signing, without Developer ID signing or notarization.

GitHub Actions runs the same tests on Windows x64, macOS Apple Silicon, and macOS
Intel. Pull requests targeting `main` also build and upload ZIP artifacts; pushes
to `main` only run tests. Manual workflow runs test and build without publishing.
Download the appropriate ZIP inside the Actions artifact. A successful build
does not verify desktop interaction or macOS privacy permissions.

To publish, tag a verified commit already merged into `main`, then push that
specific `v*` tag. The workflow tests and builds all three platforms, checks that
the commit belongs to `main`, and publishes a GitHub Release with the ZIPs,
SHA-256 files and generated release notes. Branch pushes and PRs never publish
releases. Keep published version tags fixed; use a new version for changes.

## Runtime and data

Codex is excluded from the application bundle. The tray checks the saved path,
PATH and common installation locations before offering an explicit download.
Downloading uses the official wheel URL, size and SHA-256 pinned in
`quizchirp/runtime-downloads.json`, verified against `uv.lock` during builds.
Update both when changing the Codex SDK version. No package manager is invoked
on the user's computer. Failed or cancelled downloads remove their staging files.

Windows keeps configuration, credentials and downloads in `data/` beside the
executable. macOS uses `~/Library/Application Support/QuizChirp`. The application
bundle is read-only at runtime. Never include these personal directories in an
archive. To update Windows, extract a fresh build and move the existing `data/`
directory into it after quitting the old app. On macOS, replace the `.app`.

Manual runtime paths can be entered in `[runtime].codex_bin` through **Open
configuration file**, followed by **Retry** during setup. Other file
edits require a restart. Download cancellation can take up to the current
network timeout or runtime probe to finish.

Startup, tray Retry and mouse-triggered recovery share the same checks. In any
idle error state, a mouse trigger checks input access, the runtime, screen access
and account availability, then continues that trigger's capture or submission.
It never downloads Codex, opens a login page or requests a new OS permission.
Downloads and login require explicit tray actions. In-progress states (including
login) ignore extra triggers. Tray Retry checks recovery without submitting a
question. Without input permission, use the tray because mouse events may not arrive.

## Desktop acceptance

On a machine without Python or uv, check tray startup, external Codex discovery,
explicit download/cancel/retry, login, sound preview, mouse triggers and multi-image
submission. On macOS, additionally check first-open handling and screen/input
permissions. Runtime downloads and authentication still need network access.
Desktop acceptance is separate from the automated regression suite.
