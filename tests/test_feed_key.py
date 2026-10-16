"""The feed half of a source's identity: one normaliser, and what it refuses to merge (row J, S05-10)."""

from __future__ import annotations

import pytest

from src.database.feed_key import FEED_KEY_MAX, feed_key


@pytest.mark.parametrize("empty", [None, "", "   ", "\n"])
def test_no_feed_is_the_empty_key(empty):
    assert feed_key(empty) == ""


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://Example.COM/rss", "http://example.com/rss"),  # scheme and host case
        ("https://example.com/rss/", "https://example.com/rss"),  # trailing slash
        ("https://example.com/rss#top", "https://example.com/rss"),  # fragment
        ("  https://example.com/rss  ", "https://example.com/rss"),
        ("example.com/rss", "https://example.com/rss"),  # no scheme
    ],
)
def test_spellings_of_one_feed_share_a_key(a, b):
    assert feed_key(a) == feed_key(b) != ""


@pytest.mark.parametrize(
    "a,b",
    [
        ("https://example.com/rss?cat=1", "https://example.com/rss?cat=2"),  # a query is part of the feed
        ("https://www.example.com/rss", "https://example.com/rss"),  # a host prefix is another server
        ("https://example.com/rss", "https://example.com/atom"),
        ("https://example.com/Rss", "https://example.com/rss"),  # a path is case-sensitive
    ],
)
def test_different_feeds_never_share_a_key(a, b):
    assert feed_key(a) != feed_key(b)


def test_it_never_raises_and_is_bounded():
    assert isinstance(feed_key("http://[bad"), str)  # a ValueError must not escape
    assert len(feed_key("https://example.com/" + "a" * 2000)) == FEED_KEY_MAX
    assert feed_key("https://example.com/rss") == feed_key(feed_key("https://example.com/rss"))
