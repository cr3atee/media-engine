/** Offline fixtures for the shared renderer; no marketplace or backend calls. */
import assert from "node:assert/strict";
import { offerFreshness, comparisonFreshness } from "../app/web/market_terminal/preview/presentation.js";

const observed = { price_observed_at: "2026-11-25T06:00:00Z", source_failed_at: null };
const failed = { ...observed, source_failed_at: "2026-11-25T06:05:00Z" };
let checks = 0;
function check(condition, name) { assert(condition, name); checks++; }

const unknownHtml = offerFreshness({});
check(unknownHtml.includes('data-refresh-state="unknown"'), "Missing evidence remains unknown");
check(unknownHtml.includes("Время проверки цены неизвестно"), "Unknown evidence is explained");
check(!unknownHtml.includes("<time"), "No invented timestamp");
const observedHtml = offerFreshness(observed);
check(observedHtml.includes('data-refresh-state="observed"'), "Observed is not a fresh/live promise");
check(observedHtml.includes('datetime="2026-11-25T06:00:00.000Z"'), "Original UTC instant remains machine-readable");
check(observedHtml.includes("Цена проверена"), "Quote observation is labelled");
check(!observedHtml.includes("offer-refresh-warning"), "Successful source has no failure warning");
const failedHtml = offerFreshness(failed);
check(failedHtml.includes('data-refresh-state="failed"'), "Newer source failure is explicit");
check(failedHtml.includes("Показана сохранённая цена"), "Retained quote is not claimed newly refreshed");
check(failedHtml.includes('datetime="2026-11-25T06:00:00.000Z"'), "Failure never replaces price observation time");
check(failedHtml.includes('datetime="2026-11-25T06:05:00.000Z"'), "Failure has its own time");
check(comparisonFreshness({ offers: [observed, failed] }).includes("Сравнение использует сохранённые цены"), "Comparison warns about partial refresh");
check(comparisonFreshness({ offers: [observed] }) === "", "No invented comparison failure");
check(comparisonFreshness({}) === "", "Legacy comparison payload remains valid");
for (const value of ["invalid", '<img src=x onerror="alert(1)">', "2026-11-25T06:00:00", null]) {
  const html = offerFreshness({ price_observed_at: value, source_failed_at: value });
  check(html.includes('data-refresh-state="unknown"'), "Malformed or naive dates stay unknown");
  check(!html.includes("<img"), "Untrusted evidence cannot inject HTML");
}
for (const value of ["2026-11-25T05:59:00Z", observed.price_observed_at]) {
  check(!offerFreshness({ ...observed, source_failed_at: value }).includes("offer-refresh-warning"), "Old failure does not mask a new observation");
}
check(offerFreshness({ source_failed_at: failed.source_failed_at }).includes('data-refresh-state="failed"'), "Failure without known observation is still explained");
console.log(`PASS ${checks} offline freshness presentation checks; synthetic fixtures only.`);
