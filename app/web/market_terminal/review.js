const api = "/api/v1";
const requestTimeoutMs = 15_000;
const candidatePageSize = 6;
const proposalPageSize = 9;

const elements = {
  sessionStatus: document.querySelector("#sessionStatus"),
  loginForm: document.querySelector("#loginForm"),
  emailInput: document.querySelector("#emailInput"),
  passwordInput: document.querySelector("#passwordInput"),
  loginButton: document.querySelector("#loginButton"),
  loginMessage: document.querySelector("#loginMessage"),
  sessionPanel: document.querySelector("#sessionPanel"),
  sellerName: document.querySelector("#sellerName"),
  sellerEmail: document.querySelector("#sellerEmail"),
  tenantSelect: document.querySelector("#tenantSelect"),
  tenantRole: document.querySelector("#tenantRole"),
  permissionSummary: document.querySelector("#permissionSummary"),
  reloadButton: document.querySelector("#reloadButton"),
  logoutButton: document.querySelector("#logoutButton"),
  reviewWorkspace: document.querySelector("#reviewWorkspace"),
  offerCount: document.querySelector("#offerCount"),
  linkedOfferCount: document.querySelector("#linkedOfferCount"),
  candidateCount: document.querySelector("#candidateCount"),
  proposalCount: document.querySelector("#proposalCount"),
  canonicalProductCount: document.querySelector("#canonicalProductCount"),
  decisionCount: document.querySelector("#decisionCount"),
  unqueuedOfferCount: document.querySelector("#unqueuedOfferCount"),
  catalogProgressTitle: document.querySelector("#catalogProgressTitle"),
  catalogProgressPercent: document.querySelector("#catalogProgressPercent"),
  catalogProgress: document.querySelector("#catalogProgress"),
  marketplaceProgress: document.querySelector("#marketplaceProgress"),
  tenantLabel: document.querySelector("#tenantLabel"),
  workspaceMessage: document.querySelector("#workspaceMessage"),
  queueSearchInput: document.querySelector("#queueSearchInput"),
  queueMarketplaceFilter: document.querySelector("#queueMarketplaceFilter"),
  resetQueueFilters: document.querySelector("#resetQueueFilters"),
  filterSummary: document.querySelector("#filterSummary"),
  reviewColumns: document.querySelector("#reviewColumns"),
  candidatePanel: document.querySelector("#reviewCandidates"),
  candidateList: document.querySelector("#candidateList"),
  candidatePagination: document.querySelector("#candidatePagination"),
  candidatePrevious: document.querySelector("#candidatePrevious"),
  candidateNext: document.querySelector("#candidateNext"),
  candidateRange: document.querySelector("#candidateRange"),
  proposalPanel: document.querySelector("#productProposals"),
  proposalList: document.querySelector("#proposalList"),
  proposalPagination: document.querySelector("#proposalPagination"),
  proposalPrevious: document.querySelector("#proposalPrevious"),
  proposalNext: document.querySelector("#proposalNext"),
  proposalRange: document.querySelector("#proposalRange"),
};

const state = {
  accessToken: null,
  refreshToken: null,
  memberships: [],
  activeTenantId: null,
  activeTenant: null,
  onboardingSummary: null,
  candidates: [],
  proposals: [],
  queueQuery: "",
  queueMarketplace: "",
  candidatePage: 1,
  proposalPage: 1,
  pendingMutations: new Map(),
  refreshPromise: null,
  sessionEpoch: 0,
};

class ApiRequestError extends Error {
  constructor(message, status = 0) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

elements.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void login();
});

elements.tenantSelect.addEventListener("change", () => {
  void selectTenant(elements.tenantSelect.value);
});

elements.reloadButton.addEventListener("click", () => {
  void loadQueues();
});

elements.logoutButton.addEventListener("click", () => {
  void logout();
});

elements.queueSearchInput.addEventListener("input", () => {
  state.queueQuery = elements.queueSearchInput.value.trim().toLocaleLowerCase("ru-RU");
  resetQueuePages();
  renderQueues();
});

elements.queueMarketplaceFilter.addEventListener("change", () => {
  state.queueMarketplace = elements.queueMarketplaceFilter.value;
  resetQueuePages();
  renderQueues();
});

elements.resetQueueFilters.addEventListener("click", () => {
  resetQueueFilters();
  renderQueues();
  elements.queueSearchInput.focus();
});

elements.candidatePrevious.addEventListener("click", () => {
  state.candidatePage = Math.max(1, state.candidatePage - 1);
  renderQueues();
});

elements.candidateNext.addEventListener("click", () => {
  state.candidatePage += 1;
  renderQueues();
});

elements.proposalPrevious.addEventListener("click", () => {
  state.proposalPage = Math.max(1, state.proposalPage - 1);
  renderQueues();
});

elements.proposalNext.addEventListener("click", () => {
  state.proposalPage += 1;
  renderQueues();
});

elements.candidateList.addEventListener("click", (event) => {
  void handleCandidateAction(event);
});

elements.proposalList.addEventListener("click", (event) => {
  void handleProposalAction(event);
});

renderEmptyQueues();

async function login() {
  const email = elements.emailInput.value.trim();
  const password = elements.passwordInput.value;
  setLoginBusy(true);
  setLoginMessage("Проверяем данные…");
  try {
    const tokens = await requestJson(
      "/auth/login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
      { authenticated: false, retryAuthentication: false },
    );
    setTokens(tokens);
    elements.passwordInput.value = "";
    await loadIdentity();
  } catch (error) {
    const message = errorMessage(error);
    clearSession(message);
    elements.emailInput.value = email;
    setLoginMessage(message, true);
    setSessionStatus("Ошибка входа", true);
  } finally {
    setLoginBusy(false);
  }
}

async function loadIdentity() {
  const profile = await requestJson("/me");
  state.memberships = profile.memberships.filter((membership) => membership.is_active);
  if (state.memberships.length === 0) {
    throw new ApiRequestError("Нет доступных рабочих пространств.", 403);
  }

  elements.sellerName.textContent = profile.user.display_name || "Продавец";
  elements.sellerEmail.textContent = profile.user.email;
  elements.loginForm.hidden = true;
  elements.sessionPanel.hidden = false;
  document.body.classList.add("review-authenticated");
  renderTenantOptions();
  await selectTenant(state.memberships[0].tenant_id);
  if (!elements.reviewWorkspace.hidden) {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches
      ? "auto"
      : "smooth";
    elements.reviewWorkspace.scrollIntoView({ behavior, block: "start" });
  }
}

function renderTenantOptions() {
  const options = state.memberships.map((membership) => {
    const option = document.createElement("option");
    option.value = membership.tenant_id;
    option.textContent = `${membership.tenant_name} · ${roleLabel(membership.role)}`;
    return option;
  });
  elements.tenantSelect.replaceChildren(...options);
}

async function selectTenant(tenantId) {
  if (!tenantId) {
    return;
  }
  setSessionBusy(true);
  setSessionStatus("Проверка доступа");
  try {
    const context = await requestJson(`/tenants/${encodeURIComponent(tenantId)}/context`);
    state.activeTenantId = context.tenant_id;
    state.activeTenant = context;
    elements.tenantSelect.value = context.tenant_id;
    elements.tenantRole.textContent = roleLabel(context.role);
    elements.tenantLabel.textContent = context.tenant_name;

    if (!context.permissions.includes("catalog_review")) {
      elements.permissionSummary.textContent = "Нет права catalog_review";
      elements.reviewWorkspace.hidden = true;
      setSessionStatus("Недостаточно прав", true);
      return;
    }

    elements.permissionSummary.textContent = "Проверка каталога разрешена";
    elements.reviewWorkspace.hidden = false;
    await loadQueues();
  } catch (error) {
    state.activeTenantId = null;
    state.activeTenant = null;
    elements.reviewWorkspace.hidden = true;
    elements.permissionSummary.textContent = errorMessage(error);
    setSessionStatus("Ошибка доступа", true);
  } finally {
    setSessionBusy(false);
  }
}

async function loadQueues() {
  if (!state.activeTenantId) {
    return;
  }
  const tenantId = state.activeTenantId;
  const sessionEpoch = state.sessionEpoch;
  setWorkspaceBusy(true);
  setWorkspaceMessage("Обновляем очереди…");
  try {
    const tenant = encodeURIComponent(tenantId);
    const workspace = await requestJson(
      `/tenants/${tenant}/catalog/onboarding-workspace?limit=100`,
    );
    if (
      sessionEpoch !== state.sessionEpoch ||
      tenantId !== state.activeTenantId
    ) {
      return;
    }
    state.onboardingSummary = workspace.summary;
    state.candidates = workspace.review_candidates;
    state.proposals = workspace.product_proposals;
    syncMarketplaceFilterOptions();
    renderQueues();
    renderOnboardingSummary(workspace.summary);
    setWorkspaceMessage(onboardingSummaryMessage(workspace.summary));
    setSessionStatus("Данные актуальны");
  } catch (error) {
    setWorkspaceMessage(errorMessage(error), true);
    setSessionStatus("Ошибка загрузки", true);
  } finally {
    setWorkspaceBusy(false);
  }
}

function renderQueues() {
  const candidates = state.candidates.filter(queueItemMatches);
  const proposals = state.proposals.filter(queueItemMatches);
  renderCandidates(candidates);
  renderProposals(proposals);
  elements.candidatePanel.hidden = candidates.length === 0 && proposals.length > 0;
  elements.proposalPanel.hidden = proposals.length === 0 && candidates.length > 0;
  elements.reviewColumns.classList.toggle(
    "proposals-only",
    candidates.length === 0 && proposals.length > 0,
  );
  elements.reviewColumns.classList.toggle(
    "candidates-only",
    proposals.length === 0 && candidates.length > 0,
  );
  const visible = candidates.length + proposals.length;
  const total = state.candidates.length + state.proposals.length;
  elements.filterSummary.textContent =
    visible === total
      ? `Все объявления в очередях: ${total}`
      : `Найдено ${visible} из ${total}`;
}

function renderCandidates(candidates) {
  elements.candidatePanel.classList.toggle("queue-empty", candidates.length === 0);
  if (candidates.length === 0) {
    elements.candidateList.innerHTML = emptyState(
      queueFiltersActive()
        ? "По текущему фильтру совпадений нет."
        : "Нет пар, которым сейчас нужна ручная проверка.",
    );
    renderPagination(
      elements.candidatePagination,
      elements.candidatePrevious,
      elements.candidateNext,
      elements.candidateRange,
      { page: 1, totalPages: 1, totalItems: 0, start: 0, end: 0 },
    );
    return;
  }
  const page = paginate(candidates, state.candidatePage, candidatePageSize);
  state.candidatePage = page.page;
  elements.candidateList.replaceChildren(
    ...page.items.map((candidate) => candidateCard(candidate)),
  );
  renderPagination(
    elements.candidatePagination,
    elements.candidatePrevious,
    elements.candidateNext,
    elements.candidateRange,
    page,
  );
}

function queueItemMatches(item) {
  if (state.queueMarketplace && item.marketplace !== state.queueMarketplace) {
    return false;
  }
  if (!state.queueQuery) {
    return true;
  }
  const searchable = [
    item.offer_title,
    item.proposed_name,
    item.canonical_product_name,
    item.nearest_canonical_product_name,
    item.external_id,
    item.marketplace,
  ]
    .filter(Boolean)
    .join(" ")
    .toLocaleLowerCase("ru-RU");
  return searchable.includes(state.queueQuery);
}

function syncMarketplaceFilterOptions() {
  const current = state.queueMarketplace;
  const marketplaces = [...new Set(
    [...state.candidates, ...state.proposals].map((item) => item.marketplace),
  )].sort((left, right) => left.localeCompare(right));
  const options = [document.createElement("option")];
  options[0].value = "";
  options[0].textContent = "Все площадки";
  for (const marketplace of marketplaces) {
    const option = document.createElement("option");
    option.value = marketplace;
    option.textContent = marketplace.toUpperCase();
    options.push(option);
  }
  elements.queueMarketplaceFilter.replaceChildren(...options);
  if (marketplaces.includes(current)) {
    elements.queueMarketplaceFilter.value = current;
  } else {
    state.queueMarketplace = "";
  }
}

function paginate(items, requestedPage, pageSize) {
  const totalItems = items.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const page = Math.min(Math.max(1, requestedPage), totalPages);
  const start = (page - 1) * pageSize;
  const end = Math.min(start + pageSize, totalItems);
  return {
    items: items.slice(start, end),
    page,
    totalPages,
    totalItems,
    start,
    end,
  };
}

function renderPagination(container, previous, next, range, page) {
  container.hidden = page.totalPages <= 1;
  previous.disabled = page.page <= 1;
  next.disabled = page.page >= page.totalPages;
  range.textContent =
    page.totalItems === 0
      ? "Нет записей"
      : `${page.start + 1}–${page.end} из ${page.totalItems}`;
}

function resetQueuePages() {
  state.candidatePage = 1;
  state.proposalPage = 1;
}

function resetQueueFilters() {
  state.queueQuery = "";
  state.queueMarketplace = "";
  elements.queueSearchInput.value = "";
  elements.queueMarketplaceFilter.value = "";
  resetQueuePages();
}

function queueFiltersActive() {
  return Boolean(state.queueQuery || state.queueMarketplace);
}

function candidateCard(candidate) {
  const card = document.createElement("article");
  card.className = "review-card";
  card.dataset.marketplace = candidate.marketplace;
  card.dataset.externalId = candidate.external_id;
  card.dataset.canonicalProductId = candidate.canonical_product_id;
  card.innerHTML = `
    <div class="review-card-header">
      <div>
        <span class="review-card-kicker">${escapeHtml(candidate.marketplace)}</span>
        <h3>${escapeHtml(candidate.offer_title)}</h3>
      </div>
      <span class="confidence-badge">${formatSimilarity(candidate.similarity)}</span>
    </div>
    <div class="review-facts">
      ${factHtml("Цена", money(candidate.offer_price, candidate.currency))}
      ${factHtml("ID объявления", candidate.external_id)}
      ${factHtml("Решение", decisionLabel(candidate.match_decision))}
    </div>
    <div class="candidate-link">
      <span>
        <strong>${escapeHtml(candidate.canonical_product_name)}</strong>
        <small>${escapeHtml(candidate.canonical_product_category || "Категория не задана")}</small>
      </span>
      ${externalLinkHtml(candidate.offer_url)}
    </div>
    <details class="decision-details">
      <summary>Принять решение</summary>
      <div class="decision-body">
        <label class="reason-label">
          Причина решения
          <small>Обязательна для отклонения, рекомендуется для подтверждения.</small>
          <textarea class="review-reason" maxlength="2000" placeholder="Что проверено в исходном объявлении?"></textarea>
        </label>
        <div class="review-actions">
          <button class="action-button confirm" data-action="confirm-candidate" type="button">Подтвердить связь</button>
          <button class="action-button reject" data-action="reject-candidate" type="button">Отклонить пару</button>
        </div>
      </div>
    </details>
  `;
  return card;
}

function renderProposals(proposals) {
  elements.proposalPanel.classList.toggle("queue-empty", proposals.length === 0);
  if (proposals.length === 0) {
    elements.proposalList.innerHTML = emptyState(
      queueFiltersActive()
        ? "По текущему фильтру новых товаров нет."
        : "Нет объявлений, для которых требуется создать или выбрать товар.",
    );
    renderPagination(
      elements.proposalPagination,
      elements.proposalPrevious,
      elements.proposalNext,
      elements.proposalRange,
      { page: 1, totalPages: 1, totalItems: 0, start: 0, end: 0 },
    );
    return;
  }
  const page = paginate(proposals, state.proposalPage, proposalPageSize);
  state.proposalPage = page.page;
  elements.proposalList.replaceChildren(
    ...page.items.map((proposal) => proposalCard(proposal)),
  );
  renderPagination(
    elements.proposalPagination,
    elements.proposalPrevious,
    elements.proposalNext,
    elements.proposalRange,
    page,
  );
}

function proposalCard(proposal) {
  const nearestId = proposal.nearest_canonical_product_id || "";
  const card = document.createElement("article");
  card.className = "review-card";
  card.dataset.proposalId = proposal.proposal_id;
  card.dataset.marketplace = proposal.marketplace;
  card.dataset.externalId = proposal.external_id;
  card.dataset.canonicalProductId = nearestId;
  card.innerHTML = `
    <div class="review-card-header">
      <div>
        <span class="review-card-kicker">${escapeHtml(proposal.marketplace)}</span>
        <h3>${escapeHtml(proposal.proposed_name)}</h3>
      </div>
      <span class="confidence-badge">${formatSimilarity(proposal.nearest_similarity)}</span>
    </div>
    <div class="review-facts">
      ${factHtml("Цена", money(proposal.offer_price, proposal.currency))}
      ${factHtml("ID объявления", proposal.external_id)}
      ${factHtml("Решение", decisionLabel(proposal.match_decision))}
    </div>
    ${proposalCandidateHtml(proposal)}
    <details class="decision-details">
      <summary>Принять решение</summary>
      <div class="decision-body">
        <label class="reason-label">
          Проверенные факты
          <small>Обязательны для связи с существующим товаром.</small>
          <textarea class="review-reason" maxlength="2000" placeholder="Почему это новый или уже существующий товар?"></textarea>
        </label>
        <div class="review-actions">
          <button class="action-button create" data-action="create-product" type="button">Создать новый товар</button>
          <button class="action-button resolve" data-action="resolve-existing" type="button" ${nearestId ? "" : "disabled"}>Связать с показанным</button>
        </div>
      </div>
    </details>
  `;
  return card;
}

async function handleCandidateAction(event) {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("button[data-action]");
  const card = button?.closest(".review-card");
  if (!button || !card || !state.activeTenantId) {
    return;
  }
  const reason = card.querySelector(".review-reason").value.trim();
  const action = button.dataset.action;
  if (action === "reject-candidate" && !reason) {
    setWorkspaceMessage("Для отклонения укажите проверенную причину.", true);
    card.querySelector(".review-reason").focus();
    return;
  }
  const endpoint = action === "confirm-candidate" ? "confirm" : "reject";
  const payload = {
    marketplace: card.dataset.marketplace,
    external_id: card.dataset.externalId,
    canonical_product_id: card.dataset.canonicalProductId,
    ...(reason ? { reason } : {}),
  };
  const identity = `${action}:${card.dataset.marketplace}:${card.dataset.externalId}:${card.dataset.canonicalProductId}`;
  await runCatalogMutation(
    card,
    identity,
    `/catalog/reviews/${endpoint}`,
    payload,
    action === "confirm-candidate" ? "Связь подтверждена." : "Пара отклонена.",
  );
}

async function handleProposalAction(event) {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("button[data-action]");
  const card = button?.closest(".review-card");
  if (!button || !card || !state.activeTenantId) {
    return;
  }
  const action = button.dataset.action;
  const reason = card.querySelector(".review-reason").value.trim();
  if (action === "resolve-existing" && !reason) {
    setWorkspaceMessage("Для существующего товара укажите проверенные факты.", true);
    card.querySelector(".review-reason").focus();
    return;
  }
  const base = `/catalog/product-proposals/${encodeURIComponent(card.dataset.proposalId)}`;
  const payload = {
    marketplace: card.dataset.marketplace,
    external_id: card.dataset.externalId,
    ...(reason ? { reason } : {}),
  };
  let endpoint = `${base}/confirm`;
  let successMessage = "Канонический товар создан и связан.";
  if (action === "resolve-existing") {
    endpoint = `${base}/resolve-existing`;
    payload.canonical_product_id = card.dataset.canonicalProductId;
    successMessage = "Объявление связано с существующим товаром.";
  }
  const identity = `${action}:${card.dataset.proposalId}`;
  await runCatalogMutation(card, identity, endpoint, payload, successMessage);
}

async function runCatalogMutation(card, identity, endpoint, payload, successMessage) {
  setCardBusy(card, true);
  setWorkspaceMessage("Сохраняем решение…");
  try {
    await executeMutation(identity, endpoint, payload);
    setWorkspaceMessage(successMessage);
    await loadQueues();
  } catch (error) {
    setWorkspaceMessage(errorMessage(error), true);
  } finally {
    setCardBusy(card, false);
  }
}

async function executeMutation(identity, endpoint, payload) {
  const fingerprint = JSON.stringify(payload);
  const pending = state.pendingMutations.get(identity);
  if (pending && pending.fingerprint !== fingerprint) {
    throw new ApiRequestError(
      "Предыдущий запрос завершился неоднозначно. Обновите очередь перед изменением решения.",
    );
  }
  const idempotencyKey = pending?.idempotencyKey || createIdempotencyKey();
  state.pendingMutations.set(identity, { fingerprint, idempotencyKey });
  try {
    const result = await requestJson(
      `/tenants/${encodeURIComponent(state.activeTenantId)}${endpoint}`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
    state.pendingMutations.delete(identity);
    return result;
  } catch (error) {
    if (error instanceof ApiRequestError && error.status > 0 && error.status < 500) {
      state.pendingMutations.delete(identity);
    }
    throw error;
  }
}

async function logout() {
  const refreshToken = state.refreshToken;
  setSessionBusy(true);
  try {
    if (refreshToken) {
      await requestJson(
        "/auth/logout",
        {
          method: "POST",
          body: JSON.stringify({ refresh_token: refreshToken }),
        },
        { authenticated: false, retryAuthentication: false },
      );
    }
  } catch (error) {
    setWorkspaceMessage(errorMessage(error), true);
  } finally {
    clearSession("Сессия завершена");
    setSessionBusy(false);
  }
}

async function requestJson(path, options = {}, configuration = {}) {
  const authenticated = configuration.authenticated !== false;
  const retryAuthentication = configuration.retryAuthentication !== false;
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body) {
    headers.set("Content-Type", "application/json");
  }
  if (authenticated && state.accessToken) {
    headers.set("Authorization", `Bearer ${state.accessToken}`);
  }

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), requestTimeoutMs);
  let response;
  try {
    response = await fetch(`${api}${path}`, {
      ...options,
      headers,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiRequestError("Время ожидания истекло. Повторите запрос.");
    }
    throw new ApiRequestError("Нет соединения с MediaEngine.");
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (
    response.status === 401 &&
    authenticated &&
    retryAuthentication &&
    state.refreshToken
  ) {
    try {
      await refreshSession();
    } catch {
      clearSession("Сессия истекла. Войдите снова.");
      throw new ApiRequestError("Сессия истекла. Войдите снова.", 401);
    }
    return requestJson(path, options, {
      authenticated: true,
      retryAuthentication: false,
    });
  }

  const text = await response.text();
  const body = parseJson(text, response.headers.get("content-type") || "");
  if (!response.ok) {
    throw new ApiRequestError(apiErrorMessage(body, response.status), response.status);
  }
  return body;
}

async function refreshSession() {
  if (!state.refreshPromise) {
    const sessionEpoch = state.sessionEpoch;
    state.refreshPromise = requestJson(
      "/auth/refresh",
      {
        method: "POST",
        body: JSON.stringify({ refresh_token: state.refreshToken }),
      },
      { authenticated: false, retryAuthentication: false },
    )
      .then((tokens) => {
        if (sessionEpoch !== state.sessionEpoch) {
          throw new ApiRequestError("Сессия завершена. Войдите снова.", 401);
        }
        setTokens(tokens);
      })
      .finally(() => {
        state.refreshPromise = null;
      });
  }
  await state.refreshPromise;
}

function setTokens(tokens) {
  state.accessToken = tokens.access_token;
  state.refreshToken = tokens.refresh_token;
}

function clearSession(message) {
  state.sessionEpoch += 1;
  state.accessToken = null;
  state.refreshToken = null;
  state.memberships = [];
  state.activeTenantId = null;
  state.activeTenant = null;
  state.onboardingSummary = null;
  state.candidates = [];
  state.proposals = [];
  resetQueueFilters();
  state.pendingMutations.clear();
  state.refreshPromise = null;
  document.body.classList.remove("review-authenticated");
  elements.loginForm.hidden = false;
  elements.sessionPanel.hidden = true;
  elements.reviewWorkspace.hidden = true;
  elements.loginForm.reset();
  setLoginMessage(message);
  setSessionStatus("Требуется вход");
  renderEmptyQueues();
}

function renderEmptyQueues() {
  elements.candidatePanel.hidden = false;
  elements.proposalPanel.hidden = false;
  elements.reviewColumns.classList.remove("proposals-only", "candidates-only");
  elements.candidateList.innerHTML = emptyState("Войдите, чтобы загрузить очередь.");
  elements.proposalList.innerHTML = emptyState("Войдите, чтобы загрузить предложения.");
  elements.offerCount.textContent = "0";
  elements.linkedOfferCount.textContent = "0";
  elements.candidateCount.textContent = "0";
  elements.proposalCount.textContent = "0";
  elements.canonicalProductCount.textContent = "0";
  elements.decisionCount.textContent = "0";
  elements.unqueuedOfferCount.textContent = "0";
  elements.catalogProgressTitle.textContent = "Связано 0 из 0 объявлений";
  elements.catalogProgressPercent.textContent = "0%";
  elements.catalogProgress.value = 0;
  elements.marketplaceProgress.replaceChildren();
  elements.filterSummary.textContent = "Показаны все объявления";
  elements.candidatePagination.hidden = true;
  elements.proposalPagination.hidden = true;
  elements.tenantLabel.textContent = "—";
}

function renderOnboardingSummary(summary) {
  elements.offerCount.textContent = String(summary.total_offers);
  elements.linkedOfferCount.textContent = String(summary.linked_offers);
  elements.candidateCount.textContent = String(summary.review_candidates);
  elements.proposalCount.textContent = String(summary.product_proposals);
  elements.canonicalProductCount.textContent = String(summary.canonical_products);
  elements.decisionCount.textContent = String(summary.terminal_decisions);
  elements.unqueuedOfferCount.textContent = String(summary.unqueued_offers);
  const progress =
    summary.total_offers === 0
      ? 0
      : Math.round((summary.linked_offers / summary.total_offers) * 100);
  elements.catalogProgressTitle.textContent =
    `Связано ${summary.linked_offers} из ${summary.total_offers} объявлений`;
  elements.catalogProgressPercent.textContent = `${progress}%`;
  elements.catalogProgress.value = progress;
  elements.catalogProgress.textContent = `${progress}%`;
  elements.marketplaceProgress.replaceChildren(
    ...summary.marketplaces.map((marketplace) => marketplaceProgressCard(marketplace)),
  );
}

function marketplaceProgressCard(summary) {
  const card = document.createElement("article");
  card.className = "marketplace-progress-card";

  const heading = document.createElement("strong");
  heading.textContent = summary.marketplace.toUpperCase();
  const counts = document.createElement("span");
  counts.textContent = `${summary.linked_offers} из ${summary.total_offers} связано`;
  const pending = document.createElement("small");
  pending.textContent = `${summary.review_candidates} совпадений · ${summary.product_proposals} новых · ${summary.unqueued_offers} вне очередей`;

  card.append(heading, counts, pending);
  return card;
}

function proposalCandidateHtml(proposal) {
  const sourceLink = externalLinkHtml(proposal.offer_url);
  if (!proposal.nearest_canonical_product_id) {
    return `
      <div class="candidate-link missing">
        <span>
          <strong>Похожий товар не найден</strong>
          <small>Доступно только создание нового канонического товара.</small>
        </span>
        ${sourceLink}
      </div>
    `;
  }
  return `
    <div class="candidate-link">
      <span>
        <strong>${escapeHtml(proposal.nearest_canonical_product_name)}</strong>
        <small>Ближайший существующий товар · ${formatSimilarity(proposal.nearest_similarity)}</small>
      </span>
      ${sourceLink}
    </div>
  `;
}

function factHtml(label, value) {
  return `
    <span class="review-fact">
      <small>${escapeHtml(label)}</small>
      <strong title="${escapeHtml(value)}">${escapeHtml(value)}</strong>
    </span>
  `;
}

function externalLinkHtml(value) {
  const url = safeExternalUrl(value);
  if (!url) {
    return "";
  }
  return `<a class="ghost-button" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Источник</a>`;
}

function safeExternalUrl(value) {
  if (!value) {
    return null;
  }
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.toString() : null;
  } catch {
    return null;
  }
}

function money(value, currency) {
  if (value === null || value === undefined || !currency) {
    return "Цена не указана";
  }
  const amount = Number(value);
  if (!Number.isFinite(amount)) {
    return `${value} ${currency}`;
  }
  try {
    return new Intl.NumberFormat("ru-RU", {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(amount);
  } catch {
    return `${amount.toLocaleString("ru-RU")} ${currency}`;
  }
}

function formatSimilarity(value) {
  const similarity = Number(value);
  return Number.isFinite(similarity) ? `${Math.round(similarity * 100)}%` : "—";
}

function decisionLabel(decision) {
  return {
    review: "Нужна проверка",
    no_match: "Совпадение не найдено",
  }[decision] || decision || "—";
}

function roleLabel(role) {
  return {
    owner: "Владелец",
    admin: "Администратор",
    reviewer: "Ревьюер",
    viewer: "Наблюдатель",
  }[role] || role;
}

function onboardingSummaryMessage(summary) {
  if (summary.unresolved_offers === 0) {
    return "Каталог обработан: все объявления связаны.";
  }
  return `Ожидают решения: ${summary.unresolved_offers}. В очередях: ${summary.review_candidates + summary.product_proposals}.`;
}

function emptyState(message) {
  return `<p class="empty-state">${escapeHtml(message)}</p>`;
}

function setLoginBusy(isBusy) {
  elements.loginButton.disabled = isBusy;
  elements.emailInput.disabled = isBusy;
  elements.passwordInput.disabled = isBusy;
}

function setSessionBusy(isBusy) {
  elements.tenantSelect.disabled = isBusy;
  elements.reloadButton.disabled = isBusy;
  elements.logoutButton.disabled = isBusy;
}

function setWorkspaceBusy(isBusy) {
  elements.reviewWorkspace.setAttribute("aria-busy", String(isBusy));
  elements.reloadButton.disabled = isBusy;
}

function setCardBusy(card, isBusy) {
  for (const control of card.querySelectorAll("button, textarea")) {
    control.disabled = isBusy;
  }
}

function setLoginMessage(message, isError = false) {
  elements.loginMessage.textContent = message;
  elements.loginMessage.classList.toggle("error", isError);
}

function setWorkspaceMessage(message, isError = false) {
  elements.workspaceMessage.textContent = message;
  elements.workspaceMessage.classList.toggle("error", isError);
}

function setSessionStatus(message, isError = false) {
  elements.sessionStatus.textContent = message;
  elements.sessionStatus.classList.toggle("error", isError);
}

function createIdempotencyKey() {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint32Array(4));
  return `catalog-${Array.from(bytes, (value) => value.toString(16)).join("-")}`;
}

function parseJson(text, contentType) {
  if (!text) {
    return null;
  }
  if (!contentType.toLowerCase().includes("json")) {
    throw new ApiRequestError("Сервис вернул некорректный ответ.");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiRequestError("Сервис вернул некорректный ответ.");
  }
}

function apiErrorMessage(body, status) {
  const code = body?.error?.code;
  const knownMessages = {
    invalid_credentials: "Неверная почта или пароль.",
    authentication_unavailable: "Вход временно недоступен.",
    token_revoked: "Сессия завершена. Войдите снова.",
    tenant_not_found: "Рабочее пространство недоступно.",
    permission_denied: "Недостаточно прав для этого действия.",
    idempotency_conflict: "Запрос изменился. Обновите очередь и повторите решение.",
    canonical_product_proposal_not_found: "Предложение больше недоступно.",
    canonical_product_proposal_stale: "Предложение изменилось. Обновите очередь.",
    canonical_product_proposal_conflict: "Предложение уже обработано.",
    canonical_review_target_not_found: "Товар или объявление больше недоступны.",
    canonical_offer_decision_conflict: "Эта пара уже проверена.",
    canonical_offer_link_conflict: "Объявление уже связано с другим товаром.",
  };
  if (typeof code === "string" && knownMessages[code]) {
    return knownMessages[code];
  }
  const message = body?.error?.message;
  if (typeof message === "string" && message.trim()) {
    return message;
  }
  if (status === 401) {
    return "Требуется повторный вход.";
  }
  if (status === 403) {
    return "Недостаточно прав для этого действия.";
  }
  if (status === 409) {
    return "Данные уже изменились. Обновите очередь.";
  }
  return "Не удалось выполнить запрос.";
}

function errorMessage(error) {
  return error instanceof ApiRequestError
    ? error.message
    : "Неожиданная ошибка интерфейса.";
}

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (character) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[character],
  );
}
