from __future__ import annotations

from api.services import retrieve


def test_github_link_rewrites_to_local_route() -> None:
    html = retrieve._linkify_text("See https://github.com/a/b/issues/5")  # noqa: SLF001
    assert '<a href="/gh/a/b/issues/5"' in html


def test_jira_link_rewrites_to_local_route() -> None:
    html = retrieve._linkify_text("https://x.atlassian.net/browse/ABC-42 fix")  # noqa: SLF001
    assert '<a href="/jira/x/ABC/ABC-42"' in html


def test_external_links_keep_rel_attributes() -> None:
    html = retrieve._linkify_text("Visit https://example.com/docs")  # noqa: SLF001
    assert 'rel="nofollow noopener noreferrer"' in html
