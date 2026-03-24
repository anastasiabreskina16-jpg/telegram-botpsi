from __future__ import annotations

import html


def test_html_escape() -> None:
    name = "<b>hack</b>"
    safe = html.escape(name)
    assert safe == "&lt;b&gt;hack&lt;/b&gt;"
