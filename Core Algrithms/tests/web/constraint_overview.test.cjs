// Chặn lỗi DOM khi bỏ trang Ràng buộc khỏi giao diện demo.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

function harness() {
  const web = path.resolve(__dirname, "../../src/gapo_timetabling/application/web");
  const html = readFileSync(path.join(web, "index.html"), "utf8");
  const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]));
  const dynamicIds = new Set(["manual-section", "add-manual-row"]);
  const elements = new Map();
  const listeners = new Map();
  const requests = [];
  const query = selector => {
    const id = selector.replace(/^#/, "");
    if (!ids.has(id) && !dynamicIds.has(id)) return null;
    if (!elements.has(id)) elements.set(id, {
      value: "", innerHTML: "", textContent: "", handlers: {},
      addEventListener(event, fn) { this.handlers[event] = fn; },
      close() {},
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    window: {}, console, confirm: () => true,
    document: { addEventListener: (name, fn) => listeners.set(name, fn) },
    $: query, $$: () => [], escapeHtml: value => String(value),
    apiJson: async url => {
      requests.push(url);
      assert.equal(url, "/api/input-data/form-schema");
      return { properties: { term: { $ref: "#/$defs/Term" } },
        $defs: { Term: { properties: {} } } };
    },
  });
  vm.runInContext(readFileSync(path.join(web, "data_forms.js"), "utf8"), context);
  return { context, listeners, query, requests };
}

test("khởi tạo form nhập tay không tìm trang/nút Ràng buộc đã bỏ hoặc gọi settings API", async () => {
  const h = harness();
  await h.listeners.get("DOMContentLoaded")();
  assert.deepEqual(h.requests, ["/api/input-data/form-schema"]);
  assert.match(h.query("#manual-editor").innerHTML, /Nhập thông tin học kỳ/);
  assert.equal(h.query("#save-constraints"), null);
  assert.equal(h.query("#reload-constraints"), null);
  assert.equal(h.query("#view-constraints"), null);
});

test("tạo gói học kỳ mới và định dạng JSON vẫn hoạt động sau khi bỏ sửa trọng số", async () => {
  const h = harness();
  await h.listeners.get("DOMContentLoaded")();
  h.query("#manual-json").value = JSON.stringify({ term: { term_code: "OLD" } });
  h.query("#new-manual").handlers.click();
  assert.equal(JSON.parse(h.query("#manual-json").value).term.term_code, "");
  h.query("#format-json").handlers.click();
  assert.match(h.query("#manual-editor").innerHTML, /Học kỳ/);
  assert.deepEqual(h.requests, ["/api/input-data/form-schema"]);
});
