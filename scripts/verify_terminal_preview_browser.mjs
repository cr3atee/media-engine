/** Read-only browser checks using Node 22+ and a separate Chromium debugging port. */
import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const base = process.env.TERMINAL_PREVIEW_URL ?? "http://127.0.0.1:8002";
const debug = process.env.TERMINAL_CDP_URL ?? "http://127.0.0.1:9224";
for (const address of [base, debug]) {
  const url = new URL(address);
  assert(["127.0.0.1", "localhost"].includes(url.hostname), "Use loopback test instances only");
}
const output = await mkdtemp(join(tmpdir(), "mediaengine-ui-preview-"));
const target = await (await fetch(`${debug}/json/new?about:blank`, { method: "PUT" })).json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.addEventListener("open", resolve, { once: true }); socket.addEventListener("error", reject, { once: true }); });
let sequence = 0;
let checks = 0;
const pending = new Map();
const errors = [];
const requests = [];
socket.addEventListener("message", event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const promise = pending.get(message.id);
    if (!promise) return;
    pending.delete(message.id);
    clearTimeout(promise.timer);
    if (message.error) promise.reject(new Error(JSON.stringify(message.error)));
    else promise.resolve(message.result);
  }
  if (message.method === "Runtime.exceptionThrown") errors.push(message.params);
  if (message.method === "Log.entryAdded" && message.params.entry.source === "security") errors.push(message.params);
  if (message.method === "Network.requestWillBeSent") requests.push(message.params.request);
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
  const response = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  assert(!response.exceptionDetails, JSON.stringify(response.exceptionDetails));
  return response.result.value;
}
async function until(expression) {
  for (let index = 0; index < 100; index++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Browser condition timed out: ${expression}`);
}
async function ready() {
  await until('document.querySelector("main")?.getAttribute("aria-busy") === "false"');
  await evaluate("document.fonts.ready.then(() => true)");
  await new Promise(resolve => setTimeout(resolve, 250));
}
async function navigate(query = "") {
  await send("Page.navigate", { url: `${base}/terminal/preview${query}` });
  await new Promise(resolve => setTimeout(resolve, 200));
  await ready();
}
async function click(selector) {
  const point = await evaluate(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); el.scrollIntoView({block:"center"}); const r = el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; })()`);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", button: "left", clickCount: 1, ...point });
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", button: "left", clickCount: 1, ...point });
}
async function check(name, expression) {
  assert(await evaluate(expression), name);
  checks++;
  console.log(`PASS ${name}`);
}
async function screenshot(name, fromTop = true) {
  if (fromTop) await evaluate("window.scrollTo(0, 0)");
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(output, `${name}.png`), Buffer.from(capture.data, "base64"));
}
async function size(width, height = 900) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
}

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");
  await size(1440);
  await navigate();
  await check("real public catalog loaded", 'document.querySelectorAll(".product-card").length > 0');
  await check("local font loaded", 'document.fonts.check("16px Onest")');
  await check("first products above the fold", 'document.querySelector(".product-card").getBoundingClientRect().top < 900');
  await check("square artwork", '[...document.querySelectorAll(".card-image")].every(el=>Math.abs(el.offsetWidth-el.offsetHeight)<2)');
  await check("desktop has no horizontal overflow", 'document.documentElement.scrollWidth <= innerWidth');
  await check("images loaded", '[...document.images].every(el=>el.complete && el.naturalWidth>0)');
  await check("official artwork is square and edition specific", `(() => { const expected = {'7c862a70-5619-5b6d-a2aa-798560d29f18':'minecraft-pc.jpg','9a520758-e499-5837-90bb-9e6b67d7a591':'minecraft-ios.jpg'}; return [...document.querySelectorAll('.product-card')].every(card=>{const img=card.querySelector('.product-art');const id=new URL(card.href).searchParams.get('product');return new URL(img.src).origin===location.origin && img.src.endsWith(expected[id]??'product-placeholder.svg') && img.naturalWidth===img.naturalHeight && getComputedStyle(img).objectFit==='contain' && img.alt.length>0;});})()`);
  await check("service captions removed", '!["Цена и условия покупки уточняются", "Данные подключённого каталога", "Оригинальные предложения.", "Без выдуманных скидок."].some(text=>document.querySelector("main").textContent.includes(text))');
  await check("offer counts are compact numbers with accessible labels", '[...document.querySelectorAll(".product-card .offer-count")].every(el=>/^\\d+$/.test(el.innerText.trim()) && el.getAttribute("aria-label").includes("предложени"))');
  await check("card logos come from real product memberships", `(async()=>{const response=await fetch('/api/v1/public/products?limit=50');const data=await response.json();const names={ggsel:'GGSEL',playerok:'Playerok',funpay:'FunPay'};return [...document.querySelectorAll('.product-card')].every(card=>{const product=data.items.find(p=>p.id===new URL(card.href).searchParams.get('product'));const actual=[...card.querySelectorAll('.marketplace-logos .market-mark')].map(el=>el.getAttribute('aria-label'));return product.marketplaces.length>0 && JSON.stringify(actual)===JSON.stringify(product.marketplaces.map(code=>names[code]??code)) && card.querySelector('.offer-count').innerText.trim()===String(product.offer_count);});})()`);
  await screenshot("01-catalog-desktop");
  await evaluate('document.querySelector(".product-card .market-logo").dispatchEvent(new Event("error"))');
  await check("failed logo preserves marketplace name", '(() => { const el = document.querySelector(".product-card .image-unavailable"); return !!el && el.querySelector("img").hidden && el.innerText.trim() === el.getAttribute("aria-label"); })()');
  await click(".product-card");
  await ready();
  await check("product opens in a distinct page", '!!document.querySelector("#productTitle") && !document.querySelector(".hero")');
  await check("marketplace offers visible", 'document.querySelectorAll(".offer-row").length > 0');
  await check("source links safe", '[...document.querySelectorAll(".offer-row a")].every(a=>a.protocol==="https:" && a.rel.includes("noopener"))');
  await check("mixed currencies not presented as a lowest price", '!document.querySelector(".notice")?.textContent.includes("Цены в разных валютах") || !document.querySelector(".notice")?.textContent.includes("Лучшее предложение:")');
  await screenshot("02-product-desktop");
  await evaluate('document.querySelector(".product-cover").src="/terminal/preview/missing-artwork.jpg"');
  await until('document.querySelector(".product-cover").src.endsWith("product-placeholder.svg") && document.querySelector(".product-cover").complete');
  await check("failed artwork uses neutral local fallback", 'document.querySelector(".product-cover").naturalWidth>0 && document.querySelector(".product-cover").alt==="Изображение товара недоступно"');
  await evaluate('document.querySelector(".product-cover").dispatchEvent(new Event("error"))');
  await check("fallback failure keeps layout without a retry loop", 'document.querySelector(".product-cover").classList.contains("art-unavailable") && document.querySelector(".product-cover").src.endsWith("product-placeholder.svg") && document.querySelector(".product-cover").offsetWidth===220');
  await evaluate("history.back()");
  await ready();
  await check("browser back restores catalog", '!!document.querySelector("#catalog")');
  await navigate("?q=Minecraft&marketplace=ggsel");
  await click(".product-card");
  await ready();
  await click(".back");
  await ready();
  await check("back link preserves search and marketplace", 'new URLSearchParams(location.search).get("q")==="Minecraft" && document.querySelector("[aria-current=page]").textContent.includes("GGSEL")');
  await navigate("?q=there-is-no-such-product-92");
  await check("real empty search", '!!document.querySelector(".empty") && !document.querySelector(".product-card")');
  await navigate("?screen=review");
  await check("review identifies exact target", 'document.querySelector(".target code").textContent.length===36');
  await check("link requires facts", 'document.querySelector("#facts").required');
  await click('input[value="create"]');
  await check("new product facts optional", '!document.querySelector("#facts").required');
  await click('input[value="link"]');
  await evaluate('document.querySelector("#facts").value="   "; document.querySelector("#decisionForm").requestSubmit()');
  await check("whitespace cannot confirm link", '!document.querySelector("#factsError").hidden && !document.querySelector("dialog").open');
  await evaluate('document.querySelector("#facts").value="PC, Java & Bedrock, цифровой ключ"');
  await screenshot("03-review-desktop");
  await click('#decisionForm button[type="submit"]');
  await check("confirmation repeats exact target ID", 'document.querySelector("dialog").open && document.querySelector("#dialogBody").textContent.includes(document.querySelector(".target code").textContent)');
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
  await until('!document.querySelector("dialog").open');
  await check("dismiss preserves facts", '!document.querySelector("dialog").open && document.querySelector("#facts").value.includes("Bedrock")');
  await click("#profileButton");
  await check("four explicit preview roles", 'document.querySelectorAll("#previewRole option").length===4');
  await evaluate('document.querySelector("#previewRole").value="admin";document.querySelector("#previewRole").dispatchEvent(new Event("change",{bubbles:true}))');
  await check("role switch has preview disclaimer", 'document.querySelector("#dialogBody").textContent.includes("не меняет реальные права") && document.querySelector("#roleLabel").textContent==="Админ"');
  await click("#closeDialog");
  await size(390, 844);
  await navigate();
  await check("mobile catalog fits", 'document.documentElement.scrollWidth<=innerWidth');
  await check("mobile marketplace strip stays inside each card", '[...document.querySelectorAll(".product-card")].every(card=>card.querySelector(".offer-footprint").getBoundingClientRect().right<=card.getBoundingClientRect().right+1)');
  await check("platform badges leave the artwork title visible", '[...document.querySelectorAll(".card-image .art-label")].every(el=>el.getBoundingClientRect().top>el.parentElement.getBoundingClientRect().top+el.parentElement.offsetHeight/2 && el.offsetHeight<32)');
  await screenshot("04-catalog-mobile");
  await evaluate('document.querySelector("#catalog").scrollIntoView({block:"start"})');
  await screenshot("04b-catalog-mobile-offers", false);
  await size(320, 740);
  await check("small mobile offer rows fit", 'document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll(".product-card .offer-count")].every(el=>el.getBoundingClientRect().right<=el.closest(".product-card").getBoundingClientRect().right+1)');
  await size(390, 844);
  await click(".product-card");
  await ready();
  await check("mobile product fits", 'document.documentElement.scrollWidth<=innerWidth');
  await check("mobile product cover stays square", 'Math.abs(document.querySelector(".product-cover").offsetWidth-document.querySelector(".product-cover").offsetHeight)<2');
  await screenshot("05-product-mobile");
  await navigate("?screen=review");
  await check("mobile review fits", 'document.documentElement.scrollWidth<=innerWidth');
  await check("mobile queue is a compact native selector", 'document.querySelector("#reviewSelect").offsetWidth>0 && getComputedStyle(document.querySelector(".queue button")).display==="none"');
  await screenshot("06-review-mobile");
  await size(320, 740);
  await check("small mobile review fits", 'document.documentElement.scrollWidth<=innerWidth');
  await size(720, 450);
  await navigate();
  await check("200-percent equivalent layout fits", 'document.documentElement.scrollWidth<=innerWidth');
  await size(1440);
  const missing = await fetch(`${base}/terminal/preview/not-found`);
  assert.equal(missing.status, 404);
  checks++;
  console.log("PASS actual HTML 404 HTTP status");
  await navigate("/not-found");
  await check("404 has recovery action", 'document.querySelector(".error-number").textContent==="404" && !!document.querySelector(".error-state a")');
  await screenshot("07-not-found-desktop");
  await navigate("?screen=error");
  await check("error demo does not claim logging", 'document.querySelector("main").textContent.includes("Отчёт об ошибке не отправлен")');
  await screenshot("08-error-desktop");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  await navigate();
  await click("#profileButton");
  await check("reduced motion disables animations", 'document.getAnimations().length===0');
  await click("#closeDialog");
  await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "no-preference" }] });
  await send("Emulation.setCPUThrottlingRate", { rate: 4 });
  await navigate("?screen=density");
  await check("50-card density only in labelled test mode", 'document.querySelectorAll(".product-card").length===50 && document.querySelector(".notice").textContent.includes("только в браузере")');
  await check("dense page fits", 'document.documentElement.scrollWidth<=innerWidth');
  await evaluate(`document.querySelectorAll('.market-nav a')[1].click();document.querySelector('#searchInput').value='Minecraft';document.querySelector('#searchForm').requestSubmit()`);
  await ready();
  await check("rapid navigation retains latest intent", 'document.querySelector("#catalogTitle").textContent.includes("Minecraft") && !location.search.includes("marketplace")');
  await send("Emulation.setCPUThrottlingRate", { rate: 1 });
  await send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0 });
  await evaluate('document.querySelector("#searchForm").requestSubmit()');
  await ready();
  await check("actual network failure has retry", '!!document.querySelector("[data-action=retry]") && document.querySelector("main").textContent.includes("Не удалось подключиться")');
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await click('[data-action="retry"]');
  await ready();
  await check("retry recovers catalog", 'document.querySelectorAll(".product-card").length>0');
  await check("product imagery never hotlinks external hosts", '[...document.querySelectorAll(".product-art")].every(img=>new URL(img.currentSrc||img.src).origin===location.origin)');
  assert.deepEqual(errors, [], "No runtime or CSP errors");
  checks++;
  assert(requests.filter(request=>request.url.startsWith(base)).every(request=>request.method==="GET"), "Preview must not mutate backend");
  checks++;
  console.log(`PASS ${checks} browser checks; no runtime/CSP errors; all application requests GET`);
  console.log(`Screenshots: ${output}`);
} finally {
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 }).catch(()=>{});
  socket.close();
  await fetch(`${debug}/json/close/${target.id}`).catch(()=>{});
}
