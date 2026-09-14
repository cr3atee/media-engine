const api = "/api/v1/public";

const elements = {
  apiStatus: document.querySelector("#apiStatus"),
  searchForm: document.querySelector("#searchForm"),
  searchInput: document.querySelector("#searchInput"),
  refreshButton: document.querySelector("#refreshButton"),
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
  selectedProductId: null,
};

elements.searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void loadProducts(elements.searchInput.value.trim());
});

elements.refreshButton.addEventListener("click", () => {
  void loadDashboard();
});

void loadDashboard();

async function loadDashboard() {
  setApiStatus("Connecting");
  await Promise.all([loadProducts(""), loadCategories(), loadPriceChanges()]);
}

async function loadProducts(search) {
  try {
    const query = new URLSearchParams({ limit: "12" });
    if (search) {
      query.set("q", search);
    }
    const payload = await getJson(`/products?${query.toString()}`);
    state.products = payload.items ?? [];
    renderProducts(state.products);
    setApiStatus("Online");

    if (state.products.length > 0) {
      await selectProduct(state.products[0].id);
    } else {
      clearProductDetails("No products found");
    }
  } catch (error) {
    setApiStatus("API unavailable", true);
    renderEmpty(elements.productGrid, errorMessage(error));
    clearProductDetails("Public API unavailable");
  }
}

async function loadCategories() {
  try {
    const payload = await getJson("/categories?limit=10");
    const categories = payload.items ?? [];
    if (categories.length === 0) {
      renderEmpty(elements.categoryList, "No categories available yet.");
      return;
    }
    elements.categoryList.innerHTML = categories
      .map(
        (category) => `
          <span class="pill">
            <strong>${escapeHtml(category.name)}</strong>
            <small>${category.product_count}</small>
          </span>
        `,
      )
      .join("");
  } catch (error) {
    renderEmpty(elements.categoryList, errorMessage(error));
  }
}

async function loadPriceChanges() {
  try {
    const payload = await getJson("/price-changes?limit=6");
    const changes = payload.items ?? [];
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
    renderEmpty(elements.changeList, errorMessage(error));
  }
}

async function selectProduct(productId) {
  if (!productId) {
    clearProductDetails("No product selected");
    return;
  }

  state.selectedProductId = productId;
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

function renderEmpty(target, message) {
  target.innerHTML = `<p class="empty-state">${escapeHtml(message)}</p>`;
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
