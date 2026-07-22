# tests/synth/fakes.py
"""FakeO2Lite — mirrors the VERIFIED o2litepy API (rbdannenberg/o2 and the
copy vendored in rbdannenberg/arco@498e4ab):

- method_new(path, typespec, full, handler, info): 5 required args,
  append-only handler list, no removal API.
- dispatch: first match in registration order wins; handler is called
  handler(address, types, info); payload is pulled via get_int32().

If our attach() drifts from the real contract, tests using this fake fail the
way real hardware would."""

from __future__ import annotations


class FakeO2Lite:
    def __init__(self):
        self.handlers = []          # list of (path, typespec, full, handler, info)
        self._msg_int = None

    def method_new(self, path, typespec, full, handler, info):
        self.handlers.append((path, typespec, full, handler, info))

    def get_int32(self):
        v = self._msg_int
        self._msg_int = None
        return v

    def deliver(self, address, typespec, value):
        """Simulate an inbound message: first-match dispatch, real convention."""
        for (path, ts, full, handler, info) in self.handlers:
            if full and path == address and (ts is None or ts == typespec):
                self._msg_int = value
                handler(address, typespec, info)
                return
        # real o2litepy prints and drops unmatched messages
