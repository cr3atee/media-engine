/** Real cabinet UI with intercepted API fixtures. Never writes to a database. */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.TERMINAL_PREVIEW_URL ?? "http://127.0.0.1:8001";
const debug = process.env.TERMINAL_CDP_URL ?? "http://127.0.0.1:9224";
for (const address of [base, debug]) {
  assert(["127.0.0.1", "localhost"].includes(new URL(address).hostname), "Loopback instances only");
}
const output = await mkdtemp(join(tmpdir(), "mediaengine-review-ui-"));
const target = await (await fetch(`${debug}/json/new?about:blank`, { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
let checks = 0;
const pending = new Map();
const errors = [];
const mutations = [];
let mutationStatus = 409;
let loginStatus = 401;
let empty = false;
let forbidden = false;
let expireOnce = false;
let refreshCount = 0;
let browserSession = false;
let workspaceError = null;
let mutationError = null;
let holdPath = null;
let heldReply = null;
let heldRequest = null;
let settingsTarget;
let settingsSession;
let originalZoom;
const tenant = "11111111-1111-4111-8111-111111111111";
const secondTenant = "33333333-3333-4333-8333-333333333333";
const canonical = "22222222-2222-4222-8222-222222222222";
const title = "Minecraft Java & Bedrock Edition · PC · ключ Microsoft · GLOBAL";
const candidate = { marketplace: "funpay", external_id: "fixture-review", canonical_product_id: canonical, canonical_product_name: title, canonical_product_category: "Игры", offer_title: `${title} <тест>`, offer_price: "990.00", currency: "RUB", similarity: .9, match_decision: "review", offer_url: "https://example.com/offer" };
const proposals = [
  { proposal_id: "fixture-proposal", marketplace: "ggsel", external_id: "fixture-new", proposed_name: "Minecraft Java & Bedrock Edition, цифровой ключ для компьютера", nearest_canonical_product_id: canonical, nearest_canonical_product_name: title, nearest_similarity: .7, offer_price: "790.00", currency: "RUB", match_decision: "no_match", offer_url: "https://example.com/offer" },
  { proposal_id: "fixture-missing", marketplace: "playerok", external_id: "fixture-missing", proposed_name: "Minecraft для iOS", nearest_canonical_product_id: null, nearest_canonical_product_name: null, nearest_similarity: 0, offer_price: null, currency: null, match_decision: "no_match", offer_url: "javascript:alert(1)" },
];
const summary = { total_offers: 3, linked_offers: 0, review_candidates: 1, product_proposals: 2, canonical_products: 1, terminal_decisions: 0, unqueued_offers: 0, unresolved_offers: 3, marketplaces: ["funpay", "ggsel", "playerok"].map(marketplace => ({ marketplace, linked_offers: 0, total_offers: 1, review_candidates: marketplace === "funpay" ? 1 : 0, product_proposals: marketplace === "funpay" ? 0 : 1, unqueued_offers: 0 })) };

function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
async function intercept({ requestId, request }) {
  const url = new URL(request.url);
  if (url.origin !== new URL(base).origin) return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
  if (!url.pathname.startsWith("/api/")) {
    assert.equal(request.method, "GET", "Only static GET requests may reach the server");
    return send("Fetch.continueRequest", { requestId });
  }
  let responseCode = 200;
  let body = {};
  const path = url.pathname;
  if (path.endsWith("/auth/browser/login")) {
    responseCode = loginStatus;
    browserSession = loginStatus === 200;
    body = loginStatus === 200 ? { access_token: "fixture-access", refresh_token: "fixture-refresh" } : { error: { code: "invalid_credentials" } };
  } else if (path.endsWith("/auth/browser/refresh")) {
    if (browserSession) refreshCount++;
    else responseCode = 401;
    body = { access_token: "fixture-renewed", refresh_token: "fixture-refresh" };
  } else if (path.endsWith("/me")) {
    body = { user: { display_name: "Тестовый продавец", email: "review@example.test" }, memberships: [tenant, secondTenant].map(id => ({ is_active: true, tenant_id: id, tenant_name: id === tenant ? "Проверка интерфейса (fixture)" : "Второе пространство (fixture)", role: "owner" })) };
  } else if (path.endsWith("/context")) {
    const selected = path.split("/")[4];
    body = { tenant_id: selected, tenant_name: selected === tenant ? "Проверка интерфейса (fixture)" : "Второе пространство (fixture)", role: forbidden ? "viewer" : "owner", permissions: forbidden ? [] : ["catalog_review"] };
  } else if (path.endsWith("/onboarding-workspace")) {
    if (workspaceError) { responseCode = workspaceError.status; body = { error: { code: workspaceError.code } }; }
    else if (expireOnce) { expireOnce = false; responseCode = 401; }
    else body = { summary: empty ? { ...summary, linked_offers: 3, review_candidates: 0, product_proposals: 0, unresolved_offers: 0 } : summary, review_candidates: empty ? [] : [candidate], product_proposals: empty ? [] : proposals };
  } else if (path.endsWith("/auth/browser/logout")) {
    browserSession = false;
    body = {};
  } else if (path.includes("/catalog/") && request.method === "POST") {
    mutations.push(request);
    responseCode = mutationStatus;
    body = mutationStatus === 409 ? { error: { code: "canonical_offer_link_conflict" } } : {};
    if (mutationError) body = { error: { code: mutationError } };
    if (mutationStatus === 200) empty = true;
  } else {
    throw new Error(`Unexpected fixture API request: ${request.method} ${path}`);
  }
  const reply = () => send("Fetch.fulfillRequest", { requestId, responseCode, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(body)).toString("base64") });
  if (holdPath && path.endsWith(holdPath)) {
    holdPath = null;
    heldRequest = request;
    heldReply = reply;
    return;
  }
  await reply();
}
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const item = pending.get(message.id);
    if (!item) return;
    pending.delete(message.id);
    clearTimeout(item.timer);
    if (message.error) item.reject(new Error(JSON.stringify(message.error)));
    else item.resolve(message.result);
  }
  if (message.method === "Fetch.requestPaused") void intercept(message.params).catch(error => errors.push(String(error)));
  if (message.method === "Runtime.exceptionThrown") errors.push(message.params);
  if (message.method === "Log.entryAdded" && message.params.entry.source === "security") errors.push(message.params);
});
async function evaluate(expression, sessionId) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
  assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function until(expression) {
  for (let i = 0; i < 100; i++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  await screenshot("failure");
  console.error(await evaluate('({focus: document.activeElement.outerHTML, dialog: document.querySelector("dialog").open, errors: [...document.querySelectorAll(".card-message")].map(el=>el.textContent)})'));
  throw new Error(`Timed out: ${expression}`);
}
async function check(name, expression) {
  assert(await evaluate(expression), name);
  checks++;
  console.log(`PASS ${name}`);
}
async function click(selector) {
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'instant'})`);
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  const point = await evaluate(`(() => {const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
}
async function key(key, code, windowsVirtualKeyCode, modifiers = 0) {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode, modifiers });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode, modifiers });
}
async function screenshot(name) {
  await evaluate("document.fonts.ready");
  await new Promise(resolve => setTimeout(resolve, 250));
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(output, `${name}.png`), Buffer.from(capture.data, "base64"));
}
async function setBrowserZoom(factor) {
  if (!settingsSession) {
    ({ targetId: settingsTarget } = await send("Target.createTarget", { url: "chrome://settings/appearance" }));
    ({ sessionId: settingsSession } = await send("Target.attachToTarget", { targetId: settingsTarget, flatten: true }));
    for (let i = 0; i < 50; i++) {
      if (await evaluate('typeof chrome.settingsPrivate?.getDefaultZoom === "function"', settingsSession)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    originalZoom = await evaluate("new Promise(resolve => chrome.settingsPrivate.getDefaultZoom(resolve))", settingsSession);
  }
  await evaluate(`new Promise(resolve => chrome.settingsPrivate.setDefaultZoom(${factor}, resolve))`, settingsSession);
  await send("Page.bringToFront");
}
const source = '[data-external-id="fixture-new"]';
const resolve = `${source} [data-action="resolve-existing"]`;
async function openResolve() { await click(resolve); await until('document.querySelector("#decisionDialog").open'); }
async function submit() {
  await click("#decisionConfirm");
  await until('!document.querySelector("#decisionDialog").open');
  // The native dialog close event is queued after its form submission.
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  await until('document.querySelector("#workspaceMessage").textContent !== "Сохраняем решение…" && document.querySelector("#reviewWorkspace").getAttribute("aria-busy") === "false"');
}
async function login() {
  await until('!document.querySelector("#loginButton").disabled');
  await evaluate('document.querySelector("#emailInput").value="review@example.test"; document.querySelector("#passwordInput").value="fixture-only"');
  await click("#loginButton");
}
async function waitForHeldReply() {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (heldReply) return;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error("Expected intercepted request did not arrive");
}
try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: `${base}/terminal/review` });
  await until('!!document.querySelector("#loginForm") && document.readyState === "complete"');
  await screenshot("01-login");
  await check("dark shared theme", 'getComputedStyle(document.documentElement).colorScheme === "dark"');
  await check("local Onest loaded", 'document.fonts.check("16px Onest")');
  await login();
  await until('document.querySelector("#loginMessage").classList.contains("error")');
  await check("login error is readable", 'document.querySelector("#loginMessage").textContent.includes("Неверная почта")');
  loginStatus = 200;
  await login();
  await until('document.querySelectorAll(".review-card").length === 3 && document.querySelector("#reviewWorkspace").getAttribute("aria-busy") === "false"');
  await check("real UI handles fixture tenant permissions", '!document.querySelector("#reviewWorkspace").hidden && document.querySelector("#tenantRole").textContent === "Владелец"');
  await until('[...document.images].every(img=>img.complete)');
  await check("all marketplace logos loaded", '[...document.images].every(img=>img.complete && img.naturalWidth>0)');
  await check("source and exact target separated", `document.querySelector('${source} .review-source').textContent.includes('цифровой ключ') && document.querySelector('${source} .candidate-link').textContent.includes('${canonical}')`);
  await check("external source is on source side only", `!!document.querySelector('${source} .review-source a') && !document.querySelector('${source} .candidate-link a')`);
  await check("unsafe source omitted and no target disabled", '!document.querySelector("[data-external-id=fixture-missing] a") && document.querySelector("[data-external-id=fixture-missing] .resolve").disabled');
  await check("titles escaped not interpreted", 'document.querySelector("[data-external-id=fixture-review] h3").textContent.includes("<тест>") && !document.querySelector("тест")');
  await evaluate('window.scrollTo(0,0)');
  await check("first review visible without opening statistics", 'document.querySelector(".review-card").getBoundingClientRect().top < innerHeight && !document.querySelector(".workspace-overview").open');
  await screenshot("02-workspace");
  await click('.workspace-overview > summary');
  await check("statistics remain accessible", 'document.querySelector("#offerCount").textContent === "3" && document.querySelector("#marketplaceProgress").getBoundingClientRect().height > 0');
  await click('.workspace-overview > summary');
  await evaluate('document.querySelector("#queueSearchInput").value="fixture-new"; document.querySelector("#queueSearchInput").dispatchEvent(new Event("input"))');
  await check("queue search selects exact source ID", 'document.querySelectorAll(".review-card").length === 1 && document.querySelector(".review-card").dataset.externalId === "fixture-new"');
  await click('#resetQueueFilters');
  await click('[data-external-id="fixture-review"] summary');
  await click('[data-external-id="fixture-review"] .reject');
  await check("rejection requires explanation", 'document.querySelector("[data-external-id=fixture-review] .card-message").textContent.includes("причину") && !document.querySelector("dialog").open');
  await click('[data-external-id="fixture-review"] .confirm');
  await until('document.querySelector("dialog").open');
  await check("candidate confirm uses exact target too", `document.querySelector('#decisionTargetId').textContent.includes('${canonical}') && document.querySelector('#decisionFacts').textContent.includes('не добавлен')`);
  await key("Escape", "Escape", 27);
  await until('!document.querySelector("dialog").open');
  await click(`${source} summary`);
  await click(resolve);
  await check("link requires facts inline without losing focus", `!document.querySelector('#decisionDialog').open && document.querySelector('${source} .card-message').textContent.includes('проверенные факты') && document.activeElement.matches('.review-reason')`);
  await evaluate(`document.querySelector('${source} textarea').value='PC, ключ Microsoft, GLOBAL; не аккаунт.'`);
  await openResolve();
  await check("dialog names both entities and target ID", `document.querySelector('#decisionSource').textContent.includes('цифровой ключ') && document.querySelector('#decisionTargetId').textContent.includes('${canonical}')`);
  await check("cancel gets initial focus", 'document.activeElement.value === "cancel"');
  await key("Tab", "Tab", 9, 8);
  await check("shift tab stays inside dialog", 'document.activeElement.id === "decisionConfirm"');
  await key("Tab", "Tab", 9);
  await check("tab wraps to cancel", 'document.activeElement.value === "cancel"');
  await screenshot("03-confirmation");
  await key("Escape", "Escape", 27);
  await until('!document.querySelector("#decisionDialog").open');
  await check("escape restores opener and facts", `document.activeElement.matches('${resolve}') && document.querySelector('${source} textarea').value.includes('GLOBAL')`);
  assert.equal(mutations.length, 0, "No mutation on opening or cancelling dialog"); checks++;
  mutationStatus = 409;
  await openResolve(); await submit();
  await until(`document.querySelector('${source} .card-message').textContent.includes('другим товаром')`);
  await check("409 preserves facts and does not show success", `document.querySelector('${source} textarea').value.includes('GLOBAL') && document.querySelector('#workspaceMessage').classList.contains('error')`);
  assert.equal(JSON.parse(mutations.at(-1).postData).canonical_product_id, canonical); checks++;
  mutationStatus = 503;
  await openResolve(); await submit();
  await until(`document.querySelector('${source} .card-message').textContent.includes('Не удалось')`);
  const retryKey = Object.entries(mutations.at(-1).headers).find(([k]) => k.toLowerCase() === "idempotency-key")[1];
  await openResolve(); await submit();
  await until(`document.querySelector('${source} .card-message').textContent.includes('Не удалось')`);
  assert.equal(Object.entries(mutations.at(-1).headers).find(([k]) => k.toLowerCase() === "idempotency-key")[1], retryKey); checks++;
  const count = mutations.length;
  await evaluate(`document.querySelector('${source} textarea').value='Изменённые факты'`);
  await openResolve(); await submit();
  await until(`document.querySelector('${source} .card-message').textContent.includes('неоднозначно')`);
  assert.equal(mutations.length, count, "Changed ambiguous payload not sent"); checks++;
  await screenshot("04-inline-error");
  const ratio = await evaluate("devicePixelRatio");
  await setBrowserZoom(2);
  await check("native 200 percent zoom applied", `devicePixelRatio >= ${ratio * 1.9}`);
  await check("zoomed workspace has no horizontal scroll", 'document.documentElement.scrollWidth <= innerWidth');
  await openResolve();
  await check("zoomed dialog retains accessible actions", 'document.querySelector("dialog").getBoundingClientRect().right <= innerWidth && document.querySelector("#decisionConfirm").getBoundingClientRect().height >= 44');
  await screenshot("08-dialog-zoom200");
  await key("Escape", "Escape", 27);
  await until('!document.querySelector("dialog").open');
  await setBrowserZoom(originalZoom);
  for (const width of [800, 390, 320]) {
    await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    await check(`no horizontal overflow at ${width}`, 'document.documentElement.scrollWidth <= innerWidth');
    await evaluate(`document.querySelector('${source}').scrollIntoView({block:'start'})`);
    await screenshot(`05-pair-${width}`);
    await openResolve();
    await check(`dialog fits at ${width}`, 'document.querySelector("dialog").getBoundingClientRect().right <= innerWidth && document.querySelector("dialog").getBoundingClientRect().left >= 0');
    await screenshot(`06-dialog-${width}`);
    await key("Escape", "Escape", 27);
    await until('!document.querySelector("dialog").open');
  }
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await check("reduced motion disables transitions", 'getComputedStyle(document.querySelector("#reloadButton")).transitionDuration === "0s"');
  expireOnce = true;
  await click("#reloadButton");
  await until('!document.querySelector("#reviewWorkspace").hidden && document.querySelectorAll(".review-card").length === 3 && document.querySelector("#reviewWorkspace").getAttribute("aria-busy") === "false"');
  assert.equal(refreshCount, 1); checks++;
  await click('[data-external-id="fixture-missing"] summary');
  await click('[data-external-id="fixture-missing"] .create');
  await until('document.querySelector("dialog").open');
  await check("create is optional facts and names new product", 'document.querySelector("#decisionTargetLabel").textContent === "Новый товар" && document.querySelector("#decisionFacts").textContent.includes("не добавлен")');
  mutationStatus = 503;
  await submit();
  await until('document.querySelector("[data-external-id=fixture-missing] .card-message").textContent.length > 0');
  await check("failure does not enable unavailable target", 'document.querySelector("[data-external-id=fixture-missing] .resolve").disabled');
  mutationStatus = 200;
  await click('[data-external-id="fixture-missing"] .create');
  await until('document.querySelector("dialog").open');
  await submit();
  await until('document.querySelectorAll(".review-card").length === 0');
  await check("empty completed queue is explicit", 'document.querySelector("#workspaceMessage").textContent.includes("все объявления связаны")');
  await screenshot("07-completed");
  await click("#logoutButton");
  await until('!document.querySelector("#loginForm").hidden');
  await check("logout clears workspace", 'document.querySelector("#reviewWorkspace").hidden && document.querySelectorAll(".review-card").length === 0');
  forbidden = true;
  await login();
  await until('document.querySelector("#sessionStatus").textContent === "Недостаточно прав"');
  await check("missing permission hides decisions", 'document.querySelector("#reviewWorkspace").hidden');
  forbidden = false;
  empty = false;
  const readyWorkspace = () => until('!document.querySelector("#reviewWorkspace").hidden && document.querySelectorAll(".review-card").length === 3 && !document.querySelector("#reloadButton").disabled');
  const reload = async () => { await click("#reloadButton"); await readyWorkspace(); };
  const cleared = 'document.querySelector("#reviewWorkspace").hidden && document.querySelectorAll(".review-card").length === 0 && document.querySelector("#decisionSource").textContent === "" && document.querySelector("#decisionFacts").textContent === ""';
  await reload();
  for (const issue of [{ status: 403, code: "permission_denied" }, { status: 404, code: "tenant_not_found" }]) {
    workspaceError = issue;
    await click("#reloadButton");
    await until('document.querySelector("#sessionStatus").textContent === "Доступ изменился"');
    await check(`${issue.code} purges protected data`, cleared);
    await check("revocation leaves recovery controls available", '!document.querySelector("#tenantSelect").disabled && !document.querySelector("#reloadButton").disabled && !document.querySelector("#sessionPanel").hidden');
    workspaceError = null;
    await reload();
  }
  mutationStatus = 403;
  mutationError = "permission_denied";
  await click(`${source} summary`);
  await evaluate(`document.querySelector('${source} textarea').value='Facts before revoked action'`);
  await openResolve(); await submit();
  await until('document.querySelector("#sessionStatus").textContent === "Доступ изменился"');
  await check("write permission revocation purges form and dialog", cleared);
  await reload();
  mutationStatus = 404;
  mutationError = "canonical_review_target_not_found";
  await click(`${source} summary`);
  await evaluate(`document.querySelector('${source} textarea').value='Facts for missing target'`);
  await openResolve(); await submit();
  await check("missing object is not mistaken for revoked workspace", `!document.querySelector('#reviewWorkspace').hidden && document.querySelector('${source} textarea').value.includes('missing target')`);
  mutationStatus = 503;
  mutationError = null;
  await reload();
  // A delayed mutation from A must not write status or queue into workspace B.
  await click(`${source} summary`);
  await evaluate(`document.querySelector('${source} textarea').value='Pending workspace A facts'`);
  holdPath = "/resolve-existing";
  await openResolve();
  await click("#decisionConfirm");
  await waitForHeldReply();
  const oldReply = heldReply;
  const oldKey = Object.entries(heldRequest.headers).find(([name]) => name.toLowerCase() === "idempotency-key")[1];
  heldReply = null;
  await evaluate(`document.querySelector('#tenantSelect').value='${secondTenant}'; document.querySelector('#tenantSelect').dispatchEvent(new Event('change'))`);
  await readyWorkspace();
  await oldReply();
  await evaluate('new Promise(resolve=>setTimeout(resolve,100))');
  await check("late mutation cannot overwrite new workspace", 'document.querySelector("#tenantLabel").textContent.startsWith("Второе") && !document.querySelector("#workspaceMessage").classList.contains("error")');
  await click(`${source} summary`);
  await evaluate(`document.querySelector('${source} textarea').value='Pending workspace A facts'`);
  await openResolve(); await submit();
  assert.notEqual(Object.entries(mutations.at(-1).headers).find(([name]) => name.toLowerCase() === "idempotency-key")[1], oldKey); checks++;
  assert(mutations.at(-1).url.includes(secondTenant)); checks++;
  // Force two overlapping context selections to verify stale-response guards.
  holdPath = "/context";
  await evaluate(`document.querySelector('#tenantSelect').value='${tenant}'; document.querySelector('#tenantSelect').dispatchEvent(new Event('change'))`);
  await waitForHeldReply();
  const contextReply = heldReply;
  heldReply = null;
  await check("switch hides previous workspace before response", cleared);
  await evaluate(`document.querySelector('#tenantSelect').value='${secondTenant}'; document.querySelector('#tenantSelect').dispatchEvent(new Event('change'))`);
  await readyWorkspace();
  await contextReply();
  await evaluate('new Promise(resolve=>setTimeout(resolve,100))');
  await check("late context cannot select the old tenant", `document.querySelector('#tenantSelect').value === '${secondTenant}' && document.querySelector('#tenantLabel').textContent.startsWith('Второе')`);
  workspaceError = { status: 403, code: "account_disabled" };
  await click("#reloadButton");
  await until('!document.querySelector("#loginForm").hidden');
  await check("disabled account clears identity and protected data", `${cleared} && document.querySelector('#sellerEmail').textContent === '' && document.querySelector('#tenantSelect').options.length === 0`);
  workspaceError = null;
  await login(); await readyWorkspace();
  // A pending successful read must not resurrect a logged-out session.
  empty = true;
  mutationStatus = 200;
  holdPath = "/onboarding-workspace";
  await click('[data-external-id="fixture-missing"] summary');
  await click('[data-external-id="fixture-missing"] .create');
  await until('document.querySelector("dialog").open');
  await click("#decisionConfirm");
  await waitForHeldReply();
  const queueReply = heldReply;
  heldReply = null;
  await click("#logoutButton");
  await until('!document.querySelector("#loginForm").hidden');
  await queueReply();
  await evaluate('new Promise(resolve=>setTimeout(resolve,100))');
  await check("late successful queue cannot resurrect logged-out data", cleared);
  await screenshot("09-access-revoked");
  assert.equal(errors.length, 0, JSON.stringify(errors)); checks++;
  console.log(`${checks} browser checks passed. API FIXTURES ONLY; no database writes. Screenshots: ${output}`);
} finally {
  if (settingsSession && originalZoom !== undefined) await setBrowserZoom(originalZoom);
  if (settingsTarget) await send("Target.closeTarget", { targetId: settingsTarget });
  // Close the intercepted target rather than ever resuming its fixture requests.
  await fetch(`${debug}/json/close/${target.id}`);
  if (socket.readyState !== WebSocket.CLOSED) {
    await new Promise(resolve => {
      socket.addEventListener("close", resolve, { once: true });
      socket.close();
    });
  }
}
