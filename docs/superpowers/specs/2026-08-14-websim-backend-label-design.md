# `WebSimBackend` gets a `label` — telling a Room canvas from a player canvas

Date: 2026-08-14
Status: design approved, pending implementation plan
Primary repo: **luxaeterna** (renderer). Follow-up: **mm-terrarium** (two harness call sites).

## 1. Why this exists

mm-terrarium's `harness/room_simulator.py` and `harness/o2_shroom.py --no-join` both
render a Room simulator into luxaeterna's `WebSimBackend` — a browser-canvas Shroom
served over the same code path a real player device's own `WebSimBackend` canvas uses
(`harness/o2_shroom.py`'s normal, joining mode). Both pages currently show the exact
same generic browser tab and `<title>`, so an operator with two tabs open — one
watching the Room, one watching a player device — has no way to tell which is which
without cross-referencing which process they started.

### Root cause

`luxaeterna/backends/websim.py`'s `PAGE_HTML` module constant hardcodes
`<title>Lux Aeterna — Shroom LED Simulator</title>` (`websim.py:16`) with no parameter
to customize it. `WebSimBackend.__init__` (`websim.py:78-80`) takes `capability`,
`host`, `port`, `serve` — nothing that reaches the served HTML.

## 2. Goal & success criteria

Let a `WebSimBackend` caller optionally stamp an identifying label into the served
page's title, so two simultaneously-open canvases are visually distinguishable in
their browser tabs.

- `WebSimBackend(..., label="sim-room")` serves a page whose `<title>` reads
  `Lux Aeterna — Shroom LED Simulator — sim-room`.
- `WebSimBackend(...)` with no `label` (every existing caller, unchanged) serves
  **exactly** today's title — byte-identical, so `test_page_is_self_contained_canvas`
  and every other existing assertion keeps passing with no edits.
- A label containing HTML-significant characters cannot break or inject into the
  served markup.

## 3. Non-goals (scope boundary)

- **No change to `PAGE_HTML`'s structure, styling, or script.** Only the `<title>`
  text changes, and only when a label is supplied.
- **No change to the capability handshake, websocket protocol, or `capability_message`.**
  The label is a static page-load-time string, not runtime state pushed over the
  websocket.
- **No new backend-wide "identity" concept.** This is a display label for a human
  glancing at browser tabs, not a device id the backend tracks or exposes to clients.
- **No change to the other DMX backends** (`ArtNet`, `SACN`, `ENTTECOpen`/`Pro`).
  `SACN.source_name` is precedent for the naming/docstring convention only, not a
  shared interface — those backends have no served page to label.

## 4. Architecture

Entirely additive inside `websim.py`. Data flow is unchanged; only what
`_process_request` serves for the non-`/ws` path changes, and only per-instance:

```
WebSimBackend(label=...)
        │  __init__ computes self._page_html once
        ▼
label is None  ──▶  self._page_html = PAGE_HTML                 (module constant, untouched)
label is set   ──▶  self._page_html = PAGE_HTML with <title> line
                     rewritten to append "— {html.escape(label)}"
        │
        ▼
_process_request()  serves  self._page_html.encode("utf-8")   (was: PAGE_HTML.encode(...))
```

## 5. Component design

### 5.1 `WebSimBackend.__init__` — new `label` parameter

```python
def __init__(self, capability: SurfaceCapability | None = None,
             host: str = "127.0.0.1", port: int = 0,
             serve: bool = True, label: str | None = None) -> None:
```

- Appended as the last keyword parameter, after `serve` — matches the existing
  parameter order and keeps every current positional/keyword call site valid.
- `label: str | None = None`, defaulting to no label (today's behavior).

### 5.2 Class docstring, following `SACN`'s convention

`WebSimBackend` currently has no class docstring (only the module docstring at
`websim.py:1-4`). Add one in the same NumPy-style `SACN` (`sacn.py:23-35`) already
uses, documenting `label` alongside the existing four parameters:

```python
class WebSimBackend(DMXBackend):
    """Record DMX frames and, when serving, stream them to a self-contained
    browser canvas — an on-screen LED simulator for the canonical Shroom.

    Parameters
    ----------
    capability : SurfaceCapability or None
        Pixel geometry/zones sent in the connect-time handshake. Defaults to
        ``shroom_capability()``.
    host : str
        Address to bind the websocket/HTTP server to.
    port : int
        Port to bind to (0 = OS-assigned, read back via ``.port``).
    serve : bool
        If False, frames are recorded only — no server, no port, headless.
    label : str or None
        Optional identifying text appended to the served page's ``<title>``,
        e.g. ``"sim-room"`` or a device id — lets an operator tell two open
        browser tabs apart. ``None`` (default) leaves the title unchanged.
        Stored verbatim on ``self.label`` for introspection.
    """
```

### 5.3 Storing `label` and building `self._page_html` once, in `__init__`

```python
self.label = label
self._page_html = PAGE_HTML if label is None else _labeled_page_html(label)
```

`self.label` is stored as a plain public attribute — matching `SACN.source_name`
(`sacn.py:46`, also a stored public attribute, not just consumed internally) — so a
caller or test can confirm what label a backend was constructed with without
inspecting `_page_html`/HTML at all.

A small module-level helper builds the actual HTML (kept out of `__init__` so it's
independently testable and keeps `__init__` free of string-munging):

```python
def _labeled_page_html(label: str) -> str:
    import html
    title = f"<title>Lux Aeterna — Shroom LED Simulator — {html.escape(label)}</title>"
    return PAGE_HTML.replace(
        "<title>Lux Aeterna — Shroom LED Simulator</title>", title, 1)
```

- `html.escape` guards against a label containing `<`, `&`, `"`, etc. — today's
  callers only ever pass simple dev-id strings (`"sim-room"`, `"ie1"`), but the
  backend itself has no way to constrain what a future caller passes, so escaping
  is cheap insurance rather than a real observed threat.
- Computed once at construction, not per-request — the label never changes after
  construction, so there's no reason to redo the string replace on every page load.
  `_process_request` (`websim.py:139-148`) changes its one line: serve
  `self._page_html` instead of the module-level `PAGE_HTML`.
- `.replace(..., 1)` with the exact today's-title string as the needle: if that
  string is ever absent (someone hand-edits `PAGE_HTML` and forgets this helper),
  `.replace` silently no-ops and the page serves with no label rather than raising.
  Acceptable here — a mislabeled dev tool's browser tab is not a failure mode worth
  hardening further, and the count-of-1 replace bounds the blast radius to exactly
  the title line even if the label text itself happened to contain the same
  substring.

## 6. Error handling & testing

No new error paths — `label` is either `None` or a string; there's nothing to
validate or reject. Testing:

- `tests/backends/test_websim.py` — new cases: `WebSimBackend(label="sim-room").label
  == "sim-room"`; the omitted-arg default leaves `backend.label is None` and
  `backend._page_html == PAGE_HTML` (byte-identical to today's page).
- `tests/backends/test_websim_serve.py` — extend `test_page_is_self_contained_canvas`
  style coverage with a new `test_label_appends_to_title`: construct with
  `label="sim-room"`, assert the served page's `<title>` contains both
  `"Shroom LED Simulator"` and `"sim-room"`. A second case with a label containing
  `<script>` (or similar) asserts it appears escaped, not as live markup.
- Existing `test_page_is_self_contained_canvas` and
  `test_client_receives_capability_then_frame` (both construct with no `label`)
  need no edits — confirms the default path is untouched.

## 7. Alternatives considered (and why rejected)

- **Make `PAGE_HTML` an f-string built fresh per instance.** Rejected: turns a
  simple, greppable constant into something that must be reconstructed carefully to
  stay byte-identical when unlabeled, for no benefit over a single targeted
  `.replace()` on the existing constant.
- **Interpolate the label in `_process_request` on every request** instead of once
  in `__init__`. Rejected: the label is fixed for the backend's lifetime: redoing
  the string work on every page load (including every reconnect) buys nothing.
- **Reuse `SACN`'s parameter name `source_name`.** Rejected: `source_name` is a
  wire-protocol field (E1.31's 64-byte, null-padded source name) with a real
  encoding constraint; `label` here is purely a display string with no protocol
  meaning. Different enough concepts that sharing the name would mislead more than
  it'd unify.

## 8. Decisions locked (from brainstorm)

- New parameter name: **`label: str | None = None`**, appended after `serve`, stored
  verbatim on **`self.label`** (public attribute, matching `SACN.source_name`).
- Rendering: **append**, not replace — `Lux Aeterna — Shroom LED Simulator — {label}`.
- Escaped via `html.escape`; computed once in `__init__`, not per-request.
- `PAGE_HTML` module constant stays as-is; a new `_labeled_page_html()` helper does
  the substitution only when a label is supplied.
- Two repos, sequenced: **luxaeterna first**, mm-terrarium second (mm-terrarium's
  editable install tracks this repo's checked-out state, so the follow-up needs
  this change merged/available before its own tests can exercise `label`).
