import { brandMark, handleImageError } from "/terminal/preview/presentation.js";
import { createProductAccess, productRoleLabel } from "/terminal/product-access.js";
import { createDiagnosticJournal, installFrontendDiagnostics } from "/terminal/diagnostics.js";
import { createOfferLifecycle } from "/terminal/offer-lifecycle.js";

document.addEventListener("error", handleImageError, true);

const api = "/api/v1";
const requestTimeoutMs = 15_000;
const candidatePageSize = 6;
const proposalPageSize = 9;
const decisionGuidance = Object.freeze({
  "confirm-candidate": {
    label: "Комментарий к проверке",
    requirement: "Необязательно",
    hint: "Укажите, какие признаки вы сверили в объявлении и товаре каталога.",
    placeholder: "Например: одинаковые платформа, издание и способ получения.",
    required: false,
    submitLabel: "Проверить связь",
  },
  "reject-candidate": {
    label: "Почему товары различаются?",
    requirement: "Обязательно",
    hint: "Назовите конкретное отличие: платформу, издание, регион или способ получения.",
    placeholder: "Например: объявление для Xbox, а товар каталога для PC.",
    required: true,
    submitLabel: "Проверить отклонение",
  },
  "create-product": {
    label: "Комментарий к созданию",
    requirement: "Необязательно",
    hint: "Можно зафиксировать проверенные особенности нового товара. Название будет взято из объявления.",
    placeholder: "Например: отдельное издание для iOS.",
    required: false,
    submitLabel: "Проверить создание",
  },
  "resolve-existing": {
    label: "Почему это один товар?",
    requirement: "Обязательно",
    hint: "Сверьте издание, платформу, способ получения и регион. Пример: в обоих источниках указаны Java + Bedrock для PC и цифровой ключ.",
    placeholder: "Перечислите только факты, которые удалось проверить.",
    required: true,
    submitLabel: "Проверить связь",
  },
});
let decisionFormSequence = 0;

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
  workspaceEpoch: 0,
  queueEpoch: 0,
};

class ApiRequestError extends Error {
  constructor(message, status = 0, code = "") {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

const diagnosticJournal = createDiagnosticJournal({
  request: requestJson,
  onSessionLost: () => clearSession("Сессия завершена. Войдите снова."),
});

const frontendDiagnostics = installFrontendDiagnostics({
  isAuthenticated: () => Boolean(state.accessToken),
  send: payload => requestJson(
    "/diagnostics/frontend",
    { method: "POST", body: JSON.stringify(payload) },
    { diagnosticRequest: true },
  ),
});

const productAccess = createProductAccess({
  request: requestJson,
  onSessionLost: () => clearSession("Сессия завершена. Войдите снова."),
  onProfile: user => {
    renderProductIdentity(user);
    diagnosticJournal.setProfile(user);
  },
});

const offerLifecycle = createOfferLifecycle({
  request: requestJson,
  onAccessLoss: error => handleAccessLoss(error),
  onChanged: () => loadQueues(),
});

function renderProductIdentity(user) {
  document.querySelector("#productIdentity").textContent = user
    ? productRoleLabel(user.product_role) : "";
  document.querySelector("#accountId").textContent = user?.id || "";
}

function showReviewNavigation(visible) {
  document.querySelector("#reviewCandidatesLink").hidden = !visible;
  document.querySelector("#productProposalsLink").hidden = !visible;
}

elements.loginForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void login();
});

elements.tenantSelect.addEventListener("change", () => {
  void selectTenant(elements.tenantSelect.value);
});

elements.reloadButton.addEventListener("click", () => {
  void productAccess.revalidate();
  void selectTenant(elements.tenantSelect.value);
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
elements.candidateList.addEventListener("change", handleDecisionChoice);
elements.candidateList.addEventListener("input", handleDecisionReasonInput);

elements.proposalList.addEventListener("click", (event) => {
  void handleProposalAction(event);
});
elements.proposalList.addEventListener("change", handleDecisionChoice);
elements.proposalList.addEventListener("input", handleDecisionReasonInput);

renderEmptyQueues();
void restoreSession().finally(() => window.terminalPageReady?.());

window.addEventListener("pageshow", event => {
  if (event.persisted) void restoreSession();
});
window.addEventListener("pagehide", () => clearSession(""));

/** Rehydrate from an HttpOnly cookie; no credential is written to web storage. */
async function restoreSession() {
  clearSession("");
  const epoch = state.sessionEpoch;
  setLoginBusy(true);
  setLoginMessage("Восстанавливаем вход…");
  try {
    await refreshSession();
    if (epoch !== state.sessionEpoch) return;
    await loadIdentity();
  } catch (error) {
    if (epoch !== state.sessionEpoch) return;
    clearSession(error.status === 401 ? "" : "Не удалось восстановить вход. Проверьте соединение и обновите страницу.");
  } finally {
    setLoginBusy(false);
  }
}

function browserAuth(path, options = {}) {
  const run = () => requestJson(`/auth/browser/${path}`, { method: "POST", ...options }, { authenticated: false, retryAuthentication: false });
  return navigator.locks ? navigator.locks.request("mt-browser-session", run) : run();
}

document.querySelector("#decisionDialog").addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const buttons = event.currentTarget.querySelectorAll("button:not(:disabled)");
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

async function login() {
  const email = elements.emailInput.value.trim();
  const password = elements.passwordInput.value;
  setLoginBusy(true);
  setLoginMessage("Проверяем данные…");
  try {
    const tokens = await browserAuth(
      "login",
      {
        method: "POST",
        body: JSON.stringify({ email, password }),
      },
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
  const sessionEpoch = state.sessionEpoch;
  const profile = await requestJson("/me");
  if (sessionEpoch !== state.sessionEpoch) return;
  state.memberships = profile.memberships.filter((membership) => membership.is_active);

  elements.sellerName.textContent = profile.user.display_name || profile.user.email.split("@")[0];
  elements.sellerEmail.textContent = profile.user.email;
  elements.loginForm.hidden = true;
  elements.sessionPanel.hidden = false;
  document.body.classList.add("review-authenticated");
  productAccess.setProfile(profile.user);
  renderTenantOptions();
  elements.tenantSelect.closest("label").hidden = state.memberships.length === 0;
  elements.reloadButton.textContent = state.memberships.length ? "Обновить очереди" : "Обновить доступ";
  if (state.memberships.length === 0) {
    elements.permissionSummary.textContent = "Нет доступных организаций";
    setSessionStatus("Вход выполнен");
    if (profile.user.product_role === "admin") await productAccess.open();
    return;
  }
  await selectTenant(state.memberships[0].tenant_id);
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
  invalidateWorkspace();
  const workspaceEpoch = state.workspaceEpoch;
  const sessionEpoch = state.sessionEpoch;
  const isCurrent = () => workspaceEpoch === state.workspaceEpoch && sessionEpoch === state.sessionEpoch;
  setSessionBusy(true);
  setSessionStatus("Проверка доступа");
  try {
    const context = await requestJson(`/tenants/${encodeURIComponent(tenantId)}/context`);
    if (!isCurrent()) return;
    elements.tenantSelect.value = context.tenant_id;
    elements.tenantRole.textContent = roleLabel(context.role);
    elements.tenantLabel.textContent = context.tenant_name;

    if (!context.permissions.includes("catalog_review")) {
      elements.permissionSummary.textContent = "В этой организации вам недоступна проверка каталога.";
      elements.reviewWorkspace.hidden = true;
      setSessionStatus("Недостаточно прав", true);
      return;
    }

    state.activeTenantId = context.tenant_id;
    state.activeTenant = context;
    offerLifecycle.setContext(context);
    showReviewNavigation(true);
    elements.permissionSummary.textContent = "Проверка каталога разрешена";
    elements.reviewWorkspace.hidden = false;
    await loadQueues();
  } catch (error) {
    if (!isCurrent()) return;
    if (handleAccessLoss(error)) return;
    elements.permissionSummary.textContent = errorMessage(error);
    setSessionStatus("Ошибка доступа", true);
  } finally {
    if (isCurrent()) setSessionBusy(false);
  }
}

async function loadQueues() {
  if (!state.activeTenantId) {
    return;
  }
  const tenantId = state.activeTenantId;
  const sessionEpoch = state.sessionEpoch;
  const workspaceEpoch = state.workspaceEpoch;
  const queueEpoch = ++state.queueEpoch;
  const isCurrent = () => sessionEpoch === state.sessionEpoch && workspaceEpoch === state.workspaceEpoch && queueEpoch === state.queueEpoch && tenantId === state.activeTenantId;
  setWorkspaceBusy(true);
  setWorkspaceMessage("Обновляем очереди…");
  try {
    const tenant = encodeURIComponent(tenantId);
    const workspace = await requestJson(
      `/tenants/${tenant}/catalog/onboarding-workspace?limit=100`,
    );
    if (!isCurrent()) return;
    state.onboardingSummary = workspace.summary;
    state.candidates = workspace.review_candidates;
    state.proposals = workspace.product_proposals;
    syncMarketplaceFilterOptions();
    renderQueues();
    renderOnboardingSummary(workspace.summary);
    setWorkspaceMessage(onboardingSummaryMessage(workspace.summary));
    setSessionStatus("Данные актуальны");
  } catch (error) {
    if (!isCurrent()) return;
    if (handleAccessLoss(error)) return;
    setWorkspaceMessage(errorMessage(error), true);
    setSessionStatus("Ошибка загрузки", true);
  } finally {
    if (isCurrent()) setWorkspaceBusy(false);
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

function decisionFormHtml(options) {
  const formId = `catalog-decision-${++decisionFormSequence}`;
  const choices = options.map((option) => `
    <label class="decision-option${option.disabled ? " is-disabled" : ""}">
      <input
        class="decision-choice-input ${option.className}"
        type="radio"
        name="${formId}"
        value="${option.action}"
        ${option.disabled ? "disabled" : ""}
      >
      <span>
        <strong>${option.title}</strong>
        <small>${option.description}</small>
      </span>
    </label>
  `).join("");
  return `
    <fieldset class="decision-choice">
      <legend>Как поступить?</legend>
      <div class="decision-options">${choices}</div>
    </fieldset>
    <label class="reason-label" for="${formId}-reason">
      <span class="reason-heading">
        <span data-reason-label>Комментарий к решению</span>
        <small data-reason-requirement>Сначала выберите действие</small>
      </span>
      <small id="${formId}-hint" data-reason-hint>После выбора здесь появится точное правило и пример.</small>
      <textarea
        id="${formId}-reason"
        class="review-reason"
        maxlength="2000"
        aria-describedby="${formId}-hint ${formId}-error"
        placeholder="Выберите решение выше"
        disabled
      ></textarea>
      <small id="${formId}-error" class="reason-error" role="alert" hidden></small>
    </label>
    <div class="review-actions">
      <button class="primary-button decision-submit" data-submit-decision type="button" disabled>Выберите решение</button>
    </div>
  `;
}

function candidateCard(candidate) {
  const card = document.createElement("article");
  card.className = "review-card";
  card.dataset.marketplace = candidate.marketplace;
  card.dataset.externalId = candidate.external_id;
  card.dataset.canonicalProductId = candidate.canonical_product_id;
  card.dataset.canonicalProductName = candidate.canonical_product_name;
  card.dataset.offerTitle = candidate.offer_title;
  card.innerHTML = `
    <div class="review-source">
    <div class="review-card-header">
      <div>
        <span class="review-card-kicker">${brandMark(candidate.marketplace)} Объявление · ${escapeHtml(candidate.marketplace)}</span>
        <h3>${escapeHtml(candidate.offer_title)}</h3>
      </div>
      <span class="confidence-badge">Сходство ${formatSimilarity(candidate.similarity)}</span>
    </div>
    <div class="review-facts">
      ${factHtml("Цена", money(candidate.offer_price, candidate.currency))}
      ${factHtml("ID объявления", candidate.external_id)}
      ${factHtml("Решение", decisionLabel(candidate.match_decision))}
    </div>
    ${externalLinkHtml(candidate.offer_url)}
    </div>
    <div class="candidate-link">
      <span>
        <span class="review-card-kicker">Товар каталога для связи</span>
        <strong>${escapeHtml(candidate.canonical_product_name)}</strong>
        <small>${escapeHtml(candidate.canonical_product_category || "Категория не задана")}</small>
        <small>ID: ${escapeHtml(candidate.canonical_product_id)}</small>
      </span>
    </div>
    <details class="decision-details">
      <summary>Принять решение</summary>
      <div class="decision-body">
        ${decisionFormHtml([
          {
            action: "confirm-candidate",
            className: "confirm",
            title: "Это тот же товар",
            description: "Связать объявление с товаром справа. Комментарий рекомендуется.",
          },
          {
            action: "reject-candidate",
            className: "reject",
            title: "Это разные товары",
            description: "Отклонить предложенную пару. Причина обязательна.",
          },
        ])}
      </div>
    </details>
    <p class="card-message" role="status" aria-live="polite"></p>
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
  card.dataset.canonicalProductName = proposal.nearest_canonical_product_name || "";
  card.dataset.offerTitle = proposal.proposed_name;
  card.innerHTML = `
    <div class="review-source">
    <div class="review-card-header">
      <div>
        <span class="review-card-kicker">${brandMark(proposal.marketplace)} Объявление · ${escapeHtml(proposal.marketplace)}</span>
        <h3>${escapeHtml(proposal.proposed_name)}</h3>
      </div>
      <span class="confidence-badge">Сходство ${formatSimilarity(proposal.nearest_similarity)}</span>
    </div>
    <div class="review-facts">
      ${factHtml("Цена", money(proposal.offer_price, proposal.currency))}
      ${factHtml("ID объявления", proposal.external_id)}
      ${factHtml("Решение", decisionLabel(proposal.match_decision))}
    </div>
    ${externalLinkHtml(proposal.offer_url)}
    </div>
    ${proposalCandidateHtml(proposal)}
    <details class="decision-details">
      <summary>Принять решение</summary>
      <div class="decision-body">
        ${decisionFormHtml([
          {
            action: "create-product",
            className: "create",
            title: "Это новый товар",
            description: "Создать товар с названием объявления. Комментарий необязателен.",
          },
          {
            action: "resolve-existing",
            className: "resolve",
            title: "Это товар, показанный выше",
            description: nearestId
              ? "Связать с предложенным товаром. Проверенные факты обязательны."
              : "Подходящий товар не найден; доступно только создание нового.",
            disabled: !nearestId,
          },
        ])}
      </div>
    </details>
    <p class="card-message" role="status" aria-live="polite"></p>
  `;
  return card;
}

function handleDecisionChoice(event) {
  if (!(event.target instanceof HTMLInputElement) || !event.target.matches(".decision-choice-input")) {
    return;
  }
  const card = event.target.closest(".review-card");
  const guidance = decisionGuidance[event.target.value];
  if (!card || !guidance) return;

  const reason = card.querySelector(".review-reason");
  const requirement = card.querySelector("[data-reason-requirement]");
  card.querySelector("[data-reason-label]").textContent = guidance.label;
  card.querySelector("[data-reason-hint]").textContent = guidance.hint;
  requirement.textContent = guidance.requirement;
  requirement.classList.toggle("is-required", guidance.required);
  reason.disabled = false;
  reason.required = guidance.required;
  reason.setAttribute("aria-required", String(guidance.required));
  reason.placeholder = guidance.placeholder;
  card.querySelector("[data-submit-decision]").disabled = false;
  card.querySelector("[data-submit-decision]").textContent = guidance.submitLabel;
  setReasonError(card, "");
}

function handleDecisionReasonInput(event) {
  if (!(event.target instanceof HTMLTextAreaElement) || !event.target.matches(".review-reason")) {
    return;
  }
  const card = event.target.closest(".review-card");
  if (card) setReasonError(card, "");
}

function selectedDecision(card) {
  return card.querySelector(".decision-choice-input:checked")?.value || "";
}

function setReasonError(card, message) {
  const reason = card.querySelector(".review-reason");
  const error = card.querySelector(".reason-error");
  error.textContent = message;
  error.hidden = !message;
  if (message) reason.setAttribute("aria-invalid", "true");
  else reason.removeAttribute("aria-invalid");
}

function validateDecisionReason(card, action, reason) {
  const guidance = decisionGuidance[action];
  if (!guidance?.required || reason) return true;
  const message = action === "reject-candidate"
    ? "Для отклонения укажите конкретное различие."
    : "Для связи укажите проверенные факты.";
  setReasonError(card, message);
  card.querySelector(".review-reason").focus();
  return false;
}

async function handleCandidateAction(event) {
  if (!(event.target instanceof Element)) {
    return;
  }
  const button = event.target.closest("button[data-submit-decision]");
  const card = button?.closest(".review-card");
  if (!button || !card || !state.activeTenantId) {
    return;
  }
  const reason = card.querySelector(".review-reason").value.trim();
  const action = selectedDecision(card);
  if (!action || !validateDecisionReason(card, action, reason)) return;
  if (!await confirmDecision(card, action, reason)) return;
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
  const button = event.target.closest("button[data-submit-decision]");
  const card = button?.closest(".review-card");
  if (!button || !card || !state.activeTenantId) {
    return;
  }
  const action = selectedDecision(card);
  const reason = card.querySelector(".review-reason").value.trim();
  if (!action || !validateDecisionReason(card, action, reason)) return;
  if (!await confirmDecision(card, action, reason)) return;
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
  const workspaceEpoch = state.workspaceEpoch;
  const sessionEpoch = state.sessionEpoch;
  const isCurrent = () => workspaceEpoch === state.workspaceEpoch && sessionEpoch === state.sessionEpoch;
  setCardBusy(card, true);
  setCardMessage(card, "");
  setWorkspaceMessage("Сохраняем решение…");
  try {
    await executeMutation(identity, endpoint, payload);
    if (!isCurrent()) return;
    setWorkspaceMessage(successMessage);
    await loadQueues();
  } catch (error) {
    if (!isCurrent()) return;
    if (handleAccessLoss(error)) return;
    setCardMessage(card, errorMessage(error));
    setWorkspaceMessage(errorMessage(error), true);
  } finally {
    if (isCurrent() && card.isConnected) setCardBusy(card, false);
  }
}

function setCardMessage(card, message) {
  card.querySelector(".card-message").textContent = message;
}

/** Confirm the exact pair, without sending or changing any request payload. */
async function confirmDecision(card, action, reason) {
  const dialog = document.querySelector("#decisionDialog");
  if (dialog.open) return false;
  const tenantId = state.activeTenantId;
  const sessionEpoch = state.sessionEpoch;
  const opener = document.activeElement;
  const creating = action === "create-product";
  const rejecting = action === "reject-candidate";
  document.querySelector("#decisionDialogTitle").textContent = creating
    ? "Создать новый товар?" : rejecting ? "Отклонить эту пару?" : "Связать объявление с товаром?";
  document.querySelector("#decisionDialogHint").textContent = creating
    ? "Будет создан отдельный товар с названием объявления. Проверьте, нет ли его уже в каталоге."
    : rejecting ? "Эта пара будет отклонена. Исходное объявление не удаляется."
      : "Связать объявление с каноническим товаром ниже. Совпадения названий недостаточно: проверьте условия на площадке.";
  document.querySelector("#decisionSource").textContent = card.dataset.offerTitle;
  document.querySelector("#decisionSourceId").textContent = `${card.dataset.marketplace} · ID ${card.dataset.externalId}`;
  document.querySelector("#decisionTargetLabel").textContent = creating ? "Новый товар" : "Товар каталога";
  document.querySelector("#decisionTarget").textContent = creating ? card.dataset.offerTitle : card.dataset.canonicalProductName;
  document.querySelector("#decisionTargetId").textContent = creating ? "Будет создан после подтверждения" : `ID ${card.dataset.canonicalProductId}`;
  document.querySelector("#decisionFacts").textContent = reason ? `Ваши факты: ${reason}` : "Комментарий не добавлен.";
  document.querySelector("#decisionConfirm").textContent = creating ? "Создать товар" : rejecting ? "Отклонить пару" : "Подтвердить связь";
  dialog.returnValue = "cancel";
  const confirmed = new Promise((resolve) => {
    dialog.addEventListener("close", () => {
      if (opener?.isConnected) opener.focus();
      resolve(dialog.returnValue === "confirm");
    }, { once: true });
  });
  dialog.showModal();
  return await confirmed && card.isConnected && tenantId === state.activeTenantId && sessionEpoch === state.sessionEpoch;
}

async function executeMutation(identity, endpoint, payload) {
  // Identical marketplace IDs in different workspaces must never share retries.
  identity = `${state.activeTenantId}:${identity}`;
  const fingerprint = JSON.stringify(payload);
  const pending = state.pendingMutations.get(identity);
  if (pending && pending.fingerprint !== fingerprint) {
    throw new ApiRequestError(
      "Предыдущий запрос завершился неоднозначно. Обновите очередь перед изменением решения.",
    );
  }
  const idempotencyKey = pending?.idempotencyKey || createIdempotencyKey();
  const attempt = { fingerprint, idempotencyKey };
  state.pendingMutations.set(identity, attempt);
  try {
    const result = await requestJson(
      `/tenants/${encodeURIComponent(state.activeTenantId)}${endpoint}`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify(payload),
      },
    );
    if (state.pendingMutations.get(identity) === attempt) state.pendingMutations.delete(identity);
    return result;
  } catch (error) {
    if (state.pendingMutations.get(identity) === attempt && error instanceof ApiRequestError && error.status > 0 && error.status < 500) {
      state.pendingMutations.delete(identity);
    }
    throw error;
  }
}

async function logout() {
  clearSession("Сессия завершена");
  const sessionEpoch = state.sessionEpoch;
  setSessionBusy(true);
  setLoginBusy(true);
  try {
    await browserAuth("logout");
  } catch (error) {
    if (sessionEpoch === state.sessionEpoch) {
      setLoginMessage("Вы вышли из кабинета на этом устройстве. Серверный отзыв сессии не подтверждён из-за ошибки запроса.", true);
    }
  } finally {
    if (sessionEpoch === state.sessionEpoch) {
      setSessionBusy(false);
      setLoginBusy(false);
    }
  }
}

async function requestJson(path, options = {}, configuration = {}) {
  const sessionEpoch = state.sessionEpoch;
  const authenticated = configuration.authenticated !== false;
  const retryAuthentication = configuration.retryAuthentication !== false;
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (path.startsWith("/auth/browser/")) headers.set("X-Terminal-Request", "1");
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
      credentials: "same-origin",
    });
  } catch (error) {
    if (!configuration.diagnosticRequest && authenticated && state.accessToken) {
      frontendDiagnostics.reportRequestFailure();
    }
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
    state.accessToken
  ) {
    if (sessionEpoch !== state.sessionEpoch) {
      throw new ApiRequestError("Сессия завершена. Войдите снова.", 401);
    }
    try {
      await refreshSession();
    } catch {
      if (sessionEpoch === state.sessionEpoch) clearSession("Сессия истекла. Войдите снова.");
      throw new ApiRequestError("Сессия истекла. Войдите снова.", 401);
    }
    if (sessionEpoch !== state.sessionEpoch) {
      throw new ApiRequestError("Сессия завершена. Войдите снова.", 401);
    }
    return requestJson(path, options, {
      authenticated: true,
      retryAuthentication: false,
    });
  }

  const text = await response.text();
  let body;
  try {
    body = parseJson(text, response.headers.get("content-type") || "");
  } catch (error) {
    if (!configuration.diagnosticRequest && authenticated && state.accessToken) {
      frontendDiagnostics.reportRequestFailure();
    }
    throw error;
  }
  if (!response.ok) {
    throw new ApiRequestError(apiErrorMessage(body, response.status), response.status, body?.error?.code || "");
  }
  return body;
}

async function refreshSession() {
  if (!state.refreshPromise) {
    const sessionEpoch = state.sessionEpoch;
    state.refreshPromise = browserAuth("refresh")
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
}

function clearSession(message) {
  productAccess.reset();
  state.sessionEpoch += 1;
  state.accessToken = null;
  state.memberships = [];
  invalidateWorkspace();
  state.pendingMutations.clear();
  state.refreshPromise = null;
  document.body.classList.remove("review-authenticated");
  elements.loginForm.hidden = false;
  elements.sessionPanel.hidden = true;
  elements.reviewWorkspace.hidden = true;
  elements.loginForm.reset();
  elements.sellerName.textContent = "Продавец";
  elements.sellerEmail.textContent = "";
  elements.tenantSelect.replaceChildren();
  setLoginMessage(message);
  setSessionStatus("Требуется вход");
  renderEmptyQueues();
}

/** Drop protected data immediately, including any open confirmation dialog. */
function invalidateWorkspace() {
  offerLifecycle.reset();
  showReviewNavigation(false);
  state.workspaceEpoch += 1;
  state.queueEpoch += 1;
  state.activeTenantId = null;
  state.activeTenant = null;
  state.onboardingSummary = null;
  state.candidates = [];
  state.proposals = [];
  const dialog = document.querySelector("#decisionDialog");
  if (dialog.open) dialog.close("cancel");
  for (const id of ["decisionSource", "decisionSourceId", "decisionTarget", "decisionTargetId", "decisionFacts"]) {
    document.getElementById(id).textContent = "";
  }
  resetQueueFilters();
  renderEmptyQueues();
  elements.reviewWorkspace.hidden = true;
  elements.tenantRole.textContent = "—";
  elements.permissionSummary.textContent = "Проверка прав";
  setWorkspaceMessage("");
  setWorkspaceBusy(false);
  setSessionBusy(false);
}

function handleAccessLoss(error) {
  if (!(error instanceof ApiRequestError)) return false;
  if (error.status === 401 || error.code === "account_disabled") {
    clearSession("Доступ к аккаунту изменился. Войдите снова.");
    setLoginMessage("Доступ к аккаунту изменился. Войдите снова.", true);
    return true;
  }
  if (error.status === 403 || error.code === "tenant_not_found") {
    invalidateWorkspace();
    elements.permissionSummary.textContent = "Права доступа изменились. Выберите доступное пространство или обновите доступ.";
    setSessionStatus("Доступ изменился", true);
    elements.tenantSelect.focus();
    return true;
  }
  return false;
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
  heading.innerHTML = `${brandMark(summary.marketplace)} ${escapeHtml(summary.marketplace.toUpperCase())}`;
  const counts = document.createElement("span");
  counts.textContent = `${summary.linked_offers} из ${summary.total_offers} связано`;
  const pending = document.createElement("small");
  pending.textContent = `${summary.review_candidates} совпадений · ${summary.product_proposals} новых · ${summary.unqueued_offers} вне очередей`;

  card.append(heading, counts, pending);
  return card;
}

function proposalCandidateHtml(proposal) {
  if (!proposal.nearest_canonical_product_id) {
    return `
      <div class="candidate-link missing">
        <span>
          <strong>Похожий товар не найден</strong>
          <small>Доступно только создание нового канонического товара.</small>
        </span>
      </div>
    `;
  }
  return `
    <div class="candidate-link">
      <span>
        <span class="review-card-kicker">Товар каталога для связи</span>
        <strong>${escapeHtml(proposal.nearest_canonical_product_name)}</strong>
        <small>Целевой товар для связи · сходство ${formatSimilarity(proposal.nearest_similarity)}</small>
        <small>ID: ${escapeHtml(proposal.nearest_canonical_product_id)}</small>
      </span>
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
    administrator: "Администратор пространства",
    reviewer: "Ревьюер",
    operator: "Оператор",
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
    if (isBusy) control.dataset.previouslyDisabled = String(control.disabled);
    control.disabled = isBusy || control.dataset.previouslyDisabled === "true";
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
    account_disabled: "Доступ к аккаунту отключён.",
    tenant_not_found: "Организация недоступна.",
    permission_denied: "Недостаточно прав для этого действия.",
    idempotency_conflict: "Запрос изменился. Обновите очередь и повторите решение.",
    canonical_product_proposal_not_found: "Предложение больше недоступно.",
    canonical_product_proposal_stale: "Предложение изменилось. Обновите очередь.",
    canonical_product_proposal_conflict: "Предложение уже обработано.",
    canonical_review_target_not_found: "Товар или объявление больше недоступны.",
    canonical_offer_decision_conflict: "Эта пара уже проверена.",
    canonical_offer_link_conflict: "Объявление уже связано с другим товаром.",
    offer_not_found: "Объявление не найдено в выбранной организации.",
    optimistic_concurrency_conflict: "Состояние объявления уже изменилось.",
    invalid_transition: "Это изменение больше недоступно для текущего состояния.",
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
