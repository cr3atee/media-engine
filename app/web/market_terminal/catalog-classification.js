export function createCatalogClassification({ request, onAccessLoss }) {
  const elements = {
    section: document.querySelector("#catalogClassification"),
    integration: document.querySelector("#classificationIntegration"),
    source: document.querySelector("#classificationSource"),
    hub: document.querySelector("#classificationHub"),
    subsection: document.querySelector("#classificationSection"),
    form: document.querySelector("#classificationForm"),
    submit: document.querySelector("#classificationSubmit"),
    message: document.querySelector("#classificationMessage"),
    rules: document.querySelector("#classificationRules"),
    count: document.querySelector("#classificationRuleCount"),
  };
  const state = {
    context: null,
    integrations: [],
    hubs: [],
    rules: [],
    sources: [],
    epoch: 0,
  };

  elements.integration.addEventListener("change", () => void loadIntegrationData());
  elements.source.addEventListener("change", syncRuleForm);
  elements.hub.addEventListener("change", () => {
    renderSectionOptions();
    syncSubmitState();
  });
  elements.subsection.addEventListener("change", syncSubmitState);
  elements.form.addEventListener("submit", event => {
    event.preventDefault();
    void saveRule();
  });

  function setContext(context) {
    resetState();
    state.context = context;
    elements.section.hidden = !context;
  }

  async function load() {
    if (!state.context) return;
    const epoch = ++state.epoch;
    const tenant = encodeURIComponent(state.context.tenant_id);
    setBusy(true);
    setMessage("Загружаем правила категорий…");
    try {
      const [taxonomy, integrations] = await Promise.all([
        request(`/tenants/${tenant}/catalog/classification/taxonomy`),
        request(`/tenants/${tenant}/marketplace-integrations`),
      ]);
      if (!isCurrent(epoch)) return;
      state.hubs = taxonomy.hubs;
      state.integrations = integrations;
      state.sources = [];
      renderHubOptions();
      renderIntegrationOptions();
      if (elements.integration.value) {
        await loadIntegrationData(epoch);
      } else {
        state.rules = [];
        renderRules();
        setMessage(
          integrations.length
            ? "Выберите подключение площадки."
            : "Сначала добавьте подключение площадки.",
        );
      }
    } catch (error) {
      if (!isCurrent(epoch) || onAccessLoss(error)) return;
      setMessage(error.message || "Не удалось загрузить правила категорий.", true);
    } finally {
      if (isCurrent(epoch)) setBusy(false);
    }
  }

  async function loadIntegrationData(parentEpoch = null) {
    const epoch = parentEpoch ?? ++state.epoch;
    if (!state.context || !elements.integration.value) {
      state.rules = [];
      state.sources = [];
      renderSourceOptions();
      renderRules();
      syncSubmitState();
      return;
    }
    const tenant = encodeURIComponent(state.context.tenant_id);
    const integration = encodeURIComponent(elements.integration.value);
    state.rules = [];
    state.sources = [];
    renderSourceOptions();
    renderRules();
    setBusy(true);
    setMessage("Загружаем соответствия…");
    try {
      const [rules, sources] = await Promise.all([
        request(
          `/tenants/${tenant}/catalog/classification/integrations/${integration}/rules`,
        ),
        request(
          `/tenants/${tenant}/catalog/classification/integrations/${integration}/source-categories`,
        ),
      ]);
      if (!isCurrent(epoch)) return;
      state.rules = rules;
      state.sources = mergeSources(sources, rules);
      renderSourceOptions();
      renderRules();
      setMessage(
        filteredSources().length === 0
          ? "В сохранённых объявлениях этой площадки пока нет категории источника."
          : rules.length
          ? "Правила применяются при каждом следующем опросе площадки."
          : "Для этого подключения правила ещё не заданы.",
      );
    } catch (error) {
      if (!isCurrent(epoch) || onAccessLoss(error)) return;
      setMessage(error.message || "Не удалось загрузить соответствия.", true);
    } finally {
      if (isCurrent(epoch)) setBusy(false);
    }
  }

  async function saveRule() {
    const integration = selectedIntegration();
    const source = selectedSource();
    const existing = selectedRule();
    if (!state.context || !integration || !source || !formComplete()) return;
    const epoch = state.epoch;
    const tenantId = encodeURIComponent(state.context.tenant_id);
    const integrationId = encodeURIComponent(integration.id);
    const endpoint = existing
      ? `/tenants/${tenantId}/catalog/classification/integrations/${integrationId}/rules/update`
      : `/tenants/${tenantId}/catalog/classification/integrations/${integrationId}/rules`;
    const payload = {
      marketplace: integration.marketplace,
      source_category_id: source.id,
      source_category_name: source.name,
      hub_code: elements.hub.value,
      section_code: elements.subsection.value,
    };
    if (existing) payload.expected_version = existing.version;

    setBusy(true);
    setMessage(existing ? "Обновляем правило…" : "Сохраняем правило…");
    try {
      const saved = await request(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (!isCurrent(epoch)) return;
      state.rules = [
        ...state.rules.filter(rule => rule.id !== saved.id),
        saved,
      ].sort(compareRules);
      renderRules();
      syncRuleForm();
      setMessage("Правило сохранено и будет применено при следующем опросе площадки.");
    } catch (error) {
      if (!isCurrent(epoch) || onAccessLoss(error)) return;
      setMessage(error.message || "Не удалось сохранить правило.", true);
    } finally {
      if (isCurrent(epoch)) setBusy(false);
    }
  }

  function renderIntegrationOptions() {
    const previous = elements.integration.value;
    const options = [option("", "Выберите подключение")];
    for (const integration of state.integrations) {
      const status = integration.enabled ? "включено" : "выключено";
      options.push(
        option(
          integration.id,
          `${integration.display_name} · ${integration.marketplace.toUpperCase()} · ${status}`,
        ),
      );
    }
    elements.integration.replaceChildren(...options);
    if (state.integrations.some(item => item.id === previous)) {
      elements.integration.value = previous;
    } else if (state.integrations.length === 1) {
      elements.integration.value = state.integrations[0].id;
    }
    renderSourceOptions();
  }

  function renderSourceOptions() {
    const previous = elements.source.value;
    const integration = selectedIntegration();
    const available = integration
      ? state.sources.filter(source => source.marketplace === integration.marketplace)
      : [];
    const options = [option("", "Выберите категорию площадки")];
    for (const source of available) {
      options.push(option(source.id, sourceLabel(source)));
    }
    elements.source.replaceChildren(...options);
    if (available.some(item => item.id === previous)) {
      elements.source.value = previous;
    }
    elements.source.disabled = !integration || available.length === 0;
    syncRuleForm();
  }

  function renderHubOptions() {
    const options = state.hubs.map(hub => option(hub.code, hub.name));
    elements.hub.replaceChildren(...options);
    renderSectionOptions();
  }

  function renderSectionOptions() {
    const hub = selectedHub();
    const previous = elements.subsection.value;
    const options = (hub?.sections || []).map(section =>
      option(section.code, section.name),
    );
    elements.subsection.replaceChildren(...options);
    if (options.some(item => item.value === previous)) {
      elements.subsection.value = previous;
    }
    syncSubmitState();
  }

  function renderRules() {
    elements.count.textContent = String(state.rules.length);
    if (state.rules.length === 0) {
      const empty = document.createElement("p");
      empty.className = "classification-empty";
      empty.textContent = "Сохранённых соответствий нет.";
      elements.rules.replaceChildren(empty);
      return;
    }
    elements.rules.replaceChildren(...state.rules.sort(compareRules).map(ruleRow));
  }

  function ruleRow(rule) {
    const row = document.createElement("div");
    row.className = "classification-rule";
    const source = document.createElement("span");
    const sourceName = document.createElement("strong");
    sourceName.textContent = rule.source_category_name || rule.source_category_id;
    const sourceId = document.createElement("small");
    sourceId.textContent = rule.source_category_id;
    source.append(sourceName, sourceId);

    const arrow = document.createElement("span");
    arrow.className = "classification-arrow";
    arrow.textContent = "→";
    arrow.setAttribute("aria-hidden", "true");

    const target = document.createElement("span");
    const targetName = document.createElement("strong");
    targetName.textContent = targetLabel(rule);
    const version = document.createElement("small");
    version.textContent = `Версия ${rule.version}`;
    target.append(targetName, version);
    row.append(source, arrow, target);
    return row;
  }

  function syncRuleForm() {
    const rule = selectedRule();
    if (rule) {
      elements.hub.value = rule.hub_code;
      renderSectionOptions();
      elements.subsection.value = rule.section_code;
    }
    elements.submit.textContent = rule ? "Обновить правило" : "Сохранить правило";
    syncSubmitState();
  }

  function syncSubmitState() {
    elements.submit.disabled = !formComplete();
  }

  function formComplete() {
    return Boolean(
      selectedIntegration() &&
      selectedSource() &&
      elements.hub.value &&
      elements.subsection.value,
    );
  }

  function selectedIntegration() {
    return state.integrations.find(item => item.id === elements.integration.value) || null;
  }

  function selectedSource() {
    const integration = selectedIntegration();
    if (!integration) return null;
    return state.sources.find(
      item => item.marketplace === integration.marketplace && item.id === elements.source.value,
    ) || null;
  }

  function selectedHub() {
    return state.hubs.find(item => item.code === elements.hub.value) || null;
  }

  function selectedRule() {
    const source = selectedSource();
    const integration = selectedIntegration();
    if (!source || !integration) return null;
    return state.rules.find(rule =>
      rule.integration_id === integration.id &&
      rule.marketplace === source.marketplace &&
      rule.source_category_id === source.id
    ) || null;
  }

  function targetLabel(rule) {
    const hub = state.hubs.find(item => item.code === rule.hub_code);
    const section = hub?.sections.find(item => item.code === rule.section_code);
    return `${hub?.name || rule.hub_code} · ${section?.name || rule.section_code}`;
  }

  function setBusy(isBusy) {
    elements.section.setAttribute("aria-busy", String(isBusy));
    for (const control of elements.form.querySelectorAll("select, button")) {
      control.disabled = isBusy || (control === elements.source && !selectedIntegration());
    }
    if (!isBusy) {
      elements.source.disabled = !selectedIntegration() || filteredSources().length === 0;
      syncSubmitState();
    }
  }

  function setMessage(message, isError = false) {
    elements.message.textContent = message;
    elements.message.classList.toggle("error", isError);
  }

  function filteredSources() {
    const integration = selectedIntegration();
    return integration
      ? state.sources.filter(source => source.marketplace === integration.marketplace)
      : [];
  }

  function resetState() {
    state.epoch += 1;
    state.context = null;
    state.integrations = [];
    state.hubs = [];
    state.rules = [];
    state.sources = [];
    elements.section.hidden = true;
    elements.form.reset();
    elements.integration.replaceChildren(option("", "Выберите подключение"));
    elements.source.replaceChildren(option("", "Выберите категорию площадки"));
    elements.hub.replaceChildren();
    elements.subsection.replaceChildren();
    elements.rules.replaceChildren();
    elements.count.textContent = "0";
    setMessage("");
  }

  function isCurrent(epoch) {
    return Boolean(state.context) && epoch === state.epoch;
  }

  return { load, reset: resetState, setContext };
}

function option(value, label) {
  const item = document.createElement("option");
  item.value = value;
  item.textContent = label;
  return item;
}

function sourceLabel(source) {
  const identity = source.name ? `${source.name} · ${source.id}` : source.id;
  const availability = source.offerCount > 0
    ? String(source.offerCount)
    : "правило сохранено";
  return `${identity} · ${availability}`;
}

function mergeSources(sources, rules) {
  const merged = sources.map(source => ({
    marketplace: source.marketplace,
    id: source.source_category_id,
    name: source.source_category_name,
    offerCount: source.offer_count,
  }));
  const identities = new Set(
    merged.map(source => `${source.marketplace}\u0000${source.id}`),
  );
  for (const rule of rules) {
    const identity = `${rule.marketplace}\u0000${rule.source_category_id}`;
    if (identities.has(identity)) continue;
    identities.add(identity);
    merged.push({
      marketplace: rule.marketplace,
      id: rule.source_category_id,
      name: rule.source_category_name,
      offerCount: 0,
    });
  }
  return merged;
}

function compareRules(left, right) {
  return (left.source_category_name || left.source_category_id).localeCompare(
    right.source_category_name || right.source_category_id,
    "ru",
  );
}
