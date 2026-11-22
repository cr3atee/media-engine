/** Offline unit fixtures for the real form converter; no marketplace/network calls. */
import assert from "node:assert/strict";
import { readActivationConditions } from "../app/web/market_terminal/offer-activation.js";

const values = {
  scope: "countries", regions: "ru, KZ, RU", excluded_regions: "", device: "pc",
  plan_choice: "individual", period_unit: "M", period_amount: "1",
  delivery_method: "key", account_requirement: "any", vpn_required: "false",
  window_unit: "unlimited", window_amount: "",
};
const profile = readActivationConditions(values);
assert.deepEqual(profile.regions, ["KZ", "RU"]);
assert.deepEqual(profile.excluded_regions, []);
assert.equal(profile.period, "P1M");
assert.equal(profile.vpn_required, false);
assert.equal(profile.activation_window_seconds, null);
const worldwide = readActivationConditions({ ...values, scope: "worldwide", regions: "", excluded_regions: "ru", window_unit: "3600", window_amount: "1" });
assert.deepEqual(worldwide.regions, ["*"]);
assert.deepEqual(worldwide.excluded_regions, ["RU"]);
assert.equal(worldwide.activation_window_seconds, 3600);
const day = readActivationConditions({ ...values, period_unit: "D", period_amount: "30" });
assert.equal(day.period, "P30D");
assert.notEqual(day.period, profile.period);
let checks = 10;
for (const field of ["scope", "device", "plan_choice", "period_unit", "delivery_method", "account_requirement", "vpn_required", "window_unit"]) {
  assert.throws(() => readActivationConditions({ ...values, [field]: "" })); checks++;
}
for (const change of [
  { regions: "" }, { regions: "Russia" }, { regions: "ZZ" }, { excluded_regions: "BR" },
  { scope: "worldwide", regions: "RU" }, { plan_choice: "other" },
  { plan_choice: "other", plan_code: "unknown" }, { period_amount: "0" },
  { period_amount: "1.5" }, { window_unit: "3600", window_amount: "" },
]) {
  assert.throws(() => readActivationConditions({ ...values, ...change })); checks++;
}
assert.equal(readActivationConditions({ ...values, plan_choice: "other", plan_code: "super_individual" }).plan, "super_individual"); checks++;
console.log(`PASS ${checks} offline activation form assertions; synthetic fixtures only.`);
