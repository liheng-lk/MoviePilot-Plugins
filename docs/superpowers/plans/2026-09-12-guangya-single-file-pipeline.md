# GuangYa Single-File Unified Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert GuangYaTransferAssistant to a single-runtime-file plugin and then close the TG/GYING → four transfer methods → real landing → MP-priority rename → notification loop.

**Architecture:** Keep only `plugins.v3/guangyatransferassistant/__init__.py` as Python runtime code. Inline existing stable behavior first, remove cross-module imports and MRO wrappers, then unify resource candidates and execution contracts inside the same file.

**Tech Stack:** Python 3.12, MoviePilot plugin API, GuangYa APIs, GYING HTTP protocol, pytest-style contract scripts executed by the repository validation workflow.

**Spec:** `docs/superpowers/specs/2026-09-12-guangya-single-file-design.md`

## Global Constraints

- Plugin runtime directory must contain exactly one Python file: `__init__.py`.
- Runtime source priority: `Xunlei flash > GuangYa direct share > Magnet > ED2K`.
- Magnet and ED2K use GuangYa native cloudcollection only.
- Xunlei uses JSON flash-transfer only; no ordinary upload fallback.
- GuangYa share uses native share restore.
- MoviePilot identity is authoritative for title/year/season/episode.
- Successful completion requires real target-directory landing evidence and final-name confirmation.
- Full contract suite must be green after each migration batch.

---

### Task 1: Add single-file architecture guard

**Files:**
- Modify: `tests/v3/guangyatransferassistant/run_contract_tests.py`
- Create: `tests/v3/guangyatransferassistant/test_single_file_runtime_contract.py`

**Interfaces:**
- Consumes: plugin directory path.
- Produces: CI failure whenever a runtime `*.py` other than `__init__.py` exists.

- [ ] Write a failing test that enumerates runtime `*.py` and expects exactly `["__init__.py"]`.
- [ ] Run the focused contract test and verify it fails on the current multi-file baseline.
- [ ] Wire the test into the contract runner.
- [ ] Keep the test red until Task 3 removes old modules.
- [ ] Commit the guard.

### Task 2: Inline stable runtime into `__init__.py`

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`

**Interfaces:**
- Consumes: all currently imported GuangYa runtime modules.
- Produces: one self-contained Python module exposing the same public plugin class and API behavior.

- [ ] Build an import/dependency inventory of all runtime modules reachable from current `__init__.py`.
- [ ] Inline helper/constants first in dependency order.
- [ ] Inline classes/methods while preserving current final MRO semantics.
- [ ] Replace relative imports with direct symbol references.
- [ ] Parse the resulting `__init__.py` with `ast.parse`.
- [ ] Run focused compatibility tests.
- [ ] Commit the self-contained runtime before deleting old files.

### Task 3: Remove all other runtime Python files

**Files:**
- Delete: every `plugins.v3/guangyatransferassistant/*.py` except `__init__.py`
- Modify: tests that inspect historical file locations.

**Interfaces:**
- Consumes: self-contained `__init__.py`.
- Produces: exactly one runtime Python file.

- [ ] Delete obsolete runtime modules.
- [ ] Update tests to inspect the inlined implementation instead of deleted files.
- [ ] Run the single-file guard; it must turn green.
- [ ] Run the full GuangYa contract suite.
- [ ] Commit only when the suite is green.

### Task 4: Add normalized four-type resource routing contract

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`
- Modify/Create: focused tests under `tests/v3/guangyatransferassistant/`

**Interfaces:**
- Produces: `ResourceCandidate`-compatible normalized dicts with `type in {guangya,xunlei,magnet,ed2k}` and one execution dispatcher.

- [ ] Write failing tests proving TG and GYING candidates normalize to the four resource types.
- [ ] Write failing tests proving dispatcher mapping: magnet/ed2k→cloudcollection, xunlei→JSON flash, guangya→share restore.
- [ ] Implement minimal normalization and dispatcher.
- [ ] Run focused tests and then full contracts.
- [ ] Commit.

### Task 5: Implement MP-priority final naming

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`
- Modify: naming tests.

**Interfaces:**
- Produces: one final-name function used by all four transfer methods.

- [ ] Write failing TV tests such as `Show.S01E07.2160p.WEB-DL.H265.DDP5.1.mkv → 幸运女神 - S01E07 - 2160p WEB-DL H265 DDP5.1.mkv`.
- [ ] Write failing movie tests preserving useful technical tags while replacing source identity with MP identity.
- [ ] Implement technical-tag extraction without copying conflicting source title/year/episode.
- [ ] Route GuangYa share, Xunlei and cloudcollection naming through the same function.
- [ ] Run focused and full tests.
- [ ] Commit.

### Task 6: Enforce real landing verification for all transfer methods

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`
- Modify/Create: landing-integrity tests.

**Interfaces:**
- Produces: consistent completion evidence containing target parent, file id, final name, size and verification source.

- [ ] Write failing tests for pre-existing same-name file rejection.
- [ ] Write failing tests for newly appeared file-id acceptance.
- [ ] Carry target-directory snapshot/readback into Magnet/ED2K.
- [ ] Reuse equivalent size/file-id integrity checks for Xunlei and GuangYa share.
- [ ] Ensure incomplete evidence stays pending/needs_review, never completed.
- [ ] Run focused and full tests.
- [ ] Commit.

### Task 7: Unify success notification and subscription completion

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`
- Modify/Create: notification tests.

**Interfaces:**
- Produces: exactly-once completion notification after verified landing + final-name confirmation.

- [ ] Write failing tests proving API/task success alone does not notify completion.
- [ ] Write failing tests proving verified landing emits one notification containing media, source, episodes, final name and remaining episodes.
- [ ] Implement shared completion finalizer.
- [ ] Ensure duplicate polling cannot send duplicate notifications.
- [ ] Run focused and full tests.
- [ ] Commit.

### Task 8: Validate provider truth and end-to-end source matrix

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/__init__.py`
- Modify: GYING/TG end-to-end tests.

**Interfaces:**
- Produces: observable provider evidence and end-to-end route result.

- [ ] Preserve GYING live/cache counters and force-network test semantics.
- [ ] Add fixtures for TG and GYING × guangya/xunlei/magnet/ed2k.
- [ ] Verify each path selects only authoritative missing episodes.
- [ ] Verify route priority blocks lower-priority duplicates after a higher-priority claim succeeds.
- [ ] Run full contract suite.
- [ ] Commit.

### Task 9: Documentation and final branch verification

**Files:**
- Modify: `plugins.v3/guangyatransferassistant/README.md`
- Modify: `plugins.v3/guangyatransferassistant/plugin.json` only if release metadata must change.

**Interfaces:**
- Produces: user-facing description matching actual runtime behavior.

- [ ] Document single-file architecture and four transfer methods.
- [ ] Document final naming examples and success evidence.
- [ ] Run AST parse, single-file guard and full contract suite.
- [ ] Confirm plugin directory has exactly one Python file.
- [ ] Review diff for accidental business regressions.
- [ ] Commit final verification state.
