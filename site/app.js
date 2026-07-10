/**
 * AI WIRE - フィード描画スクリプト
 * data/manifest.json を読み込み、日付グループ + カード形式で描画する。
 * ビルドステップ不要。ブラウザで直接動作する。
 */

const MANIFEST_URL = "data/manifest.json";
const NEW_WINDOW_HOURS = 24;

const feedEl = document.getElementById("feed");
const filtersEl = document.getElementById("filters");
const lastUpdatedEl = document.getElementById("last-updated");

let allPosts = [];
let activeTag = "__all__";

init();

async function init() {
  try {
    const res = await fetch(MANIFEST_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`manifest.json の取得に失敗しました (HTTP ${res.status})`);
    const data = await res.json();

    allPosts = Array.isArray(data.posts) ? data.posts : [];
    renderLastUpdated(data.generated_at);
    renderFilters(allPosts);
    render();
  } catch (err) {
    feedEl.innerHTML = `<p class="empty-state">読み込みに失敗しました: ${escapeHtml(err.message)}</p>`;
  }
}

function renderLastUpdated(generatedAt) {
  if (!generatedAt) return;
  const d = new Date(generatedAt);
  if (Number.isNaN(d.getTime())) return;
  lastUpdatedEl.textContent = d.toLocaleString("ja-JP", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
  lastUpdatedEl.setAttribute("datetime", generatedAt);
}

function renderFilters(posts) {
  const tagSet = new Set();
  posts.forEach((p) => (p.tags || []).forEach((t) => tagSet.add(t)));

  [...tagSet].sort().forEach((tag) => {
    const btn = document.createElement("button");
    btn.className = "filter-chip";
    btn.type = "button";
    btn.dataset.tag = tag;
    btn.textContent = tag;
    filtersEl.appendChild(btn);
  });

  filtersEl.addEventListener("click", (e) => {
    const btn = e.target.closest(".filter-chip");
    if (!btn) return;
    activeTag = btn.dataset.tag;
    [...filtersEl.querySelectorAll(".filter-chip")].forEach((c) =>
      c.classList.toggle("is-active", c === btn)
    );
    render();
  });
}

function render() {
  const posts = allPosts.filter(
    (p) => activeTag === "__all__" || (p.tags || []).includes(activeTag)
  );

  if (posts.length === 0) {
    feedEl.innerHTML = `<p class="empty-state">該当する記事がまだありません。エージェントによる投稿をお待ちください。</p>`;
    return;
  }

  const groups = groupByDate(posts);
  feedEl.innerHTML = "";

  for (const [date, items] of groups) {
    const group = document.createElement("section");
    group.className = "date-group";

    const heading = document.createElement("h2");
    heading.className = "date-heading";
    heading.textContent = formatDateHeading(date);
    group.appendChild(heading);

    items.forEach((post) => group.appendChild(renderCard(post)));
    feedEl.appendChild(group);
  }
}

function renderCard(post) {
  const card = document.createElement("article");
  const isNew = isWithinHours(post.date, NEW_WINDOW_HOURS);
  card.className = "card" + (isNew ? " is-new" : "");

  const tagsHtml = (post.tags || [])
    .map((t) => `<span class="tag-pill">${escapeHtml(t)}</span>`)
    .join("");

  const bodyHtml = post.body
    ? `<div class="card-body">${escapeHtml(post.body)}</div>`
    : "";

  card.innerHTML = `
    <div class="card-top">
      <span>${escapeHtml(post.date)}</span>
      ${isNew ? '<span class="badge-new">NEW</span>' : ""}
    </div>
    <h3 class="card-title">${escapeHtml(post.title)}</h3>
    ${tagsHtml ? `<div class="card-tags">${tagsHtml}</div>` : ""}
    <p class="card-summary">${escapeHtml(post.summary)}</p>
    ${bodyHtml}
    <a class="card-source" href="${escapeAttr(post.source_url)}" target="_blank" rel="noopener noreferrer">
      ${escapeHtml(post.source_name)} で読む →
    </a>
  `;
  return card;
}

function groupByDate(posts) {
  const map = new Map();
  posts.forEach((p) => {
    if (!map.has(p.date)) map.set(p.date, []);
    map.get(p.date).push(p);
  });
  return [...map.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1));
}

function formatDateHeading(dateStr) {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("ja-JP", {
    year: "numeric", month: "long", day: "numeric", weekday: "short",
  });
}

function isWithinHours(dateStr, hours) {
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return false;
  const diffMs = Date.now() - d.getTime();
  return diffMs >= 0 && diffMs <= hours * 60 * 60 * 1000;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(str) {
  return escapeHtml(str);
}
