// Kiểm thử logic giao diện bằng Node chuẩn, không phụ thuộc thư viện/browser.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function harness() {
  const elements = new Map();
  class Element {
    value = "";
    textContent = "";
    disabled = false;
    classList = { add() {}, remove() {}, toggle() {} };
    listeners = {};
    options = [];
    addEventListener(name, fn) { this.listeners[name] = fn; }
    showModal() { this.open = true; }
    close() { this.open = false; }
    set innerHTML(html) {
      this.html = html;
      this.options = [...html.matchAll(/<option value="([^"]*)"([^>]*)>/g)]
        .map(match => ({ value: match[1], selected: match[2].includes("selected") }));
      this.value = (this.options.find(item => item.selected) || this.options[0])?.value || "";
    }
    get innerHTML() { return this.html || ""; }
  }
  const query = selector => {
    if (!elements.has(selector)) elements.set(selector, new Element());
    return elements.get(selector);
  };
  const context = vm.createContext({
    URLSearchParams, console,
    document: { addEventListener() {}, querySelector: query }, window: {},
  });
  const web = path.resolve(__dirname, "../../src/gapo_timetabling/application/web");
  vm.runInContext(readFileSync(path.join(web, "app.js"), "utf8"), context);
  vm.runInContext(readFileSync(path.join(web, "schedule_adjustment.js"), "utf8"), context);
  vm.runInContext("state.currentRunId=7; state.scheduleWeek=2;", context);
  context.loadSchedule = async () => {};
  context.toast = () => {};
  context.escapeHtml = value => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;");
  const requests = [];
  context.apiJson = async (url, options) => {
    requests.push({ url, options });
    if (options?.method === "POST") return { revision_id: 9 };
    if (url.endsWith("schedule-revisions")) return { items: [
      { revision_id: 8, note: "Cũ", general_quality_score: 0, lecturer_preference_score: 0 },
      { revision_id: 9, note: "Mới", general_quality_score: 0, lecturer_preference_score: 0,
        preference_domain_mode: "OCCURRENCE" },
    ] };
    return { active_week_numbers: [1, 2, 3], items: [
      { iso_weekday: 3, start_period: 4, end_period: 6, location_id: 10,
        location_code: "A201", teaching_date: "2026-08-26" },
    ] };
  };
  query("#schedule-revision").value = "8";
  const item = { section_code: "JAVA01", part_code: "JAVA01_LT", part_type: "LECTURE",
    stability_group_no: 1, iso_weekday: 2, start_period: 1, location_id: 10, active_week_numbers: [2] };
  return { context, query, requests, item };
}

test("mở thẻ mặc định chỉ buổi đang xem, ghi đúng tuần và revision nguồn", async () => {
  const h = harness();
  await h.context.openScheduleAdjustment(h.item);
  const params = new URL(h.requests[0].url, "http://local").searchParams;
  assert.equal(params.get("scope"), "SINGLE_SESSION");
  assert.equal(params.get("week_number"), "2");
  assert.equal(params.get("revision_id"), "8");
  assert.match(h.query("#adjustment-option").innerHTML, /26\/08\/2026/);
  assert.equal(h.query("#save-adjustment").disabled, false);
  h.query("#adjustment-note").value = "Đổi riêng tuần 2";
  await h.context.saveScheduleAdjustment({ preventDefault() {} });
  const payload = JSON.parse(h.requests.find(item => item.options?.method === "POST").options.body);
  assert.equal(payload.scope, "SINGLE_SESSION");
  assert.equal(payload.week_number, 2);
  assert.equal(payload.parent_revision_id, 8);
  assert.equal(h.query("#schedule-revision").value, "9");
  assert.equal(h.query("#adjustment-dialog").open, false);
});

test("đổi toàn bộ tuần tải miền chung và không gửi tuần riêng lẻ", async () => {
  const h = harness();
  await h.context.openScheduleAdjustment(h.item);
  h.query("#adjustment-scope").value = "ALL_WEEKS";
  await h.context.loadAdjustmentOptions();
  const params = new URL(h.requests[1].url, "http://local").searchParams;
  assert.equal(params.get("scope"), "ALL_WEEKS");
  assert.equal(params.has("week_number"), false);
  h.query("#adjustment-note").value = "Đổi toàn nhóm";
  await h.context.saveScheduleAdjustment({ preventDefault() {} });
  const payload = JSON.parse(h.requests.find(item => item.options?.method === "POST").options.body);
  assert.equal(payload.scope, "ALL_WEEKS");
  assert.equal(payload.week_number, null);
});

test("phản hồi miền cũ không ghi đè khi đổi nhanh phạm vi", async () => {
  const h = harness();
  const responses = [];
  h.context.apiJson = () => new Promise(resolve => responses.push(resolve));
  const first = h.context.openScheduleAdjustment(h.item);
  h.query("#adjustment-scope").value = "ALL_WEEKS";
  const second = h.context.loadAdjustmentOptions();
  responses[1]({ active_week_numbers: [1, 2], items: [{ iso_weekday: 4, start_period: 7,
    end_period: 9, location_id: 20, location_code: "NEW" }] });
  await second;
  responses[0]({ items: [{ iso_weekday: 2, start_period: 1, end_period: 3,
    location_id: 10, location_code: "OLD" }] });
  await first;
  assert.match(h.query("#adjustment-option").innerHTML, /NEW/);
  assert.doesNotMatch(h.query("#adjustment-option").innerHTML, /OLD/);
});

test("không cho lưu khi miền rỗng hoặc API tải miền lỗi", async () => {
  const h = harness();
  h.context.apiJson = async () => ({ items: [] });
  await h.context.openScheduleAdjustment(h.item);
  assert.equal(h.query("#save-adjustment").disabled, true);
  h.context.apiJson = async () => { throw new Error("Nguồn không hợp lệ"); };
  await h.context.loadAdjustmentOptions();
  assert.equal(h.query("#save-adjustment").disabled, true);
  assert.match(h.query("#adjustment-result").textContent, /Nguồn không hợp lệ/);
});
