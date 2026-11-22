const periodUnits = { M: "месяц", D: "день", W: "неделя", Y: "год" };
const deliveryLabels = { key: "Ключ / цифровой код", own_account: "Активация на своём аккаунте", new_account: "Новый готовый аккаунт" };
const accountLabels = { new_only: "Только новый аккаунт", existing_only: "Только существующий", any: "Новый или существующий" };

function codes(value) {
  const result = [...new Set(String(value ?? "").trim().toUpperCase().split(/[\s,;]+/u).filter(Boolean))].sort();
  if (result.some(code => !/^[A-Z]{2}$/.test(code) || ["XX", "ZZ"].includes(code))) throw new Error("Укажите известные страны двухбуквенными кодами: RU, KZ, BR.");
  return result;
}

function amount(value, maximum) {
  const number = Number(value);
  if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(number) || number < 1 || number > maximum) {
    throw new Error("Укажите положительное целое количество в допустимом диапазоне.");
  }
  return number;
}

/** Convert only explicit form choices, never infer missing activation facts. */
export function readActivationConditions(values) {
  if (!["countries", "worldwide"].includes(values.scope)) throw new Error("Подтвердите регион активации.");
  const regions = codes(values.regions);
  const excluded = codes(values.excluded_regions);
  if (values.scope === "countries" && (!regions.length || excluded.length)) throw new Error("Укажите разрешённые страны; исключения доступны для общего региона.");
  if (values.scope === "worldwide" && regions.length) throw new Error("Для общего региона используйте только список исключений.");
  if (!["pc", "mobile", "any"].includes(values.device)) throw new Error("Подтвердите устройство.");
  const plan = String((values.plan_choice === "other" ? values.plan_code : values.plan_choice) ?? "").trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(plan)) throw new Error("Подтвердите тариф и его одинаковое обозначение в сравниваемых объявлениях.");
  if (["unknown", "unconfirmed", "unspecified", "other", "any"].includes(plan)) throw new Error("Укажите подтверждённый тариф, а не отметку «неизвестно».");
  if (values.period_unit !== "PERPETUAL" && !Object.hasOwn(periodUnits, values.period_unit)) throw new Error("Подтвердите срок подписки.");
  if (!Object.hasOwn(deliveryLabels, values.delivery_method)) throw new Error("Подтвердите способ получения.");
  if (!Object.hasOwn(accountLabels, values.account_requirement)) throw new Error("Подтвердите требования к аккаунту.");
  if (!["true", "false"].includes(values.vpn_required)) throw new Error("Подтвердите, нужен ли VPN.");
  if (!["unlimited", "3600", "86400", "1"].includes(values.window_unit)) throw new Error("Подтвердите срок использования кода.");
  const window = values.window_unit === "unlimited" ? null : amount(values.window_amount, 2147483647) * Number(values.window_unit);
  if (window !== null && !Number.isSafeInteger(window)) throw new Error("Срок использования слишком велик.");
  return {
    version: 1,
    regions: values.scope === "worldwide" ? ["*"] : regions,
    excluded_regions: excluded,
    device: values.device, plan,
    period: values.period_unit === "PERPETUAL" ? "PERPETUAL" : `P${amount(values.period_amount, 99999)}${values.period_unit}`,
    delivery_method: values.delivery_method, account_requirement: values.account_requirement,
    vpn_required: values.vpn_required === "true", activation_window_seconds: window,
  };
}

function countryNames(list) {
  const names = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["ru"], { type: "region" }) : null;
  return list.map(code => { try { return names?.of(code) || code; } catch { return code; } }).join(", ");
}

export function createOfferActivationReview({ request, onAccessLoss, externalUrl, formatMoney }) {
  const byId = id => document.getElementById(id);
  const el = Object.fromEntries([
    "activationReview", "activationReviewLink", "activationTitle", "activationClose",
    "activationLookup", "activationMarketplace", "activationExternalId", "activationLoad",
    "activationMessage", "activationDetails", "activationOfferTitle", "activationSourceState", "activationSource",
    "activationForm", "activationRegionsLabel", "activationExclusionsLabel", "activationRegionNames",
    "activationPlanCodeLabel", "activationPeriodAmountLabel", "activationWindowAmountLabel",
    "activationSave", "activationClear", "activationRetry", "activationDialog", "activationDialogTitle",
    "activationConfirmation", "activationConfirm",
  ].map(id => [id, byId(id)]));
  const field = name => el.activationForm.elements.namedItem(name);
  let tenantId = null;
  let target = null;
  let epoch = 0;
  let busy = false;
  let pending = null;
  let draft = null;
  let opener = null;

  function message(text, error = false) {
    el.activationMessage.textContent = text;
    el.activationMessage.classList.toggle("error", error);
  }

  function sync() {
    const locked = busy || Boolean(pending);
    el.activationReview.setAttribute("aria-busy", String(busy));
    for (const node of el.activationLookup.elements) node.disabled = locked;
    for (const node of el.activationForm.elements) node.disabled = locked || !target;
    el.activationRetry.hidden = !pending;
    el.activationRetry.disabled = busy;
    el.activationClear.disabled ||= !target?.conditions;
    const countries = field("scope").value === "countries";
    el.activationRegionsLabel.hidden = !countries;
    field("regions").required = countries;
    field("regions").disabled ||= !countries;
    el.activationExclusionsLabel.hidden = field("scope").value !== "worldwide";
    field("excluded_regions").disabled ||= field("scope").value !== "worldwide";
    const customPlan = field("plan_choice").value === "other";
    el.activationPlanCodeLabel.hidden = !customPlan;
    field("plan_code").required = customPlan;
    field("plan_code").disabled ||= !customPlan;
    const periodAmount = field("period_unit").value !== "PERPETUAL";
    el.activationPeriodAmountLabel.hidden = !periodAmount;
    field("period_amount").required = periodAmount;
    field("period_amount").disabled ||= !periodAmount;
    const windowAmount = field("window_unit").value !== "unlimited";
    el.activationWindowAmountLabel.hidden = !windowAmount;
    field("window_amount").required = windowAmount;
    field("window_amount").disabled ||= !windowAmount;
    updateCountryPreview();
  }

  function updateCountryPreview() {
    try {
      const worldwide = field("scope").value === "worldwide";
      const selected = codes(field(worldwide ? "excluded_regions" : "regions").value);
      el.activationRegionNames.textContent = selected.length ? `${worldwide ? "Исключены: " : ""}${countryNames(selected)}` : "";
    } catch { el.activationRegionNames.textContent = "Проверьте коды стран."; }
  }

  function clearTarget() {
    epoch += 1;
    target = null; pending = null; draft = null; busy = false;
    if (el.activationDialog.open) el.activationDialog.close("cancel");
    el.activationForm.reset();
    el.activationDetails.hidden = true;
    el.activationOfferTitle.textContent = "";
    el.activationSource.removeAttribute("href");
    el.activationSource.hidden = true;
    sync();
  }

  function reset() {
    clearTarget(); tenantId = null;
    el.activationReview.hidden = true;
    el.activationReviewLink.hidden = true;
    el.activationExternalId.value = "";
    message("");
  }

  function setContext(context) {
    reset();
    tenantId = context?.permissions?.includes("catalog_review") ? context.tenant_id : null;
    el.activationReviewLink.hidden = !tenantId;
  }

  function open() {
    if (!tenantId) return;
    el.activationReview.hidden = false;
    el.activationTitle.focus();
    el.activationReview.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function path(marketplace, externalId) {
    return `/tenants/${encodeURIComponent(tenantId)}/catalog/offers/` +
      `${encodeURIComponent(marketplace)}/${encodeURIComponent(externalId)}/activation-conditions`;
  }

  function renderTarget() {
    el.activationForm.reset();
    el.activationOfferTitle.textContent = target.title || `${target.marketplace.toUpperCase()} · ${target.external_id}`;
    const price = formatMoney(target.price, target.currency);
    el.activationSourceState.textContent = `${target.marketplace.toUpperCase()} · ID ${target.external_id} · ${price} · ` +
      (target.conditions ? "Условия указаны" : "Условия ещё не подтверждены");
    const url = externalUrl(target.url);
    el.activationSource.hidden = !url;
    if (url) el.activationSource.href = url;
    const conditions = target.conditions;
    if (conditions) {
      field("scope").value = conditions.regions.includes("*") ? "worldwide" : "countries";
      field("regions").value = conditions.regions.includes("*") ? "" : conditions.regions.join(", ");
      field("excluded_regions").value = conditions.excluded_regions.join(", ");
      field("device").value = conditions.device;
      const knownPlan = [...field("plan_choice").options].some(option => option.value === conditions.plan);
      field("plan_choice").value = knownPlan ? conditions.plan : "other";
      field("plan_code").value = knownPlan ? "" : conditions.plan;
      if (conditions.period === "PERPETUAL") field("period_unit").value = "PERPETUAL";
      else {
        const match = /^P(\d+)([DWMY])$/.exec(conditions.period);
        if (match) { field("period_amount").value = match[1]; field("period_unit").value = match[2]; }
      }
      field("delivery_method").value = conditions.delivery_method;
      field("account_requirement").value = conditions.account_requirement;
      field("vpn_required").value = String(conditions.vpn_required);
      const seconds = conditions.activation_window_seconds;
      const unit = seconds === null ? "unlimited" : seconds % 86400 === 0 ? "86400" : seconds % 3600 === 0 ? "3600" : "1";
      field("window_unit").value = unit;
      field("window_amount").value = seconds === null ? "" : String(seconds / Number(unit));
    }
    el.activationDetails.hidden = false;
    sync();
  }

  async function load() {
    if (!tenantId || busy || pending || !el.activationLookup.reportValidity()) return;
    const marketplace = el.activationMarketplace.value;
    const externalId = el.activationExternalId.value.trim();
    if (!externalId) { message("Укажите ID объявления.", true); return; }
    clearTarget();
    const current = epoch;
    busy = true; sync(); message("Загружаем исходные данные объявления…");
    try {
      const result = await request(path(marketplace, externalId));
      if (current !== epoch || !tenantId) return;
      target = result; renderTarget();
      message("Проверьте описание источника. Заполняйте только подтверждённые условия.");
    } catch (error) {
      if (current !== epoch || onAccessLoss(error)) return;
      message(errorText(error), true);
    } finally { if (current === epoch) { busy = false; sync(); } }
  }

  function prepare(clear = false) {
    if (!tenantId || !target || busy || pending) return;
    const reason = field("reason").value.trim();
    if (!reason) { message("Укажите факты, на которых основано изменение.", true); field("reason").focus(); return; }
    if (!clear && !el.activationForm.reportValidity()) return;
    try {
      const conditions = clear ? null : readActivationConditions(Object.fromEntries(new FormData(el.activationForm)));
      draft = { tenantId, marketplace: target.marketplace, externalId: target.external_id,
        body: { offer_id: target.offer_id, expected_version: target.version,
          expected_source_fingerprint: target.source_fingerprint, conditions, reason } };
      opener = clear ? el.activationClear : el.activationSave;
      el.activationDialogTitle.textContent = clear ? "Сбросить условия в неизвестные?" : "Подтвердить условия активации?";
      const summary = conditions ? [
        `Регион: ${conditions.regions.includes("*") ? "любой" : countryNames(conditions.regions)}`,
        `Исключения: ${countryNames(conditions.excluded_regions) || "не указаны"}`,
        `Устройство: ${conditions.device}; тариф: ${conditions.plan}; срок: ${conditions.period}`,
        `Получение: ${deliveryLabels[conditions.delivery_method]}`,
        `Аккаунт: ${accountLabels[conditions.account_requirement]}`,
        `VPN: ${conditions.vpn_required ? "требуется" : "не требуется"}`,
        `Использовать код: ${conditions.activation_window_seconds === null ? "без ограничения срока" : `в течение ${conditions.activation_window_seconds} секунд`}`,
      ].join("\n") : "Сравнение с другими предложениями будет недоступно до новой проверки.";
      el.activationConfirmation.textContent = `${target.marketplace.toUpperCase()} · ${target.external_id}\n${target.title || ""}\n\n${summary}\n\nФакты: ${reason}\n\nЦена и связь с товаром не изменятся.`;
      el.activationDialog.returnValue = "cancel";
      el.activationDialog.showModal();
    } catch (error) { message(error.message, true); }
  }

  async function execute() {
    if (!pending || busy || pending.tenantId !== tenantId) return;
    const command = pending;
    const current = epoch;
    busy = true; sync(); message("Сохраняем условия и запись проверки…");
    try {
      const result = await request(path(command.marketplace, command.externalId), {
        method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body),
      });
      if (current !== epoch || command.tenantId !== tenantId) return;
      const fresh = await request(path(command.marketplace, command.externalId));
      if (current !== epoch || command.tenantId !== tenantId) return;
      pending = null; target = fresh; renderTarget();
      message(result.replayed ? "Результат подтверждён повторным запросом. Дубль не создан." : "Условия сохранены. Проверка записана в журнал.");
    } catch (error) {
      if (current !== epoch || onAccessLoss(error)) return;
      if (error.status >= 400 && error.status < 500) {
        pending = null;
        if (error.status === 409 || error.status === 404) {
          target = null; el.activationDetails.hidden = true;
          message(`${errorText(error)} Загрузите объявление заново и проверьте актуальные данные.`, true);
        } else message(errorText(error), true);
      } else message(`${errorText(error)} Повторите тот же запрос для проверки результата.`, true);
    } finally { if (current === epoch) { busy = false; sync(); } }
  }

  el.activationReviewLink.addEventListener("click", event => { event.preventDefault(); open(); });
  document.getElementById("reviewWorkspace").addEventListener("click", event => {
    const link = event.target.closest("[data-activation-review]");
    if (!link || !tenantId) return;
    event.preventDefault();
    open();
    if (busy || pending) { message("Сначала завершите текущую проверку или повторите запрос.", true); return; }
    const card = link.closest(".review-card");
    el.activationMarketplace.value = card.dataset.marketplace;
    el.activationExternalId.value = card.dataset.externalId;
    void load();
  });
  el.activationClose.addEventListener("click", () => { el.activationReview.hidden = true; el.activationReviewLink.focus(); });
  el.activationLookup.addEventListener("submit", event => { event.preventDefault(); void load(); });
  for (const node of [el.activationMarketplace, el.activationExternalId]) node.addEventListener("input", () => {
    if (!busy && !pending) { clearTarget(); message(""); }
  });
  el.activationForm.addEventListener("change", event => {
    if (event.target.name === "scope") {
      field(event.target.value === "worldwide" ? "regions" : "excluded_regions").value = "";
    }
    sync();
  });
  el.activationForm.addEventListener("input", updateCountryPreview);
  el.activationForm.addEventListener("submit", event => { event.preventDefault(); prepare(); });
  el.activationClear.addEventListener("click", () => prepare(true));
  el.activationRetry.addEventListener("click", () => { void execute(); });
  el.activationDialog.addEventListener("close", () => {
    const command = draft; draft = null;
    if (el.activationDialog.returnValue === "confirm" && command && command.tenantId === tenantId) {
      pending = { ...command, key: crypto.randomUUID() }; void execute();
    } else if (!el.activationReview.hidden) opener?.focus();
  });
  el.activationDialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const buttons = el.activationDialog.querySelectorAll("button");
    const first = buttons[0], last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  reset();
  return { setContext, reset, open };
}

function errorText(error) {
  return {
    activation_source_conflict: "Объявление изменилось после загрузки формы.",
    activation_version_conflict: "Условия уже изменены другой проверкой.",
    idempotency_conflict: "Этот ключ запроса уже использован для другого действия.",
    offer_not_found: "Активное объявление не найдено в выбранной организации.",
    activation_reason_required: "Укажите проверенные факты.",
  }[error.code] || error.message || "Не удалось выполнить запрос.";
}
