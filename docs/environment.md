# Environment

The resolved toolchain, the machine it was resolved on, and the setup steps that
are not obvious from `pyproject.toml`. The version matrix itself lives in
[`adr/0001-toolchain-resolution.md`](adr/0001-toolchain-resolution.md) and is not
duplicated here.

## The machine

| | |
|---|---|
| Host | Windows with WSL2, WSL version `2.7.10.0`, WSLg `1.0.73.2` |
| Guest | `Ubuntu 26.04 LTS`, kernel `6.18.33.2-microsoft-standard-WSL2` |
| CPU | `Intel Core i7-14700K`, `28` logical processors |
| Memory available to the guest | about `14` GiB |
| GPU | `NVIDIA GeForce RTX 5070`, `12227` MiB, visible to the guest |

**Everything lives inside the WSL2 filesystem.** The repository is at
`/home/elijah/autofill-audit` and the virtual environment at
`/home/elijah/.venvs/autofill-audit`. Nothing about this project is stored on
the Windows side, and that is a working constraint rather than a preference:
this author's Windows paths contain spaces, and Playwright's browser download
and launch handling, pytest's rootdir discovery, and shell quoting inside
pre-commit hooks all behave inconsistently under them. The Windows drives are
also reached through a translation layer that is slow for the many-small-files
work that `git status`, test collection, and linting all are.

The GPU is for training and for the local language model. No phase adds a CUDA
execution provider to the tool's own inference path, which runs on the
onnxruntime CPU execution provider so that installing the tool never implies
installing a CUDA runtime.

## Python and the virtual environment

```bash
/usr/bin/python3.14 -m venv ~/.venvs/autofill-audit
. ~/.venvs/autofill-audit/bin/activate
pip install -U pip pip-tools
pip install -e ".[dev,llm]"
```

CI does not do this. CI installs the exact pin set and then the project without
its dependencies, so that a CI run never resolves its own dependency graph:

```bash
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

## Playwright

```bash
playwright install chromium --with-deps
```

`--with-deps` invokes the distribution package manager and therefore needs root.
On this machine `sudo` is passwordless, so the flag worked and no manual
dependency list was needed. The specification's fallback path, installing the
system libraries by hand once and recording the list here, was not required and
so is not recorded: writing down a list that was never used would be an
invitation to follow it later and install the wrong thing.

If `--with-deps` is refused on another machine, Chromium itself still installs
without root. Run `playwright install chromium` first, then resolve the system
libraries separately, and add the resolved list to this file at that point.

Installed here: the **full Chromium** build, not the headless shell. The
specification requires this because part of the hostile corpus tier depends on
layout and on custom element upgrade behaviour, and the reduced build's
divergences are not worth discovering in the middle of a benchmark. The headless
shell and an ffmpeg build are downloaded alongside it by the installer; they are
harmless and are not used.

CI caches `~/.cache/ms-playwright` on a key that includes the Playwright version
taken out of `requirements.lock`. That is deliberate: Playwright pins a browser
build per release, and a cache key without the version eventually serves a stale
browser whose launch failure reads like an unrelated bug.

## Git identity and pushing from WSL

The repository sets its identity locally rather than relying on a global config:

```bash
git config user.name "Olajide Badejo"
git config user.email "251888067+Olajide-Badejo@users.noreply.github.com"
```

The GitHub CLI is installed on the Windows side, not inside the guest. Rather
than installing and authenticating a second copy, the repository borrows the
Windows one as its credential helper:

```bash
git config credential.helper \
  '!/mnt/c/Program\ Files/GitHub\ CLI/gh.exe auth git-credential'
```

The leading `!` marks the value as a shell command rather than a helper name,
and the escaped space survives git's own parsing of the value. With this in
place, `git push` from inside WSL authenticates through the Windows credential
store and no token is written into the guest filesystem.

## Pre-commit

```bash
. ~/.venvs/autofill-audit/bin/activate
pre-commit install --install-hooks
pre-commit install --hook-type commit-msg
```

Every project hook is `language: system` and therefore runs the tools out of the
activated virtual environment. This is on purpose. Letting pre-commit build its
own isolated environments would create a second copy of ruff and mypy that
drifts from the one CI uses, and the first time it drifted, the local result and
the CI result would disagree with no visible cause.

Consequence: **the virtual environment must be active when committing.** With it
inactive the hooks fail to find their entry points rather than silently passing.

The `commit-msg` hook is separate and must be installed separately, as above. It
rejects forbidden dash characters and attribution artifacts in the message.

## The report engine

TeX Live is installed in full, with `latexmk` at `/usr/bin/latexmk`. That is the
fallback condition the specification names, so `latexmk` is the resolved engine
and `make reports` wraps it. `tectonic` is also present at
`/usr/local/bin/tectonic` and is not used. The reasoning is in ADR 0001.

### What the three documents actually need, resolved at P7

ADR 0001 promised this list, because choosing `latexmk` means the report build
depends on a distribution this repository does not provision. Everything below is
in the standard distribution and is what `tectonic` would fetch on a machine
without one:

`fontenc`, `inputenc`, `lmodern`, `geometry`, `microtype`, `booktabs`,
`longtable`, `array`, `graphicx`, `xcolor`, `caption`, `enumitem`, `fancyvrb`,
`parskip`, `hyperref` and the `url` package it loads.

Nothing else is used, no class beyond the standard `report` class, and no font
beyond the Latin Modern set that ships with the distribution.

### How `make reports` is wired

```bash
make reports        # regenerate tables and figures, then build every report present
make reports-clean  # remove everything the above produces, so a rebuild starts from nothing
```

Two properties of that target are deliberate.

**Tables and figures are regenerated first, every time.** They are produced from
committed result files by `scripts/make_report_tables.py` and
`scripts/make_report_figures.py`, and a hand-typed table is a law 3 violation
whatever it looks like, so generation is a prerequisite of the build rather than
a step somebody remembers.

**`latexmk -auxdir=build` separates intermediates from deliverables.** Every
auxiliary file goes to each report's own `build/` directory, which `.gitignore`
ignores, and the compiled PDF is left beside its source, where it is committed.
Spec section 17.2 names the main report's deliverable path as
`report/build/main.pdf` and section 17.3 names the debug report's as
`report_debug/debug_report.pdf`, which are two different conventions; the
`.gitignore` committed at P0 ignores `build/` directories, so the two
deliverables sit at symmetric paths beside their sources rather than one of them
living inside an ignored directory behind a negation rule.

`report_for_me/` is built when it is present and is never committed. Its absence
is not an error and `make reports` says so and carries on.

### The demo animation

`scripts/make_demo_gif.sh` runs the tool for real against
`tests/fixtures/checkout_hostile.html`, captures its stdout and its exit status,
and hands both to `scripts/make_demo_gif.py`, which renders the transcript as
frames with Pillow. Nothing in the animation is written by hand.

Frames rather than a terminal recorder, for two reasons. A recorder captures wall
clock timings, so two runs of the same command produce two different artefacts
and the committed asset can never be reproduced byte for byte. And it would add a
binary that is not in the lock file to the set of things a contributor needs
before they can regenerate a committed asset. Pillow arrives with matplotlib,
which is already in the `dev` extra for the report figures.

## Ollama

Not installed inside the guest at P0, and not needed before P6. The language
model comparison is a research-mode feature: it is never required to run the
tool, never required by the test suite, and never touched by CI. The model tag,
its quantization, and the observed memory headroom are resolved at P6 and
recorded in [`adr/0007-llm-model-and-quantization.md`](adr/0007-llm-model-and-quantization.md).

### As resolved at P6

Ollama was already installed on the Windows host with the model pulled, and the
Windows build binds to loopback only, so from inside the guest the model blob was
visible on disk and unreachable over the network. Installing Ollama inside WSL2
and pointing `OLLAMA_MODELS` at the Windows store reuses the blob with no
re-pull.

Three settings, all in ADR 0007 with their reasoning: the systemd unit is
disabled and the server is started by hand for a run, the keep-alive is bounded
at ten minutes with an explicit unload when a run finishes, and the context
length is set explicitly rather than left to the default.

The live LLM tests need two conditions, `AUTOFILL_AUDIT_LLM_TESTS=1` **and** a
reachable server carrying the tag. CI has neither and must keep having neither.
The default everywhere is a skip with the reason printed.
## Playwright, as resolved at P2

Full Chromium, not the headless shell, per spec section 3.3. The corpus depends
on custom-element upgrade behaviour and on layout, and the reduced build's
divergences are not worth discovering during a benchmark.

### Frames, origins, and what `file://` does

Three facts about this environment, each of which changed a design decision:

**Playwright can evaluate inside a cross-origin frame.** It drives each frame
through its own session, so an evaluation succeeding says nothing about whether
the page itself could reach that frame. The extractor therefore asks the parent
document for the frame's `contentDocument` inside a try block, which is the
check a script on that page would make, and which is what spec section 9.6 means
by a frame that cannot be accessed.

**A `srcdoc` frame inherits its parent's origin.** This is what makes a same
origin frame fixture possible under `file://` at all. Two separate local files
are opaque origins to each other in Chromium unless the browser is launched with
file access relaxed, which is a flag this project does not want to depend on.

**A `data:` URL frame gets an opaque origin.** Which makes it unreadable from
the parent, offline, with no second server, and is how the cross-origin fixture
is written.

**`window.origin` on a `file://` page is the string `null`.** Comparing origins
between a parent and a child is therefore useless here, which is a second reason
the accessibility test is the `contentDocument` one.

### Browser lifecycle in the test suite

One launch per pytest session, a fresh context per page. Twenty fixtures at
roughly half a second of launch each is ten seconds of nothing happening on
every run; one launch and twenty contexts costs the launch once and still gives
every page its own storage and cookies. `loader.browser_session` exists for
this and for the corpus sweep, which would otherwise pay the launch cost several
hundred times.

### The traversal script is a `.js` file

`src/autofill_audit/extract/traverse.js`, injected once per frame root. Keeping
it as a file rather than as a Python string means it can be read and edited as
JavaScript. It is listed in the wheel's package data, because an installed
extractor with nothing to inject is an installed extractor that does not work.
