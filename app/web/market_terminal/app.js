import { brands, brandMark, handleImageError, infoFor, offerFootprint, productImage, money as offerMoney } from "/terminal/preview/presentation.js";

const api = "/api/v1/public";
const requestTimeoutMs = 15_000;

const elements = {
  apiStatus: document.querySelector("#apiStatus"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  searchButton: document.querySelector("#searchButton"),
  marketplaceFilter: document.querySelector("#marketplaceFilter"),
  sortFilter: document.querySelector("#sortFilter"),
  minPriceInput: document.querySelector("#minPriceInput"),
  maxPriceInput: document.querySelector("#maxPriceInput"),
  refreshButton: document.querySelector("#refreshButton"),
  catalogTitle: document.querySelector("#catalogTitle"),
  productCount: document.querySelector("#productCount"),
  dropCount: document.querySelector("#dropCount"),
  productGrid: document.querySelector("#productGrid"),
  catalogPagination: document.querySelector("#catalogPagination"),
  loadMoreButton: document.querySelector("#loadMoreButton"),
  catalogPageStatus: document.querySelector("#catalogPageStatus"),
  categoryList: document.querySelector("#categoryList"),
  changeList: document.querySelector("#changeList"),
  detailPanel: document.querySelector("#details"),
  detailTitle: document.querySelector("#detailTitle"),
  detailMeta: document.querySelector("#detailMeta"),
  offerList: document.querySelector("#offerList"),
  comparisonCard: document.querySelector("#comparisonCard"),
  historyCard: document.querySelector("#historyCard"),
  main: document.querySelector("#main"),
  catalogView: document.querySelector("#catalogView"),
  filters: document.querySelector("#catalogFilters"),
  filtersButton: document.querySelector("#filtersButton"),
  marketplaceNav: document.querySelector("#marketplaceNav"),
  back: document.querySelector("#backToCatalog"),
};
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
let pageAnimation;
let locationSearch = window.location.search;

document.addEventListener("error", handleImageError, true);
elements.filtersButton.addEventListener("click", () => setFiltersOpen(elements.filters.hidden));
document.querySelector("#retryDetails").addEventListener("click", () => void selectProduct(state.selectedProductId, false));
elements.back.addEventListener("click", event => {
  if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  if (history.state?.fromCatalog) history.back();
  else {
    state.selectedProductId = null;
    syncLocationState("replace");
    setView(false, true);
    void loadDashboard();
  }
});
document.addEventListener("keydown", event => {
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
    event.preventDefault();
    elements.searchInput.focus();
  }
});
reducedMotion.addEventListener("change", () => { if (reducedMotion.matches) pageAnimation?.cancel(); });

function setFiltersOpen(open) {
  elements.filters.hidden = !open;
  elements.filtersButton.setAttribute("aria-expanded", String(open));
}

function setView(product, focus = false) {
  elements.catalogView.hidden = product;
  elements.detailPanel.hidden = !product;
  if (!product) document.title = "Каталог · Market Terminal";
  const backUrl = new URL(location.href);
  backUrl.searchParams.delete("product");
  backUrl.hash = "";
  elements.back.href = backUrl.href;
  pageAnimation?.cancel();
  if (!reducedMotion.matches) pageAnimation = elements.main.animate([
    { opacity: .65, transform: "translateY(10px)" }, { opacity: 1, transform: "translateY(0)" },
  ], { duration: 220, easing: "cubic-bezier(.25,1,.5,1)" });
  if (focus) {
    elements.main.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  }
}

function renderMarketplaceNav() {
  elements.marketplaceNav.innerHTML = [["", "Все площадки"], ...Object.entries(brands)].map(([value, name]) => `<button type="button" data-marketplace="${value}" aria-pressed="${elements.marketplaceFilter.value === value}">${value ? brandMark(value) : ""}${name}</button>`).join("");
  for (const button of elements.marketplaceNav.querySelectorAll("button")) button.addEventListener("click", () => {
    elements.marketplaceFilter.value = button.dataset.marketplace;
    void runProductSearch(elements.searchInput.value.trim());
  });
}

const state = {
  products: [],
  categories: [],
  priceChanges: [],
  selectedProductId: null,
  selectedCategoryCode: "",
  selectedCategoryName: "",
  isBusy: false,
  isLoadingMore: false,
  nextCatalogCursor: null,
  catalogPageMessage: "",
  catalogRequestVersion: 0,
  categoryRequestVersion: 0,
  priceChangeRequestVersion: 0,
  detailRequestVersion: 0,
};

elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void runProductSearch(elements.searchInput.value.trim());
});

elements.refreshButton.addEventListener("click", () => {
  void loadDashboard();
});

elements.loadMoreButton.addEventListener("click", () => {
  void loadMoreProducts();
});

elements.marketplaceFilter.addEventListener("change", () => {
  void runProductSearch(elements.searchInput.value.trim());
});

elements.sortFilter.addEventListener("change", () => {
  void runProductSearch(elements.searchInput.value.trim());
});

for (const input of [elements.minPriceInput, elements.maxPriceInput]) {
  input.addEventListener("input", () => {
    elements.maxPriceInput.setCustomValidity("");
  });
}

window.addEventListener("popstate", async (event) => {
  // In-page anchors must not reload the catalog or race with opening a product.
  if (window.location.search === locationSearch) return;
  locationSearch = window.location.search;
  restoreLocationState();
  await loadDashboard();
  elements.main.focus({ preventScroll: true });
  window.scrollTo({ top: event.state?.scroll ?? 0, behavior: "instant" });
});

restoreLocationState();
void loadDashboard().finally(() => window.terminalPageReady?.());

async function loadDashboard() {
  if (!priceRangeIsValid()) {
    return;
  }
  const requestVersion = beginCatalogRequest();
  setView(Boolean(state.selectedProductId));
  renderMarketplaceNav();
  setDashboardBusy(true);
  setApiStatus("Подключение");
  await Promise.all([
    loadProducts(elements.searchInput.value.trim(), requestVersion),
    loadCategories(),
    loadPriceChanges(),
  ]);
  if (isCurrentCatalogRequest(requestVersion)) {
    setDashboardBusy(false);
    updateSummary();
  }
}

async function runProductSearch(search) {
  if (!priceRangeIsValid()) {
    return;
  }
  elements.searchInput.value = search;
  state.detailRequestVersion += 1;
  state.selectedProductId = null;
  syncLocationState("replace");
  setView(false, true);
  renderMarketplaceNav();
  const requestVersion = beginCatalogRequest();
  setDashboardBusy(true);
  await loadProducts(search, requestVersion);
  if (isCurrentCatalogRequest(requestVersion)) {
    setDashboardBusy(false);
  }
}

async function loadProducts(search, requestVersion, append = false) {
  try {
    const query = productQuery(search, append ? state.nextCatalogCursor : null);
    const marketplace = elements.marketplaceFilter.value;

    const payload = await getJson(`/products?${query.toString()}`);
    if (!isCurrentCatalogRequest(requestVersion)) {
      return;
    }
    const incomingProducts = payload.items ?? [];
    state.products = append
      ? appendUniqueProducts(state.products, incomingProducts)
      : incomingProducts;
    state.nextCatalogCursor = payload.next_cursor ?? null;
    state.catalogPageMessage = "";
    elements.catalogTitle.textContent = catalogTitle(
      search,
      marketplace,
      state.selectedCategoryName,
    );
    renderProducts(state.products);
    updateCatalogPagination();
    updateSummary();
    setApiStatus("Подключено");

    if (append) {
      return;
    }
    const preferredProductId = state.selectedProductId;
    if (preferredProductId) {
      await selectProduct(preferredProductId, false);
    } else {
      setView(false);
    }
  } catch (error) {
    if (!isCurrentCatalogRequest(requestVersion)) {
      return;
    }
    if (append) {
      setApiStatus("Не удалось загрузить следующую страницу", true);
      state.catalogPageMessage = "Повторите загрузку.";
      return;
    }
    state.products = [];
    state.nextCatalogCursor = null;
    updateCatalogPagination();
    updateSummary();
    setApiStatus("API недоступен", true);
    renderEmpty(elements.productGrid, errorMessage(error));
    clearProductDetails("Данные временно недоступны");
  }
}

function productQuery(search, cursor) {
  const query = new URLSearchParams({ limit: "12" });
  const marketplace = elements.marketplaceFilter.value;
  const minPrice = elements.minPriceInput.value.trim();
  const maxPrice = elements.maxPriceInput.value.trim();
  const [sort, direction] = elements.sortFilter.value.split(":", 2);
  if (search) {
    query.set("q", search);
  }
  if (marketplace) {
    query.set("marketplace", marketplace);
  }
  if (state.selectedCategoryName) {
    query.set("category", state.selectedCategoryName);
  }
  if (minPrice) {
    query.set("min_price", minPrice);
  }
  if (maxPrice) {
    query.set("max_price", maxPrice);
  }
  if (cursor) {
    query.set("cursor", cursor);
  }
  query.set("sort", sort);
  query.set("direction", direction);
  return query;
}

async function loadMoreProducts() {
  if (state.isBusy || state.isLoadingMore || !state.nextCatalogCursor) {
    return;
  }
  state.isLoadingMore = true;
  state.catalogPageMessage = "";
  updateCatalogPagination();
  const requestVersion = state.catalogRequestVersion;
  await loadProducts(
    elements.searchInput.value.trim(),
    requestVersion,
    true,
  );
  if (isCurrentCatalogRequest(requestVersion)) {
    state.isLoadingMore = false;
    updateCatalogPagination();
  }
}

function appendUniqueProducts(current, incoming) {
  const knownIds = new Set(current.map((product) => product.id));
  return current.concat(
    incoming.filter((product) => {
      if (knownIds.has(product.id)) {
        return false;
      }
      knownIds.add(product.id);
      return true;
    }),
  );
}

function updateCatalogPagination() {
  const canLoadMore = Boolean(state.nextCatalogCursor);
  elements.catalogPagination.hidden = !canLoadMore && !state.isLoadingMore;
  elements.loadMoreButton.disabled = state.isBusy || state.isLoadingMore;
  elements.loadMoreButton.textContent = state.isLoadingMore
    ? "Загрузка"
    : "Показать ещё";
  elements.catalogPageStatus.textContent = state.isLoadingMore
    ? "Загружаем следующую страницу"
    : state.catalogPageMessage || `Показано: ${state.products.length}`;
}

function beginCatalogRequest() {
  state.isLoadingMore = false;
  state.catalogPageMessage = "";
  state.catalogRequestVersion += 1;
  return state.catalogRequestVersion;
}

function isCurrentCatalogRequest(requestVersion) {
  return requestVersion === state.catalogRequestVersion;
}

async function loadCategories() {
  const requestVersion = beginCategoryRequest();
  try {
    const payload = await getJson("/categories?limit=10");
    if (!isCurrentCategoryRequest(requestVersion)) {
      return;
    }
    const categories = payload.items ?? [];
    state.categories = categories;
    state.selectedCategoryCode =
      categories.find(
        (category) => category.name === state.selectedCategoryName,
      )?.code ?? "";
    updateSummary();
    if (categories.length === 0) {
      renderEmpty(elements.categoryList, "Категории пока недоступны.");
      return;
    }
    renderCategories(categories);
  } catch (error) {
    if (!isCurrentCategoryRequest(requestVersion)) {
      return;
    }
    state.categories = [];
    updateSummary();
    renderEmpty(elements.categoryList, errorMessage(error));
  }
}

function beginCategoryRequest() {
  state.categoryRequestVersion += 1;
  return state.categoryRequestVersion;
}

function isCurrentCategoryRequest(requestVersion) {
  return requestVersion === state.categoryRequestVersion;
}

async function loadPriceChanges() {
  const requestVersion = beginPriceChangeRequest();
  try {
    const payload = await getJson("/price-changes?limit=6");
    if (!isCurrentPriceChangeRequest(requestVersion)) {
      return;
    }
    const changes = payload.items ?? [];
    state.priceChanges = changes;
    updateSummary();
    if (changes.length === 0) {
      renderEmpty(elements.changeList, "Снижений цены пока нет.");
      return;
    }
    renderPriceChanges(changes);
  } catch (error) {
    if (!isCurrentPriceChangeRequest(requestVersion)) {
      return;
    }
    state.priceChanges = [];
    updateSummary();
    renderEmpty(elements.changeList, errorMessage(error));
  }
}

function beginPriceChangeRequest() {
  state.priceChangeRequestVersion += 1;
  return state.priceChangeRequestVersion;
}

function isCurrentPriceChangeRequest(requestVersion) {
  return requestVersion === state.priceChangeRequestVersion;
}

async function selectProduct(productId, updateLocation = true) {
  if (!productId) {
    state.detailRequestVersion += 1;
    state.selectedProductId = null;
    clearProductDetails("Товар не выбран");
    return;
  }

  const requestVersion = state.detailRequestVersion + 1;
  state.detailRequestVersion = requestVersion;
  state.selectedProductId = productId;
  if (updateLocation) {
    syncLocationState("push");
  }
  setView(true, updateLocation);
  renderProducts(state.products);
  prepareProductDetails(productId);

  try {
    const [detail, offers, comparison, history] = await Promise.allSettled(
      [
        getJson(`/products/${productId}`),
        getJson(`/products/${productId}/offers?limit=20`),
        getJson(`/products/${productId}/comparison`),
        getJson(`/products/${productId}/price-history?period=all&limit=50`),
      ],
    );
    if (!isCurrentDetailRequest(requestVersion, productId)) {
      return;
    }

    renderDetailSummary(detail, productId);
    renderDetailResult(
      offers,
      elements.offerList,
      (payload) => renderOffers(payload.items ?? []),
      "Предложения недоступны",
    );
    renderDetailResult(
      comparison,
      elements.comparisonCard,
      renderComparison,
      "Сравнение недоступно",
    );
    renderDetailResult(
      history,
      elements.historyCard,
      (payload) => renderHistory(payload.items ?? []),
      "История цены недоступна",
    );
  } catch (error) {
    if (!isCurrentDetailRequest(requestVersion, productId)) {
      return;
    }
    clearProductDetails("Информация о товаре недоступна");
    renderEmpty(elements.offerList, errorMessage(error));
  } finally {
    if (isCurrentDetailRequest(requestVersion, productId)) {
      setProductDetailsBusy(false);
    }
  }
}

function renderDetailSummary(result, productId) {
  if (result.status === "fulfilled") {
    const detail = result.value;
    const art = infoFor(detail);
    elements.detailTitle.textContent = art.title;
    document.querySelector("#detailSubtitle").textContent = art.subtitle;
    document.querySelector("#originalName").textContent = detail.name;
    document.querySelector("#detailArtwork").innerHTML = productImage(art, "product-cover", 220);
    elements.detailMeta.innerHTML = offerFootprint(detail);
    document.title = `${art.title} · Market Terminal`;
    return;
  }

  const product = state.products.find((item) => item.id === productId);
  elements.detailTitle.textContent =
    product?.name ?? "Информация о товаре недоступна";
  elements.detailMeta.textContent =
    `Краткая информация недоступна: ${errorMessage(result.reason)}`;
}

function renderDetailResult(result, target, renderer, unavailableLabel) {
  if (result.status === "fulfilled") {
    renderer(result.value);
    return;
  }
  renderEmpty(target, `${unavailableLabel}: ${errorMessage(result.reason)}`);
}

function prepareProductDetails(productId) {
  const product = state.products.find((item) => item.id === productId);
  elements.detailTitle.textContent = product?.name ?? "Загрузка товара";
  elements.detailMeta.textContent = "Загружаем данные площадок";
  document.querySelector("#detailSubtitle").textContent = "";
  document.querySelector("#originalName").textContent = product?.name ?? "";
  document.querySelector("#detailArtwork").innerHTML = productImage(infoFor(product ?? { id: productId, name: "Товар" }), "product-cover", 220);
  renderEmpty(elements.offerList, "Загружаем предложения...");
  renderEmpty(elements.comparisonCard, "Готовим сравнение...");
  renderEmpty(elements.historyCard, "Загружаем историю цены...");
  setProductDetailsBusy(true);
}

function isCurrentDetailRequest(requestVersion, productId) {
  return (
    requestVersion === state.detailRequestVersion &&
    productId === state.selectedProductId
  );
}

function setProductDetailsBusy(isBusy) {
  elements.detailPanel.setAttribute("aria-busy", String(isBusy));
}

function renderProducts(products) {
  elements.productGrid.classList.toggle("compact", products.length <= 2);
  if (products.length === 0) {
    renderEmpty(elements.productGrid, "Товары пока недоступны.");
    return;
  }

  elements.productGrid.innerHTML = products
    .map((product) => {
      const bestOffer = product.best_offer;
      const art = infoFor(product);
      const url = new URL(location.href);
      url.hash = "";
      url.searchParams.set("product", product.id);
      return `
        <a class="product-card" href="${escapeHtml(url.href)}" data-product-id="${escapeHtml(product.id)}">
          <div class="card-image">${productImage(art, "", 512, true)}<span class="art-label">${escapeHtml(art.label)}</span></div>
          <div class="card-copy"><h3>${escapeHtml(art.title)}</h3><p>${escapeHtml(art.subtitle)}</p>
            <span class="card-price">${bestOffer ? moneyHtml(bestOffer.price, bestOffer.currency) : "Все цены в сравнении"} <span aria-hidden="true">↗</span></span>
            ${offerFootprint(product)}
          </div>
        </a>
      `;
    })
    .join("");

  for (const card of elements.productGrid.querySelectorAll(".product-card")) {
    card.addEventListener("click", (event) => {
      if (event.button || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      void selectProduct(card.dataset.productId ?? null);
    });
  }
}

function renderCategories(categories) {
  const disabled = state.isBusy ? " disabled" : "";
  const allActive = state.selectedCategoryName ? "" : " active";
  const categoryButtons = categories
    .map((category, index) => {
      const active =
        category.code === state.selectedCategoryCode ? " active" : "";
      return `
        <button
          class="category-filter${active}"
          type="button"
          data-category-index="${index}"
          aria-pressed="${String(Boolean(active))}"
          ${disabled}
        >
          <strong>${escapeHtml(category.name)}</strong>
          <small>${escapeHtml(category.product_count)}</small>
        </button>
      `;
    })
    .join("");

  elements.categoryList.innerHTML = `
    <button
      class="category-filter${allActive}"
      type="button"
      data-category-index="-1"
      aria-pressed="${String(Boolean(allActive))}"
      ${disabled}
    >
      <strong>Все товары</strong>
      <small>Сбросить</small>
    </button>
    ${categoryButtons}
  `;

  for (const button of elements.categoryList.querySelectorAll(".category-filter")) {
    button.addEventListener("click", () => {
      const index = Number(button.dataset.categoryIndex);
      selectCategory(index >= 0 ? categories[index] : null);
    });
  }
}

function renderPriceChanges(changes) {
  const disabled = state.isBusy ? " disabled" : "";
  elements.changeList.innerHTML = changes
    .map((change, index) => {
      const content = `
        <span class="change-topline">
          <strong class="change-name">${escapeHtml(change.product_name)}</strong>
          <span class="discount-badge">-${formatPercent(change.discount_percent)}</span>
        </span>
        <small>${escapeHtml(change.marketplace)} / ${formatDate(change.changed_at)}</small>
        <span class="change-prices">
          <del>${moneyHtml(change.old_price, change.currency)}</del>
          <span aria-hidden="true">&rarr;</span>
          <strong>${moneyHtml(change.new_price, change.currency)}</strong>
        </span>
      `;
      if (!change.product_id) {
        return `<article class="change">${content}</article>`;
      }
      return `
        <button
          class="change change-action"
          type="button"
          data-change-index="${index}"
          aria-label="Открыть сравнение для ${escapeHtml(change.product_name)}"
          ${disabled}
        >
          ${content}
        </button>
      `;
    })
    .join("");

  for (const button of elements.changeList.querySelectorAll(".change-action")) {
    button.addEventListener("click", () => {
      const change = changes[Number(button.dataset.changeIndex)];
      if (!change?.product_id) {
        return;
      }
      void selectProduct(change.product_id);
      elements.detailTitle.focus({ preventScroll: true });
      elements.detailPanel.scrollIntoView({ block: "start" });
    });
  }
}

function selectCategory(category) {
  state.selectedCategoryCode = category?.code ?? "";
  state.selectedCategoryName = category?.name ?? "";
  renderCategories(state.categories);
  void runProductSearch(elements.searchInput.value.trim());
}

function renderOffers(offers) {
  if (offers.length === 0) {
    renderEmpty(elements.offerList, "Для этого товара пока нет предложений.");
    return;
  }

  elements.offerList.innerHTML = offers
    .map(
      (offer) => `
        <article class="offer-row">
          <div class="offer-market">${brandMark(offer.marketplace)}${escapeHtml(brands[offer.marketplace] ?? offer.marketplace)}</div>
          <div class="offer-description"><p class="offer-name">${escapeHtml(offer.title ?? "Предложение без названия")}</p><p class="offer-seller">${escapeHtml(offer.seller_name ?? "Продавец не указан")}</p></div>
          <span class="offer-price">${moneyHtml(offer.price, offer.currency)}</span>
          ${escapeAttribute(offer.url ?? "") !== "#" ? `<a class="secondary" href="${escapeAttribute(offer.url)}" target="_blank" rel="noopener noreferrer">На площадку <span aria-hidden="true">↗</span></a>` : '<span class="subtle">Ссылка недоступна</span>'}
        </article>
      `,
    )
    .join("");
}

function renderComparison(comparison) {
  if (comparison.status === "currency_mismatch") {
    elements.comparisonCard.innerHTML = '<p class="notice">Цены в разных валютах. Показываем их без пересчёта и не выбираем общее самое дешёвое предложение.</p>';
    return;
  }
  if (!comparison.best_offer) {
    renderEmpty(elements.comparisonCard, "Сопоставимых цен пока нет.");
    return;
  }

  const differences = comparison.differences ?? [];
  elements.comparisonCard.innerHTML = `
    <p class="eyebrow">${escapeHtml(comparisonStatusLabel(comparison.status))}</p>
    <h3>Лучшее предложение</h3>
    <p class="price">${moneyHtml(comparison.best_offer.price, comparison.best_offer.currency)}</p>
    <p>${escapeHtml(comparison.best_offer.marketplace)} / ${escapeHtml(comparison.best_offer.title ?? "")}</p>
    ${
      differences.length
        ? `<div class="comparison-list">
            ${differences
              .map(
                (difference) => `
                  <span class="comparison-row">
                    <strong>${escapeHtml(difference.offer.marketplace)}</strong>
                    <small>${escapeHtml(differenceLabel(difference))}</small>
                  </span>
                `,
              )
              .join("")}
          </div>`
        : '<p class="soft-label">Доступно только одно сопоставимое предложение.</p>'
    }
  `;
}

function renderHistory(points) {
  if (points.length === 0) {
    renderEmpty(elements.historyCard, "История цены пока не накоплена.");
    return;
  }

  const seriesByCurrency = new Map();
  for (const point of points) {
    const currency = point.currency || "Валюта не указана";
    const series = seriesByCurrency.get(currency) ?? [];
    series.push(point);
    seriesByCurrency.set(currency, series);
  }

  elements.historyCard.innerHTML = Array.from(seriesByCurrency.entries())
    .map(([currency, series]) => renderHistorySeries(currency, series))
    .join("");
}

function renderHistorySeries(currency, points) {
  const ordered = [...points].sort(
    (left, right) =>
      new Date(left.collected_at).getTime() -
      new Date(right.collected_at).getTime(),
  );
  const prices = ordered.map((point) => Number(point.price));
  const lowest = Math.min(...prices);
  const highest = Math.max(...prices);
  const lowestPoint = ordered[prices.indexOf(lowest)];
  const highestPoint = ordered[prices.indexOf(highest)];
  const range = highest - lowest;
  const latest = ordered[ordered.length - 1];
  const marketplaces = new Set(ordered.map((point) => point.marketplace)).size;

  return `
    <section class="history-series">
      <header class="history-heading">
        <strong>${escapeHtml(currency)}</strong>
        <small>${escapeHtml(countLabel(ordered.length, "точка", "точки", "точек"))} / ${escapeHtml(countLabel(marketplaces, "площадка", "площадки", "площадок"))}</small>
      </header>
      <div class="history-bars" aria-label="${escapeHtml(`История цены в ${currency}`)}">
        ${ordered
          .map((point) => {
            const price = Number(point.price);
            const heightClass = historyHeightClass(price, lowest, range);
            const label = `${point.marketplace} / ${money(point.price, point.currency)} / ${formatDate(point.collected_at)}`;
            return `<span class="history-bar ${heightClass}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}"></span>`;
          })
          .join("")}
      </div>
      <div class="history-stats">
        <span><small>Минимум</small><strong>${moneyHtml(lowestPoint.price, currency)}</strong></span>
        <span><small>Максимум</small><strong>${moneyHtml(highestPoint.price, currency)}</strong></span>
        <span><small>Сейчас</small><strong>${moneyHtml(latest.price, currency)}</strong></span>
      </div>
    </section>
  `;
}

function historyHeightClass(price, lowest, range) {
  const height = range === 0 ? 60 : 20 + ((price - lowest) / range) * 80;
  const step = Math.round(height / 10) * 10;
  return `history-height-${Math.min(100, Math.max(20, step))}`;
}

function clearProductDetails(message) {
  elements.detailTitle.textContent = message;
  elements.detailMeta.textContent = "Ожидаем данные";
  renderEmpty(elements.offerList, "Выберите доступный товар.");
  renderEmpty(elements.comparisonCard, "Здесь появится сравнение.");
  renderEmpty(elements.historyCard, "Здесь появится история цены.");
  setProductDetailsBusy(false);
}

async function getJson(path) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(
    () => controller.abort(),
    requestTimeoutMs,
  );

  try {
    const response = await fetch(`${api}${path}`, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    const text = await response.text();
    const body = parsePublicJson(
      text,
      response.headers.get("content-type") ?? "",
    );
    if (!response.ok) {
      throw new Error(publicApiErrorMessage(body, response.status));
    }
    if (body === null) {
      throw new Error("Сервис вернул некорректный ответ.");
    }
    return body;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error("Время ожидания истекло. Попробуйте ещё раз.");
    }
    if (error instanceof TypeError) {
      throw new Error("Не удалось подключиться. Проверьте соединение и попробуйте ещё раз.");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

function parsePublicJson(text, contentType) {
  if (!text || !isJsonContentType(contentType)) {
    return null;
  }
  try {
    const body = JSON.parse(text);
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      return null;
    }
    return body;
  } catch {
    return null;
  }
}

function isJsonContentType(contentType) {
  const mediaType = contentType.split(";", 1)[0].trim().toLowerCase();
  return mediaType === "application/json" || mediaType.endsWith("+json");
}

function publicApiErrorMessage(body, status) {
  for (const value of [body?.error?.message, body?.detail]) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return `Не удалось получить данные (ошибка ${status}).`;
}

function setApiStatus(label, isError = false) {
  elements.apiStatus.textContent = label;
  elements.apiStatus.classList.toggle("error", isError);
}

function setDashboardBusy(isBusy) {
  state.isBusy = isBusy;
  document.querySelector(".shell").setAttribute("aria-busy", String(isBusy));
  elements.refreshButton.disabled = isBusy;
  elements.searchButton.disabled = isBusy;
  elements.marketplaceFilter.disabled = isBusy;
  elements.sortFilter.disabled = isBusy;
  elements.minPriceInput.disabled = isBusy;
  elements.maxPriceInput.disabled = isBusy;
  elements.loadMoreButton.disabled = isBusy || state.isLoadingMore;
  for (const button of elements.marketplaceNav.querySelectorAll("button")) button.disabled = isBusy;
  for (const button of elements.categoryList.querySelectorAll(".category-filter")) {
    button.disabled = isBusy;
  }
  for (const button of elements.changeList.querySelectorAll(".change-action")) {
    button.disabled = isBusy;
  }
  elements.refreshButton.textContent = isBusy ? "Загрузка" : "Обновить";
}

function updateSummary() {
  const count = `${state.products.length}${state.nextCatalogCursor ? "+" : ""}`;
  elements.productCount.textContent = count;
  elements.productCount.setAttribute("aria-label", `Товаров загружено: ${count}`);
  elements.dropCount.textContent = String(state.priceChanges.length);
  document.querySelector("#catalogHero").hidden = Boolean(elements.searchInput.value || elements.marketplaceFilter.value || state.selectedCategoryName);
}

function renderEmpty(target, message) {
  target.innerHTML = `<p class="empty-state">${escapeHtml(message)}</p>`;
}

function restoreLocationState() {
  const params = new URLSearchParams(window.location.search);
  elements.searchInput.value = params.get("q") ?? "";
  setSelectValue(
    elements.marketplaceFilter,
    params.get("marketplace") ?? "",
    "",
  );

  const sort = params.get("sort") ?? "recently_updated";
  const direction = params.get("direction") ?? "desc";
  setSelectValue(
    elements.sortFilter,
    `${sort}:${direction}`,
    "recently_updated:desc",
  );

  elements.minPriceInput.value = params.get("min_price") ?? "";
  elements.maxPriceInput.value = params.get("max_price") ?? "";
  elements.maxPriceInput.setCustomValidity("");
  state.selectedCategoryCode = "";
  state.selectedCategoryName = params.get("category") ?? "";
  state.selectedProductId = params.get("product");
  setFiltersOpen(Boolean(params.get("min_price") || params.get("max_price") || params.get("sort") || params.get("category")));
}

function syncLocationState(mode) {
  const url = new URL(window.location.href);
  const [sort, direction] = elements.sortFilter.value.split(":", 2);

  setUrlParam(url, "q", elements.searchInput.value.trim());
  setUrlParam(url, "marketplace", elements.marketplaceFilter.value);
  setUrlParam(url, "category", state.selectedCategoryName);
  setUrlParam(url, "min_price", elements.minPriceInput.value.trim());
  setUrlParam(url, "max_price", elements.maxPriceInput.value.trim());
  setUrlParam(url, "sort", sort === "recently_updated" ? "" : sort);
  setUrlParam(url, "direction", direction === "desc" ? "" : direction);
  setUrlParam(url, "product", state.selectedProductId ?? "");

  if (url.href === window.location.href) {
    return;
  }
  if (mode === "push") window.history.replaceState({ scroll: window.scrollY }, "", location.href);
  window.history[mode === "push" ? "pushState" : "replaceState"](mode === "push" ? { fromCatalog: true } : {}, "", url);
  locationSearch = url.search;
}

function setSelectValue(select, value, fallback) {
  const isAllowed = Array.from(select.options).some(
    (option) => option.value === value,
  );
  select.value = isAllowed ? value : fallback;
}

function setUrlParam(url, name, value) {
  if (value) {
    url.searchParams.set(name, value);
  } else {
    url.searchParams.delete(name);
  }
}

function priceRangeIsValid() {
  const minPrice = elements.minPriceInput.value;
  const maxPrice = elements.maxPriceInput.value;
  elements.maxPriceInput.setCustomValidity("");

  for (const input of [elements.minPriceInput, elements.maxPriceInput]) {
    if (!input.checkValidity()) {
      setFiltersOpen(true);
      input.reportValidity();
      return false;
    }
  }

  if (minPrice && maxPrice && Number(minPrice) > Number(maxPrice)) {
    setFiltersOpen(true);
    elements.maxPriceInput.setCustomValidity(
      "Максимальная цена должна быть не меньше минимальной.",
    );
    elements.maxPriceInput.reportValidity();
    return false;
  }
  return true;
}

function catalogTitle(search, marketplace, category) {
  if (search) {
    return `Результаты по запросу «${search}»`;
  }
  const filters = [category, marketplaceLabel(marketplace)].filter(Boolean);
  if (filters.length > 0) {
    return `Товары: ${filters.join(" / ")}`;
  }
  return "Каталог";
}

function marketplaceLabel(value) {
  if (!value) {
    return "";
  }
  return {
    ggsel: "GGSEL",
    playerok: "Playerok",
    funpay: "FunPay",
  }[value] ?? value;
}

function comparisonStatusLabel(status) {
  return {
    complete: "Сравнение готово",
    partial: "Частичное сравнение",
    currency_mismatch: "Цены в разных валютах",
    no_valid_prices: "Нет доступных цен",
    unmatched: "Товар не сопоставлен",
  }[status] ?? status;
}

function differenceReasonLabel(reason) {
  return {
    "best offer price unavailable": "Цена лучшего предложения недоступна",
    "best price is zero": "Лучшая цена равна нулю",
    "currency mismatch": "Цена указана в другой валюте",
    "price unavailable": "Цена недоступна",
  }[reason] ?? "Сравнение недоступно";
}

function countLabel(value, one, few, many) {
  const count = Number(value);
  const modulo100 = Math.abs(count) % 100;
  const modulo10 = modulo100 % 10;
  let label = many;
  if (modulo100 < 11 || modulo100 > 14) {
    if (modulo10 === 1) {
      label = one;
    } else if (modulo10 >= 2 && modulo10 <= 4) {
      label = few;
    }
  }
  return `${count} ${label}`;
}

function money(value, currency) {
  return offerMoney({ price: value, currency });
}

function moneyHtml(value, currency) {
  return escapeHtml(money(value, currency));
}

function differenceLabel(difference) {
  if (
    difference.absolute_difference !== null &&
    difference.absolute_difference !== undefined
  ) {
    return `+${money(
      difference.absolute_difference,
      difference.offer.currency,
    )}`;
  }
  return differenceReasonLabel(difference.reason);
}

function formatPercent(value) {
  return `${Number(value).toFixed(1)}%`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Дата не указана";
  }
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

function errorMessage(error) {
  return error instanceof Error
    ? error.message
    : "Не удалось получить данные. Попробуйте ещё раз.";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  const text = String(value);
  if (!text.startsWith("http://") && !text.startsWith("https://")) {
    return "#";
  }
  return escapeHtml(text);
}
