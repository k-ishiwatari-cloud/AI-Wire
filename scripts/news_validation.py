"""生成された記事候補を検証する純粋関数群。

- タイトル類似度による重複判定(文字bigramのTF-IDFコサイン類似度)
- web_search が実際に参照したURLとの照合
- source_url の到達確認
"""
from __future__ import annotations

import http.client
import ipaddress
import math
import re
import socket
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from typing import Any, Callable, Iterable, NamedTuple
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

# 既存記事387件を投稿順に再生して決めた値(2026-09時点)。0.43以上はほぼ同一ニュースの言い換えで、
# これより下げると同じ企業の別ニュース(例: Anthropic の別モデル発表)を誤検出し始める。
# 言い換えの激しい重複(類似度0.4未満)はタイトルだけでは区別できないため取りこぼす。
TITLE_SIMILARITY_THRESHOLD = 0.43

URL_CHECK_TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; AI-WIRE-link-checker/1.0)"

# 「存在しない」と断定できるステータスのみ不合格にする。
# 403/401/429 などは bot ブロックでも返るため、実在ページを誤って落とさないよう合格扱い。
NOT_FOUND_STATUSES = {404, 410}

_JAPAN_SUFFIX_RE = re.compile(r"[(（]\s*(japan|国内|日本)\s*[)）]")
_NON_WORD_RE = re.compile(r"[\W_]+")
_TRACKING_PARAM_RE = re.compile(r"^(utm_\w+|fbclid|gclid)$", re.IGNORECASE)


# ---- タイトル類似度 ----

def _normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKC", title).lower()
    text = _JAPAN_SUFFIX_RE.sub("", text)
    return _NON_WORD_RE.sub("", text)


def _bigrams(title: str) -> Counter:
    text = _normalize_title(title)
    if len(text) < 2:
        return Counter([text]) if text else Counter()
    return Counter(text[i:i + 2] for i in range(len(text) - 1))


def _idf(titles: Iterable[str]) -> Callable[[str], float]:
    docs = [set(_bigrams(t)) for t in titles]
    df = Counter(g for doc in docs for g in doc)
    n = len(docs)
    return lambda gram: math.log((n + 1) / (df[gram] + 1)) + 1


def _cosine(a: str, b: str, idf: Callable[[str], float]) -> float:
    va = {g: c * idf(g) for g, c in _bigrams(a).items()}
    vb = {g: c * idf(g) for g, c in _bigrams(b).items()}
    norm = math.sqrt(sum(v * v for v in va.values()) * sum(v * v for v in vb.values()))
    if norm == 0:
        return 0.0
    return sum(v * vb.get(g, 0.0) for g, v in va.items()) / norm


def title_similarity(a: str, b: str, corpus: Iterable[str]) -> float:
    """corpus 全体での出現頻度で重み付けした、2つのタイトルの類似度(0〜1)。"""
    return _cosine(a, b, _idf([*corpus, a, b]))


def find_similar_title(
    title: str,
    existing: list[str],
    threshold: float = TITLE_SIMILARITY_THRESHOLD,
) -> tuple[str, float] | None:
    """existing の中で最も類似度の高いタイトルが閾値以上なら (タイトル, 類似度) を返す。"""
    if not existing:
        return None
    idf = _idf([*existing, title])
    best = max(((t, _cosine(title, t, idf)) for t in existing), key=lambda x: x[1])
    return best if best[1] >= threshold else None


# ---- 他のまとめサイトのまとめ ----

# ニュースが少ない時間帯に、AI が他サイトの日次・週次まとめを 1 本の記事として拾ってしまう。
# 二次情報のさらに二次情報で価値が低いので載せない(AI WIRE のまとめは自サイトの記事から作る)。
_DIGEST_TITLE_RE = re.compile(
    r"ダイジェスト|デイリー|日次まとめ|週次まとめ|総合まとめ|日次AI|週次AI|日次ブリーフ|週次ブリーフ|"
    r"ニュースレター|recap|roundup|round-up|digest|briefing",
    re.IGNORECASE,
)
# 機能名にも使われる語(「業界要約」機能など)。見出しの頭のラベルのときだけまとめとみなす
_LABEL_DIGEST_TITLE_RE = re.compile(
    r"^(?:[^「」『』【】]{0,10}?|[【「『])(業界要約|業界まとめ|週刊まとめ|今週のAIニュース)(?:[】」』：:（(]|$)"
)
# 「概況」「短報」「総覧」は単一のニュースの報道にも使われるので、期間を示す語と組み合わさったときだけ数える
_WEAK_DIGEST_TITLE_RE = re.compile(r"概況|短報|総覧")
_PERIOD_RE = re.compile(r"日次|週次|週末|月次|\d{1,2}/\d{1,2}|\d{1,2}月\d{1,2}日")
# URL のパスの 1 区切り(/ と / の間)全体がこれらの語なら、まとめのページ。
# 区切りの一部に含むだけ(例: .../next-week-2026-09-18/、/on-the-issues/)の通常の記事は対象外
_DIGEST_PATH_SEGMENTS = {
    "daily", "digest", "archive", "archives", "edition", "newsletter", "newsletters",
    "briefing", "recap", "roundup", "week", "issues", "ai-news-today", "feed",
}
_DIGEST_SEGMENT_RE = re.compile(
    r"(?:^|-)(?:daily-digest|digest|recap|roundup)$"
    r"|^week-[a-z]{3,9}-\d{1,2}(?:-\d{4})?(?:\.html?)?$",  # 週ごとのまとめ(例: /news/week-oct-19/)
    re.IGNORECASE,
)
# パスの最後がこれらの語なら、個別記事ではなく記事一覧のページ(例: https://huggingface.co/blog)
_LISTING_LAST_SEGMENTS = {"blog", "news", "newsroom", "press", "press-releases", "company-announcements"}
# これらのサイトでパスの最後が日付だけなら、その日の発表をまとめたページ(例: https://getyourbrief.com/ai/2026-10-29)。
# 日付を slug にする個別記事のサイトもあるので、まとめと分かっているサイトに限る
_DATE_PAGE_HOSTS = {"getyourbrief.com", "aidr.today", "explainx.ai"}
_DATE_ONLY_SEGMENT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# パスがこれだけなら、言語別のトップページ(例: https://ai.zhudong.net/en/)
_LANGUAGE_SEGMENTS = {
    "en", "ja", "jp", "zh", "cn", "tw", "ko", "kr", "de", "fr", "es", "it", "pt", "ru", "ar",
    "en-us", "en-gb", "ja-jp", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "ko-kr",
}


def _url_parts(url: str) -> tuple[str, list[str]] | None:
    """(ホスト名, パスの区切り)。形式不正なら None。"""
    try:
        parts = urlsplit(url)
        path = unquote(parts.path)
        host = (parts.hostname or "").removeprefix("www.")
    except ValueError:
        return None
    return host, [s for s in path.lower().split("/") if s]


def content_digest_reason(title: str, url: str) -> str | None:
    """記事そのものがまとめ(見出しがまとめ、または出典がトップページで中身を確かめられない)なら、その判定理由。

    出典が記事一覧や日付のページでも、中身が個別のニュースなら None(digest_reason では除外される)。
    AI WIRE の週次まとめの材料を選ぶのに使う。"""
    parts = _url_parts(url)
    if parts is None:
        return None
    _, segments = parts
    if not segments or (len(segments) == 1 and segments[0] in _LANGUAGE_SEGMENTS):
        return "トップページ"
    if match := _DIGEST_TITLE_RE.search(title):
        return f"タイトルの語「{match.group(0)}」"
    if match := _LABEL_DIGEST_TITLE_RE.search(title):
        return f"タイトルの語「{match.group(1)}」"
    if (match := _WEAK_DIGEST_TITLE_RE.search(title)) and (period := _PERIOD_RE.search(title)):
        return f"タイトルの語「{match.group(0)}」「{period.group(0)}」"
    return None


def digest_reason(title: str, url: str) -> str | None:
    """他サイトのまとめ(日次・週次のダイジェスト、ニュースレター、トップページ、記事一覧)を指す記事候補なら、
    その判定理由。該当しなければ None。形式不正の URL は到達確認で落とすので、ここでは None を返す。"""
    if reason := content_digest_reason(title, url):
        return reason
    parts = _url_parts(url)
    if parts is None:
        return None
    host, segments = parts
    for s in segments:
        if s in _DIGEST_PATH_SEGMENTS or _DIGEST_SEGMENT_RE.search(s):
            return f"URL のパス「{s}」"
    if segments[-1] in _LISTING_LAST_SEGMENTS:
        return f"記事一覧のページ「/{segments[-1]}」"
    if host in _DATE_PAGE_HOSTS and _DATE_ONLY_SEGMENT_RE.match(segments[-1]):
        return f"日付だけのページ「/{segments[-1]}」"
    return None


def is_digest(title: str, url: str) -> bool:
    return digest_reason(title, url) is not None


# ---- URL 正規化・引用元照合 ----

def normalize_url(url: str) -> str:
    """同一ページとみなせるURLを同じ文字列にする(比較専用。http/https・www・既定ポート・クエリ順を同一視)。"""
    url = url.strip()
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".")
        port = parts.port
    except ValueError:
        return url
    if host.startswith("www."):
        host = host[4:]
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                             if not _TRACKING_PARAM_RE.match(k)))
    scheme = "https" if parts.scheme.lower() in ("http", "https") else parts.scheme.lower()
    return urlunsplit((scheme, netloc, parts.path.rstrip("/"), query, ""))


def is_cited(url: str, sources: Iterable[str]) -> bool:
    return normalize_url(url) in {normalize_url(s) for s in sources}


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def extract_source_urls(resp: Any) -> set[str]:
    """Responses API の応答から、web_search が実際に参照したURLを集める。

    - web_search_call の action.sources (include=["web_search_call.action.sources"] 指定時)
    - web_search_call の action.url (open_page / find_in_page)
    - message 内の url_citation 注釈
    """
    urls: set[str] = set()
    for item in _get(resp, "output") or []:
        kind = _get(item, "type")
        if kind == "web_search_call":
            action = _get(item, "action")
            if action is None:
                continue
            for source in _get(action, "sources") or []:
                if _get(source, "url"):
                    urls.add(_get(source, "url"))
            if _get(action, "url"):
                urls.add(_get(action, "url"))
        elif kind == "message":
            for content in _get(item, "content") or []:
                for ann in _get(content, "annotations") or []:
                    if _get(ann, "type") == "url_citation" and _get(ann, "url"):
                        urls.add(_get(ann, "url"))
    return urls


# ---- URL 到達確認 ----

class UrlCheck(NamedTuple):
    ok: bool
    reason: str


def _is_well_formed(url: str) -> bool:
    if re.search(r"\s", url):
        return False
    try:
        parts = urlsplit(url)
        parts.port  # 不正なポートは ValueError
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.username is None
        and parts.password is None
    )


def is_public_host(host: str) -> bool:
    """host(名前解決後の全アドレス)がグローバルアドレスのみなら True。名前解決失敗は socket.gaierror。"""
    try:
        addrs = [ipaddress.ip_address(host)]
    except ValueError:
        addrs = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in socket.getaddrinfo(host, None)]
    for addr in addrs:
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if not addr.is_global:
            return False
    return True


class _BlockedHost(Exception):
    pass


class _PublicHostOnlyHandler(urllib.request.BaseHandler):
    """モデル出力のURLで内部ネットワークへ到達しないよう、全リクエスト(リダイレクト先を含む)の宛先を検査する。"""

    def http_request(self, req):
        host = urlsplit(req.full_url).hostname or ""
        if not is_public_host(host):
            raise _BlockedHost(host)
        return req

    https_request = http_request


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """標準ハンドラは ftp: への遷移も許すため、リダイレクト先を userinfo なしの http(s) に限定する。

    遷移先の宛先アドレスは、新しいリクエストとして _PublicHostOnlyHandler が検査する。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_well_formed(newurl):
            if fp is not None:
                fp.close()
            raise _BlockedHost(f"不正なリダイレクト先: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_default_opener = urllib.request.build_opener(_PublicHostOnlyHandler(), _SafeRedirectHandler()).open


def check_url(url: str, opener: Callable[..., Any] | None = None, timeout: float = URL_CHECK_TIMEOUT) -> UrlCheck:
    """URLが実在しないと断定できる場合(と内部アドレス宛て)のみ ok=False を返す。

    判定不能(タイムアウト、bot ブロック、サーバーエラー等)は ok=True とし、理由を reason に残す。
    """
    if not _is_well_formed(url):
        return UrlCheck(False, "URLの形式が不正")
    opener = opener or _default_opener
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=timeout) as resp:
            resp.read(1024)
        return UrlCheck(True, "")
    except _BlockedHost as exc:
        return UrlCheck(False, f"内部アドレス宛てのため拒否: {exc}")
    except urllib.error.HTTPError as exc:
        try:
            if exc.code in NOT_FOUND_STATUSES:
                return UrlCheck(False, f"HTTP {exc.code}")
            return UrlCheck(True, f"HTTP {exc.code} (判定不能のため許容)")
        finally:
            exc.close()
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, socket.gaierror):
            return UrlCheck(False, f"ホスト名を解決できない: {exc.reason}")
        return UrlCheck(True, f"接続エラー (判定不能のため許容): {exc.reason}")
    except (http.client.InvalidURL, ValueError) as exc:
        return UrlCheck(False, f"URLの形式が不正: {exc}")
    except socket.gaierror as exc:
        return UrlCheck(False, f"ホスト名を解決できない: {exc}")
    except (TimeoutError, OSError, http.client.HTTPException) as exc:
        return UrlCheck(True, f"接続エラー (判定不能のため許容): {exc}")
