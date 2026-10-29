"""Google Analytics(gtag.js)の設置と、同意モードの初期設定を確認する。"""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[2] / "site"
PAGES = ("index.html", "privacy.html", "404.html")
MEASUREMENT_ID = "G-F59NHKG7G0"

# 同意が必要な地域: EEA(EU27 + アイスランド・リヒテンシュタイン・ノルウェー)、英国、スイス
CONSENT_REGIONS = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    "IS", "LI", "NO", "GB", "CH",
}


def _head(name: str) -> str:
    html = (SITE / name).read_text(encoding="utf-8")
    return html[html.index("<head>"):html.index("</head>")]


def _analytics_js() -> str:
    return (SITE / "analytics.js").read_text(encoding="utf-8")


def test_every_page_loads_analytics_settings_before_gtag():
    loader = f'<script async src="https://www.googletagmanager.com/gtag/js?id={MEASUREMENT_ID}"></script>'
    for name in PAGES:
        head = _head(name)
        settings = head.index('<script src="/analytics.js"></script>')
        assert head.count(loader) == 1, name
        assert settings < head.index(loader), name  # 同意の初期値を gtag.js より先に積む


def test_consent_defaults_denied_in_regions_requiring_consent():
    js = _analytics_js()
    default = js[js.index("gtag('consent', 'default'"):js.index("gtag('js'")]
    for key in ("ad_storage", "ad_user_data", "ad_personalization", "analytics_storage"):
        assert re.search(rf"{key}: 'denied'", default), key
    regions = set(re.findall(r"'([A-Z]{2})'", default))
    assert regions == CONSENT_REGIONS


def test_config_uses_measurement_id_after_consent_default():
    js = _analytics_js()
    assert js.index("gtag('consent', 'default'") < js.index(f"gtag('config', '{MEASUREMENT_ID}')")
    assert js.count(MEASUREMENT_ID) == 1
