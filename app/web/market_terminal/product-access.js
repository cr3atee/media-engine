/** Product role administration uses the cabinet's existing in-memory auth session. */
const labels = { user: "Пользователь", partner: "Партнёр", moderator: "Модератор", admin: "Администратор" };
const hints = {
  user: "Обычный аккаунт. Доступ к организациям не изменяется.",
  partner: "Партнёрский аккаунт. Доступ к организациям выдаётся отдельно.",
  moderator: "Аккаунт модератора. Эта роль сама по себе не открывает чужие данные.",
  admin: "Может назначать роли и просматривать историю доступа. Не получает автоматически доступ ко всем организациям.",
};
export function productRoleLabel(role) { return labels[role] || "Пользователь"; }

export function createProductAccess({ request, onSessionLost, onProfile }) {
  const ids = ["productAccess", "productAccessLink", "accessClose", "accessTitle", "accessLookup", "accessUserId", "accessLoad", "accessMessage", "accessDetails", "accessForm", "accessTarget", "accessCurrent", "accessRole", "accessRoleHint", "accessReason", "accessReview", "accessRetry", "accessAudit", "accessDialog", "accessConfirmation"];
  const el = Object.fromEntries(ids.map(id => [id, document.getElementById(id)]));
  let profile = null;
  let epoch = 0;
  let target = null;
  let pending = null;
  let busy = false;
  let draft = null;
  let verifying = false;

  function message(text, error = false) {
    el.accessMessage.textContent = text;
    el.accessMessage.classList.toggle("error", error);
  }
  function controls() {
    el.productAccess.setAttribute("aria-busy", String(busy));
    for (const node of [el.accessUserId, el.accessLoad, el.accessRole, el.accessReason, el.accessReview]) {
      node.disabled = busy || Boolean(pending);
    }
    el.accessReview.disabled ||= !target?.enabled || el.accessRole.value === target?.product_role;
    el.accessRetry.hidden = !pending;
    el.accessRetry.disabled = busy;
  }
  function clearTarget() {
    epoch++;
    target = null; pending = null; draft = null; busy = false;
    if (el.accessDialog.open) el.accessDialog.close("cancel");
    el.accessConfirmation.textContent = "";
    el.accessDetails.hidden = true;
    el.accessTarget.textContent = "";
    el.accessCurrent.textContent = "";
    el.accessAudit.replaceChildren();
    el.accessReason.value = "";
    controls();
  }
  function reset() {
    clearTarget();
    profile = null;
    el.productAccess.hidden = true;
    el.productAccessLink.hidden = true;
    el.accessUserId.value = "";
    message("");
    onProfile(null);
  }
  function setProfile(user) {
    if (profile?.id !== user?.id || user?.product_role !== "admin") {
      clearTarget();
      el.accessUserId.value = "";
    }
    profile = user;
    onProfile(user);
    el.productAccessLink.hidden = user?.product_role !== "admin";
    if (el.productAccessLink.hidden) el.productAccess.hidden = true;
  }
  function failed(error) {
    if (error.status === 401 || error.code === "account_disabled") {
      reset(); onSessionLost(); return;
    }
    if (error.status === 403) {
      reset(); onSessionLost(); return;
    }
    const messages = {
      version_conflict: "Роль уже изменена. Загрузите аккаунт заново и проверьте новое состояние.",
      idempotency_conflict: "Этот запрос уже использован. Загрузите аккаунт заново.",
      last_product_admin: "Это последний активный администратор. Сначала назначьте другого.",
      role_target_unavailable: "Аккаунт не найден или отключён. Проверьте ID.",
      product_role_unchanged: "Эта роль уже назначена. Загрузите актуальные данные.",
      invalid_role_command: "Проверьте роль и непустую причину изменения.",
    };
    message(messages[error.code] || "Не удалось получить подтверждение сервера. Проверьте соединение и повторите запрос.", true);
  }
  async function revalidate() {
    // Mutations enforce live access server-side. Do not discard an uncertain command
    // (and its replay key) because a concurrent focus check lost its connection.
    if (!profile || verifying || busy || pending) return;
    const current = epoch;
    verifying = true;
    try {
      const data = await request("/me");
      if (current === epoch) setProfile(data.user);
    } catch (error) {
      if (current !== epoch) return;
      // Do not leave protected account details visible when access cannot be checked.
      clearTarget();
      failed(error);
    } finally { verifying = false; }
  }
  async function open() {
    if (profile?.product_role !== "admin") return;
    el.productAccess.hidden = false;
    await revalidate();
    if (!el.productAccess.hidden) {
      el.accessTitle.focus();
      el.productAccess.scrollIntoView({ block: "start", behavior: "instant" });
    }
  }
  function renderAudit(actions) {
    el.accessAudit.replaceChildren();
    if (!actions.length) {
      const item = document.createElement("li");
      item.textContent = "Роль ещё не менялась.";
      el.accessAudit.append(item);
    }
    for (const action of actions) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = `${productRoleLabel(action.previous_role)} → ${productRoleLabel(action.resulting_role)}`;
      const reason = document.createElement("p"); reason.textContent = action.reason;
      const meta = document.createElement("small");
      meta.textContent = `${new Date(action.created_at).toLocaleString("ru-RU")} · ${action.actor_user_id ? `Администратор ${action.actor_user_id}` : "Первичное назначение оператором"} · версия ${action.resulting_version}`;
      item.append(title, reason, meta); el.accessAudit.append(item);
    }
  }
  async function load() {
    if (busy || pending || profile?.product_role !== "admin") return;
    const id = el.accessUserId.value.trim().toLowerCase();
    clearTarget();
    if (!/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id)) {
      message("Введите полный ID аккаунта в формате UUID.", true); return;
    }
    const current = epoch;
    busy = true; controls(); message("Загружаем аккаунт и историю…");
    try {
      const [user, actions] = await Promise.all([
        request(`/platform/users/${id}/role`), request(`/platform/users/${id}/role-audit`),
      ]);
      if (current !== epoch) return;
      target = user;
      el.accessTarget.textContent = user.id;
      el.accessCurrent.textContent = `${productRoleLabel(user.product_role)} · версия ${user.version}${user.enabled ? "" : " · Аккаунт отключён"}`;
      el.accessRole.value = user.product_role;
      el.accessRoleHint.textContent = hints[user.product_role];
      renderAudit(actions);
      el.accessDetails.hidden = false;
      message(user.enabled ? "Выберите новую роль и укажите причину." : "Для отключённого аккаунта смена роли недоступна.");
    } catch (error) { if (current === epoch) failed(error); }
    finally { if (current === epoch) { busy = false; controls(); } }
  }
  async function save() {
    if (!pending || busy || profile?.product_role !== "admin") return;
    const current = epoch;
    const command = pending;
    busy = true; controls(); message("Сохраняем роль…");
    try {
      await request(`/platform/users/${command.userId}/role`, {
        method: "POST", headers: { "Idempotency-Key": command.key }, body: JSON.stringify(command.body),
      });
      if (current !== epoch) return;
      pending = null; busy = false;
      // Revocation of our own role must hide the panel before another admin read.
      if (command.userId === profile.id) setProfile({ ...profile, product_role: command.body.role });
      if (profile?.product_role !== "admin") return;
      await load();
      if (epoch === current + 1 && target) message("Роль сохранена. История обновлена.");
    } catch (error) {
      if (current !== epoch) return;
      if (error.status >= 400 && error.status < 500) clearTarget();
      failed(error);
    } finally {
      if (current === epoch) { busy = false; controls(); }
    }
  }
  el.productAccessLink.addEventListener("click", event => { event.preventDefault(); void open(); });
  el.accessClose.addEventListener("click", () => { el.productAccess.hidden = true; el.productAccessLink.focus(); });
  el.accessLookup.addEventListener("submit", event => { event.preventDefault(); void load(); });
  el.accessUserId.addEventListener("input", () => { if (!busy && !pending) { clearTarget(); message(""); } });
  el.accessRole.addEventListener("change", () => { el.accessRoleHint.textContent = hints[el.accessRole.value]; controls(); });
  el.accessForm.addEventListener("submit", event => {
    event.preventDefault();
    if (!target?.enabled || busy || pending || el.accessRole.value === target.product_role) return;
    const reason = el.accessReason.value.trim();
    if (!reason) { message("Укажите причину изменения.", true); el.accessReason.focus(); return; }
    draft = { userId: target.id, body: { role: el.accessRole.value, expected_version: target.version, reason } };
    el.accessConfirmation.textContent = `Аккаунт: ${target.id}\n${productRoleLabel(target.product_role)} → ${productRoleLabel(draft.body.role)}\nПричина: ${reason}${target.id === profile.id ? "\nВы меняете собственную роль." : ""}`;
    el.accessDialog.returnValue = "cancel";
    el.accessDialog.showModal();
  });
  el.accessDialog.addEventListener("close", () => {
    const command = draft; draft = null;
    if (el.accessDialog.returnValue === "confirm" && command && profile?.product_role === "admin") {
      pending = { ...command, key: crypto.randomUUID() }; void save();
    } else if (!el.productAccess.hidden && target) el.accessReview.focus();
  });
  el.accessDialog.addEventListener("keydown", event => {
    if (event.key !== "Tab") return;
    const [first, last] = el.accessDialog.querySelectorAll("button");
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  el.accessRetry.addEventListener("click", () => { void save(); });
  window.addEventListener("focus", () => { if (!el.productAccess.hidden) void revalidate(); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !el.productAccess.hidden) void revalidate(); });
  return { setProfile, reset, open, revalidate };
}
