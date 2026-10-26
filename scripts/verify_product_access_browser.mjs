/** Real role controls with isolated API fixtures; no API traffic reaches a DB. */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.TERMINAL_PREVIEW_URL ?? "http://127.0.0.1:8003";
const debug = process.env.TERMINAL_CDP_URL ?? "http://127.0.0.1:9224";
for (const address of [base, debug]) assert(["127.0.0.1", "localhost"].includes(new URL(address).hostname));
const output = await mkdtemp(join(tmpdir(), "mediaengine-access-ui-"));
const tab = await (await fetch(`${debug}/json/new?about:blank`, { method: "PUT" })).json();
const socket = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});
let sequence = 0;
let checks = 0;
const replies = new Map();
const errors = [];
const requests = [];
const mutations = [];
const actor = "11111111-1111-4111-8111-111111111111";
const other = "22222222-2222-4222-8222-222222222222";
let role = "admin";
let target = { id: other, product_role: "user", enabled: true, version: 1 };
let audit = [];
let failure = null;
let hold = false;
let release = null;
let malformed = false;
let failIdentity = false;
let expire = false;
let refreshes = 0;
let browserSession = false;
let settingsTarget;
let settingsSession;
let originalZoom;
const results = new Map();

function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => reject(new Error(`CDP timeout: ${method}`)), 15000);
    replies.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
async function intercept({ requestId, request }) {
  const url = new URL(request.url);
  if (url.origin !== new URL(base).origin) return send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" });
  if (!url.pathname.startsWith("/api/")) {
    assert.equal(request.method, "GET");
    return send("Fetch.continueRequest", { requestId });
  }
  requests.push(request);
  let code = 200;
  let data = {};
  const path = url.pathname;
  if (path.endsWith("/auth/browser/login")) { browserSession = true; data = { access_token: "fixture-access" }; }
  else if (path.endsWith("/auth/browser/logout")) { browserSession = false; data = {}; }
  else if (path.endsWith("/auth/browser/refresh")) {
    if (browserSession) { refreshes++; data = { access_token: "fixture-renewed" }; }
    else { code = 401; data = { error: { code: "browser_session_missing" } }; }
  }
  else if (path.endsWith("/me")) {
    data = { user: { id: actor, product_role: role, display_name: "Анна · администратор", email: "admin@example.test" }, memberships: [] };
    if (failIdentity) { code = 503; data = { error: { code: "unavailable" } }; }
  } else if (path.includes("/platform/users/")) {
    assert(Object.entries(request.headers).some(([key, value]) => key.toLowerCase() === "authorization" && value.startsWith("Bearer ")));
    if (expire) { expire = false; code = 401; }
    else if (role !== "admin") { code = 403; data = { error: { code: "product_admin_required" } }; }
    else if (request.method === "POST") {
      mutations.push(request);
      const key = Object.entries(request.headers).find(([name]) => name.toLowerCase() === "idempotency-key")[1];
      const command = JSON.parse(request.postData);
      if (failure && failure !== "lost-success") { code = failure.status; data = { error: { code: failure.code } }; }
      else if (results.has(key)) data = results.get(key);
      else {
        data = { id: crypto.randomUUID(), user_id: target.id, actor_user_id: actor, previous_role: target.product_role, resulting_role: command.role, resulting_version: target.version + 1, reason: command.reason, created_at: "2026-10-26T08:00:00Z" };
        results.set(key, data); audit.unshift(data);
        target = { ...target, product_role: command.role, version: target.version + 1 };
        if (path.includes(actor)) role = command.role;
        if (failure === "lost-success") { code = 503; data = { error: { code: "unavailable" } }; }
      }
    } else if (path.endsWith("/role-audit")) data = audit;
    else data = path.includes(actor) ? { ...target, id: actor, product_role: role } : target;
  } else throw new Error(`Unexpected fixture API: ${request.method} ${path}`);
  const reply = () => send("Fetch.fulfillRequest", {
    requestId, responseCode: code, responseHeaders: [{ name: "Content-Type", value: "application/json" }],
    body: Buffer.from(malformed && path.endsWith("/role-audit") ? "not-json" : JSON.stringify(data)).toString("base64"),
  });
  if (hold && path.endsWith("/role") && request.method === "GET") { hold = false; release = reply; return; }
  await reply();
}
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const item = replies.get(message.id);
    if (item) { clearTimeout(item.timer); replies.delete(message.id); message.error ? item.reject(new Error(JSON.stringify(message.error))) : item.resolve(message.result); }
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
    await new Promise(resolve => setTimeout(resolve, 60));
  }
  throw new Error(`Timeout: ${expression}; ${JSON.stringify(await evaluate('({message:document.querySelector("#accessMessage").textContent, login:document.querySelector("#loginMessage").textContent})'))}`);
}
async function check(name, expression) { assert(await evaluate(expression), name); checks++; console.log(`PASS ${name}`); }
async function click(selector) {
  await evaluate("document.fonts.ready");
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center',behavior:'instant'})`);
  await evaluate('new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))');
  const point = await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
}
async function key(key, code, value, modifiers = 0) {
  for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key, code, windowsVirtualKeyCode: value, modifiers });
}
async function login() {
  await until('!document.querySelector("#loginButton").disabled');
  await evaluate('document.querySelector("#emailInput").value="admin@example.test"; document.querySelector("#passwordInput").value="fixture-only"');
  await click("#loginButton");
  await until('!document.querySelector("#sessionPanel").hidden');
}
async function load(id = other) {
  await until('!document.querySelector("#accessLoad").disabled');
  await evaluate(`document.querySelector('#accessUserId').value=${JSON.stringify(id)};document.querySelector('#accessUserId').dispatchEvent(new Event('input'))`);
  await click("#accessLoad");
  await until('!document.querySelector("#accessDetails").hidden && !document.querySelector("#accessLoad").disabled');
}
async function change(next, reason = "Проверенное назначение партнёра") {
  await evaluate(`document.querySelector('#accessRole').value=${JSON.stringify(next)};document.querySelector('#accessRole').dispatchEvent(new Event('change'));document.querySelector('#accessReason').value=${JSON.stringify(reason)}`);
  await click("#accessReview");
  await until('document.querySelector("#accessDialog").open');
}
async function confirm() { await click('#accessDialog button[value="confirm"]'); await until('!document.querySelector("#accessDialog").open'); }
async function screenshot(name) {
  await evaluate("document.fonts.ready");
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(output, `${name}.png`), Buffer.from(capture.data, "base64"));
}
async function zoom(factor) {
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
try {
  await send("Page.enable"); await send("Runtime.enable"); await send("Log.enable");
  await send("Fetch.enable", { patterns: [{ urlPattern: "*" }] });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: `${base}/terminal/review` });
  await until('Boolean(document.querySelector("#loginButton"))');
  await until('document.readyState === "complete"');
  await check("role controls hidden before login", 'document.querySelector("#productAccess").hidden && document.querySelector("#productAccessLink").hidden');
  for (const value of ["user", "partner", "moderator"]) {
    role = value; await login();
    await check(`${value} gets identity without admin controls or a workspace`, `document.querySelector('#productAccessLink').hidden && document.querySelector('#reviewWorkspace').hidden && document.querySelector('#accountId').textContent.includes('${actor}')`);
    await click("#logoutButton"); await until('!document.querySelector("#loginButton").disabled');
  }
  role = "admin"; await login();
  await until('!document.querySelector("#productAccess").hidden');
  await check("admin without memberships can manage roles", '!document.querySelector("#productAccessLink").hidden && document.querySelector("#reviewWorkspace").hidden');
  await evaluate('document.querySelector("#accessUserId").value="not-a-uuid"'); await click("#accessLoad");
  await check("invalid UUID rejected locally", 'document.querySelector("#accessMessage").textContent.includes("UUID")');
  await load();
  await check("empty audit and unchanged role disable save", 'document.querySelector("#accessAudit").textContent.includes("ещё не менялась") && document.querySelector("#accessReview").disabled');
  await evaluate('document.querySelector("#accessRole").value="partner"; document.querySelector("#accessRole").dispatchEvent(new Event("change")); document.querySelector("#accessReason").value="   "');
  await click("#accessReview");
  await check("blank reason cannot submit", '!document.querySelector("#accessDialog").open && document.querySelector("#accessMessage").textContent.includes("причину")');
  await change("partner");
  await check("confirmation contains exact account, transition and reason", `document.querySelector('#accessConfirmation').textContent.includes('${other}') && document.querySelector('#accessConfirmation').textContent.includes('Пользователь → Партнёр')`);
  await screenshot("01-confirmation-desktop");
  await key("Tab", "Tab", 9, 8);
  await check("dialog traps reverse Tab", 'document.activeElement.value === "confirm"');
  await key("Tab", "Tab", 9);
  await check("dialog traps forward Tab", 'document.activeElement.value === "cancel"');
  await key("Escape", "Escape", 27);
  await until('!document.querySelector("#accessDialog").open');
  await check("escape returns focus without mutation", 'document.activeElement.id === "accessReview"');
  assert.equal(mutations.length, 0); checks++;
  failure = "lost-success";
  await change("partner"); await confirm();
  await until('!document.querySelector("#accessRetry").hidden && !document.querySelector("#accessRetry").disabled');
  await check("uncertain result locks command fields", 'document.querySelector("#accessRole").disabled && document.querySelector("#accessUserId").disabled && document.querySelector("#accessReason").disabled');
  failIdentity = true;
  await evaluate('window.dispatchEvent(new Event("focus"))');
  await check("focus does not discard an uncertain command", '!document.querySelector("#accessRetry").hidden && document.querySelector("#accessReason").disabled');
  failIdentity = false;
  failure = null; await click("#accessRetry");
  await until('document.querySelector("#accessMessage").textContent.includes("Роль сохранена")');
  const keyOf = request => Object.entries(request.headers).find(([name]) => name.toLowerCase() === "idempotency-key")[1];
  assert.equal(keyOf(mutations[0]), keyOf(mutations[1])); assert.equal(mutations[0].postData, mutations[1].postData); assert.equal(audit.length, 1); checks += 3;
  await check("success updates version and audit", 'document.querySelector("#accessCurrent").textContent.includes("версия 2") && document.querySelectorAll("#accessAudit li").length === 1');
  audit[0].reason = '<img src=x onerror="alert(1)">'; await load();
  await check("audit text is not interpreted as HTML", '!document.querySelector("#accessAudit img") && document.querySelector("#accessAudit").textContent.includes("<img")');
  audit[0].reason = "Проверено партнёрское подключение. Доступ к рабочим пространствам выдаётся отдельно.";
  await load();
  await screenshot("02-access-desktop");
  await zoom(2);
  await check("native 200 percent zoom applied", 'Math.abs(devicePixelRatio - 2) < .1');
  await check("zoomed editor has no horizontal overflow", 'document.documentElement.scrollWidth <= innerWidth + 1');
  await change("moderator");
  await check("zoomed confirmation fits viewport", 'document.querySelector("#accessDialog").getBoundingClientRect().width < innerWidth');
  await screenshot("05-confirmation-zoom");
  await key("Escape", "Escape", 27);
  await zoom(1);
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: false });
  await evaluate('document.querySelector("#accessTitle").scrollIntoView({block:"start",behavior:"instant"})');
  await screenshot("03-access-mobile");
  await check("mobile has no horizontal overflow", 'document.documentElement.scrollWidth <= innerWidth + 1');
  await change("moderator"); await screenshot("04-confirmation-mobile");
  await check("mobile dialog fits viewport", 'document.querySelector("#accessDialog").getBoundingClientRect().width < innerWidth');
  await key("Escape", "Escape", 27);
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await check("reduced motion removes long transitions", 'parseFloat(getComputedStyle(document.querySelector("#accessReview")).transitionDuration) < .01');
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  for (const code of ["version_conflict", "last_product_admin", "idempotency_conflict"]) {
    failure = { status: 409, code }; await load(); await change("moderator"); await confirm();
    await until('document.querySelector("#accessDetails").hidden');
    await check(`${code} clears stale editor and offers reload`, 'document.querySelector("#accessMessage").classList.contains("error") && !document.querySelector("#accessLoad").disabled');
  }
  failure = null; malformed = true;
  await evaluate(`document.querySelector('#accessUserId').value='${other}'`); await click("#accessLoad");
  await until('document.querySelector("#accessMessage").classList.contains("error")');
  await check("malformed audit cannot leave half-loaded target", 'document.querySelector("#accessDetails").hidden');
  malformed = false; expire = true; await load(); assert.equal(refreshes, 1); checks++;
  target.enabled = false; await load();
  await evaluate('document.querySelector("#accessRole").value="admin";document.querySelector("#accessRole").dispatchEvent(new Event("change"))');
  await check("disabled account cannot be changed", 'document.querySelector("#accessReview").disabled && document.querySelector("#accessCurrent").textContent.includes("отключён")');
  target.enabled = true; await load();
  failIdentity = true; await evaluate('window.dispatchEvent(new Event("focus"))');
  await until('document.querySelector("#accessDetails").hidden');
  await check("failed access recheck removes protected details", 'document.querySelector("#accessAudit").childElementCount === 0');
  failIdentity = false; await load();
  role = "user"; await evaluate('window.dispatchEvent(new Event("focus"))');
  await until('document.querySelector("#productAccessLink").hidden');
  await check("revocation clears data and navigation", 'document.querySelector("#productAccess").hidden && document.querySelector("#accessAudit").childElementCount === 0 && document.querySelector("#accessUserId").value === ""');
  await click("#logoutButton"); await until('!document.querySelector("#loginButton").disabled');
  role = "admin"; await login();
  await load(); role = "user"; await change("moderator"); await confirm();
  await until('!document.querySelector("#loginForm").hidden');
  await check("server 403 clears session and account data", 'document.querySelector("#accessTarget").textContent === "" && document.querySelector("#productAccessLink").hidden');
  role = "admin"; await login();
  hold = true;
  await evaluate(`document.querySelector('#accessUserId').value='${other}'`); await click("#accessLoad");
  for (let i = 0; i < 100 && !release; i++) await new Promise(resolve => setTimeout(resolve, 50));
  assert(release); await click("#logoutButton"); await release();
  await new Promise(resolve => setTimeout(resolve, 150));
  await check("late response cannot restore logged-out details", 'document.querySelector("#accessDetails").hidden && document.querySelector("#accessTarget").textContent === ""');
  role = "admin"; await login(); await load(actor); await change("user"); await confirm();
  await until('document.querySelector("#productAccessLink").hidden');
  await check("self-demotion immediately hides admin controls", 'document.querySelector("#productAccess").hidden && document.querySelector("#productIdentity").textContent.startsWith("Пользователь")');
  await check("credentials are never stored in browser storage", 'localStorage.length === 0 && sessionStorage.length === 0');
  assert.equal(errors.length, 0, JSON.stringify(errors)); checks++;
  console.log(`${checks} browser checks passed. Isolated fixtures; no database writes. Screenshots: ${output}`);
} finally {
  if (settingsSession && originalZoom !== undefined) await zoom(originalZoom);
  if (settingsTarget) await send("Target.closeTarget", { targetId: settingsTarget });
  await fetch(`${debug}/json/close/${tab.id}`);
  if (socket.readyState !== WebSocket.CLOSED) {
    await new Promise(resolve => {
      socket.addEventListener("close", resolve, { once: true });
      socket.close();
    });
  }
}
