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
    digest_reason,
    is_digest,
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


# ---- 他のまとめサイトのまとめ ----

@pytest.mark.parametrize("title, url", [
    ("10月23日付のAI短報アーカイブ（日次まとめ）", "https://metamesh.biz/archive/2026/10/23"),
    ("日次AIダイジェスト：10月18日の主要トピックまとめ", "https://aitimes.fyi/edition/2026-10-18"),
    ("週次AIまとめ：複数社で能力と安全性の議論が集中", "https://agihunt.info/en/daily/2026-09-04"),
    ("AI Tools Recap：エージェント関連の最新事例まとめ", "https://aitoolsrecap.com/ai-news-today"),
    ("エージェント関連の短報：最新の事例とインシデント追跡（総覧）", "https://agentnewsdaily.com/"),
    ("業界ダイジェスト：OpenAI訓練方針やエージェント事案の続報",
     "https://www.axios.com/newsletters/axios-ai-plus-112255f2-e25f-4dbf-a107-92126a1869ca"),
    ("24日付：日次AI概況（業界誌まとめ）", "https://aiuniversejournal.org/issues/2026-10-24/"),
    ("業界総覧：10月10–11日のAI短報", "https://ai0.news/posts/2026-10-11-daily-digest/"),
    ("エージェント群の外部投稿問題、調査報告が波紋に", "https://aibriefs.news/briefing/2026-09-12"),
    ("AIセキュリティ週次ブリーフ：エージェント・規制動向を整理", "https://eyeon.ai/feed?date=2026-10-09"),
    ("Hugging Face、エージェント関連の投稿を公開", "https://huggingface.co/blog"),
    ("OpenAI、複数の発表", "https://openai.com/news/company-announcements/?display=list"),
    ("通常の見出し", "https://example.com/%64igest/2026-11-06"),
    ("AI速報：AI Breaking Wireの10/12概況", "https://aibreakingwire.com/news/ai-brief-2026-10-12"),
    ("業界概況：AI学習コスト・動向の最新分析（週次）", "https://www.tomshardware.com/tech-industry/this-week-premium"),
    ("業界要約：エージェント関連の新規インシデントと方針転換", "https://example.com/en/news/1"),
    ("通常の見出し", "https://thejarrus.com/en/news/week-oct-19/"),
    ("AI週刊まとめ", "https://example.com/news/1"),
    ("AI週刊まとめ（10/19）", "https://example.com/news/1"),
    ("今週のAIニュース：新モデル発表と規制動向", "https://example.com/news/1"),
    ("通常の見出し", "https://example.com/news/week-september-9/"),
    ("通常の見出し", "https://example.com/news/WEEK-OCT-19/"),
    ("通常の見出し", "https://example.com/news/week-oct-19-2026/"),
    ("通常の見出し", "https://example.com/news/week-oct-19.html"),
    # 日付だけのページは、その日の発表をまとめたもの
    ("複数の小規模企業が10月29日にAI製品・提携を発表", "https://getyourbrief.com/ai/2026-10-29"),
    ("通常の見出し", "https://aidr.today/date/2026-10-17?lang=en"),
    ("通常の見出し", "https://explainx.ai/catch-up-on-ai/2026-10-18"),
    ("通常の見出し", "https://example.com/news/week-oct-19-2026.html"),
    ("【週刊まとめ】新モデル発表と規制動向", "https://example.com/news/1"),
    ("「今週のAIニュース」：新モデル発表と規制動向", "https://example.com/news/1"),
    ("0123456789業界要約：見出しの頭から10字まではラベル", "https://example.com/news/1"),
])
def test_digests_of_other_curation_sites_are_detected(title, url):
    assert is_digest(title, url)


@pytest.mark.parametrize("title, url", [
    ("Anthropic、悪用事例をまとめた脅威報告を公開",
     "https://www.axios.com/2026/09/12/anthropic-ai-threat-report-russia-iran-china"),
    ("AI博覧会のアーカイブ配信を開始", "https://prtimes.jp/main/html/rd/p/000000838.000053344.html"),
    ("Google、Gemini 3.8 FlashをGA公開", "https://blog.google/products/gemini/gemini-3-8-flash/"),
    ("経産省、AI事業者ガイドラインの週次説明会を開催", "https://www.meti.go.jp/press/2026/10/20261001001/20261001001.html"),
    # URL の単語の一部に daily / week / issues などを含むだけの通常の記事
    ("OpenAIのサム・オルトマン氏が国連安全保障理事会で説明へ",
     "https://www.reuters.com/world/openai-sam-altman-brief-un-security-council-next-week-2026-09-18/"),
    ("MicrosoftがAI支援の詐欺サービスを停止",
     "https://blogs.microsoft.com/on-the-issues/2026/09/22/disrupting-eviltokens-the-ai-chatbot-built-for-cybercrime/"),
    ("上院向けのAIブリーフィングをサンダース氏が招集", "https://www.axios.com/2026/09/09/sanders-senators-ai-briefing"),
    # 「概況」「短報」だけでは単一のニュースの報道もある。日次・週次・日付と組み合わさったときだけまとめとみなす
    ("FTC捜査報道を受けた業界影響の概況",
     "https://www.cbsnews.com/news/ftc-subpoenas-anthropic-openai-consumer-protection/"),
    # 週刊誌の報道は個別のニュース
    ("週刊東洋経済、生成AIの導入実態を特集", "https://toyokeizai.net/articles/-/900001"),
    ("開発者向けイベントの週を発表", "https://example.com/news/week-of-ai-2026"),
    ("通常の見出し", "https://example.com/news/next-week-oct-19/"),
    ("通常の見出し", "https://example.com/news/week-oct-19-launch/"),
    # 機能名としての「業界要約」「週刊まとめ」は個別のニュース
    ("AIによる「業界要約」機能を提供開始", "https://example.com/news/1"),
    ("Slackに「週刊まとめ」機能を追加", "https://example.com/news/2"),
    # 日付を含むだけの個別記事の URL
    ("通常の見出し", "https://www.axios.com/2026/09/12/anthropic-ai-threat-report"),
    # 日付を slug にする個別記事のサイトもあるので、日付だけのページはまとめと分かっているサイトに限る
    ("通常の見出し", "https://blog.example.com/posts/2026-10-29"),
    ("01234567890業界要約：11字目からは本文中の語", "https://example.com/news/1"),
])
def test_ordinary_news_is_not_a_digest(title, url):
    assert not is_digest(title, url)


def test_malformed_url_is_not_treated_as_digest_and_does_not_raise():
    """形式不正の URL は到達確認で落とす。ここで例外を出してその回の候補全体を止めない。"""
    assert digest_reason("通常の見出し", "https://[bad/news") is None


def test_digest_reason_names_the_matched_rule():
    assert "トップページ" in digest_reason("通常の見出し", "https://www.reuters.com/")
    assert "概況" in digest_reason("10月12日の業界概況", "https://example.com/news/1")
    assert "archive" in digest_reason("通常の見出し", "https://metamesh.biz/archive/2026/10/23")
