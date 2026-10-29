const marketplaces = new Set(["ggsel", "playerok", "funpay"]);

export function createOfferLifecycle({ request, onAccessLoss, onChanged }) {
  const ids = [
    "offerLifecycle", "offerLifecycleLink", "offerLifecycleClose", "offerLifecycleTitle",
    "offerLifecycleLookup", "offerMarketplace", "offerExternalId", "offerLifecycleLoad",
    "offerLifecycleMessage", "offerLifecycleDetails", "offerLifecycleIdentity",
    "offerLifecycleState", "offerLifecycleVersion", "offerLifecycleUpdated",
    "offerLifecycleActionForm", "offerLifecycleReason", "offerLifecycleAction",
    "offerLifecycleRetry", "offerLifecycleDialog", "offerLifecycleDialogTitle",
    "offerLifecycleConfirmation", "offerLifecycleConfirm",
  ];
  const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
  let tenantId = null;
  let target = null;
  let pending = null;
  let draft = null;
  let busy = false;
  let epoch = 0;

  function message(text, error = false) {
    el.offerLifecycleMessage.textContent = text;
    el.offerLifecycleMessage.classList.toggle("error", error);
  }

  function updateControls() {
    el.offerLifecycle.setAttribute("aria-busy", String(busy));
    for (const node of [
      el.offerMarketplace,
      el.offerExternalId,
      el.offerLifecycleLoad,
      el.offerLifecycleReason,
      el.offerLifecycleAction,
    ]) {
      node.disabled = busy || Boolean(pending);
    }
    el.offerLifecycleAction.disabled ||= !target;
    el.offerLifecycleRetry.hidden = !pending;
    el.offerLifecycleRetry.disabled = busy;
  }

  function clearTarget({ keepLookup = true } = {}) {
    epoch += 1;
    target = null;
    pending = null;
    draft = null;
    busy = false;
    if (el.offerLifecycleDialog.open) el.offerLifecycleDialog.close("cancel");
    el.offerLifecycleDetails.hidden = true;
    el.offerLifecycleIdentity.textContent = "";
    el.offerLifecycleState.textContent = "";
    el.offerLifecycleState.dataset.state = "";
    el.offerLifecycleVersion.textContent = "";
    el.offerLifecycleUpdated.textContent = "";
    el.offerLifecycleReason.value = "";
    el.offerLifecycleConfirmation.textContent = "";
    if (!keepLookup) {
      el.offerMarketplace.value = "funpay";
      el.offerExternalId.value = "";
    }
    updateControls();
  }

  function reset() {
    clearTarget({ keepLookup: false });
    tenantId = null;
    el.offerLifecycle.hidden = true;
    el.offerLifecycleLink.hidden = true;
    message("");
  }

  function setContext(context) {
    clearTarget({ keepLookup: false });
    tenantId = context?.permissions?.includes("catalog_review") ? context.tenant_id : null;
    el.offerLifecycleLink.hidden = !tenantId;
    if (!tenantId) el.offerLifecycle.hidden = true;
  }

  function open() {
    if (!tenantId) return;
    el.offerLifecycle.hidden = false;
    el.offerLifecycleTitle.focus();
    el.offerLifecycle.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function identity() {
    const marketplace = el.offerMarketplace.value.trim().toLowerCase();
    const externalId = el.offerExternalId.value.trim();
    if (!marketplaces.has(marketplace)) {
      message("Выберите поддерживаемую площадку.", true);
      el.offerMarketplace.focus();
      return null;
    }
    if (!externalId || externalId.length > 255) {
      message("Введите ID объявления длиной до 255 символов.", true);
      el.offerExternalId.focus();
      return null;
    }
    return { marketplace, externalId };
  }

  function availabilityPath(value) {
    return `/tenants/${encodeURIComponent(tenantId)}/catalog/offers/` +
      `${encodeURIComponent(value.marketplace)}/${encodeURIComponent(value.externalId)}/availability`;
  }

  function renderTarget() {
    if (!target) return;
    const retired = target.status === "retired";
    el.offerLifecycleIdentity.textContent = `${target.marketplace.toUpperCase()} · ${target.external_id}`;
    el.offerLifecycleState.textContent = retired ? "Скрыто вручную" : "Активно";
    el.offerLifecycleState.dataset.state = target.status;
    el.offerLifecycleVersion.textContent = String(target.version);
    el.offerLifecycleUpdated.textContent = formatDate(target.updated_at);
    el.offerLifecycleAction.textContent = retired ? "Вернуть объявление" : "Скрыть объявление";
    el.offerLifecycleAction.classList.toggle("danger-button", !retired);
    el.offerLifecycleAction.classList.toggle("primary-button", retired);
    el.offerLifecycleDetails.hidden = false;
    updateControls();
  }

  async function load() {
    if (!tenantId || busy || pending) return;
    const value = identity();
    if (!value) return;
    clearTarget();
    const current = epoch;
    busy = true;
    updateControls();
    message("Проверяем состояние объявления…");
    try {
      const result = await request(availabilityPath(value));
      if (current !== epoch || !tenantId) return;
      target = result;
      renderTarget();
      message("Состояние объявления загружено.");
    } catch (error) {
      if (current !== epoch) return;
      if (onAccessLoss(error)) return;
      message(errorText(error), true);
    } finally {
      if (current === epoch) {
        busy = false;
        updateControls();
      }
    }
  }

  async function revalidate() {
    if (!target || busy || pending || el.offerLifecycle.hidden) return;
    const value = { marketplace: target.marketplace, externalId: target.external_id };
    const current = epoch;
    try {
      const result = await request(availabilityPath(value));
      if (current !== epoch || !tenantId) return;
      target = result;
      renderTarget();
    } catch (error) {
      if (current !== epoch) return;
      if (onAccessLoss(error)) return;
      clearTarget();
      message(errorText(error), true);
    }
  }

  function prepareMutation() {
    if (!target || busy || pending || !tenantId) return;
    const reason = el.offerLifecycleReason.value.trim();
    if (!reason) {
      message("Укажите причину изменения доступности.", true);
      el.offerLifecycleReason.focus();
      return;
    }
    const action = target.status === "retired" ? "restore" : "retire";
    draft = {
      tenantId,
      marketplace: target.marketplace,
      externalId: target.external_id,
      action,
      body: { expected_version: target.version, reason },
    };
    const actionText = action === "retire"
      ? "Объявление исчезнет из каталога и сравнений. История, связь с товаром и цены сохранятся."
      : "Объявление снова станет доступно каталогу, если источник также считает его активным.";
    el.offerLifecycleDialogTitle.textContent = action === "retire"
      ? "Скрыть объявление?"
      : "Вернуть объявление?";
    el.offerLifecycleConfirmation.textContent =
      `${target.marketplace.toUpperCase()} · ${target.external_id}\n${actionText}\nПричина: ${reason}`;
    el.offerLifecycleConfirm.textContent = action === "retire"
      ? "Скрыть объявление"
      : "Вернуть объявление";
    el.offerLifecycleConfirm.className = action === "retire" ? "danger-button" : "primary-button";
    el.offerLifecycleDialog.returnValue = "cancel";
    el.offerLifecycleDialog.showModal();
  }

  async function execute() {
    if (!pending || busy || !tenantId || pending.tenantId !== tenantId) return;
    const command = pending;
    const current = epoch;
    busy = true;
    updateControls();
    message(command.action === "retire" ? "Скрываем объявление…" : "Возвращаем объявление…");
    try {
      const result = await request(
        `/tenants/${encodeURIComponent(command.tenantId)}/catalog/offers/` +
          `${encodeURIComponent(command.marketplace)}/${encodeURIComponent(command.externalId)}/${command.action}`,
        {
          method: "POST",
          headers: { "Idempotency-Key": command.key },
          body: JSON.stringify(command.body),
        },
      );
      if (current !== epoch || command.tenantId !== tenantId) return;
      pending = null;
      target = {
        ...target,
        status: result.resulting_state,
        version: result.resulting_version,
        updated_at: result.recorded_at,
        retired_at: result.resulting_state === "retired" ? result.recorded_at : null,
      };
      el.offerLifecycleReason.value = "";
      renderTarget();
      message(result.replayed
        ? "Результат подтверждён повторным запросом."
        : command.action === "retire"
          ? "Объявление скрыто. История и связь с товаром сохранены."
          : "Объявление возвращено.");
      void onChanged();
    } catch (error) {
      if (current !== epoch) return;
      if (onAccessLoss(error)) return;
      if (error?.status === 409) {
        pending = null;
        busy = false;
        updateControls();
        await load();
        message("Состояние уже изменилось. Показаны актуальные данные.", true);
        return;
      }
      if (error?.status >= 400 && error?.status < 500) {
        pending = null;
        clearTarget();
        message(errorText(error), true);
        return;
      }
      message(
        pending
          ? `${errorText(error)} Повторите запрос: тот же ключ защитит от дубля.`
          : errorText(error),
        true,
      );
    } finally {
      if (current === epoch) {
        busy = false;
        updateControls();
      }
    }
  }

  el.offerLifecycleLink.addEventListener("click", event => { event.preventDefault(); open(); });
  el.offerLifecycleClose.addEventListener("click", () => {
    el.offerLifecycle.hidden = true;
    el.offerLifecycleLink.focus();
  });
  el.offerLifecycleLookup.addEventListener("submit", event => { event.preventDefault(); void load(); });
  for (const node of [el.offerMarketplace, el.offerExternalId]) {
    node.addEventListener("input", () => {
      if (!busy && !pending) {
        clearTarget();
        message("");
      }
    });
  }
  el.offerLifecycleActionForm.addEventListener("submit", event => {
    event.preventDefault();
    prepareMutation();
  });
  el.offerLifecycleDialog.addEventListener("close", () => {
    const command = draft;
    draft = null;
    if (el.offerLifecycleDialog.returnValue === "confirm" && command && command.tenantId === tenantId) {
      pending = { ...command, key: createIdempotencyKey() };
      void execute();
    } else if (!el.offerLifecycle.hidden && target) {
      el.offerLifecycleAction.focus();
    }
  });
  el.offerLifecycleDialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const buttons = el.offerLifecycleDialog.querySelectorAll("button");
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
  el.offerLifecycleRetry.addEventListener("click", () => { void execute(); });
  window.addEventListener("focus", () => { void revalidate(); });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) void revalidate();
  });

  updateControls();
  return { setContext, reset, open, revalidate };
}

function createIdempotencyKey() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint32Array(4));
  return `offer-${Array.from(bytes, value => value.toString(16)).join("-")}`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function errorText(error) {
  return typeof error?.message === "string" && error.message
    ? error.message
    : "Не удалось выполнить запрос.";
}
