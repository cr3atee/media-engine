/** Shared, local-only catalog presentation. Never changes marketplace data. */
const assets = "/terminal/preview";
export const brands = { ggsel: "GGSEL", playerok: "Playerok", funpay: "FunPay" };
const brandAssets = { ggsel: "ggsel.ico", playerok: "playerok.svg", funpay: "funpay.ico" };
export const artwork = {
  "7c862a70-5619-5b6d-a2aa-798560d29f18": { title: "Minecraft", subtitle: "Java & Bedrock Edition · PC", label: "PC", image: "minecraft-pc.jpg", alt: "Minecraft: Java & Bedrock Edition для PC, обложка Microsoft Store" },
  "9a520758-e499-5837-90bb-9e6b67d7a591": { title: "Minecraft", subtitle: "Активация промокодом · iOS", label: "iOS", image: "minecraft-ios.jpg", alt: "Minecraft для iOS, иконка приложения Mojang из App Store" },
};

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

export function brandMark(marketplace) {
  const known = Object.hasOwn(brands, marketplace);
  const name = known ? brands[marketplace] : marketplace;
  return `<span class="market-mark ${known ? marketplace : "image-unavailable"}" role="img" aria-label="${escapeHtml(name)}" title="${escapeHtml(name)}">${known ? `<img src="${assets}/${brandAssets[marketplace]}" alt="" width="28" height="28" class="market-logo">` : ""}<span class="logo-fallback" aria-hidden="true">${escapeHtml(name)}</span></span>`;
}

export function offerFootprint(product) {
  const marketplaces = [...new Set(Array.isArray(product.marketplaces) ? product.marketplaces : [])];
  const category = new Intl.PluralRules("ru-RU").select(product.offer_count);
  const countLabel = `${product.offer_count} ${{ one: "предложение", few: "предложения", many: "предложений", other: "предложений" }[category]}`;
  return `<div class="offer-footprint"><div class="marketplace-logos">${marketplaces.map(brandMark).join("")}</div>
    <span class="offer-count" role="img" aria-label="${escapeHtml(countLabel)}" title="${escapeHtml(countLabel)}"><svg viewBox="0 0 20 20" aria-hidden="true"><rect x="6" y="6" width="11" height="11" rx="2"/><path d="M3 13V5a2 2 0 0 1 2-2h8"/></svg><span aria-hidden="true">${escapeHtml(product.offer_count)}</span></span>
  </div>`;
}

export function infoFor(product) {
  return artwork[product.id] ?? { title: product.name, subtitle: product.category ?? "Цифровой товар", label: "Товар", image: "product-placeholder.svg", alt: "Изображение товара отсутствует" };
}

export function productImage(art, className = "", size = 512, lazy = false) {
  return `<img class="product-art ${className}" src="${assets}/${art.image}" width="${size}" height="${size}" alt="${escapeHtml(art.alt)}" ${lazy ? 'loading="lazy"' : ""} decoding="async">`;
}

export function money(offer) {
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

export function handleImageError(event) {
  const image = event.target;
  if (!(image instanceof HTMLImageElement)) return;
  if (image.classList.contains("market-logo")) {
    image.hidden = true;
    image.parentElement.classList.add("image-unavailable");
  } else if (image.classList.contains("product-art")) {
    image.alt = "Изображение товара недоступно";
    if (image.getAttribute("src") !== `${assets}/product-placeholder.svg`) image.src = `${assets}/product-placeholder.svg`;
    else image.classList.add("art-unavailable");
  }
}
