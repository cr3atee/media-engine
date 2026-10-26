/** Real browser cookies + real auth endpoints over isolated memory repositories. */
import assert from "node:assert/strict";
import { spawn } from "node:child_process";

const base = "http://127.0.0.1:8004";
const debug = process.env.TERMINAL_CDP_URL ?? "http://127.0.0.1:9224";
assert(["127.0.0.1", "localhost"].includes(new URL(debug).hostname));
const code = `import uvicorn
from app.repositories.provider import create_memory_provider
from tests.api.test_seller_auth_api import _client, _seed_identity
from tests.repositories.contracts.factories import run_async
p=create_memory_provider()
run_async(_seed_identity(p))
app=_client(p).app
app.state.public_read_repository_scope_factory=None
uvicorn.run(app,host='127.0.0.1',port=8004,log_level='error')`;
const server = spawn(".venv/Scripts/python.exe", ["-c", code], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
let serverError = "";
server.stderr.on("data", data => { serverError += data.toString(); });
let tab;
let socket;
let sequence = 0;
let checks = 0;
const pending = new Map();
const errors = [];
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => reject(new Error(`Timeout: ${method}`)), 15000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  assert(!result.exceptionDetails, JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function until(expression) {
  for (let i = 0; i < 120; i++) {
    try { if (await evaluate(expression)) return; } catch { /* navigation replaces the context */ }
    await new Promise(resolve => setTimeout(resolve, 80));
  }
  throw new Error(`Browser condition failed: ${expression}`);
}
async function check(name, expression) { assert(await evaluate(expression), name); checks++; console.log(`PASS ${name}`); }
async function ready() { await until('document.querySelector("#sessionPanel") && !document.querySelector("#sessionPanel").hidden'); }
async function login() {
  await until('document.querySelector("#loginButton") && !document.querySelector("#loginButton").disabled');
  await evaluate(`document.querySelector('#emailInput').value='seller@example.com';document.querySelector('#passwordInput').value='correct horse battery staple';document.querySelector('#loginForm').requestSubmit()`);
  try {
    await ready();
  } catch (error) {
    const state = await evaluate(`({
      message: document.querySelector('#loginMessage')?.textContent,
      status: document.querySelector('#sessionStatus')?.textContent,
      loginHidden: document.querySelector('#loginForm')?.hidden,
      script: document.querySelector('script[src="/terminal/review.js"]')?.src,
    })`);
    throw new Error(`${error.message}; UI=${JSON.stringify(state)}; server=${serverError}`);
  }
}
try {
  let started = false;
  for (let i = 0; i < 100; i++) {
    if (server.exitCode !== null) throw new Error(`Isolated server failed: ${serverError}`);
    try { started = (await fetch(`${base}/terminal/review`)).ok; } catch { /* startup */ }
    if (started) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert(started);
  tab = await (await fetch(`${debug}/json/new?about:blank`, { method: "PUT" })).json();
  socket = new WebSocket(tab.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const item = pending.get(message.id);
    if (item) { clearTimeout(item.timer); pending.delete(message.id); message.error ? item.reject(new Error(JSON.stringify(message.error))) : item.resolve(message.result); }
    if (message.method === "Runtime.exceptionThrown") errors.push(message.params);
  });
  await send("Runtime.enable"); await send("Page.enable"); await send("Network.enable");
  await send("Page.navigate", { url: `${base}/terminal/review` });
  await login();
  const cookies = await send("Network.getCookies", { urls: [`${base}/api/v1/auth/browser/refresh`] });
  const cookie = cookies.cookies.find(item => item.name === "mt_refresh_local");
  assert(cookie?.httpOnly && cookie.sameSite === "Strict" && cookie.path === "/api/v1/auth/browser"); checks++;
  await check("refresh credential is invisible to page JavaScript", '!document.cookie.includes("mt_refresh") && localStorage.length === 0 && sessionStorage.length === 0');
  await evaluate(`document.querySelector('.cabinet-nav a[href="/terminal"]').click()`);
  await until('location.pathname === "/terminal" && document.querySelector("a.profile")');
  await evaluate('document.querySelector("a.profile").click()');
  await ready();
  await check("catalog to cabinet keeps signed-in identity", 'document.querySelector("#sellerEmail").textContent === "seller@example.com" && document.querySelector("#loginForm").hidden');
  await send("Page.reload"); await ready();
  await check("page reload restores login", 'document.querySelector("#sellerEmail").textContent === "seller@example.com"');
  const rotated = await send("Network.getCookies", { urls: [`${base}/api/v1/auth/browser/refresh`] });
  assert.notEqual(rotated.cookies.find(item => item.name === "mt_refresh_local").value, cookie.value); checks++;
  await until('!document.querySelector("#logoutButton").disabled');
  await evaluate('document.querySelector("#logoutButton").click()');
  await until('!document.querySelector("#loginForm").hidden && !document.querySelector("#loginButton").disabled');
  await send("Page.reload");
  await until('document.querySelector("#loginButton") && !document.querySelector("#loginButton").disabled');
  await check("logout survives reload and revokes restoration", 'document.querySelector("#sessionPanel").hidden && !document.querySelector("#loginForm").hidden');
  await login();
  await evaluate(`document.querySelector('.cabinet-nav a[href="/terminal"]').click()`);
  await until('location.pathname === "/terminal"');
  await evaluate('history.back()'); await ready();
  await check("browser Back restores identity safely", 'document.querySelector("#sellerEmail").textContent === "seller@example.com"');
  await until('!document.querySelector("#logoutButton").disabled');
  await evaluate('document.querySelector("#logoutButton").click()');
  await until('!document.querySelector("#loginButton").disabled');
  assert.equal(errors.length, 0, JSON.stringify(errors)); checks++;
  console.log(`${checks} real-cookie browser checks passed; isolated memory backend only.`);
} finally {
  if (tab) await fetch(`${debug}/json/close/${tab.id}`);
  if (socket && socket.readyState !== WebSocket.CLOSED) await new Promise(resolve => { socket.addEventListener("close", resolve, { once: true }); socket.close(); });
  server.kill();
}
