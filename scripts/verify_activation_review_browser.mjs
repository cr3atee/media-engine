/** Real browser/API roundtrips restricted to explicitly seeded local test fixtures. */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.ACTIVATION_REVIEW_BROWSER_URL;
const debug = process.env.TERMINAL_CDP_URL ?? "http://127.0.0.1:9224";
const email = "activation-reviewer@example.test";
const password = process.env.ACTIVATION_REVIEW_TEST_PASSWORD;
const tenant = "00000000-0000-0000-0000-0000000061a9";
const externalId = "activation-fixture-2";
assert.equal(process.env.ACTIVATION_REVIEW_BROWSER_MUTATIONS, "TEST_FIXTURES_ONLY");
assert(password && base, "Provide explicit test credentials and isolated app URL");
for (const address of [base, debug]) {
  const url = new URL(address);
  assert.equal(url.protocol, "http:");
  assert(["localhost", "127.0.0.1"].includes(url.hostname));
  if (address === base) assert(!["", "80", "8000", "8001"].includes(url.port), "Never mutate the working catalog/review apps");
}
const path = `/api/v1/tenants/${tenant}/catalog/offers/funpay/${externalId}/activation-conditions`;
const login = await fetch(`${base}/api/v1/auth/login`, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }),
});
assert.equal(login.status, 200, "Isolated fixture identity must exist before browser verification");
const { access_token: token } = await login.json();
async function api(body) {
  const response = await fetch(base + path, {
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...(body ? { "Idempotency-Key": crypto.randomUUID() } : {}) },
    ...(body ? { method: "POST", body: JSON.stringify(body) } : {}),
  });
  assert.equal(response.status, 200, "Fixture API request failed");
  return response.json();
}
const initial = await api();
assert.equal(initial.tenant_id, tenant);
assert.equal(initial.external_id, externalId);
assert(initial.title.startsWith("Offline fixture subscription"), "Never mutate real marketplace offers");
assert.equal(initial.conditions, null, "Start with the PG verifier's unknown fixture profile");
const sourceFacts = value => ({ title: value.title, price: value.price, currency: value.currency, url: value.url, offer_id: value.offer_id, canonical_product_id: value.canonical_product_id });
const output = await mkdtemp(join(tmpdir(), "mediaengine-activation-review-"));
const tab = await (await fetch(`${debug}/json/new?about:blank`, { method: "PUT" })).json();
const socket = new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
let sequence = 0, checks = 0, loseNextResponse = false;
const pending = new Map(), errors = [], posts = [];
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const promise = pending.get(message.id);
    if (promise) {
      pending.delete(message.id); clearTimeout(promise.timer);
      if (message.error) promise.reject(new Error(JSON.stringify(message.error)));
      else promise.resolve(message.result);
    }
  }
  if (message.method === "Runtime.exceptionThrown") errors.push(message.params);
  if (message.method === "Network.requestWillBeSent") {
    const request = message.params.request;
    if (request.url === base + path && request.method === "POST") posts.push(request);
  }
  if (message.method === "Fetch.requestPaused") {
    const { requestId, request, responseStatusCode } = message.params;
    const lose = loseNextResponse && request.method === "POST" && responseStatusCode === 200;
    if (lose) loseNextResponse = false;
    void send(lose ? "Fetch.failRequest" : "Fetch.continueRequest", { requestId, ...(lose ? { errorReason: "ConnectionClosed" } : {}) }).catch(error => errors.push(String(error)));
  }
});
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function until(expression) {
  for (let i = 0; i < 120; i++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Browser condition timed out: ${expression}`);
}
function check(name, value) {
  assert(value, name); checks++; console.log(`PASS ${name}`);
}
async function click(selector) {
  const point = await evaluate(`(() => { const el=document.querySelector(${JSON.stringify(selector)}); el.scrollIntoView({block:'center',behavior:'instant'}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
}
async function key(key, code, windowsVirtualKeyCode, modifiers = 0) {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key, code, windowsVirtualKeyCode, modifiers });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key, code, windowsVirtualKeyCode, modifiers });
}
async function field(name, value) {
  await evaluate(`(() => { const el=document.querySelector('#activationForm [name="${name}"]'); el.value=${JSON.stringify(value)}; el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true})); })()`);
}
async function load() {
  await click("#activationLoad");
  await until('!document.querySelector("#activationDetails").hidden && document.querySelector("#activationReview").getAttribute("aria-busy")==="false"');
}
async function screenshot(name) {
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(output, name + ".png"), Buffer.from(capture.data, "base64"));
}
async function fill() {
  for (const [name, value] of Object.entries({
    scope: "countries", regions: "RU, KZ", device: "pc", plan_choice: "individual",
    period_unit: "M", period_amount: "1", delivery_method: "key", account_requirement: "any",
    vpn_required: "false", window_unit: "unlimited", reason: "Synthetic browser fixture facts only; not a real marketplace review.",
  })) await field(name, value);
}
try {
  for (const method of ["Page.enable", "Runtime.enable", "Network.enable", "Accessibility.enable"]) await send(method);
  await send("Network.clearBrowserCookies");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
  await send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1050, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: base + "/terminal/review" });
  await until('document.querySelector("#loginButton") && !document.querySelector("#loginButton").disabled');
  await until('document.documentElement.classList.contains("terminal-ready")');
  await evaluate(`(() => { document.querySelector('#emailInput').value=${JSON.stringify(email)}; document.querySelector('#passwordInput').value=${JSON.stringify(password)}; })()`);
  await click("#loginButton");
  await until('!document.querySelector("#activationReviewLink").hidden');
  check("reviewer receives tenant-scoped activation navigation", await evaluate(`document.querySelector('#tenantSelect').value===${JSON.stringify(tenant)}`));
  await click("#activationReviewLink");
  await evaluate(`document.querySelector('#activationMarketplace').value='funpay'; document.querySelector('#activationExternalId').value=${JSON.stringify(externalId)}`);
  await load();
  check("unknown facts have no permissive defaults", await evaluate('[...document.querySelectorAll("#activationForm select")].every(el=>el.value==="")'));
  await click("#activationSave");
  check("missing fields do not open confirmation or POST", posts.length === 0 && await evaluate('!document.querySelector("#activationDialog").open'));
  await fill();
  await field("plan_choice", "other"); await field("plan_code", "bad code!");
  await field("plan_choice", "individual");
  check("hidden custom-plan field is disabled, not blocking native validation", await evaluate('document.querySelector("[name=plan_code]").disabled && document.querySelector("#activationForm").checkValidity()'));
  await field("reason", "   "); await click("#activationSave");
  check("whitespace evidence is rejected without POST", posts.length === 0 && await evaluate('!document.querySelector("#activationDialog").open'));
  await field("reason", "Synthetic browser fixture facts only; not a real marketplace review.");
  await click("#activationSave");
  await until('document.querySelector("#activationDialog").open');
  check("confirmation identifies exact offer and explicit facts", await evaluate(`document.querySelector('#activationConfirmation').textContent.includes(${JSON.stringify(externalId)}) && document.querySelector('#activationConfirmation').textContent.includes('P1M')`));
  await evaluate('document.querySelector("#activationConfirm").focus()');
  await key("Tab", "Tab", 9);
  check("dialog traps forward keyboard focus", await evaluate('document.activeElement===document.querySelector("#activationDialog button[value=cancel]")'));
  await key("Tab", "Tab", 9, 8);
  check("dialog traps reverse keyboard focus", await evaluate('document.activeElement.id==="activationConfirm"'));
  await key("Escape", "Escape", 27);
  await until('!document.querySelector("#activationDialog").open');
  check("Escape preserves draft and sends no POST", posts.length === 0 && await evaluate('document.activeElement.id==="activationSave" && document.querySelector("[name=reason]").value.startsWith("Synthetic")'));
  await send("Fetch.enable", { patterns: [{ urlPattern: base + path, requestStage: "Response" }] });
  loseNextResponse = true;
  await click("#activationSave"); await click("#activationConfirm");
  await until('!document.querySelector("#activationRetry").hidden && !document.querySelector("#activationRetry").disabled');
  const committed = await api();
  check("lost response happens after real committed update", committed.conditions?.period === "P1M" && committed.version === initial.version + 1);
  check("ambiguous command locks editable fields", await evaluate('document.querySelector("[name=reason]").disabled && document.querySelector("#activationLoad").disabled'));
  await click("#activationRetry");
  await until('document.querySelector("#activationRetry").hidden && !document.querySelector("#activationSave").disabled');
  const replayed = await api();
  check("same-command retry does not create second revision", posts.length === 2 && replayed.version === committed.version);
  const idempotency = request => Object.entries(request.headers).find(([name]) => name.toLowerCase() === "idempotency-key")?.[1];
  check("retry reuses exact body and idempotency key", Boolean(idempotency(posts[0])) && idempotency(posts[0]) === idempotency(posts[1]) && posts[0].postData === posts[1].postData);
  await send("Fetch.disable");
  await field("reason", "Synthetic stale browser command.");
  await click("#activationSave");
  await api({ offer_id: replayed.offer_id, expected_version: replayed.version, expected_source_fingerprint: replayed.source_fingerprint, conditions: { ...replayed.conditions, regions: ["BR"] }, reason: "Concurrent synthetic fixture reviewer." });
  await click("#activationConfirm");
  await until('document.querySelector("#activationDetails").hidden && document.querySelector("#activationReview").getAttribute("aria-busy")==="false"');
  check("stale form requires reload instead of silent overwrite", await evaluate('document.querySelector("#activationMessage").classList.contains("error") && document.querySelector("#activationRetry").hidden'));
  await load();
  check("fresh reload displays actual concurrent revision", await evaluate('document.querySelector("[name=regions]").value==="BR"'));
  await fill();
  await evaluate('document.querySelector("#activationReview").scrollIntoView({behavior:"instant",block:"start"})');
  await evaluate("document.fonts.ready.then(()=>true)");
  check("desktop form has no horizontal overflow", await evaluate('document.documentElement.scrollWidth<=innerWidth'));
  await screenshot("desktop");
  const { nodes } = await send("Accessibility.getFullAXTree");
  check("form exposes named native controls to accessibility tree", nodes.filter(node => !node.ignored && ["combobox", "textbox", "spinbutton"].includes(node.role?.value) && node.name?.value).length >= 13);
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate('document.querySelector("#activationReview").scrollIntoView({behavior:"instant",block:"start"})');
  check("mobile form uses one column with no horizontal overflow", await evaluate('document.documentElement.scrollWidth<=innerWidth && getComputedStyle(document.querySelector("#activationForm")).gridTemplateColumns.split(" ").length===1'));
  await screenshot("mobile");
  await field("reason", "Explicit reset of synthetic test conditions.");
  await click("#activationClear");
  await until('document.querySelector("#activationDialog").open');
  check("mobile confirmation fits viewport", await evaluate('document.querySelector("#activationDialog").getBoundingClientRect().width<=innerWidth'));
  await screenshot("mobile-confirmation");
  await click("#activationConfirm");
  await until('document.querySelector("#activationRetry").hidden && !document.querySelector("#activationSave").disabled && document.querySelector("[name=scope]").value===""');
  const cleared = await api();
  check("explicit reset persists unknown without permissive defaults", cleared.conditions === null && cleared.version === initial.version + 3);
  check("source facts, price and canonical link remain unchanged", JSON.stringify(sourceFacts(initial)) === JSON.stringify(sourceFacts(cleared)));
  await evaluate('window.__activationReloadProbe = true');
  await send("Page.reload");
  await until('window.__activationReloadProbe !== true && document.querySelector("#activationReviewLink")?.hidden === false');
  check("session survives full reload", await evaluate('document.querySelector("#loginForm").hidden'));
  check("no uncaught JavaScript exceptions", errors.length === 0);
  console.log(`PASS ${checks} browser checks; synthetic fixture mutations only. Screenshots: ${output}`);
} catch (error) {
  console.error("Sanitized UI state:", await evaluate('({status:document.querySelector("#sessionStatus")?.textContent,message:document.querySelector("#loginMessage")?.textContent,activation:document.querySelector("#activationMessage")?.textContent})').catch(() => null));
  await screenshot("failure").catch(() => {});
  console.error("Screenshots:", output);
  throw error;
} finally {
  await send("Fetch.disable").catch(() => {});
  socket.close();
  await fetch(`${debug}/json/close/${tab.id}`).catch(() => {});
}
