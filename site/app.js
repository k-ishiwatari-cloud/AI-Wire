/**
 * AI WIRE - フィードの絞り込みと新着表示
 * 記事一覧はビルド時に scripts/render_site.py が HTML として書き出している。
 * ここではタグでの絞り込み、NEW バッジ、最終更新時刻の閲覧者ローカル表示だけを行う。
 * ビルドステップ不要。ブラウザで直接動作する。
 */

const NEW_WINDOW_HOURS = 24;

const filtersEl = document.getElementById("filters");
const lastUpdatedEl = document.getElementById("last-updated");
const cards = [...document.querySelectorAll(".card")];
const cardTags = new Map(cards.map((card) => [card, parseTags(card.dataset.tags)]));

markNewCards();
renderLastUpdated();
if (filtersEl) filtersEl.addEventListener("click", onFilterClick);

function parseTags(value) {
  try {
    const tags = JSON.parse(value || "[]");
    return Array.isArray(tags) ? tags : [];
  } catch {
    return [];
  }
}

function markNewCards() {
  cards.forEach((card) => {
    if (!isWithinHours(card.dataset.postedAt, NEW_WINDOW_HOURS)) return;
    card.classList.add("is-new");
    const badge = document.createElement("span");
    badge.className = "badge-new";
    badge.textContent = "NEW";
    card.querySelector(".card-top")?.appendChild(badge);
  });
}

function renderLastUpdated() {
  const generatedAt = lastUpdatedEl?.getAttribute("datetime");
  if (!generatedAt) return;
  const d = new Date(generatedAt);
  if (Number.isNaN(d.getTime())) return;
  lastUpdatedEl.textContent = d.toLocaleString("ja-JP", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function onFilterClick(e) {
  const btn = e.target.closest(".filter-chip");
  if (!btn) return;
  [...filtersEl.querySelectorAll(".filter-chip")].forEach((c) =>
    c.classList.toggle("is-active", c === btn)
  );
  applyFilter(btn.dataset.tag);
}

function applyFilter(tag) {
  cards.forEach((card) => {
    card.hidden = tag !== "__all__" && !cardTags.get(card).includes(tag);
  });
  // 表示する記事がなくなった日付グループは見出しごと隠す(描画省略用の外枠 .date-block ごと)
  const blocks = [...document.querySelectorAll(".date-group")].map((group) => {
    const block = group.closest(".date-block") || group;
    block.hidden = !group.querySelector(".card:not([hidden])");
    return block;
  });
  // タイムラインの縦線は、表示中の最後の日付で止める
  const visible = blocks.filter((block) => !block.hidden);
  blocks.forEach((block) => block.classList.toggle("is-last", block === visible[visible.length - 1]));
}

function isWithinHours(dateStr, hours) {
  if (!dateStr) return false;
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return false;
  const diffMs = Date.now() - d.getTime();
  return diffMs >= 0 && diffMs <= hours * 60 * 60 * 1000;
}
