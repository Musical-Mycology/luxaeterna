"""The served page's layout, tested as behavior rather than as text.

PAGE_HTML's only previous coverage was test_page_is_self_contained_canvas, a
substring grep, which cannot see that 852 of an 864-pixel surface were being
drawn off-canvas. This runs the page's real script under Node's vm against a
canvas stub. Mirrors the pattern mm-terrarium adopted (tests/js/ driven from a
pytest wrapper) after its Room panel shipped a rebuild defect past 843 passing
tests: a grep over source text is not a test of behavior.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from luxaeterna.backends.websim import PAGE_HTML

RUNNER = Path(__file__).resolve().parents[1] / "js" / "websim_layout.test.js"


def _page_script() -> str:
    """The page's <script> body, so the served page is the single source of
    truth and the tests cannot drift from what browsers actually receive."""
    match = re.search(r"<script>(.*)</script>", PAGE_HTML, re.S)
    assert match, "PAGE_HTML no longer contains a single <script> block"
    return match.group(1)


def test_page_script_is_extractable():
    """Guards the wrapper itself: if PAGE_HTML is restructured so the regex
    stops matching, fail here with a clear reason rather than silently
    handing node an empty file that passes every assertion vacuously."""
    assert "function pos(" in _page_script()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_layout_behaviour():
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
        handle.write(_page_script())
        script_path = handle.name
    try:
        proc = subprocess.run(
            ["node", str(RUNNER), script_path],
            capture_output=True, text=True, timeout=60,
        )
    finally:
        Path(script_path).unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
