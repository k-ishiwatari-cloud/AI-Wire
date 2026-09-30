import http.client
import socket
import urllib.error
from types import SimpleNamespace

import pytest

from news_validation import (
    TITLE_SIMILARITY_THRESHOLD,
    check_url,
    extract_source_urls,
    find_similar_title,
    is_cited,
    normalize_url,
    title_similarity,
)


# ---- タイトル類似度 ----

def test_identical_titles_are_similar(recent_titles):
    title = "Google、Gemini 3.8 FlashをGA公開"
    assert title_similarity(title, title, recent_titles) == pytest.approx(1.0)


def test_japan_suffix_and_punctuation_are_ignored(recent_titles):
    a = "さくらインターネット、医療特化LLMを商用提供開始（Japan）"
    b = "さくらインターネット 医療特化LLMを商用提供開始"
    assert title_similarity(a, b, recent_titles) == pytest.approx(1.0)


def test_dart_duplicates_are_detected(recent_titles):
    existing = recent_titles + ["ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）"]
    hit = find_similar_title("NTTドコモ、少データ環境で高精度予測するDARTを発表", existing)
    assert hit is not None
    assert hit[0] == "ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）"
    assert hit[1] >= TITLE_SIMILARITY_THRESHOLD


def test_different_stories_from_same_company_are_not_duplicates(recent_titles):
    existing = recent_titles + ["ドコモ、少データ下でも高精度予測を実現するAI技術を確立（DART）"]
    assert find_similar_title("NTTドコモ、新聞活用の生成AIサービスを正式リリース", existing) is None
    assert find_similar_title("OpenAI、新しい音声モデルをAPIで提供開始", existing) is None


def test_find_similar_title_with_empty_corpus():
    assert find_similar_title("何かのニュース", []) is None


# ---- URL 正規化・引用元照合 ----

def test_normalize_url_ignores_fragment_tracking_trailing_slash_and_host_case():
    assert normalize_url("https://Example.com/a/b/?utm_source=x&id=3#top") == "https://example.com/a/b?id=3"
    assert normalize_url("https://example.com/") == "https://example.com"


def test_is_cited():
    sources = {"https://prtimes.jp/main/html/rd/p/000000922.000118641.html?utm_source=openai"}
    assert is_cited("https://prtimes.jp/main/html/rd/p/000000922.000118641.html", sources)
    assert not is_cited("https://www.docomo.ne.jp/info/news_release/topics/20260928_01.html", sources)


def _obj(**kw):
    return SimpleNamespace(**kw)


def test_extract_source_urls_from_search_sources_open_page_and_citations():
    resp = _obj(output=[
        _obj(type="web_search_call", action=_obj(type="search", sources=[
            _obj(type="url", url="https://a.example/1"),
            _obj(type="url", url="https://a.example/2"),
        ])),
        _obj(type="web_search_call", action=_obj(type="open_page", url="https://b.example/page")),
        _obj(type="web_search_call", action=_obj(type="search", sources=None)),
        _obj(type="reasoning"),
        _obj(type="message", content=[
            _obj(type="output_text", text="...", annotations=[
                _obj(type="url_citation", url="https://c.example/news"),
                _obj(type="file_citation"),
            ]),
        ]),
    ])
    assert extract_source_urls(resp) == {
        "https://a.example/1",
        "https://a.example/2",
        "https://b.example/page",
        "https://c.example/news",
    }


def test_extract_source_urls_accepts_dict_shaped_items():
    resp = {"output": [
        {"type": "web_search_call", "action": {"type": "search", "sources": [{"url": "https://d.example/x"}]}},
    ]}
    assert extract_source_urls(resp) == {"https://d.example/x"}


def test_extract_source_urls_without_output():
    assert extract_source_urls(_obj(output=None)) == set()


# ---- URL 到達確認 ----

class _Resp:
    def __init__(self, status=200):
        self.status = status

    def read(self, n=-1):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _raising(exc):
    def opener(req, timeout):
        raise exc
    return opener


def _http_error(code):
    return urllib.error.HTTPError("https://x.example", code, "err", {}, None)


def test_check_url_ok():
    assert check_url("https://x.example/a", opener=lambda req, timeout: _Resp()).ok


@pytest.mark.parametrize("code", [404, 410])
def test_check_url_rejects_not_found(code):
    result = check_url("https://x.example/a", opener=_raising(_http_error(code)))
    assert not result.ok
    assert str(code) in result.reason


@pytest.mark.parametrize("code", [401, 403, 429, 500, 503])
def test_check_url_tolerates_bot_blocking_and_server_errors(code):
    assert check_url("https://x.example/a", opener=_raising(_http_error(code))).ok


def test_check_url_rejects_dns_failure():
    exc = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
    assert not check_url("https://no-such-host.example/a", opener=_raising(exc)).ok


def test_check_url_tolerates_timeout():
    assert check_url("https://slow.example/a", opener=_raising(TimeoutError("timed out"))).ok
    exc = urllib.error.URLError(TimeoutError("timed out"))
    assert check_url("https://slow.example/a", opener=_raising(exc)).ok


def test_check_url_rejects_invalid_url_raised_by_http_client():
    assert not check_url("https://x.example/a", opener=_raising(http.client.InvalidURL("bad"))).ok


@pytest.mark.parametrize("url", [
    "https://openai.com/ja-JP/news/ (see 'Rapidly scaling online storage",
    "ftp://example.com/file",
    "example.com/no-scheme",
    "https://",
])
def test_check_url_rejects_malformed_urls_without_network(url):
    def opener(req, timeout):
        raise AssertionError("network must not be touched")
    assert not check_url(url, opener=opener).ok


# ---- レビュー指摘への回帰テスト ----

@pytest.mark.parametrize("a,b", [
    ("https://x.example/p?b=2&a=1", "https://x.example/p?a=1&b=2"),
    ("https://x.example:443/p", "https://x.example/p"),
    ("http://x.example/p", "https://x.example/p"),
    ("https://www.x.example/p", "https://x.example/p"),
    ("https://x.example./p", "https://x.example/p"),
])
def test_normalize_url_equivalents(a, b):
    assert normalize_url(a) == normalize_url(b)


def test_normalize_url_does_not_raise_on_broken_ipv6():
    normalize_url("http://[::1")


def test_check_url_rejects_broken_ipv6_without_raising():
    assert not check_url("http://[::1", opener=lambda req, timeout: _Resp()).ok


def test_check_url_closes_http_error():
    err = _http_error(404)
    closed = []
    err.close = lambda: closed.append(True)
    check_url("https://x.example/a", opener=_raising(err))
    assert closed


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://localhost/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/",
    "http://[::1]/",
    "http://user:pass@example.com/",
])
def test_check_url_rejects_internal_or_credentialed_targets(url, monkeypatch):
    """既定の opener は、接続前(リダイレクト先を含む)に内部アドレスを拒否する。"""
    def no_connect(*args, **kwargs):
        raise AssertionError("must not connect")
    monkeypatch.setattr(http.client.HTTPConnection, "connect", no_connect)
    assert not check_url(url).ok


def test_is_public_host_uses_resolved_addresses(monkeypatch):
    from news_validation import is_public_host
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("10.1.2.3", 0))])
    assert not is_public_host("evil.example")
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))])
    assert is_public_host("example.com")


def test_is_public_host_rejects_mixed_global_and_private(monkeypatch):
    from news_validation import is_public_host
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, port: [
        (None, None, None, None, ("93.184.216.34", 0)),
        (None, None, None, None, ("192.168.0.1", 0)),
    ])
    assert not is_public_host("mixed.example")


@pytest.mark.parametrize("newurl", [
    "ftp://127.0.0.1/secret",
    "file:///etc/passwd",
    "https://user:pass@example.com/",
])
def test_redirect_to_non_http_or_credentialed_url_is_blocked(newurl):
    import urllib.request
    from news_validation import _BlockedHost, _SafeRedirectHandler
    req = urllib.request.Request("https://public.example/a")
    with pytest.raises(_BlockedHost):
        _SafeRedirectHandler().redirect_request(req, None, 302, "Found", {}, newurl)


def test_redirect_to_private_http_host_is_blocked_by_request_hook(monkeypatch):
    """http(s) へのリダイレクトは許すが、遷移先リクエストも宛先検査を通る。"""
    import urllib.request
    from news_validation import _BlockedHost, _PublicHostOnlyHandler, _SafeRedirectHandler
    req = urllib.request.Request("https://public.example/a")
    new_req = _SafeRedirectHandler().redirect_request(req, None, 302, "Found", {}, "http://10.0.0.1/admin")
    assert new_req is not None
    with pytest.raises(_BlockedHost):
        _PublicHostOnlyHandler().http_request(new_req)


def test_blocked_redirect_closes_response():
    import urllib.request
    from news_validation import _BlockedHost, _SafeRedirectHandler
    closed = []
    fp = SimpleNamespace(close=lambda: closed.append(True))
    with pytest.raises(_BlockedHost):
        _SafeRedirectHandler().redirect_request(
            urllib.request.Request("https://public.example/a"), fp, 302, "Found", {}, "ftp://127.0.0.1/x")
    assert closed
