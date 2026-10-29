"""プライバシーポリシーページの必須記載事項を確認する。

Google AdSense / Google Analytics の利用規約で記載が求められる事項
(Cookie による広告配信、オプトアウト方法、Google によるデータ利用の説明)を含める。
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "site"
PRIVACY = SITE / "privacy.html"


def _html() -> str:
    return PRIVACY.read_text(encoding="utf-8")


def test_privacy_page_is_a_standalone_html_page():
    html = _html()
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert '<html lang="ja">' in html
    assert "<title>" in html and "プライバシーポリシー" in html
    assert 'href="style.css"' in html


def test_privacy_page_is_linked_from_top_page():
    assert 'href="privacy.html"' in (SITE / "index.html").read_text(encoding="utf-8")


def test_operator_and_effective_date():
    html = _html()
    assert "AI WIRE 運営事務局" in html
    assert re.search(r"制定日[:：]?\s*\d{4}年\d{1,2}月\d{1,2}日", html)


def test_adsense_required_disclosures():
    html = _html()
    assert "Google AdSense" in html
    assert "Cookie" in html
    assert "https://www.google.com/settings/ads" in html  # パーソナライズ広告の無効化
    assert "https://www.aboutads.info" in html  # 第三者配信事業者の Cookie 無効化
    assert "https://policies.google.com/technologies/partner-sites" in html


def test_google_analytics_disclosures():
    html = _html()
    assert "Google Analytics" in html
    assert "https://tools.google.com/dlpage/gaoptout" in html


def test_external_transmission_lists_each_destination():
    """外部送信される情報について、送信先ごとに記載する。"""
    html = _html()
    section = html[html.index("外部送信"):]
    for service in ("Google AdSense", "Google Analytics", "Google Fonts"):
        assert service in section, service


def test_contact_section_exists():
    html = _html()
    assert "お問い合わせ" in html


def test_no_placeholders_left():
    """問い合わせフォームURL・ドメイン名などのプレースホルダーが残っていない。"""
    assert "{{" not in _html()


def test_mentions_web_beacons_and_ip_collection_by_third_parties():
    """Google パブリッシャー向けポリシー: 第三者が Cookie・ウェブビーコン・IP アドレスで情報を収集しうることを明示する。"""
    html = _html()
    assert "ウェブビーコン" in html
    assert "IPアドレス" in html


def test_avoids_overstated_claims():
    html = _html()
    assert "匿名で収集" not in html  # GA の完全な匿名性は保証できない
    assert "にアクセスすれば" not in html  # aboutads.info は訪問だけでは無効化されない


def test_explains_how_operator_details_are_provided():
    """運営主体の名称・住所等は、本人の求めに応じて遅滞なく回答する形で知り得る状態にする。"""
    html = _html()
    assert "遅滞なく" in html
    assert "開示" in html


def test_table_headers_have_scope():
    html = _html()
    assert html.count('<th scope="col">') == 3


def test_explains_consent_mode_behavior_for_analytics():
    """同意モード(advanced): 同意がない場合も Cookie を使わない計測信号が送られうることを説明する。"""
    html = _html()
    ga = html[html.index("Google Analytics"):html.index("5. 利用者情報の外部送信")]
    assert "欧州経済領域" in ga
    assert "Cookie を使用しない" in ga
