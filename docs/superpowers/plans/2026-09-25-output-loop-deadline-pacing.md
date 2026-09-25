# Output Loop Deadline Pacing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hold both 44 Hz output loops at a 44 Hz mean on macOS by pacing to absolute deadlines instead of sleeping the remaining interval.

**Architecture:** A small local `TickPacer` (`luxaeterna/pacing.py`) sleeps to a deadline, advances it one period, and resyncs instead of bursting after a stall. `MultiUniverseOutputLoop._loop` and `OutputLoop._loop` call `pacer.wait()` in place of their fixed remaining sleep; both take injectable `clock`/`sleep` so the loop is testable offline.

**Tech Stack:** Python stdlib (`time`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-25-output-loop-deadline-pacing-design.md`

## Global Constraints

- Run tests with the root venv from the worktree cwd: `/Users/chris/projects/luxaeterna/.venv/bin/pytest` (no editable install; `pythonpath=["."]`).
- No dependency on mm-terrarium.
- `fps` semantics unchanged: ~1 s window, `frames / elapsed`, counts only ticks that sent.
- `sleep` is never called with a non-positive value.

---

### Task 1: `TickPacer`

**Files:**
- Create: `luxaeterna/pacing.py`
- Test: `tests/test_pacing.py`

- [ ] Write `tests/test_pacing.py` (fake clock; sleep oversleeps 4 ms): mean rate over N waits, work subtracted, stall resync without burst, no non-positive sleeps, first wait sleeps one period, bad period raises. Run: fails on import.
- [ ] Implement `TickPacer(period, *, clock=time.monotonic, sleep=time.sleep)` with `wait()` per spec §2.1. Run: passes.
- [ ] Commit `feat(pacing): TickPacer, deadline pacing that repays sleep slack`.

### Task 2: pace both output loops

**Files:**
- Modify: `luxaeterna/universeset.py` (`MultiUniverseOutputLoop.__init__`, `_loop`)
- Modify: `luxaeterna/output.py` (`OutputLoop.__init__`, `_loop`)
- Test: `tests/test_universeset.py`, `tests/test_output_hook.py`

- [ ] Add loop-level tests: with the 4 ms-oversleep fake, `_loop()` run synchronously for ~3 s fake time gives `fps` within 1% of 44; a 100 ms stall in `on_frame` is followed by no tick interval shorter than one period less 1 ms. Run: fail (`clock` kwarg unknown).
- [ ] Add keyword-only `clock`/`sleep` to both constructors; in `_loop` build a fresh `TickPacer(self.frame_interval, clock=self._clock, sleep=self._sleep)`, use `self._clock` for the fps timer, replace the remaining-sleep block with `pacer.wait()`. Run: pass.
- [ ] Full suite green. Commit `fix(output): pace the 44 Hz output loops to deadlines, not the remaining interval`.
