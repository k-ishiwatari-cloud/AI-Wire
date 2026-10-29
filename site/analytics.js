/**
 * Google Analytics(gtag.js)の設定。
 * gtag.js 本体より先に読み込み、同意モードの初期値 → 計測設定の順に dataLayer へ積む。
 *
 * 同意が必要な地域(EEA・英国・スイス)では、Google の同意管理(AdSense の
 * 「プライバシーとメッセージ」)で閲覧者が同意するまで、Cookie を使う計測・広告を拒否状態にする。
 * 同意の結果は同意管理側が gtag の consent update で反映する。
 */
window.dataLayer = window.dataLayer || [];
function gtag() { dataLayer.push(arguments); }

gtag('consent', 'default', {
  ad_storage: 'denied',
  ad_user_data: 'denied',
  ad_personalization: 'denied',
  analytics_storage: 'denied',
  region: [
    // EEA(EU 27か国)
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
    'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
    // EEA(EU 以外)
    'IS', 'LI', 'NO',
    // 英国・スイス
    'GB', 'CH',
  ],
  wait_for_update: 500,
});

gtag('js', new Date());
gtag('config', 'G-F59NHKG7G0');
