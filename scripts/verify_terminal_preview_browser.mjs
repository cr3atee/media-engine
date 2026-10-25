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
let settingsTarget;
let settingsSession;
let originalZoom;
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
function send(method, params = {}, sessionId) {
  return new Promise((resolve, reject) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 20000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params, sessionId }));
  });
}
async function evaluate(expression, sessionId) {
  const response = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true }, sessionId);
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
  const passed = await evaluate(expression);
  if (!passed) console.error("Browser state:", await evaluate('({focusedTag:document.activeElement.tagName,focusedId:document.activeElement.id,modal:document.querySelector("dialog")?.matches(":modal"),width:innerWidth,ratio:devicePixelRatio})'));
  assert(passed, name);
  checks++;
  console.log(`PASS ${name}`);
}
async function screenshot(name, fromTop = true) {
  if (fromTop) await evaluate("window.scrollTo(0, 0)");
  await until('document.getAnimations().every(animation => animation.playState !== "running" || animation.effect?.getComputedTiming().iterations === Infinity)');
  const capture = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(output, `${name}.png`), Buffer.from(capture.data, "base64"));
}
async function size(width, height = 900) {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
}

async function press(key, code, windowsVirtualKeyCode, modifiers = 0) {
  const params = { key, code, windowsVirtualKeyCode, nativeVirtualKeyCode: windowsVirtualKeyCode, modifiers };
  const text = key === "Enter" ? "\r" : key.length === 1 && !modifiers ? key : undefined;
  await send("Input.dispatchKeyEvent", { type: "keyDown", ...params, text });
  await send("Input.dispatchKeyEvent", { type: "keyUp", ...params });
}

async function tabTo(selector) {
  for (let index = 0; index < 60; index++) {
    if (await evaluate(`document.activeElement.matches(${JSON.stringify(selector)})`)) return;
    await press("Tab", "Tab", 9);
  }
  throw new Error(`Keyboard cannot reach ${selector}`);
}

async function setBrowserZoom(factor) {
  if (!settingsSession) {
    ({ targetId: settingsTarget } = await send("Target.createTarget", { url: "chrome://settings/appearance" }));
    ({ sessionId: settingsSession } = await send("Target.attachToTarget", { targetId: settingsTarget, flatten: true }));
    for (let index = 0; index < 50; index++) {
      if (await evaluate('typeof chrome.settingsPrivate?.getDefaultZoom === "function"', settingsSession)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    originalZoom = await evaluate("new Promise(resolve => chrome.settingsPrivate.getDefaultZoom(resolve))", settingsSession);
  }
  await evaluate(`new Promise(resolve => chrome.settingsPrivate.setDefaultZoom(${factor}, resolve))`, settingsSession);
  await send("Page.bringToFront");
}

async function catalogReady() {
  await until('document.querySelector(".shell")?.getAttribute("aria-busy") === "false"');
  await evaluate("document.fonts.ready.then(() => true)");
}

async function workingCatalog(query = "") {
  await send("Page.navigate", { url: `${base}/terminal${query}` });
  await new Promise(resolve => setTimeout(resolve, 200));
  await catalogReady();
}

try {
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Log.enable");
  await send("Network.enable");
  await send("Network.setCacheDisabled", { cacheDisabled: true });
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

  await navigate();
  await press("Tab", "Tab", 9);
  await check("keyboard starts at visible skip link", 'document.activeElement.matches(".skip") && document.activeElement.getBoundingClientRect().top>=0');
  await press("Enter", "Enter", 13);
  await check("skip link moves focus to content", 'document.activeElement.id==="main"');
  await tabTo("#searchInput");
  await send("Input.insertText", { text: "Minecraft" });
  await press("Enter", "Enter", 13);
  await ready();
  await check("keyboard search announces new content through focus", 'document.activeElement.id==="main" && document.querySelector("#catalogTitle").textContent.includes("Minecraft")');
  await tabTo(".product-card");
  await check("keyboard product link has visible focus", 'document.activeElement.matches(":focus-visible") && parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2');
  await screenshot("09-keyboard-card-focus", false);
  await press("Enter", "Enter", 13);
  await ready();
  await check("keyboard opens product with content focus", 'document.activeElement.id==="main" && !!document.querySelector("#productTitle")');
  await tabTo(".back");
  await press("Enter", "Enter", 13);
  await ready();
  await check("keyboard return preserves search", 'document.querySelector("#catalogTitle").textContent.includes("Minecraft")');
  await tabTo("#profileButton");
  await press("Enter", "Enter", 13);
  await check("dialog has an accessible name and initial focus", 'document.querySelector("dialog").open && document.activeElement.id==="closeDialog" && document.getElementById(document.querySelector("dialog").getAttribute("aria-labelledby")).textContent.length>0');
  await press("Tab", "Tab", 9, 8);
  await check("dialog reverse tab stays inside", 'document.activeElement.closest("dialog")!==null');
  await press("Tab", "Tab", 9);
  await check("dialog forward tab stays inside", 'document.activeElement.closest("dialog")!==null');
  await press("Escape", "Escape", 27);
  await check("escape restores focus to dialog opener", '!document.querySelector("dialog").open && document.activeElement.id==="profileButton"');
  await press("Enter", "Enter", 13);
  await tabTo('.screen-links a[href$="screen=review"]');
  await press("Enter", "Enter", 13);
  await ready();
  await tabTo("#facts");
  await send("Input.insertText", { text: "   " });
  await tabTo('#decisionForm button[type="submit"]');
  await press("Enter", "Enter", 13);
  await check("invalid keyboard submission focuses explained error", 'document.activeElement.id==="facts" && document.activeElement.getAttribute("aria-invalid")==="true" && document.activeElement.getAttribute("aria-describedby").includes("factsError") && !document.querySelector("#factsError").hidden');
  await send("Input.insertText", { text: "PC, Java & Bedrock" });
  await press("/", "Slash", 191);
  await check("search shortcut does not steal textarea focus", 'document.activeElement.id==="facts"');
  await tabTo('#decisionForm button[type="submit"]');
  await press("Enter", "Enter", 13);
  await check("keyboard confirmation identifies target", 'document.querySelector("dialog").open && document.querySelector("#dialogBody").textContent.includes(document.querySelector(".target code").textContent)');
  await press("Escape", "Escape", 27);
  await check("dismiss returns to decision without losing facts", 'document.activeElement.matches("#decisionForm button[type=submit]") && document.querySelector("#facts").value.includes("Bedrock")');

  // Set native zoom only in the dedicated test profile, not CSS zoom or pinch scale.
  await send("Emulation.clearDeviceMetricsOverride");
  const { windowId } = await send("Browser.getWindowForTarget");
  await send("Browser.setWindowBounds", { windowId, bounds: { width: 1440, height: 1000 } });
  await setBrowserZoom(1);
  await navigate();
  const baseline = await evaluate('({width:innerWidth,ratio:devicePixelRatio})');
  await setBrowserZoom(2);
  await navigate();
  await check("native browser zoom is actually 200 percent", `Math.abs(devicePixelRatio/${baseline.ratio}-2)<0.05 && Math.abs(innerWidth/${baseline.width}-.5)<0.02`);
  await check("200-percent catalog reflows without overflow", 'document.documentElement.scrollWidth<=innerWidth && document.querySelectorAll(".product-card").length>0');
  await check("200-percent compact cards keep logos and count together", '[...document.querySelectorAll(".compact .offer-footprint")].every(row=>Math.abs(row.querySelector(".marketplace-logos").getBoundingClientRect().top-row.querySelector(".offer-count").getBoundingClientRect().top)<8)');
  await screenshot("10-native-zoom-catalog");
  await evaluate('document.querySelector("#catalogTitle").scrollIntoView({block:"start"})');
  await screenshot("10b-native-zoom-cards", false);
  await tabTo(".product-card");
  await press("Enter", "Enter", 13);
  await ready();
  await check("200-percent product preserves prices and source actions", 'document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll(".offer-row")].every(row=>row.querySelector(".offer-price").getBoundingClientRect().width>0 && row.querySelector("a").getBoundingClientRect().right<=innerWidth)');
  await screenshot("11-native-zoom-product");
  await evaluate('document.querySelector(".offer-row").scrollIntoView({block:"start"})');
  await screenshot("11b-native-zoom-prices", false);
  await navigate("?screen=review");
  await check("200-percent review preserves form and action", 'document.documentElement.scrollWidth<=innerWidth && document.querySelector("#facts").getBoundingClientRect().right<=innerWidth && document.querySelector("#decisionForm button[type=submit]").getBoundingClientRect().right<=innerWidth');
  await screenshot("12-native-zoom-review");
  await evaluate('document.querySelector("#facts").scrollIntoView({block:"center"})');
  await screenshot("12b-native-zoom-form", false);
  await tabTo("#profileButton");
  await press("Enter", "Enter", 13);
  await check("200-percent dialog fits viewport and scrolls vertically", '(() => {const el=document.querySelector("dialog");const r=el.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight+1 && el.scrollWidth<=el.clientWidth;})()');
  await screenshot("13-native-zoom-dialog");
  await press("Escape", "Escape", 27);
  await setBrowserZoom(originalZoom);
  await size(1440);
  await workingCatalog();
  await check("working catalog uses real products without preview tools", 'document.querySelectorAll(".product-card").length===2 && !document.querySelector("#previewTools") && !document.querySelector("#profileButton") && document.querySelector("#details").hidden');
  await check("working catalog has local official artwork", '[...document.querySelectorAll(".product-art")].every(img=>img.complete && img.naturalWidth>0 && img.src.startsWith(location.origin))');
  await check("working catalog starts above fold", 'document.querySelector(".product-card").getBoundingClientRect().top<innerHeight-120');
  await screenshot("14-working-catalog");
  await click("#filtersButton");
  await check("working filters expose previous sort and price controls", '!document.querySelector("#catalogFilters").hidden && document.querySelectorAll("#sortFilter option").length===4');
  await evaluate('document.querySelector("#minPriceInput").value="100";document.querySelector("#maxPriceInput").value="10"');
  await click('#catalogFilters button[type="submit"]');
  await check("working price range rejects inverted bounds", '!document.querySelector("#maxPriceInput").checkValidity() && document.activeElement.id==="maxPriceInput"');
  await evaluate('document.querySelector("#minPriceInput").value="";document.querySelector("#maxPriceInput").value="";document.querySelector("#maxPriceInput").dispatchEvent(new Event("input"));document.querySelector("#searchInput").value="Minecraft";document.querySelector("#sortFilter").value="name:asc";document.querySelector("#searchForm").requestSubmit()');
  await catalogReady();
  await check("working search and sort survive in URL", 'new URLSearchParams(location.search).get("q")==="Minecraft" && new URLSearchParams(location.search).get("sort")==="name" && document.querySelectorAll(".product-card").length===2');
  await click('[data-marketplace="playerok"]');
  await catalogReady();
  await check("working marketplace filter preserves query and sort", 'new URLSearchParams(location.search).get("marketplace")==="playerok" && document.querySelector("#sortFilter").value==="name:asc" && document.querySelector("#searchInput").value==="Minecraft"');
  await screenshot("15-working-filters");
  const catalogQuery = await evaluate("location.search");
  await click(".product-card");
  await until('document.querySelector("#details").getAttribute("aria-busy")==="false"');
  await check("working product is a distinct view with source rows", 'document.querySelector("#catalogView").hidden && !document.querySelector("#details").hidden && document.querySelectorAll(".offer-row").length>0');
  await check("working detail shows original name and truthful currency status", 'document.querySelector("#originalName").textContent.length>0 && document.querySelector("#comparisonCard").textContent.includes("разных валютах")');
  await check("working history section remains available", 'document.querySelector("#historyCard").textContent.trim().length>0');
  await check("working source links are safe", '[...document.querySelectorAll(".offer-row a")].every(a=>a.protocol==="https:" && a.rel.includes("noopener") && a.rel.includes("noreferrer"))');
  await screenshot("16-working-product");
  await click("#backToCatalog");
  await until(`location.search===${JSON.stringify(catalogQuery)} && !document.querySelector("#catalogView").hidden`);
  await catalogReady();
  await check("working back restores filters and page title", 'document.querySelector("#marketplaceFilter").value==="playerok" && document.querySelector("#sortFilter").value==="name:asc" && document.title.startsWith("Каталог")');
  if (await evaluate('!!document.querySelector(\'.category-filter[data-category-index="0"]\')')) {
    await click('.category-filter[data-category-index="0"]');
    await catalogReady();
    await check("working category uses existing API state", 'new URLSearchParams(location.search).has("category")');
  } else {
    await check("missing real categories have an explicit empty state", 'document.querySelector("#categoryList").textContent.includes("пока недоступны")');
  }
  await workingCatalog("?q=not-a-real-product-xyz");
  await check("working empty search never shows stale product", '!document.querySelector(".product-card") && document.querySelector("#details").hidden');
  await workingCatalog("?category=not-a-real-category-xyz");
  await check("category deep link sends filter and returns honest empty result", '!document.querySelector(".product-card") && performance.getEntriesByType("resource").some(entry=>entry.name.includes("/api/v1/public/products?") && new URL(entry.name).searchParams.get("category")==="not-a-real-category-xyz")');
  await workingCatalog("?product=7c862a70-5619-5b6d-a2aa-798560d29f18");
  await check("working product deep link loads", '!document.querySelector("#details").hidden && document.querySelector("#detailTitle").textContent==="Minecraft"');
  await click("#backToCatalog");
  await catalogReady();
  await check("direct product can return without browser history", '!document.querySelector("#catalogView").hidden && !new URLSearchParams(location.search).has("product")');
  await size(390, 844);
  await workingCatalog();
  await check("working mobile catalog fits", 'document.documentElement.scrollWidth<=innerWidth');
  await screenshot("17-working-mobile");
  await click("#filtersButton");
  await check("working mobile filters fit", 'document.documentElement.scrollWidth<=innerWidth && document.querySelector("#maxPriceInput").getBoundingClientRect().right<=innerWidth');
  await click(".product-card");
  await until('document.querySelector("#details").getAttribute("aria-busy")==="false"');
  await check("working mobile product fits", 'document.documentElement.scrollWidth<=innerWidth');
  await screenshot("18-working-mobile-product");
  await size(320, 844);
  await check("working narrow product fits", 'document.documentElement.scrollWidth<=innerWidth');
  await size(1440);
  await workingCatalog();
  await send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await click("#refreshButton");
  await catalogReady();
  await check("working offline state retains explained retry", 'document.querySelector("#apiStatus").classList.contains("error") && !document.querySelector("#refreshButton").disabled && document.querySelector("#productGrid").textContent.includes("Проверьте соединение")');
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await click("#refreshButton");
  await catalogReady();
  await check("working retry restores real catalog", 'document.querySelectorAll(".product-card").length===2');
  await check("working cabinet link retains authenticated workspace", 'document.querySelector(".header .profile").getAttribute("href")==="/terminal/review"');
  await workingCatalog();
  await press("Tab", "Tab", 9);
  await press("Enter", "Enter", 13);
  await check("working keyboard skip reaches content", 'document.activeElement.id==="main"');
  await tabTo(".product-card");
  await check("working keyboard card focus is visible", 'document.activeElement.matches(":focus-visible") && parseFloat(getComputedStyle(document.activeElement).outlineWidth)>=2');
  await press("Enter", "Enter", 13);
  await until('document.querySelector("#details").getAttribute("aria-busy")==="false"');
  await check("working keyboard product focuses new view", 'document.activeElement.id==="main" && !document.querySelector("#details").hidden');
  await send("Emulation.clearDeviceMetricsOverride");
  await setBrowserZoom(2);
  await workingCatalog();
  await check("working catalog supports native 200-percent zoom", 'devicePixelRatio>=2 && document.documentElement.scrollWidth<=innerWidth');
  await screenshot("19-working-zoom");
  await click(".product-card");
  await until('document.querySelector("#details").getAttribute("aria-busy")==="false"');
  await check("working zoom preserves prices and actions", 'document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll(".offer-row a")].every(a=>a.getBoundingClientRect().right<=innerWidth)');
  await evaluate('document.querySelector(".offer-row").scrollIntoView({block:"start"})');
  await screenshot("20-working-zoom-prices", false);
  await setBrowserZoom(originalZoom);
  assert.deepEqual(errors, [], "No runtime or CSP errors");
  checks++;
  assert(requests.filter(request=>request.url.startsWith(base)).every(request=>request.method==="GET"), "Preview must not mutate backend");
  checks++;
  console.log(`PASS ${checks} browser checks; no runtime/CSP errors; all application requests GET`);
  console.log(`Screenshots: ${output}`);
} finally {
  if (settingsSession && originalZoom !== undefined) await setBrowserZoom(originalZoom).catch(error=>console.error("Could not restore test-profile zoom:", error.message));
  if (settingsTarget) await send("Target.closeTarget", { targetId: settingsTarget }).catch(()=>{});
  await send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 }).catch(()=>{});
  socket.close();
  await fetch(`${debug}/json/close/${target.id}`).catch(()=>{});
}
