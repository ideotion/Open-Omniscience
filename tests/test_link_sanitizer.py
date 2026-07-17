"""
Tests for the newsletter link sanitiser (recipient protection).

The sanitiser is pure and network-free: it strips recipient-identifying tracker
parameters, unwraps redirect wrappers whose destination is embedded in the URL,
and flags (without trusting) wrappers that resolve their destination server-side.
"""

from __future__ import annotations

from urllib.parse import quote

from src.privacy.link_sanitizer import (
    RECIPIENT_PARAMS,
    sanitize_text,
    sanitize_url,
)


def test_strips_recipient_params_keeps_others():
    s = sanitize_url("https://news.example/article?id=42&mc_eid=ABC123&utm_source=nl&ref=home")
    assert "mc_eid" not in s.url
    assert "utm_source" not in s.url
    assert "id=42" in s.url
    assert "ref=home" in s.url
    assert "mc_eid" in s.stripped_params


def test_marketo_mkt_tok_is_recipient_param():
    assert "mkt_tok" in RECIPIENT_PARAMS
    s = sanitize_url("https://example.com/page?mkt_tok=eyJsZWFkIjoxfQ&x=1")
    assert "mkt_tok" not in s.url
    assert "x=1" in s.url


def test_unwraps_embedded_destination_and_cleans_it():
    real = "https://publisher.example/story?mc_eid=SECRET&p=1"
    wrapped = "https://click.tracker.example/redirect?url=" + quote(real, safe="")
    s = sanitize_url(wrapped)
    assert s.unwrapped is True
    assert s.url.startswith("https://publisher.example/story")
    # the destination's own recipient token is stripped on the way through
    assert "mc_eid" not in s.url
    assert "p=1" in s.url


def test_unwraps_base64_encoded_destination():
    import base64

    real = "https://dest.example/x"
    token = base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    s = sanitize_url(f"https://u123.ct.sendgrid.net/ls/click?upn={token}")
    assert s.unwrapped is True
    assert s.url == real


def test_path_embedded_destination_is_recovered():
    s = sanitize_url("https://link.tracker.example/CL0/https://real.example/article/1/abcd")
    assert s.unwrapped is True
    assert s.url.startswith("https://real.example/article")


def test_opaque_mailchimp_wrapper_is_flagged_not_trusted():
    # Mailchimp resolves the destination server-side; the path is recipient-keyed.
    url = "https://news.us1.list-manage.com/track/click?u=abc&id=def&e=RECIPIENT"
    s = sanitize_url(url)
    assert s.tracker_wrapped is True
    assert s.url == "https://news.us1.list-manage.com"  # token-bearing path dropped
    assert "RECIPIENT" not in s.url


def test_non_http_scheme_left_untouched():
    s = sanitize_url("mailto:editor@news.example?subject=hi")
    assert s.url == "mailto:editor@news.example?subject=hi"
    assert s.tracker_wrapped is False


def test_sanitize_text_rewrites_inline_links_and_counts():
    body = (
        "Read more at https://news.example/a?mc_eid=ZZZ&id=7 and click "
        "https://x.us2.list-manage.com/track/click?e=ME here. Plain "
        "https://ok.example/page stays."
    )
    out, stats = sanitize_text(body)
    assert "mc_eid" not in out
    assert "ME" not in out  # recipient token in the wrapped link is gone
    assert "[tracked link -> https://x.us2.list-manage.com]" in out
    assert "https://ok.example/page" in out
    assert stats.links_seen == 3
    assert stats.params_stripped >= 1
    assert stats.trackers_wrapped == 1


def test_sanitize_text_preserves_trailing_punctuation():
    out, _ = sanitize_text("See (https://ok.example/p?utm_source=x).")
    assert "https://ok.example/p" in out
    assert out.rstrip().endswith(").")
    assert "utm_source" not in out


def test_malformed_embedded_destination_does_not_crash():
    """Field bug 2026-07-16: a redirect wrapper whose recovered destination looks
    like a malformed IPv6-literal URL (a plausible real-world sender encoding bug,
    not just adversarial input) made ``urlsplit`` raise ``ValueError`` inside the
    recursive unwrap call -- crashing the whole ``sanitize_text`` call and, one
    layer up, the caller's entire batch (``ingest_emails`` loses every already-
    parsed message in the current uncommitted batch on a single bad link).
    Reproduced directly against this exact input before the fix; must not raise,
    and must not silently drop the rest of the text either."""
    bad_dest = "http://[bad-ipv6-not-closed/x"
    wrapper = "https://tracker.example.com/click?url=" + quote(bad_dest, safe="")
    text = f"Check this out: {wrapper} for more info."

    # The public single-URL entry point must not raise either.
    s = sanitize_url(wrapper)
    assert s.url  # some string came back, whatever it is -- never an exception

    out, stats = sanitize_text(text)
    assert "for more info." in out  # the rest of the message survives
    assert stats.links_seen == 1


def test_a_second_legitimate_link_in_the_same_text_still_sanitises_after_a_bad_one():
    """The malformed link must not poison sibling links processed in the same
    ``sanitize_text`` call (a realistic shape: one bad link + one good one in the
    same email body)."""
    bad_dest = "http://[bad-ipv6-not-closed/x"
    wrapper = "https://tracker.example.com/click?url=" + quote(bad_dest, safe="")
    good = "https://publisher.example/story?mc_eid=SECRET&p=1"
    out, stats = sanitize_text(f"Bad: {wrapper} Good: {good}")
    assert stats.links_seen == 2
    assert "mc_eid" not in out  # the legitimate link was still sanitised
    assert "publisher.example/story" in out


def test_embedded_in_path_variant_of_the_same_malformed_destination():
    """The path-embedded recovery route (``_embedded_in_path``, distinct code path
    from the query-parameter route) must be equally hardened."""
    bad_dest = "http://[bad-ipv6-not-closed/x"
    wrapper = "https://tracker.example.com/redirect/" + quote(bad_dest, safe="")
    s = sanitize_url(wrapper)
    assert s.url  # never raises
