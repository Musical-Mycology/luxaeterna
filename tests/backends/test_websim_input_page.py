"""The page's input handlers, tested as behavior rather than as text.

Same wrapper shape as test_websim_layout.py: extract the <script> body
from PAGE_HTML so the served page stays the single source of truth."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from luxaeterna.backends.websim import PAGE_HTML

RUNNER = Path(__file__).resolve().parents[1] / "js" / "websim_input.test.js"


def _page_script() -> str:
    match = re.search(r"<script>(.*)</script>", PAGE_HTML, re.S)
    assert match, "PAGE_HTML no longer contains a single <script> block"
    return match.group(1)


def test_page_declares_input_handlers():
    script = _page_script()
    assert "onpointerdown" in script
    assert "ondblclick" in script


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_page_input_behaviour():
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
