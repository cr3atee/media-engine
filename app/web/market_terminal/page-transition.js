(() => {
  const root = document.documentElement;
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const startedAt = performance.now();
  let fallbackTimer;
  let overlay;

  root.classList.add("terminal-js", "terminal-loading");

  function mountOverlay() {
    if (overlay || !document.body) return;

    overlay = document.createElement("div");
    overlay.className = "terminal-transition";
    overlay.setAttribute("role", "status");
    overlay.setAttribute("aria-live", "polite");
    overlay.setAttribute("aria-label", "Загрузка страницы");

    const mark = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    mark.classList.add("terminal-transition-mark");
    mark.setAttribute("viewBox", "0 0 40 40");
    mark.setAttribute("aria-hidden", "true");

    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M5 31V9l15 12L35 9v22M5 10l15 12v13");
    mark.append(path);
    overlay.append(mark);
    document.body.prepend(overlay);
  }

  function finishLoading({ immediate = false } = {}) {
    clearTimeout(fallbackTimer);
    const minimumVisibleMs = reducedMotion.matches ? 0 : 260;
    const elapsed = performance.now() - startedAt;
    const delay = immediate ? 0 : Math.max(0, minimumVisibleMs - elapsed);

    window.setTimeout(() => {
      root.classList.remove("terminal-loading", "terminal-leaving");
      root.classList.add("terminal-ready");
      overlay?.setAttribute("aria-hidden", "true");
    }, delay);
  }

  function beginNavigation() {
    mountOverlay();
    overlay?.setAttribute("aria-hidden", "false");
    root.classList.remove("terminal-ready", "terminal-loading");
    root.classList.add("terminal-leaving");
    return reducedMotion.matches ? 0 : 140;
  }

  function terminalUrl(value) {
    const url = new URL(value || window.location.href, window.location.href);
    return url.origin === window.location.origin && url.pathname.startsWith("/terminal")
      ? url
      : null;
  }

  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    ) return;

    const anchor = event.target.closest("a[href]");
    if (!anchor || anchor.target || anchor.hasAttribute("download")) return;
    const rawHref = anchor.getAttribute("href") ?? "";
    const url = terminalUrl(rawHref);
    if (!url) return;
    const sameDocument =
      rawHref !== "" &&
      url.pathname === window.location.pathname &&
      url.search === window.location.search;
    if (sameDocument) return;

    event.preventDefault();
    const delay = beginNavigation();
    window.setTimeout(() => window.location.assign(url.href), delay);
  });

  document.addEventListener("submit", (event) => {
    if (event.defaultPrevented) return;
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "get") return;
    const url = terminalUrl(form.action);
    if (!url) return;

    event.preventDefault();
    const query = new URLSearchParams(new FormData(form));
    url.search = query.toString();
    const delay = beginNavigation();
    window.setTimeout(() => window.location.assign(url.href), delay);
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountOverlay, { once: true });
  } else {
    mountOverlay();
  }

  window.terminalPageReady = finishLoading;
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) finishLoading({ immediate: true });
  });
  window.addEventListener("load", () => {
    if (document.body?.dataset.transitionReady !== "app") finishLoading();
  }, { once: true });

  fallbackTimer = window.setTimeout(finishLoading, 5000);
})();
