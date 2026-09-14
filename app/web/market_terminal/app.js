const api = "/api/v1/public";

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
  offerCount: document.querySelector("#offerCount"),
  categoryCount: document.querySelector("#categoryCount"),
  dropCount: document.querySelector("#dropCount"),
  productGrid: document.querySelector("#productGrid"),
  categoryList: document.querySelector("#categoryList"),
  changeList: document.querySelector("#changeList"),
  detailTitle: document.querySelector("#detailTitle"),
  detailMeta: document.querySelector("#detailMeta"),
  offerList: document.querySelector("#offerList"),
  comparisonCard: document.querySelector("#comparisonCard"),
  historyCard: document.querySelector("#historyCard"),
};

const state = {
  products: [],
  categories: [],
  priceChanges: [],
  selectedProductId: null,
  selectedCategoryCode: "",
  selectedCategoryName: "",
  isBusy: false,
};

elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void runProductSearch(elements.searchInput.value.trim());
});

elements.refreshButton.addEventListener("click", () => {
  void loadDashboard();
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

window.addEventListener("popstate", () => {
  restoreLocationState();
  void loadDashboard();
});

restoreLocationState();
void loadDashboard();

async function loadDashboard() {
  if (!priceRangeIsValid()) {
    return;
  }
  setDashboardBusy(true);
  setApiStatus("Connecting");
  await Promise.all([
    loadProducts(elements.searchInput.value.trim()),
    loadCategories(),
    loadPriceChanges(),
  ]);
  setDashboardBusy(false);
  updateSummary();
}

async function runProductSearch(search) {
  if (!priceRangeIsValid()) {
    return;
  }
  elements.searchInput.value = search;
  state.selectedProductId = null;
  syncLocationState("replace");
  setDashboardBusy(true);
  await loadProducts(search);
  setDashboardBusy(false);
}

async function loadProducts(search) {
  try {
    const preferredProductId = state.selectedProductId;
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
    query.set("sort", sort);
    query.set("direction", direction);

    const payload = await getJson(`/products?${query.toString()}`);
    state.products = payload.items ?? [];
    elements.catalogTitle.textContent = catalogTitle(
      search,
      marketplace,
      state.selectedCategoryName,
    );
    renderProducts(state.products);
    updateSummary();
    setApiStatus("Online");

    if (preferredProductId) {
      await selectProduct(preferredProductId, false);
    } else if (state.products.length > 0) {
      await selectProduct(state.products[0].id, false);
    } else {
      clearProductDetails("No products found");
    }
  } catch (error) {
    state.products = [];
    updateSummary();
    setApiStatus("API unavailable", true);
    renderEmpty(elements.productGrid, errorMessage(error));
    clearProductDetails("Public API unavailable");
  }
}

async function loadCategories() {
  try {
    const payload = await getJson("/categories?limit=10");
    const categories = payload.items ?? [];
    state.categories = categories;
    state.selectedCategoryCode =
      categories.find(
        (category) => category.name === state.selectedCategoryName,
      )?.code ?? "";
    updateSummary();
    if (categories.length === 0) {
      renderEmpty(elements.categoryList, "No categories available yet.");
      return;
    }
    renderCategories(categories);
  } catch (error) {
    state.categories = [];
    updateSummary();
    renderEmpty(elements.categoryList, errorMessage(error));
  }
}

async function loadPriceChanges() {
  try {
    const payload = await getJson("/price-changes?limit=6");
    const changes = payload.items ?? [];
    state.priceChanges = changes;
    updateSummary();
    if (changes.length === 0) {
      renderEmpty(elements.changeList, "No price drops available yet.");
      return;
    }
    elements.changeList.innerHTML = changes
      .map(
        (change) => `
          <article class="change">
            <strong>${escapeHtml(change.product_name)}</strong>
            <small>
              ${escapeHtml(change.marketplace)} / ${money(change.new_price, change.currency)}
              / ${formatPercent(change.discount_percent)} down
            </small>
          </article>
        `,
      )
      .join("");
  } catch (error) {
    state.priceChanges = [];
    updateSummary();
    renderEmpty(elements.changeList, errorMessage(error));
  }
}

async function selectProduct(productId, updateLocation = true) {
  if (!productId) {
    clearProductDetails("No product selected");
    return;
  }

  state.selectedProductId = productId;
  if (updateLocation) {
    syncLocationState("push");
  }
  renderProducts(state.products);

  try {
    const [detail, offers, comparison, history] = await Promise.all([
      getJson(`/products/${productId}`),
      getJson(`/products/${productId}/offers?limit=20`),
      getJson(`/products/${productId}/comparison`),
      getJson(`/products/${productId}/price-history?period=all&limit=50`),
    ]);

    elements.detailTitle.textContent = detail.name;
    elements.detailMeta.textContent = [
      detail.category,
      `${detail.offer_count} offers`,
      `${detail.marketplace_count} marketplaces`,
    ]
      .filter(Boolean)
      .join(" / ");
    renderOffers(offers.items ?? []);
    renderComparison(comparison);
    renderHistory(history.items ?? []);
  } catch (error) {
    clearProductDetails("Product details unavailable");
    renderEmpty(elements.offerList, errorMessage(error));
  }
}

function renderProducts(products) {
  if (products.length === 0) {
    renderEmpty(elements.productGrid, "No public products available yet.");
    return;
  }

  elements.productGrid.innerHTML = products
    .map((product) => {
      const active = product.id === state.selectedProductId ? " active" : "";
      const bestOffer = product.best_offer;
      return `
        <button class="product-card${active}" type="button" data-product-id="${product.id}">
          <span>
            <span class="tile-mark">${initials(product.name)}</span>
            <strong>${escapeHtml(product.name)}</strong>
          </span>
          <span>
            <span class="price">${bestOffer ? money(bestOffer.price, bestOffer.currency) : "No price"}</span>
            <small>${product.offer_count} offers / ${product.marketplace_count} markets</small>
          </span>
        </button>
      `;
    })
    .join("");

  for (const card of elements.productGrid.querySelectorAll(".product-card")) {
    card.addEventListener("click", () => {
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
          class="pill category-filter${active}"
          type="button"
          data-category-index="${index}"
          aria-pressed="${String(Boolean(active))}"
          ${disabled}
        >
          <strong>${escapeHtml(category.name)}</strong>
          <small>${category.product_count}</small>
        </button>
      `;
    })
    .join("");

  elements.categoryList.innerHTML = `
    <button
      class="pill category-filter${allActive}"
      type="button"
      data-category-index="-1"
      aria-pressed="${String(Boolean(allActive))}"
      ${disabled}
    >
      <strong>All products</strong>
      <small>Reset</small>
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

function selectCategory(category) {
  state.selectedCategoryCode = category?.code ?? "";
  state.selectedCategoryName = category?.name ?? "";
  renderCategories(state.categories);
  void runProductSearch(elements.searchInput.value.trim());
}

function renderOffers(offers) {
  if (offers.length === 0) {
    renderEmpty(elements.offerList, "No marketplace offers for this product yet.");
    return;
  }

  elements.offerList.innerHTML = offers
    .map(
      (offer) => `
        <a class="offer-row" href="${escapeAttribute(offer.url ?? "#")}" target="_blank" rel="noreferrer">
          <span>
            <span class="marketplace">${escapeHtml(offer.marketplace)}</span>
            <strong>${escapeHtml(offer.title ?? "Untitled offer")}</strong>
            <small>${escapeHtml(offer.seller_name ?? "Seller unknown")}</small>
          </span>
          <span class="price">${money(offer.price, offer.currency)}</span>
        </a>
      `,
    )
    .join("");
}

function renderComparison(comparison) {
  if (!comparison.best_offer) {
    renderEmpty(elements.comparisonCard, "No comparable prices for this product yet.");
    return;
  }

  const differences = comparison.differences ?? [];
  elements.comparisonCard.innerHTML = `
    <p class="eyebrow">${escapeHtml(comparison.status)}</p>
    <h3>Best offer</h3>
    <p class="price">${money(comparison.best_offer.price, comparison.best_offer.currency)}</p>
    <p>${escapeHtml(comparison.best_offer.marketplace)} / ${escapeHtml(comparison.best_offer.title ?? "")}</p>
    ${
      differences.length
        ? `<div class="pill-list">
            ${differences
              .map(
                (difference) => `
                  <span class="pill">
                    <strong>${escapeHtml(difference.offer.marketplace)}</strong>
                    <small>${difference.absolute_difference ? `+${money(difference.absolute_difference, difference.offer.currency)}` : escapeHtml(difference.reason ?? "n/a")}</small>
                  </span>
                `,
              )
              .join("")}
          </div>`
        : '<p class="soft-label">Only one comparable offer.</p>'
    }
  `;
}

function renderHistory(points) {
  if (points.length === 0) {
    renderEmpty(elements.historyCard, "No price history points yet.");
    return;
  }

  const prices = points.map((point) => Number(point.price));
  const max = Math.max(...prices, 1);
  const latest = points[points.length - 1];
  elements.historyCard.innerHTML = `
    <div class="history-bars" aria-label="Price history chart">
      ${points
        .map((point) => {
          const height = Math.max((Number(point.price) / max) * 100, 8);
          return `<span class="history-bar" style="height: ${height}%" title="${money(point.price, point.currency)}"></span>`;
        })
        .join("")}
    </div>
    <p class="soft-label">${points.length} points / latest ${money(latest.price, latest.currency)}</p>
  `;
}

function clearProductDetails(message) {
  elements.detailTitle.textContent = message;
  elements.detailMeta.textContent = "Waiting for public data";
  renderEmpty(elements.offerList, "Select a product when data is available.");
  renderEmpty(elements.comparisonCard, "Comparison will appear here.");
  renderEmpty(elements.historyCard, "History will appear here.");
}

async function getJson(path) {
  const response = await fetch(`${api}${path}`, {
    headers: { Accept: "application/json" },
  });
  const text = await response.text();
  const body = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const detail = body.error?.message ?? body.detail ?? response.statusText;
    throw new Error(detail);
  }
  return body;
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
  for (const button of elements.categoryList.querySelectorAll(".category-filter")) {
    button.disabled = isBusy;
  }
  elements.refreshButton.textContent = isBusy ? "Loading" : "Refresh";
}

function updateSummary() {
  const offerCount = state.products.reduce(
    (total, product) => total + Number(product.offer_count ?? 0),
    0,
  );

  elements.productCount.textContent = String(state.products.length);
  elements.offerCount.textContent = String(offerCount);
  elements.categoryCount.textContent = String(state.categories.length);
  elements.dropCount.textContent = String(state.priceChanges.length);
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
  window.history[mode === "push" ? "pushState" : "replaceState"]({}, "", url);
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
      input.reportValidity();
      return false;
    }
  }

  if (minPrice && maxPrice && Number(minPrice) > Number(maxPrice)) {
    elements.maxPriceInput.setCustomValidity(
      "Maximum price must be greater than or equal to minimum price.",
    );
    elements.maxPriceInput.reportValidity();
    return false;
  }
  return true;
}

function catalogTitle(search, marketplace, category) {
  if (search) {
    return `Results for "${search}"`;
  }
  const filters = [category, marketplaceLabel(marketplace)].filter(Boolean);
  if (filters.length > 0) {
    return `${filters.join(" / ")} products`;
  }
  return "Product cards";
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

function money(value, currency) {
  if (value === null || value === undefined) {
    return "No price";
  }
  return `${String(value)} ${currency ?? ""}`.trim();
}

function formatPercent(value) {
  return `${Number(value).toFixed(1)}%`;
}

function initials(value) {
  return value
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0])
    .join("")
    .toUpperCase();
}

function errorMessage(error) {
  return error instanceof Error ? error.message : "Unexpected public API error.";
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
