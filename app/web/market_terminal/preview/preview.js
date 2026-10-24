/** Read-only design preview. Role switches and review actions never grant access or write data. */
const root = "/terminal/preview";
const api = "/api/v1/public";
const main = document.querySelector("#main");
const dialog = document.querySelector("#infoDialog");
const dialogBody = document.querySelector("#dialogBody");
const searchInput = document.querySelector("#searchInput");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const brands = { ggsel: "GGSEL", playerok: "Playerok", funpay: "FunPay" };
const brandAssets = { ggsel: "ggsel.ico", playerok: "playerok.svg", funpay: "funpay.ico" };
const roles = {
  user: ["Пользователь", "Каталог, поиск, сравнение предложений и переход на площадку."],
  partner: ["Партнёр", "Работа со своими объявлениями и источниками в своём рабочем пространстве."],
  moderator: ["Модератор", "Проверка соответствий и решений по каталогу в разрешённом рабочем пространстве."],
  admin: ["Админ", "Управление доступом и просмотр технических ошибок с отдельным серверным разрешением."],
};

// Editorial titles are limited to these reviewed local records. They never alter domain data.
const artwork = {
  "7c862a70-5619-5b6d-a2aa-798560d29f18": { title: "Minecraft", subtitle: "Java & Bedrock Edition · PC", label: "PC", image: "cube.svg" },
  "9a520758-e499-5837-90bb-9e6b67d7a591": { title: "Minecraft", subtitle: "Активация промокодом · iOS", label: "iOS", image: "world.svg" },
};

let activeRequest;
let renderVersion = 0;
let pageAnimation;
let dialogAnimation;
let toastTimeout;
let previewRole = "user";
let reviewOffers = [];
let reviewProduct;
let reviewSelection = 0;
let catalogCache;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function link(params = {}) {
  const query = new URLSearchParams(params);
  return `${root}${query.size ? `?${query}` : ""}`;
}

function brandMark(marketplace) {
  const known = Object.hasOwn(brands, marketplace);
  const name = known ? brands[marketplace] : marketplace;
  return `<span class="market-mark ${known ? marketplace : "image-unavailable"}" role="img" aria-label="${escapeHtml(name)}" title="${escapeHtml(name)}">${known ? `<img src="${root}/${brandAssets[marketplace]}" alt="" width="28" height="28" class="market-logo">` : ""}<span class="logo-fallback" aria-hidden="true">${escapeHtml(name)}</span></span>`;
}

function offerFootprint(product) {
  const marketplaces = [...new Set(Array.isArray(product.marketplaces) ? product.marketplaces : [])];
  const countLabel = plural(product.offer_count, ["предложение", "предложения", "предложений"]);
  return `<div class="offer-footprint"><div class="marketplace-logos">${marketplaces.map(brandMark).join("")}</div>
    <span class="offer-count" role="img" aria-label="${escapeHtml(countLabel)}" title="${escapeHtml(countLabel)}"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="6" y="6" width="11" height="11" rx="2"/><path d="M3 13V5a2 2 0 0 1 2-2h8"/></svg><span aria-hidden="true">${escapeHtml(product.offer_count)}</span></span>
  </div>`;
}

function marketplaceName(value) {
  return brands[value] ?? value;
}

function safeSource(value) {
  try {
    const url = new URL(value);
    const allowed = ["ggsel.net", "ggsell.com", "playerok.com", "funpay.com"];
    return url.protocol === "https:" && !url.username && !url.password && allowed.includes(url.hostname) ? url.href : null;
  } catch {
    return null;
  }
}

function money(offer) {
  if (offer.price === null || offer.price === undefined || offer.price === "") return "Цена не указана";
  const value = Number(offer.price);
  if (!Number.isFinite(value) || value < 0) return "Цена не указана";
  if (!offer.currency) return `${new Intl.NumberFormat("ru-RU").format(value)} · валюта не указана`;
  try {
    return new Intl.NumberFormat("ru-RU", { style: "currency", currency: offer.currency, maximumFractionDigits: 2 }).format(value);
  } catch {
    return `${new Intl.NumberFormat("ru-RU").format(value)} ${offer.currency}`;
  }
}

function plural(value, forms) {
  const category = new Intl.PluralRules("ru-RU").select(value);
  return `${value} ${forms[{ one: 0, few: 1, many: 2, other: 2 }[category]]}`;
}

function infoFor(product) {
  return artwork[product.id] ?? { title: product.name, subtitle: product.category ?? "Цифровой товар", label: "Товар", image: "cube.svg" };
}

async function getJson(path, signal) {
  const response = await fetch(`${api}${path}`, { signal, headers: { Accept: "application/json" } });
  const isJson = response.headers.get("content-type")?.includes("application/json");
  const payload = isJson ? await response.json() : null;
  if (!response.ok || !payload) {
    const error = new Error("Public data unavailable");
    error.status = response.status;
    const requestId = payload?.error?.request_id;
    error.requestId = typeof requestId === "string" && /^[a-zA-Z0-9._-]{1,80}$/.test(requestId) ? requestId : null;
    throw error;
  }
  return payload;
}

function show(html, { focus = true, scroll = 0 } = {}) {
  main.innerHTML = html;
  document.title = `${main.querySelector("h1, h2")?.textContent ?? "Предпросмотр"} · Market Terminal`;
  main.setAttribute("aria-busy", "false");
  pageAnimation?.cancel();
  if (!reducedMotion.matches) {
    pageAnimation = main.animate([{ opacity: .65, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" }], {
      duration: 220, easing: "cubic-bezier(.25,1,.5,1)",
    });
  }
  if (focus) main.focus({ preventScroll: true });
  window.scrollTo({ top: scroll, behavior: "instant" });
}

function errorMarkup({ status = 500, requestId = null, demo = false } = {}) {
  const missing = status === 404;
  const offline = status === 0;
  const unavailable = [429, 503, 504].includes(status);
  const title = missing ? "Кажется, здесь ничего нет" : offline ? "Не удалось подключиться" : unavailable ? "Сервис временно недоступен" : "Не получилось открыть страницу";
  const explanation = missing ? "Ссылка могла устареть, а товар больше не доступен. Попробуйте найти его в каталоге." : offline ? "Проверьте соединение и попробуйте ещё раз. Ваши действия в других разделах не затронуты." : "Попробуйте ещё раз немного позже. Мы не будем показывать неполные данные как готовый результат.";
  return `<section class="error-state" aria-labelledby="errorTitle">
    <span class="error-number" aria-hidden="true">${missing ? "404" : offline ? "↯" : "!"}</span>
    <span class="eyebrow">${demo ? "Пример состояния интерфейса" : "Market Terminal"}</span>
    <h1 id="errorTitle">${title}</h1><p>${explanation}</p>
    <div class="actions"><a class="primary" data-nav href="${root}">В каталог</a>${missing || demo ? "" : '<button class="secondary" data-action="retry">Повторить</button>'}</div>
    ${requestId ? `<p class="diagnostic">Код обращения: ${escapeHtml(requestId)}</p>` : ""}
    ${demo ? '<p class="diagnostic">Демонстрация. Отчёт об ошибке не отправлен.</p>' : ""}
  </section>`;
}

function marketplaceNav(params) {
  const active = params.get("marketplace") ?? "";
  return `<nav class="market-nav" aria-label="Площадки">${[["", "Все площадки"], ...Object.entries(brands)].map(([key, name]) => {
    const query = { ...(params.get("q") ? { q: params.get("q") } : {}), ...(key ? { marketplace: key } : {}) };
    return `<a data-nav href="${escapeHtml(link(query))}" ${active === key ? 'aria-current="page"' : ""}>${key ? brandMark(key) : '<span aria-hidden="true">▦</span>'}${name}</a>`;
  }).join("")}</nav>`;
}

function productCard(product, params) {
  const art = infoFor(product);
  const price = product.best_offer ? money(product.best_offer) : "Все цены в сравнении";
  const query = { screen: "product", product: product.id, ...(params.get("q") ? { q: params.get("q") } : {}), ...(params.get("marketplace") ? { marketplace: params.get("marketplace") } : {}) };
  return `<a class="product-card" data-nav href="${escapeHtml(link(query))}">
    <div class="card-image"><img src="${root}/${art.image}" width="600" height="600" alt="" loading="lazy"><span class="art-label">${escapeHtml(art.label)}</span></div>
    <div class="card-copy"><h3>${escapeHtml(art.title)}</h3><p>${escapeHtml(art.subtitle)}</p>
      <span class="card-price">${escapeHtml(price)} <span aria-hidden="true">↗</span></span>
      ${offerFootprint(product)}
    </div></a>`;
}

function catalogMarkup(products, params, nextCursor) {
  const query = params.get("q") ?? "";
  const density = params.get("screen") === "density";
  const tiles = density && products.length ? Array.from({ length: 50 }, (_, index) => products[index % products.length]) : products;
  const title = query ? `Результаты: «${query}»` : "Каталог";
  return `${!query && !params.get("marketplace") ? `<section class="hero" aria-labelledby="heroTitle"><div class="hero-copy">
      <span class="eyebrow">Меньше поиска. Больше игры.</span><h1 id="heroTitle">Ваш следующий мир.<span class="hero-continuation">В одном поиске.</span></h1>
      <p>Сравните предложения площадок и выберите подходящий вариант игры.</p>
      <a class="primary" href="#catalog">Выбрать игру <span aria-hidden="true">↗</span></a>
    </div></section>
    <div class="game-strip"><a data-nav class="game-tile" href="${root}"><span class="tile-symbol" aria-hidden="true"><svg viewBox="0 0 24 24"><rect x="3" y="3" width="6" height="6" rx="1"/><rect x="15" y="3" width="6" height="6" rx="1"/><rect x="3" y="15" width="6" height="6" rx="1"/><rect x="15" y="15" width="6" height="6" rx="1"/></svg></span><span>Все товары</span></a>
    ${products.some(product => Object.hasOwn(artwork, product.id)) ? `<a data-nav class="game-tile" href="${root}?q=Minecraft"><img src="${root}/cube.svg" width="64" height="64" alt=""><span>Minecraft<small>PC и iOS</small></span></a>` : ""}
    </div>` : ""}
    ${marketplaceNav(params)}
    <section id="catalog" aria-labelledby="catalogTitle"><div class="catalog-heading"><div><h2 id="catalogTitle">${escapeHtml(title)}</h2><span class="count" title="Товаров загружено" aria-label="Товаров загружено: ${tiles.length}${nextCursor ? "+" : ""}">${tiles.length}${nextCursor ? "+" : ""}</span></div></div>
    ${density ? '<p class="notice neutral">Тест плотности: реальные карточки повторены 50 раз только в браузере. В каталог ничего не добавлено.</p>' : ""}
    ${tiles.length ? `<div class="product-grid ${tiles.length <= 2 ? "compact" : ""}">${tiles.map(product => productCard(product, params)).join("")}</div>` : '<div class="empty"><span class="tile-symbol" aria-hidden="true">⌕</span><h2>Ничего не нашлось</h2><p>Попробуйте другое название или снимите фильтр площадки.</p><a class="secondary" data-nav href="/terminal/preview">Сбросить поиск</a></div>'}
    ${nextCursor ? '<button class="secondary" data-action="more">Показать ещё</button>' : ""}
    </section>`;
}

function offerRow(offer) {
  const source = safeSource(offer.url);
  return `<article class="offer-row"><div class="offer-market">${brandMark(offer.marketplace)}${escapeHtml(marketplaceName(offer.marketplace))}</div>
    <div class="offer-description"><p class="offer-name">${escapeHtml(offer.title ?? "Название не указано")}</p><p class="offer-seller">Продавец: ${escapeHtml(offer.seller_name ?? "не указан")}</p></div>
    <span class="offer-price">${escapeHtml(money(offer))}</span>
    ${source ? `<a class="secondary" href="${escapeHtml(source)}" target="_blank" rel="noopener noreferrer">На площадку <span aria-hidden="true">↗</span></a>` : '<span class="subtle">Ссылка недоступна</span>'}
  </article>`;
}

function productMarkup(product, comparison, params) {
  const art = infoFor(product);
  const backQuery = { ...(params.get("q") ? { q: params.get("q") } : {}), ...(params.get("marketplace") ? { marketplace: params.get("marketplace") } : {}) };
  const mismatch = comparison.status === "currency_mismatch";
  return `<a class="back" data-nav href="${escapeHtml(link(backQuery))}"><span aria-hidden="true">←</span> Назад к товарам</a>
    <section class="product-hero" aria-labelledby="productTitle"><img class="product-cover" src="${root}/${art.image}" width="220" height="220" alt="Иллюстрация оформления; не официальная обложка">
    <div><span class="eyebrow">${escapeHtml(art.subtitle)}</span><h1 id="productTitle">${escapeHtml(art.title)}</h1>
    ${offerFootprint(product)}
    <a class="primary" href="#offers">Все предложения <span aria-hidden="true">↓</span></a>
    <details class="original-name"><summary>Исходное название товара</summary><p>${escapeHtml(product.name)}</p>${artwork[product.id] ? '<p>Краткий заголовок подготовлен для макета. Название в каталоге не изменено.</p>' : ""}</details></div></section>
    <section id="offers" aria-labelledby="offersTitle"><div class="offers-heading"><h2 id="offersTitle">Предложения площадок</h2><span class="subtle">${product.updated_at ? `Обновлено ${escapeHtml(new Date(product.updated_at).toLocaleDateString("ru-RU"))}` : "Время обновления не передано источником"}</span></div>
    ${mismatch ? '<p class="notice"><span aria-hidden="true">ⓘ</span><span><strong>Цены в разных валютах.</strong> Мы показываем их без пересчёта и не выбираем общее самое дешёвое предложение.</span></p>' : comparison.best_offer ? `<p class="notice neutral">Лучшее предложение по результату сравнения: ${escapeHtml(money(comparison.best_offer))} · ${escapeHtml(marketplaceName(comparison.best_offer.marketplace))}</p>` : '<p class="notice neutral">Лучшее предложение пока не определено. Проверьте цену, валюту и условия каждого объявления.</p>'}
    ${comparison.offers.length ? comparison.offers.map(offerRow).join("") : '<div class="empty"><h2>Предложений пока нет</h2><p>Товар есть в каталоге, но доступные предложения ещё не получены.</p></div>'}
    <p class="detail-note">Покупка проходит на выбранной площадке. Проверьте регион активации, платформу и способ получения перед оплатой.</p></section>`;
}

function reviewMarkup() {
  if (!reviewProduct || !reviewOffers.length) return '<div class="empty"><h1>Нет объявления для примера</h1><p>Для макета проверки нужны товары и предложения в подключённом каталоге.</p></div>';
  const product = reviewProduct;
  const art = infoFor(product);
  const offer = reviewOffers[reviewSelection];
  return `<div class="review-top"><div><span class="eyebrow">Рабочее пространство · макет</span><h1>Проверка объявления</h1><p>Сначала сравните две стороны. Затем выберите решение.</p></div><a class="secondary" href="/terminal/review">Текущий кабинет ↗</a></div>
    <p class="notice neutral">Это пример на уже связанном объявлении. Решения в макете не сохраняются, рабочая очередь не меняется.</p>
    <div class="review-layout"><aside class="queue" aria-label="Объявления для просмотра"><p>Примеры из каталога</p><select class="queue-select" id="reviewSelect" aria-label="Объявление для просмотра">${reviewOffers.map((item, index) => `<option value="${index}" ${index === reviewSelection ? "selected" : ""}>${escapeHtml(marketplaceName(item.marketplace))} · ${escapeHtml(money(item))}</option>`).join("")}</select>${reviewOffers.map((item, index) => `<button type="button" data-review-index="${index}" aria-pressed="${reviewSelection === index}">${brandMark(item.marketplace)}<strong>${escapeHtml(marketplaceName(item.marketplace))}</strong><small>${escapeHtml(money(item))}</small></button>`).join("")}</aside>
    <section aria-label="Сопоставление объявления"><div class="pair">
      <article class="pair-card"><span class="eyebrow">01 · Исходное объявление</span><div class="offer-market">${brandMark(offer.marketplace)}${escapeHtml(marketplaceName(offer.marketplace))}</div><h3>${escapeHtml(offer.title ?? "Название не указано")}</h3><p>${escapeHtml(money(offer))} · ${escapeHtml(offer.seller_name ?? "Продавец не указан")}</p><p>ID объявления</p><code>${escapeHtml(offer.external_id ?? "не указан")}</code></article>
      <article class="pair-card target"><span class="eyebrow">02 · Товар, к которому привязываем</span><img src="${root}/${art.image}" alt="" width="60" height="60"><h3>${escapeHtml(art.title)} · ${escapeHtml(art.subtitle)}</h3><p>${escapeHtml(product.name)}</p><p>ID товара в каталоге</p><code>${escapeHtml(product.id)}</code></article>
    </div>
    <form class="decision-form" id="decisionForm"><fieldset><legend>Какое решение принимаем?</legend><div class="decision-options">
      <label class="decision-choice"><input type="radio" name="decision" value="link" checked> Связать с этим товаром</label>
      <label class="decision-choice"><input type="radio" name="decision" value="create"> Создать новый товар</label>
      <label class="decision-choice"><input type="radio" name="decision" value="reject"> Это другой товар</label>
    </div></fieldset><label for="facts">На чём основано решение <span id="factsRequired">· обязательно</span></label>
    <p id="factsHelp">Укажите совпавшие платформу, издание и способ активации. Только факты из объявления.</p>
    <textarea id="facts" name="facts" required maxlength="2000" aria-describedby="factsHelp factsError" placeholder="Например: в обоих объявлениях PC, Java & Bedrock, цифровой ключ."></textarea>
    <p class="validation" id="factsError" hidden>Добавьте проверенные факты, чтобы подтвердить связь.</p>
    <div class="form-actions"><p class="subtle">Перед подтверждением ещё раз покажем точный товар.</p><button class="primary" type="submit">Проверить решение <span aria-hidden="true">→</span></button></div></form></section></div>`;
}

async function render({ focus = true, scroll = 0 } = {}) {
  const version = ++renderVersion;
  activeRequest?.abort();
  const controller = new AbortController();
  activeRequest = controller;
  const timer = window.setTimeout(() => controller.abort("timeout"), 15000);
  const params = new URLSearchParams(location.search);
  const screen = params.get("screen") ?? "catalog";
  searchInput.value = params.get("q") ?? "";
  main.setAttribute("aria-busy", "true");
  main.innerHTML = '<div class="loading" role="status"><span class="spinner" aria-hidden="true"></span> Открываем каталог…</div>';
  try {
    let html;
    if (location.pathname.endsWith("/not-found")) {
      html = errorMarkup({ status: 404 });
    } else if (["error", "offline"].includes(screen)) {
      html = errorMarkup({ status: screen === "offline" ? 0 : 500, demo: true });
    } else if (screen === "product") {
      const id = params.get("product") ?? "";
      if (!/^[a-f0-9-]{36}$/i.test(id)) {
        html = errorMarkup({ status: 404 });
      } else {
        const [product, comparison] = await Promise.all([
          getJson(`/products/${id}`, controller.signal), getJson(`/products/${id}/comparison`, controller.signal),
        ]);
        html = productMarkup(product, comparison, params);
      }
    } else if (screen === "review") {
      const response = await getJson("/products?limit=1", controller.signal);
      const product = response.items[0];
      const comparison = product ? await getJson(`/products/${product.id}/comparison`, controller.signal) : null;
      if (version !== renderVersion) return;
      reviewProduct = product;
      reviewOffers = comparison?.offers ?? [];
      reviewSelection = 0;
      html = reviewMarkup();
    } else if (["catalog", "density", "empty"].includes(screen)) {
      const query = new URLSearchParams({ limit: "50" });
      if (params.get("q")) query.set("search", params.get("q"));
      if (Object.hasOwn(brands, params.get("marketplace"))) query.set("marketplace", params.get("marketplace"));
      const payload = screen === "empty" ? { items: [], next_cursor: null } : await getJson(`/products?${query}`, controller.signal);
      if (version !== renderVersion) return;
      catalogCache = { ...payload, query, params };
      html = catalogMarkup(payload.items, params, payload.next_cursor);
      if (screen === "empty") html = '<p class="notice neutral">Демонстрация пустой выдачи. Настоящий каталог не изменён.</p>' + html;
    } else {
      html = errorMarkup({ status: 404 });
    }
    if (version === renderVersion) show(html, { focus, scroll });
  } catch (error) {
    if (version !== renderVersion) return;
    const status = controller.signal.reason === "timeout" ? 504 : error.status ?? 0;
    show(errorMarkup({ status, requestId: error.requestId }), { focus, scroll });
  } finally {
    window.clearTimeout(timer);
  }
}

async function loadMore() {
  const current = catalogCache;
  if (!current?.next_cursor) return;
  const version = renderVersion;
  const button = main.querySelector('[data-action="more"]');
  button.disabled = true;
  const query = new URLSearchParams(current.query);
  query.set("cursor", current.next_cursor);
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 15000);
  try {
    const payload = await getJson(`/products?${query}`, controller.signal);
    if (version !== renderVersion) return;
    const known = new Set(current.items.map(item => item.id));
    current.items.push(...payload.items.filter(item => !known.has(item.id)));
    current.next_cursor = payload.next_cursor;
    const scroll = window.scrollY;
    show(catalogMarkup(current.items, current.params, current.next_cursor), { scroll });
  } catch {
    if (version === renderVersion) {
      button.disabled = false;
      toast("Не удалось загрузить следующую страницу. Уже загруженные товары сохранены.");
    }
  } finally {
    window.clearTimeout(timer);
  }
}

function navigate(url) {
  history.replaceState({ scroll: window.scrollY }, "", location.href);
  history.pushState({ scroll: 0 }, "", url);
  if (dialog.open) dialog.close();
  void render();
}

function openDialog(title, content) {
  document.querySelector("#dialogTitle").textContent = title;
  dialogBody.innerHTML = content;
  dialogAnimation?.cancel();
  if (!dialog.open) dialog.showModal();
  if (!reducedMotion.matches) dialogAnimation = dialog.animate([
    { opacity: 0, transform: "translateY(8px) scale(.98)" }, { opacity: 1, transform: "none" },
  ], { duration: 200, easing: "cubic-bezier(.2,0,.2,1)" });
}

function about() {
  openDialog("Найти. Сравнить. Выбрать.", `<ol><li>Найдите игру или сервис в подключённом каталоге.</li><li>Сравните предложения одного варианта товара. Разные валюты не пересчитываем.</li><li>Проверьте условия и перейдите на сайт площадки для покупки.</li></ol><p>Сейчас это новый визуальный предпросмотр. Каталог и цены читаются из действующего API. Покупок, сохранения решений и выдачи прав здесь нет.</p><p>Иллюстрации созданы для оформления и не являются официальными обложками игр.</p>`);
}

function tools() {
  openDialog("Предпросмотр интерфейса", `<p>Проверка экранов и будущей навигации. Переключатель роли не меняет реальные права доступа.</p>
    <span class="tools-label">Экраны</span><div class="screen-links"><a data-nav href="${root}">Витрина</a><a data-nav href="${root}?screen=review">Проверка объявления</a><a href="${root}/not-found">404</a><a data-nav href="${root}?screen=error">Сбой</a><a data-nav href="${root}?screen=offline">Нет сети</a><a data-nav href="${root}?screen=empty">Нет товаров</a><a data-nav href="${root}?screen=density">50 карточек</a></div>
    <label class="tools-label" for="previewRole">Роль в макете</label><select class="role-select" id="previewRole">${Object.entries(roles).map(([id, [title]]) => `<option value="${id}" ${id === previewRole ? "selected" : ""}>${title}</option>`).join("")}</select>
    <p class="role-note" id="roleNote">${roles[previewRole][1]}</p><p class="subtle">Серверная матрица четырёх продуктовых ролей и постоянный журнал ошибок ещё не подключены к новому интерфейсу.</p>`);
}

function toast(message) {
  const element = document.querySelector("#toast");
  window.clearTimeout(toastTimeout);
  element.textContent = message;
  element.hidden = false;
  toastTimeout = window.setTimeout(() => { element.hidden = true; }, 6000);
}

document.querySelector("#searchForm").addEventListener("submit", (event) => {
  event.preventDefault();
  navigate(link(searchInput.value.trim() ? { q: searchInput.value.trim() } : {}));
});
document.querySelector("#aboutButton").addEventListener("click", about);
document.querySelector("#previewTools").addEventListener("click", tools);
document.querySelector("#profileButton").addEventListener("click", tools);
document.querySelector("#closeDialog").addEventListener("click", () => dialog.close());
document.addEventListener("error", (event) => {
  if (event.target instanceof HTMLImageElement && event.target.classList.contains("market-logo")) {
    event.target.hidden = true;
    event.target.parentElement.classList.add("image-unavailable");
  }
}, true);
document.addEventListener("click", (event) => {
  const anchor = event.target.closest("a[data-nav]");
  if (anchor && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0) {
    event.preventDefault();
    navigate(anchor.href);
    return;
  }
  const button = event.target.closest("[data-action]");
  if (button?.dataset.action === "retry") void render();
  if (button?.dataset.action === "about") about();
  if (button?.dataset.action === "more") void loadMore();
  const selected = event.target.closest("[data-review-index]");
  if (selected) {
    reviewSelection = Number(selected.dataset.reviewIndex);
    show(reviewMarkup(), { scroll: window.scrollY });
    main.querySelector(`[data-review-index="${reviewSelection}"]`).focus({ preventScroll: true });
  }
  if (event.target.closest("[data-confirm-preview]")) {
    dialog.close();
    toast("Решение просмотрено. Это макет: данные и рабочая очередь не изменены.");
  }
});
document.addEventListener("change", (event) => {
  if (event.target.id === "reviewSelect") {
    reviewSelection = Number(event.target.value);
    show(reviewMarkup(), { scroll: window.scrollY });
    document.querySelector("#reviewSelect").focus({ preventScroll: true });
  }
  if (event.target.id === "previewRole" && Object.hasOwn(roles, event.target.value)) {
    previewRole = event.target.value;
    document.querySelector("#roleLabel").textContent = roles[previewRole][0];
    document.querySelector("#roleNote").textContent = roles[previewRole][1];
  }
  if (event.target.name === "decision") {
    const optional = event.target.value === "create";
    document.querySelector("#facts").required = !optional;
    document.querySelector("#factsRequired").textContent = optional ? "· необязательно" : "· обязательно";
    document.querySelector("#factsHelp").textContent = optional ? "Можно пояснить, чем новый вариант отличается от показанного товара." : event.target.value === "reject" ? "Укажите различия, из-за которых объявления нельзя объединить." : "Укажите совпавшие платформу, издание и способ активации. Только факты из объявления.";
    document.querySelector("#factsError").hidden = true;
    document.querySelector("#facts").removeAttribute("aria-invalid");
  }
});
document.addEventListener("submit", (event) => {
  if (event.target.id !== "decisionForm") return;
  event.preventDefault();
  const form = event.target;
  const decision = new FormData(form).get("decision");
  const facts = form.querySelector("#facts");
  if (decision !== "create" && !facts.value.trim()) {
    document.querySelector("#factsError").hidden = false;
    facts.setAttribute("aria-invalid", "true");
    facts.focus();
    return;
  }
  const action = { link: "Связать с указанным товаром", create: "Создать отдельный товар", reject: "Отклонить соответствие" }[decision];
  const offer = reviewOffers[reviewSelection];
  openDialog("Проверьте решение", `<span class="eyebrow">Только демонстрация</span><h3>${action}</h3><p>Объявление: ${escapeHtml(offer.title)}<br>ID: ${escapeHtml(offer.external_id)}</p>
    ${decision === "create" ? '<p>Будет создан новый товар. Связь с показанным товаром не устанавливается.</p>' : `<p>Товар: <strong>${escapeHtml(reviewProduct.name)}</strong><br>ID: ${escapeHtml(reviewProduct.id)}</p>`}
    ${facts.value.trim() ? `<p>Основание: ${escapeHtml(facts.value.trim())}</p>` : ""}
    <p class="notice neutral">В этом предпросмотре запись в базу данных отключена.</p><button class="primary" data-confirm-preview type="button">Завершить просмотр решения</button>`);
});
window.addEventListener("popstate", (event) => {
  if (dialog.open) dialog.close();
  void render({ scroll: event.state?.scroll ?? 0 });
});
document.addEventListener("keydown", (event) => {
  if (event.key === "/" && !dialog.open && !event.ctrlKey && !event.metaKey && !event.altKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    event.preventDefault();
    searchInput.focus();
  }
});
reducedMotion.addEventListener("change", () => {
  if (reducedMotion.matches) { pageAnimation?.cancel(); dialogAnimation?.cancel(); }
});
void render({ focus: false });
