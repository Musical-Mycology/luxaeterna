# LightSession renders at O2 time Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `LightSession.render_into` hands ugens the injected clock's own reading as `t`, so every session on a box that shares one clock (mm-terrarium injects `o2lite.time_get` into every fixture session in o2lite mode) agrees on `t`, and a rainbow spanning two fixtures is continuous instead of skewed by each session's construction time.

**Architecture:** One function changes: the session drops its private `_start` epoch and passes the clock reading straight through as `t`; `dt` stays the delta since the previous read. The ugen audit found that only `LFO`, `Rainbow` and `Noise` read `ctx.time`, and they are exactly the phase-from-absolute-time generators the change exists for; every other stateful unit (`Envelope`, `SegmentLevel` including `loop_from`, `Smooth`, `ChannelSweep`, `Signature.elapsed`, `GainSignature`) integrates `ctx.dt` from its own local zero, so welcome and status signatures already carry their own origin. The audit therefore lands as tests that pin those two properties, not as ugen changes. A final task verifies mm-terrarium's suite against the changed luxaeterna and updates the mm-terrarium documents that said Plan 3 was not started.

**Tech Stack:** Python 3.10+, numpy, pytest. luxaeterna worktree at `/Users/chris/projects/luxaeterna/.claude/worktrees/session-o2-time-7feab3` (branch `claude/session-o2-time-7feab3`); mm-terrarium worktree at `/Users/chris/projects/mm-terrarium/.claude/worktrees/plan-3-luxaeterna-epoch-7feab3` (branch `claude/plan-3-luxaeterna-epoch-7feab3`, fast-forwarded to main at PR #83).

**Spec:** mm-terrarium `docs/superpowers/specs/2026-09-01-per-fixture-light-sessions-design.md`, section 7 ("luxaeterna: render at O2 time"), plus the handoff `docs/superpowers/handoffs/2026-09-01-rooms-catalog-and-o2-time-handoff.md`, "Scope of Plan 3". Both are on mm-terrarium `main` as of PR #83.

## Global Constraints

- Tests run ONLY through the worktree's venv symlink: `.venv/bin/python -m pytest tests -q` from the worktree root. Both worktrees already carry the symlink. Baselines: luxaeterna 251 passed; mm-terrarium 1986 passed, 1 skipped.
- No em dashes in anything authored (code comments, docstrings, docs, commit messages). Use `--` where a dash is wanted; luxaeterna's existing files also use the real em dash character in old docstrings, leave those alone but never add one.
- First-frame `dt` stays "a small positive constant, as today" (spec section 7): the value is `1e-6`, exactly what `max(now - now, 1e-6)` produced before.
- `t` is the injected clock's reading, unmodified. No offset, no capture of a first reading anywhere in `LightSession`.
- No ugen changes. If a task's test reveals a ugen that reads `ctx.time` as elapsed-since-start, STOP and report; it is a design finding, not something to patch quietly.
- Commit messages follow the repo's conventional style (`feat(synth): ...`, `test(synth): ...`, `docs: ...`). No attribution lines.
- The luxaeterna worktree's `.venv` is a symlink excluded via `.git/info/exclude`; never `git add -A`. Add files by name.

---

### Task 1: `t` is the clock reading

**Files:**
- Modify: `luxaeterna/synth/session.py:29-40` (constructor) and `:97-117` (`render_into`)
- Test: `tests/synth/test_session.py`

**Interfaces:**
- Consumes: `LightSession(cap, clock=...)`, `render_into(universe)`, `LightEngine.render_into(universe, bindings, t, dt, frame, gain)` (unchanged signatures).
- Produces: the contract later tasks pin: for a session whose clock returns `c` on a given `render_into` call, the engine receives `t == c`; the first call receives `dt == 1e-6`; every later call receives `dt == max(c - previous_c, 1e-6)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/synth/test_session.py`:

```python
def _probe(session):
    """Wrap the engine so each render_into records the (t, dt) the session
    handed it. The engine is the only consumer of t, so this is the seam
    that observes the session's clock contract without a ugen in the way."""
    seen = []
    real = session._engine.render_into

    def spy(universe, bindings, t, dt, frame, gain=1.0):
        seen.append((t, dt))
        return real(universe, bindings, t, dt, frame, gain)

    session._engine.render_into = spy
    return seen


def test_t_is_the_clock_reading_not_elapsed_since_first_render():
    cap = shroom_capability("ie3")
    clk = iter([1000.0, 1000.02, 1000.04]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    assert [t for t, _ in seen] == [1000.0, 1000.02, 1000.04]


def test_two_sessions_first_rendered_at_different_readings_agree_on_t():
    # The property the change exists for: mm-terrarium builds one session
    # per Room fixture, each first rendered at a slightly different instant,
    # and all of them must read the same t for the same clock value.
    cap = shroom_capability("ie3")
    a = LightSession(cap, clock=iter([10.0, 900.0]).__next__)
    b = LightSession(cap, clock=iter([500.0, 900.0]).__next__)
    seen_a, seen_b = _probe(a), _probe(b)
    uni = Universe()
    a.render_into(uni); b.render_into(uni)      # construction skew
    a.render_into(uni); b.render_into(uni)      # the same clock value
    assert seen_a[1][0] == seen_b[1][0] == 900.0


def test_first_frame_dt_is_the_small_constant_and_later_dt_is_the_delta():
    cap = shroom_capability("ie3")
    clk = iter([1000.0, 1000.02, 1000.05]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    dts = [dt for _, dt in seen]
    assert dts[0] == 1e-6
    assert abs(dts[1] - 0.02) < 1e-9
    assert abs(dts[2] - 0.03) < 1e-9


def test_a_stalled_clock_never_yields_a_zero_dt():
    # A frozen or backwards clock (a hub restart resets o2lite time) must
    # not hand ugens dt == 0 or a negative dt: Smooth divides by tau and
    # SegmentLevel integrates dt, so the floor is what keeps them sane.
    cap = shroom_capability("ie3")
    clk = iter([50.0, 50.0, 49.0]).__next__
    session = LightSession(cap, clock=clk)
    seen = _probe(session)
    uni = Universe()
    for _ in range(3):
        session.render_into(uni)
    assert [dt for _, dt in seen] == [1e-6, 1e-6, 1e-6]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/synth/test_session.py -q -k "clock_reading or agree_on_t or small_constant or stalled_clock"`
Expected: the first two FAIL (`t` currently reads `0.0`, `0.02`, ... and `890.0 != 400.0`); the `dt` tests PASS already (they pin behavior that must survive the change).

- [ ] **Step 3: Make the change**

In `luxaeterna/synth/session.py`, replace the two constructor lines

```python
        self._start: float | None = None
        self._last: float | None = None
```

with

```python
        self._last: float | None = None    # previous clock reading, for dt
```

and replace the head of `render_into`

```python
    def render_into(self, universe) -> None:
        now = self._clock()
        if self._start is None:
            self._start = now
            self._last = now
        t = now - self._start
        dt = max(now - self._last, 1e-6)
        self._last = now
```

with

```python
    def render_into(self, universe) -> None:
        # t is the injected clock's own reading, not elapsed time since this
        # session's first frame. Every session handed the same clock (every
        # Room fixture session on a Terrarium, in o2lite mode) therefore
        # agrees on t, which is what lets one rainbow declaration paint a
        # continuous gradient across fixtures rendered by different
        # sessions. Anything that needs a local origin integrates dt
        # (Envelope, SegmentLevel, Smooth, the status signatures); nothing
        # may assume t starts near zero.
        now = self._clock()
        if self._last is None:
            dt = 1e-6                        # first frame: no previous read
        else:
            dt = max(now - self._last, 1e-6)  # floor: stalled or reset clock
        self._last = now
        t = now
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 255 passed (251 + 4). Every pre-existing session test uses a clock starting at `0.0`, so their `t` sequence is byte-identical before and after.

- [ ] **Step 5: Commit**

```bash
git add luxaeterna/synth/session.py tests/synth/test_session.py
git commit -m "feat(synth): render_into hands ugens the clock reading as t, not time since first frame"
```

---

### Task 2: the audit, pinned by tests

**Files:**
- Test: `tests/synth/test_control_ugens.py`, `tests/synth/test_field_ugens.py`, `tests/synth/test_status.py`, `tests/synth/test_session.py`

**Interfaces:**
- Consumes: Task 1's contract (`t` is the clock reading). `RenderContext(time, frame, dt, positions, n, channels)` from `luxaeterna/synth/signal.py`. The `ctx(...)` helpers already defined at the top of each ugen test file: `test_control_ugens.py` has `ctx(frame, time=0.0, dt=1/44, n=4, channels=3)`, `test_field_ugens.py` has `ctx(frame=0, n=8, channels=3, time=0.0, dt=1/44)`, `test_status.py` has `_ctx(f, dt=0.05, n=12, ch=3)`.
- Produces: nothing new in code. The tests are the deliverable: a future ugen that reads `ctx.time` as elapsed time fails here.

- [ ] **Step 1: Pin the dt-integrators (control rate)**

Append to `tests/synth/test_control_ugens.py`:

```python
def _run(ugen, times, dt=1 / 44):
    return [float(ugen.render(ctx(f, time=t, dt=dt))) for f, t in enumerate(times)]


def test_dt_integrators_ignore_absolute_time():
    # Since the session hands ugens the raw clock reading as t (large, and
    # never starting at zero), anything with a local origin must build it
    # from dt alone. Same dt sequence at t near zero and at t = 1e6 must
    # produce byte-identical output for every dt-integrating control ugen.
    n = 30
    near = [f / 44 for f in range(n)]
    far = [1e6 + f / 44 for f in range(n)]

    def fresh():
        s = Smooth(Const(0.0), tau=0.1)
        e = Envelope(attack=0.1, decay=0.1, sustain=0.5, release=0.2)
        e.gate_on()
        return s, e

    s1, e1 = fresh()
    s1.set_target(1.0)
    s2, e2 = fresh()
    s2.set_target(1.0)
    assert _run(s1, near) == _run(s2, far)
    assert _run(e1, near) == _run(e2, far)


def test_time_readers_depend_only_on_absolute_time():
    # LFO reads ctx.time and nothing else: two instances agree at the same
    # t regardless of what either rendered before. This is the continuity
    # property at the ugen level.
    a = LFO("sine", hz=0.25)
    b = LFO("sine", hz=0.25)
    for f, t in enumerate([0.0, 0.5, 1.0]):
        a.render(ctx(f, time=t))
    va = float(a.render(ctx(3, time=1e6 + 0.3)))
    vb = float(b.render(ctx(0, time=1e6 + 0.3)))
    assert va == vb
```

- [ ] **Step 2: Pin the field-rate readers**

Append to `tests/synth/test_field_ugens.py` (add `Rainbow`, `SegmentLevel` to the existing `from luxaeterna.synth.ugens import (...)` line):

```python
def test_rainbow_and_noise_depend_only_on_absolute_time():
    # Two fresh instances at the same t are identical, and an instance that
    # rendered a different history first lands on the same frame. This is
    # what makes two fixture sessions sharing a clock paint one gradient.
    def rainbow():
        return Rainbow(Const(1.0), Const(0.0), span=1.0, speed=0.05)
    a, b = rainbow(), rainbow()
    for f, t in enumerate([0.0, 7.0, 99.0]):
        a.render(ctx(frame=f, time=t))
    fa = a.render(ctx(frame=3, time=518000.25))
    fb = b.render(ctx(frame=0, time=518000.25))
    assert np.array_equal(fa, fb)
    assert fa.max() > 0.0

    na, nb = Noise(Const([1, 1, 1]), scale=2.0, speed=3.0), Noise(Const([1, 1, 1]), scale=2.0, speed=3.0)
    for f, t in enumerate([0.0, 7.0]):
        na.render(ctx(frame=f, time=t))
    assert np.array_equal(na.render(ctx(frame=2, time=518000.25)),
                          nb.render(ctx(frame=0, time=518000.25)))


def test_segment_level_loop_is_local_time_not_absolute():
    # loop_from wraps the ugen's OWN integrated time. A large absolute t on
    # the first frame must not be read as "already past the end".
    def run(times, dt=0.5):
        lvl = SegmentLevel([(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)], loop_from=0.0)
        return [float(lvl.render(ctx(frame=f, time=t, dt=dt)))
                for f, t in enumerate(times)]
    near = [f * 0.5 for f in range(5)]
    far = [1e6 + f * 0.5 for f in range(5)]
    assert run(near) == run(far)
    assert abs(run(far)[-1] - 0.5) < 1e-6      # wrapped to local 0.5, as before
```

- [ ] **Step 3: Pin the status signatures**

Append to `tests/synth/test_status.py`:

```python
def test_signatures_advance_on_dt_and_render_the_same_at_any_absolute_time():
    # Welcome, loaded, error and the close fade all keep their own elapsed
    # clock from dt. A session whose first t is 1e6 (an O2 clock that has
    # been up for days) must play them exactly as one starting at zero.
    def play(name, offset, frames=40, dt=0.05):
        sig = registry.build(name)
        out = []
        for f in range(frames):
            sig.advance(dt)
            c = RenderContext(time=offset + f * dt, frame=f, dt=dt,
                              positions=np.linspace(0, 1, 12), n=12, channels=3)
            out.append((sig.gain, sig.done,
                        sig.render(c).copy() if sig.renders else None))
        return out

    for name in ("sys:loaded", "sys:error", "sys:closing", "sys:idle",
                 "sys:disconnected", "sys:selftest"):
        near, far = play(name, 0.0), play(name, 1e6)
        for (g1, d1, f1), (g2, d2, f2) in zip(near, far):
            assert (g1, d1) == (g2, d2), name
            if f1 is not None:
                assert np.array_equal(f1, f2), name
```

Note: `sys:identify` is deliberately left out of that loop. It renders `Noise`, which reads `ctx.time` by design (the sparkle scrolls with the shared clock), so its frames legitimately differ between the two offsets while its `gain`/`done` do not. If you want it covered, assert only the `(gain, done)` pair for it.

- [ ] **Step 4: Pin the whole lifecycle and the rainbow at the session level**

Append to `tests/synth/test_session.py`:

```python
RAINBOW_MANIFEST = {
    "bit_name": "cont", "instruments": [{
        "instrument": "rainbow", "target": "primary",
        # level declared so the breath is externally driven (a constant
        # here) rather than SegmentLevel's local clock, matching how
        # mm-terrarium's TestBit declares the Room rainbow.
        "params": {"hue": 0.0, "level": 1.0, "span": 1.0, "speed": 0.05},
    }],
    "welcome": {"instrument": "glow", "duration": 0.5},
}


def test_full_lifecycle_with_a_large_first_clock_reading():
    # An O2 clock that has been running for a long time before this session
    # was built: welcome (glow) -> running -> close fade -> idle must all
    # complete, because every signature keeps its own dt-integrated clock.
    cap = shroom_capability("ie3")
    clk = iter([1e6 + i * 0.02 for i in range(600)]).__next__
    session = build_session(LightManifest.from_dict(RAINBOW_MANIFEST), cap, clock=clk)
    uni = Universe()
    session.render_into(uni)
    assert session.state == "loading"
    _run_until(session, uni, "running")
    session.clear()
    session.render_into(uni)
    assert session.state == "closing"
    _run_until(session, uni, "idle")


def test_rainbow_frames_agree_across_sessions_at_the_same_clock_value():
    # Two sessions, first rendered 490 s apart (the construction skew two
    # Room fixtures have), both RUNNING, then rendered at the same clock
    # reading: byte-identical frames. Before this slice each session's
    # t started at zero at ITS first frame, so the two rainbows were offset
    # by 490 s of scroll.
    cap = shroom_capability("ie3")

    def running_session(first):
        clk = iter([first + i * 0.02 for i in range(200)] + [5000.0, 5000.02]).__next__
        s = build_session(LightManifest.from_dict(RAINBOW_MANIFEST), cap, clock=clk)
        u = Universe()
        _run_until(s, u, "running")
        return s, u

    a, ua = running_session(10.0)
    b, ub = running_session(500.0)
    # Drain each schedule to its 5000.0 entry so both render at the same
    # clock reading. The session's _last is the previous clock read, which
    # is the cheapest honest way to know which entry was just consumed.
    for s, u in ((a, ua), (b, ub)):
        while s._last != 5000.0:
            s.render_into(u)
    assert ua.get_frame()[:36] == ub.get_frame()[:36]
    assert max(ua.get_frame()[:36]) > 0
    # And it is not a constant frame: one more tick (5000.02) moves the hue.
    a.render_into(ua)
    assert ua.get_frame()[:36] != ub.get_frame()[:36]
```

- [ ] **Step 5: Run the suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 262 passed (255 + 7). If `test_rainbow_frames_agree_across_sessions_at_the_same_clock_value` fails on the equality, first check that both sessions reached `running` with the same `(gain)`: `_run_until` returns on the first frame in `running`, and the close of `sys:loaded`/welcome sets gain to 1.0, so the frames differ only if some ugen kept absolute-time state. That would be an audit finding: stop and report per the Global Constraints.

- [ ] **Step 6: Commit**

```bash
git add tests/synth/test_control_ugens.py tests/synth/test_field_ugens.py tests/synth/test_status.py tests/synth/test_session.py
git commit -m "test(synth): pin the clock contract: dt-integrators ignore absolute t, time readers agree across sessions"
```

---

### Task 3: luxaeterna docs and the cross-repo verification

**Files:**
- Modify: `luxaeterna/synth/session.py:1-10` (module docstring)
- Modify: `luxaeterna/synth/engine.py:34-40` (class docstring)
- Modify: `docs/deployment.md` (one short paragraph, placed after the line-128 paragraph that ends "That design is unchanged by anything here.")

**Interfaces:**
- Consumes: Tasks 1 and 2 complete on the luxaeterna branch.
- Produces: the verified statement that mm-terrarium's suite is green against this branch, recorded in the PR description by Task 4.

- [ ] **Step 1: Document the clock contract where a reader looks for it**

In `luxaeterna/synth/session.py`, extend the module docstring by appending, before the closing `"""`:

```
Time: render_into hands ugens the injected clock's reading as t, unmodified;
dt is the delta since the previous read (first frame 1e-6). Sessions that
share a clock agree on t, so a phase-from-time instrument (rainbow, LFO,
noise) is continuous across sessions. Anything needing a local origin
integrates dt; t never starts near zero and must not be assumed to.
```

In `luxaeterna/synth/engine.py`, change the docstring sentence

```
    Timing (t/dt/frame) is supplied by the caller — the LightSession owns the
    clock.
```

to

```
    Timing (t/dt/frame) is supplied by the caller — the LightSession owns the
    clock, and t is that clock's raw reading (shared across every session on
    the same clock), not seconds since this engine's first frame.
```

In `docs/deployment.md`, append this paragraph after the paragraph that ends "That design is unchanged by anything here.":

```
One timing fact matters in every deployment row above: `render_into` passes
the injected clock's reading straight through as `t`. On a Terrarium that
clock is `o2lite.time_get`, injected by Control into every fixture session,
so a `rainbow` declared on `primary` across two fixtures scrolls as one
gradient even though each fixture has its own session. Instruments that
need a local origin (envelopes, segment levels, the status signatures)
integrate `dt` instead; `t` starts wherever the clock is, never at zero.
```

- [ ] **Step 2: Run luxaeterna's suite**

Run: `.venv/bin/python -m pytest tests -q`
Expected: 262 passed.

- [ ] **Step 3: Verify mm-terrarium against this branch**

**RUN ON: MYCOLOGICAL** (any dev box with both checkouts):

```bash
cd /Users/chris/projects/mm-terrarium/.claude/worktrees/plan-3-luxaeterna-epoch-7feab3 && PYTHONPATH=/Users/chris/projects/luxaeterna/.claude/worktrees/session-o2-time-7feab3 .venv/bin/python -c "import luxaeterna; print(luxaeterna.__file__)"
```

Expected: the printed path is under `.claude/worktrees/session-o2-time-7feab3`. If it prints the main checkout instead, the editable finder took precedence; in that case run the suite from a shell where `PYTHONPATH` is set and confirm with `python -c "import sys; print(sys.meta_path)"`, or temporarily `git checkout claude/session-o2-time-7feab3` in the main luxaeterna checkout. Do not proceed on a wrong path.

```bash
cd /Users/chris/projects/mm-terrarium/.claude/worktrees/plan-3-luxaeterna-epoch-7feab3 && PYTHONPATH=/Users/chris/projects/luxaeterna/.claude/worktrees/session-o2-time-7feab3 .venv/bin/python -m pytest tests -q 2>&1 | tail -3
```

Expected: `1986 passed, 1 skipped`. mm-terrarium's fake clocks start at `0.0` or `1000.0` and no test asserts an absolute rainbow hue, so nothing there pins the old epoch. Any failure is a real finding: record which test and why in the task report before touching anything.

- [ ] **Step 4: Commit**

```bash
git add luxaeterna/synth/session.py luxaeterna/synth/engine.py docs/deployment.md
git commit -m "docs(synth): state the clock contract: t is the shared clock reading, local origins integrate dt"
```

---

### Task 4: mm-terrarium documents that said Plan 3 was not started

**Files (all in the mm-terrarium worktree `/Users/chris/projects/mm-terrarium/.claude/worktrees/plan-3-luxaeterna-epoch-7feab3`):**
- Modify: `tests/test_devicelink_agent.py:1717-1718` (docstring)
- Modify: `docs/superpowers/specs/2026-09-01-per-fixture-light-sessions-design.md` section 12 (the "Plan 3 ... is not started" paragraph and the checklist sentence)
- Modify: `docs/MM_TERRARIUM.md:3699-3700` (the "Plan 3 ... has not started" sentence) and the *Relationships to other repos* luxaeterna paragraph near line 3864
- Modify: `docs/superpowers/handoffs/2026-09-01-rooms-catalog-and-o2-time-handoff.md` (Plan 3 section header and lead)

**Interfaces:**
- Consumes: the luxaeterna PR number, once Task 3's branch is pushed and its PR opened (the orchestrator supplies it; write `luxaeterna PR #<N>` with the real number).
- Produces: a docs-only mm-terrarium commit on `claude/plan-3-luxaeterna-epoch-7feab3`.

- [ ] **Step 1: Fix the docstring drift**

In `tests/test_devicelink_agent.py`, replace

```
    because RenderContext.time is derived from the injected clock
    (luxaeterna's LightSession.render_into: t = now - self._start), so a
    frozen clock yields byte-identical output regardless of which
```

with

```
    because RenderContext.time IS the injected clock's reading
    (luxaeterna's LightSession.render_into: t = now, since its O2-time
    slice; before that, t = now - self._start), so a
    frozen clock yields byte-identical output regardless of which
```

- [ ] **Step 2: Spec section 12**

Replace

```
Plan 3 (section 7, luxaeterna rendering at O2 time) is not started. The
interrupt contract (section 8) remains a named follow-up slice, not part
of either.
```

with

```
Plan 3 (section 7, luxaeterna rendering at O2 time) landed 2026-09-02 as
luxaeterna PR #<N> (branch `claude/session-o2-time-7feab3`):
`LightSession.render_into` passes the clock reading through as `t`, `dt`
is unchanged (first frame `1e-6`). The audit found no ugen or director
state that assumed `t` starts at zero: only `LFO`, `Rainbow` and `Noise`
read `ctx.time`, and each is a phase-from-absolute-time generator; every
local-origin unit integrates `dt`. The audit is pinned by tests rather
than by code changes. mm-terrarium's 1986-test suite was run against that
branch and stayed green; no Control-side change was needed. The
interrupt contract (section 8) remains a named follow-up slice.
```

and change `step 5 (rainbow continuity across fixtures) waits on Plan 3.` to `step 5 (rainbow continuity across fixtures) is unblocked by Plan 3 and still unrun.`

- [ ] **Step 3: Deep-dive**

In `docs/MM_TERRARIUM.md`, replace `Plan 3 (luxaeterna rendering at O2 time) has not\n  started.` (the sentence ending the "Rooms catalog" entry's deferred-minors paragraph) with:

```
Plan 3 (luxaeterna rendering at O2 time) landed 2026-09-02 as
  luxaeterna PR #<N>; see the luxaeterna note under *Relationships to
  other repos*.
```

Then, in the *Relationships to other repos* section, after the sentence ending `now fails loudly in luxaeterna instead of silently truncating pixels.`, append to that same bullet:

```
  A third fact, from luxaeterna PR #<N> (2026-09-02, Plan 3 of the
  per-fixture light sessions spec): `LightSession.render_into` hands ugens
  the injected clock's reading as `t`, not seconds since that session's
  first frame. Every fixture session this repo builds shares
  `DeviceLinkAgent`'s clock (`o2lite.time_get` in o2lite mode), so a
  `rainbow` on `primary` scrolls as one gradient across `main` and
  `accent` instead of two ramps offset by their construction skew. Nothing
  Control-side changed; the live checklist's step 5 (rainbow continuity,
  measured off the canvases) is now runnable.
```

- [ ] **Step 4: Handoff**

In the handoff, change the header `## Scope of Plan 3: luxaeterna renders at O2 time (spec section 7, luxaeterna repo)` to end with ` -- DONE` and insert as its first paragraph:

```
**Landed** 2026-09-02 as luxaeterna PR #<N> (branch
`claude/session-o2-time-7feab3`, plan
`docs/superpowers/plans/2026-09-02-session-o2-time.md` in that repo).
The paragraph below is the scope it was planned against; the audit found
nothing to change beyond `render_into` and is pinned by tests. Spec
section 10 step 5 is unblocked and still unrun.
```

Also change line 15's `**Plan 3 (luxaeterna renders at O2 time) remains the scope of this handoff**` to `**Plan 3 (luxaeterna renders at O2 time) is done too; only the live checklists remain**`.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/python -m pytest tests -q 2>&1 | tail -1` (from the mm-terrarium worktree; no code changed, this only proves the docstring edit did not break the file).
Expected: `1986 passed, 1 skipped`.

```bash
git add tests/test_devicelink_agent.py docs/superpowers/specs/2026-09-01-per-fixture-light-sessions-design.md docs/MM_TERRARIUM.md docs/superpowers/handoffs/2026-09-01-rooms-catalog-and-o2-time-handoff.md
git commit -m "docs: Plan 3 (luxaeterna O2 time) landed; spec status, deep-dive note, handoff, docstring drift"
```

---

## Live verification (not part of this plan's tasks; for the operator)

Spec section 10 step 5, unchanged: with the luxaeterna PR installed in mm-terrarium's `.venv` (an editable install of `main` after merge, or `PYTHONPATH` at the branch), load TEST, spawn both simulators, and measure hue slope per pixel off both canvases as in the 2026-08-19 check. Equal slope and `accent` continuing `main`'s ramp is the pass. **RUN ON: MYCOLOGICAL.**
