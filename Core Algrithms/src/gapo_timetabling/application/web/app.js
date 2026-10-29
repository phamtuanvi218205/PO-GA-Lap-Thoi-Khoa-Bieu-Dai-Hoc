"use strict";

const state = {
  terms: [],
  selectedTerm: "",
  readyScenarios: [],
  currentJob: null,
  pollTimer: null,
  currentRunId: null,
  scheduleWeek: 1,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const friendlyCountNames = {
  approved_section_count: "Lớp đã duyệt",
  teaching_part_count: "Phần giảng dạy",
  lecturer_count: "Giảng viên",
  room_count: "Phòng học",
  plan_count: "Phương án tổ chức",
  class_session_count: "Buổi học theo tuần",
};

const terminalStatuses = new Set(["COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"]);

document.addEventListener("DOMContentLoaded", () => {
  bindNavigation();
  bindInputActions();
  bindPreparationActions();
  bindOptimizationActions();
  bindScheduleActions();
  checkApi();
  loadTerms();
});

function bindNavigation() {
  $$(".nav-item").forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.view));
  });
  $$('[data-go]').forEach((button) => {
    button.addEventListener("click", () => navigate(button.dataset.go));
  });
}

function navigate(viewName) {
  $$(".nav-item").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.view === viewName);
  });
  $$(".view").forEach((view) => view.classList.remove("is-visible"));
  const target = $(`#view-${viewName}`);
  if (!target) return;
  target.classList.add("is-visible");
  $("#page-title").textContent = target.dataset.title;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function checkApi() {
  try {
    await apiJson("/health");
    $("#api-status-text").className = "connection-status online";
    $("#api-status-text").textContent = "Đã kết nối";
  } catch (error) {
    $("#api-status-text").className = "connection-status offline";
    $("#api-status-text").textContent = "Mất kết nối";
  }
}

async function loadTerms() {
  const select = $("#term-select");
  select.innerHTML = '<option value="">Đang tải học kỳ…</option>';
  try {
    const payload = await apiJson("/api/input-data/terms");
    state.terms = payload.items || [];
    select.innerHTML = state.terms.length
      ? '<option value="">Chọn học kỳ</option>'
      : '<option value="">Chưa có học kỳ</option>';
    state.terms.forEach((term) => {
      const option = document.createElement("option");
      option.value = term.term_code;
      option.textContent = `${term.term_name} (${term.term_code})`;
      select.append(option);
    });
    if (state.selectedTerm && state.terms.some((term) => term.term_code === state.selectedTerm)) {
      select.value = state.selectedTerm;
    }
    updateSelectedTerm(select.value);
  } catch (error) {
    select.innerHTML = '<option value="">Không tải được học kỳ</option>';
    toast(error.message, true);
  }
}

function updateSelectedTerm(termCode) {
  const changed = state.selectedTerm !== termCode;
  state.selectedTerm = termCode;
  state.scheduleWeek = 1;
  if (changed) {
    state.readyScenarios = [];
    updateScenarioSelect();
  }
  const term = state.terms.find((item) => item.term_code === termCode);
  $("#prepare-term").textContent = term ? `${term.term_name} · ${term.term_code}` : "Chưa chọn học kỳ";
  updateWeekNavigation();
}

function bindInputActions() {
  $("#refresh-terms").addEventListener("click", loadTerms);
  $("#term-select").addEventListener("change", (event) => updateSelectedTerm(event.target.value));

  const fileInput = $("#excel-file");
  const zone = $("#upload-zone");
  fileInput.addEventListener("change", () => {
    $("#excel-file-name").textContent = fileInput.files[0]?.name || "Chưa có tệp được chọn";
  });
  ["dragenter", "dragover"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.add("is-dragging");
  }));
  ["dragleave", "drop"].forEach((name) => zone.addEventListener(name, (event) => {
    event.preventDefault();
    zone.classList.remove("is-dragging");
  }));
  zone.addEventListener("drop", (event) => {
    const file = event.dataTransfer.files[0];
    if (!file) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    fileInput.files = transfer.files;
    $("#excel-file-name").textContent = file.name;
  });

  $("#preview-excel").addEventListener("click", () => uploadExcel("preview"));
  $("#apply-excel").addEventListener("click", () => uploadExcel("apply"));
  $("#load-manual").addEventListener("click", loadManualBundle);
  $("#format-json").addEventListener("click", formatManualJson);
  $("#validate-manual").addEventListener("click", () => submitManual("validate"));
  $("#apply-manual").addEventListener("click", () => submitManual("apply"));
}

async function uploadExcel(action) {
  const file = $("#excel-file").files[0];
  if (!file) {
    toast("Hãy chọn một tệp Excel trước.", true);
    return;
  }
  const form = new FormData();
  form.append("file", file);
  const box = $("#excel-result");
  setResultBox(box, "Đang đọc và kiểm tra workbook…");
  try {
    const payload = await apiJson(`/api/input-data/excel/${action}`, { method: "POST", body: form });
    setResultBox(box, resultSummary(payload, action === "apply" ? "Đã lưu dữ liệu Excel" : "Workbook hợp lệ"));
    if (payload.term_code) {
      state.selectedTerm = payload.term_code;
      await loadTerms();
    }
    toast(action === "apply" ? "Đã lưu dữ liệu học kỳ." : "Workbook đã vượt qua kiểm tra.");
  } catch (error) {
    setResultBox(box, error.message, true);
  }
}

async function loadManualBundle() {
  if (!requireTerm()) return;
  try {
    const payload = await apiJson(`/api/input-data/terms/${encodeURIComponent(state.selectedTerm)}`);
    $("#manual-json").value = JSON.stringify(payload, null, 2);
    if (window.renderManualEditor) window.renderManualEditor();
    toast("Đã nạp dữ liệu học kỳ vào biểu mẫu.");
  } catch (error) {
    setResultBox($("#manual-result"), error.message, true);
  }
}

function formatManualJson() {
  try {
    const value = parseManualJson();
    $("#manual-json").value = JSON.stringify(value, null, 2);
  } catch (error) {
    setResultBox($("#manual-result"), error.message, true);
  }
}

async function submitManual(action) {
  const box = $("#manual-result");
  let bundle;
  try {
    bundle = parseManualJson();
  } catch (error) {
    setResultBox(box, error.message, true);
    return;
  }
  setResultBox(box, "Đang kiểm tra dữ liệu nhập tay…");
  try {
    const payload = await apiJson(`/api/input-data/${action}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bundle),
    });
    setResultBox(box, resultSummary(payload, action === "apply" ? "Đã lưu dữ liệu nhập tay" : "Dữ liệu hợp lệ"));
    if (payload.term_code) {
      state.selectedTerm = payload.term_code;
      await loadTerms();
    }
    toast(action === "apply" ? "Đã lưu dữ liệu học kỳ." : "Dữ liệu nhập tay hợp lệ.");
  } catch (error) {
    setResultBox(box, error.message, true);
  }
}

function parseManualJson() {
  const raw = $("#manual-json").value.trim();
  if (!raw) throw new Error("Chưa có dữ liệu JSON để kiểm tra.");
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new Error(`JSON không hợp lệ: ${error.message}`);
  }
}

function bindPreparationActions() {
  $("#reset-semester").addEventListener("click", resetSemesterForDemo);
  $("#check-readiness").addEventListener("click", checkReadiness);
  $("#prepare-semester").addEventListener("click", prepareSemester);
}

async function resetSemesterForDemo() {
  if (!requireTerm()) return;
  const term = state.terms.find((item) => item.term_code === state.selectedTerm);
  const label = term ? `${term.term_name} (${term.term_code})` : state.selectedTerm;
  const confirmed = window.confirm(
    `Đặt lại ${label}?\n\n` +
    "Các scenario, run, kết quả thời khóa biểu, plan và session đã sinh sẽ bị xóa. " +
    "Dữ liệu nguồn như môn, lớp, giảng viên, phòng và lịch bận vẫn được giữ."
  );
  if (!confirmed) return;

  const button = $("#reset-semester");
  const box = $("#reset-result");
  button.disabled = true;
  setResultBox(box, "Đang đặt lại dữ liệu đã sinh…");
  try {
    const payload = await apiJson(
      `/api/input-data/terms/${encodeURIComponent(state.selectedTerm)}/scheduling-data`,
      { method: "DELETE" }
    );
    const deleted = payload.deleted_counts || {};
    const total = Object.values(deleted).reduce((sum, value) => sum + Number(value || 0), 0);
    setResultBox(box, `Đã đặt lại học kỳ. Đã xóa ${formatNumber(total)} dòng dữ liệu phát sinh; dữ liệu nguồn được giữ nguyên.`);
    clearInterval(state.pollTimer);
    state.pollTimer = null;
    state.readyScenarios = [];
    state.currentJob = null;
    state.currentRunId = null;
    state.scheduleWeek = 1;
    updateScenarioSelect();
    $("#readiness-card").className = "readiness-card empty-state";
    $("#readiness-card").innerHTML = "<h3>Học kỳ đã được đặt lại. Hãy kiểm tra dữ liệu hoặc tạo bài toán mới.</h3>";
    toast("Đã đặt lại học kỳ để chạy demo lại.");
  } catch (error) {
    setResultBox(box, error.message, true);
  } finally {
    button.disabled = false;
  }
}

async function checkReadiness() {
  if (!requireTerm()) return;
  renderReadinessLoading();
  try {
    const report = await apiJson(`/api/input-data/terms/${encodeURIComponent(state.selectedTerm)}/readiness`);
    renderReadiness(report);
  } catch (error) {
    renderReadinessError(error.message);
  }
}

async function prepareSemester() {
  if (!requireTerm()) return;
  renderReadinessLoading("Đang sinh plan, session và kiểm tra miền lựa chọn…");
  try {
    const payload = await apiJson(`/api/input-data/terms/${encodeURIComponent(state.selectedTerm)}/prepare`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_scenario_candidates: 10 }),
    });
    renderReadiness(payload.readiness);
    state.readyScenarios = (payload.scenarios || []).filter(
      (item) => item.runnable || item.preparation_status === "READY"
    );
    updateScenarioSelect();
    if (state.readyScenarios.length === 1) {
      toast("Đã tự động chọn bài toán phù hợp nhất.");
      navigate("optimize");
    } else {
      renderReadinessError("Không có bài toán hợp lệ để chạy thuật toán.");
    }
  } catch (error) {
    renderReadinessError(error.message);
  }
}

function renderReadinessLoading(message = "Đang kiểm tra dữ liệu học kỳ…") {
  const card = $("#readiness-card");
  card.className = "readiness-card empty-state";
  card.innerHTML = `<h3>${escapeHtml(message)}</h3>`;
}

function renderReadiness(report) {
  const card = $("#readiness-card");
  const ready = Boolean(report.ready);
  card.className = `readiness-card ${ready ? "ready" : "not-ready"}`;
  const counts = Object.entries(report.counts || {}).map(([key, value]) => `
    <div class="count-item"><span>${escapeHtml(friendlyCountNames[key] || humanizeKey(key))}</span><strong>${escapeHtml(value)}</strong></div>
  `).join("");
  const issues = (report.issues || []).map((issue) => `
    <li><strong>${escapeHtml(issue.code || issue.severity)}</strong> · ${escapeHtml(issue.message || issue.detail || JSON.stringify(issue))}</li>
  `).join("");
  card.innerHTML = `
    <div class="readiness-head">
      <h3>${ready ? "Dữ liệu đã sẵn sàng" : "Dữ liệu chưa sẵn sàng"}</h3>
      <span class="readiness-status">${ready ? "READY" : "CẦN BỔ SUNG"}</span>
    </div>
    ${counts ? `<div class="count-grid">${counts}</div>` : ""}
    ${issues ? `<ul class="issue-list">${issues}</ul>` : '<p style="margin:16px 0 0;color:#567268">Không phát hiện lỗi bắt buộc.</p>'}
  `;
}

function renderReadinessError(message) {
  const card = $("#readiness-card");
  card.className = "readiness-card not-ready";
  card.innerHTML = `<div class="readiness-head"><h3>Không thể kiểm tra dữ liệu</h3><span class="readiness-status">LỖI</span></div><ul class="issue-list"><li>${escapeHtml(message)}</li></ul>`;
}

function updateScenarioSelect() {
  const scenario = state.readyScenarios[0];
  $("#scenario-select").value = scenario ? String(scenario.scenario_id) : "";
  $("#scenario-display").value = scenario
    ? `${scenario.scenario_code} · ID ${scenario.scenario_id}`
    : "Chưa có bài toán sẵn sàng";
}

function bindOptimizationActions() {
  $("#start-run").addEventListener("click", startOptimization);
  $("#cancel-run").addEventListener("click", cancelOptimization);
  $("#view-run-schedule").addEventListener("click", () => {
    if (!state.currentRunId) return;
    $("#schedule-run-id").value = state.currentRunId;
    navigate("schedule");
    loadSchedule();
  });
}

async function startOptimization() {
  const scenarioId = Number($("#scenario-select").value);
  if (!scenarioId) {
    toast("Chưa có scenario READY. Hãy chuẩn bị bài toán trước.", true);
    return;
  }
  const population = Number($("#population-size").value);
  const maxFe = Number($("#max-fe").value);
  const timeoutRaw = $("#timeout-seconds").value.trim();
  const body = {
    algorithm: $("#algorithm-select").value,
    population_size: population,
    max_fitness_evaluations: maxFe,
    random_seed: Number($("#random-seed").value),
    max_initialization_attempts: Math.max(6000, population * 100),
    max_offspring_attempts: 5,
    timeout_seconds: timeoutRaw ? Number(timeoutRaw) : null,
  };
  clearInterval(state.pollTimer);
  renderRun({ status: "PENDING", job_id: "Đang tạo", fitness_evaluations: 0, max_fitness_evaluations: maxFe, progress_ratio: 0 });
  try {
    const job = await apiJson(`/api/scenarios/${scenarioId}/optimization-jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    state.currentJob = job;
    state.currentRunId = job.run_id;
    renderRun(job);
    $("#cancel-run").disabled = false;
    pollJob(job.job_id);
  } catch (error) {
    renderRunError(error.message);
    toast(error.message, true);
  }
}

async function pollJob(jobId) {
  const update = async () => {
    try {
      const job = await apiJson(`/api/optimization-jobs/${encodeURIComponent(jobId)}`);
      state.currentJob = job;
      if (job.run_id) state.currentRunId = job.run_id;
      renderRun(job);
      if (terminalStatuses.has(job.status)) {
        clearInterval(state.pollTimer);
        state.pollTimer = null;
        $("#cancel-run").disabled = true;
        if (job.status === "COMPLETED") {
          $("#view-run-schedule").disabled = false;
          $("#schedule-run-id").value = job.run_id;
          toast("Thuật toán đã hoàn thành. Có thể mở thời khóa biểu.");
        }
      }
    } catch (error) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      renderRunError(error.message);
    }
  };
  await update();
  if (!state.pollTimer && !terminalStatuses.has(state.currentJob?.status)) {
    state.pollTimer = setInterval(update, 2000);
  }
}

async function cancelOptimization() {
  if (!state.currentJob?.job_id) return;
  try {
    const job = await apiJson(`/api/optimization-jobs/${encodeURIComponent(state.currentJob.job_id)}/cancel`, { method: "POST" });
    state.currentJob = job;
    renderRun(job);
    toast("Đã gửi yêu cầu hủy. Thuật toán sẽ dừng tại checkpoint an toàn.");
  } catch (error) {
    toast(error.message, true);
  }
}

function renderRun(job) {
  const statusLabels = {
    PENDING: "Đang chờ worker",
    QUEUED: "Đang chờ worker",
    RUNNING: "Đang tối ưu",
    COMPLETED: "Đã hoàn thành",
    FAILED: "Chạy thất bại",
    CANCEL_REQUESTED: "Đang yêu cầu hủy",
    CANCELLED: "Đã hủy",
    TIMED_OUT: "Đã hết thời gian",
  };
  const progress = Math.max(0, Math.min(1, Number(job.progress_ratio || 0)));
  $("#run-status").textContent = statusLabels[job.status] || job.status;
  $("#run-badge").textContent = job.run_id ? `RUN ${job.run_id}` : job.job_id || "ID —";
  $("#run-progress").style.width = `${(progress * 100).toFixed(1)}%`;
  $("#run-progress-label").textContent = `${(progress * 100).toFixed(1)}%`;
  $("#run-fe-label").textContent = `${formatNumber(job.fitness_evaluations || 0)} / ${formatNumber(job.max_fitness_evaluations || 0)} FE`;
  $("#run-iteration").textContent = job.max_iterations ? `${job.completed_iterations || 0} / ${job.max_iterations}` : "—";
  $("#run-general").textContent = formatScore(job.best_general_quality_score);
  $("#run-lecturer").textContent = formatScore(job.best_lecturer_preference_score);
  const errorBox = $("#run-error");
  if (job.error_message) {
    errorBox.textContent = job.error_message;
    errorBox.classList.remove("is-hidden");
  } else {
    errorBox.classList.add("is-hidden");
  }
  $("#cancel-run").disabled = terminalStatuses.has(job.status) || !job.job_id;
  $("#view-run-schedule").disabled = job.status !== "COMPLETED";
}

function renderRunError(message) {
  $("#run-status").textContent = "Không thể bắt đầu";
  const errorBox = $("#run-error");
  errorBox.textContent = message;
  errorBox.classList.remove("is-hidden");
  $("#cancel-run").disabled = true;
}

function bindScheduleActions() {
  $("#load-schedule").addEventListener("click", loadSchedule);
  $("#previous-week").addEventListener("click", () => changeScheduleWeek(-1));
  $("#next-week").addEventListener("click", () => changeScheduleWeek(1));
  ["#schedule-run-id", "#filter-lecturer", "#filter-section"].forEach((selector) => {
    $(selector).addEventListener("keydown", (event) => {
      if (event.key === "Enter") loadSchedule();
    });
  });
}

function changeScheduleWeek(offset) {
  const maximum = selectedTermWeekCount();
  state.scheduleWeek = Math.min(maximum, Math.max(1, state.scheduleWeek + offset));
  updateWeekNavigation();
  if (Number($("#schedule-run-id").value)) loadSchedule();
}

function selectedTermWeekCount() {
  const term = state.terms.find((item) => item.term_code === state.selectedTerm);
  if (!term?.start_date || !term?.end_date) return 1;
  const start = new Date(`${term.start_date}T00:00:00`);
  const end = new Date(`${term.end_date}T00:00:00`);
  // Học kỳ kết thúc vào Chủ nhật nên chênh lệch ngày không phải số tuần tròn.
  // Lấy phần nguyên để khoảng Thứ Hai tuần 1 đến Chủ nhật tuần 15 hiện đúng 15.
  return Math.max(1, Math.floor((end - start) / 604800000) + 1);
}

function updateWeekNavigation() {
  const maximum = selectedTermWeekCount();
  state.scheduleWeek = Math.min(maximum, Math.max(1, state.scheduleWeek));
  $("#current-week-label").textContent = `Tuần ${state.scheduleWeek} / ${maximum}`;
  $("#previous-week").disabled = state.scheduleWeek <= 1;
  $("#next-week").disabled = state.scheduleWeek >= maximum;
}

async function loadSchedule() {
  const runId = Number($("#schedule-run-id").value);
  if (!runId) {
    toast("Hãy nhập run ID đã hoàn thành.", true);
    return;
  }
  const container = $("#schedule-container");
  container.innerHTML = '<div class="empty-state schedule-empty"><h3>Đang tải thời khóa biểu</h3></div>';
  try {
    if (window.refreshScheduleRevisions) await window.refreshScheduleRevisions(runId);
    const params = scheduleQueryParams();
    const payload = await apiJson(`/api/runs/${runId}/schedule?${params.toString()}`);
    state.currentRunId = runId;
    renderSchedule(payload.items || []);
    updateExportLinks(runId, params);
  } catch (error) {
    container.innerHTML = `<div class="empty-state schedule-empty"><div><h3>Không thể hiển thị lịch</h3><p>${escapeHtml(error.message)}</p></div></div>`;
    disableExportLinks();
  }
}

function scheduleQueryParams() {
  const params = new URLSearchParams();
  const lecturer = $("#filter-lecturer").value.trim();
  const section = $("#filter-section").value.trim();
  if (lecturer) params.set("lecturer_query", lecturer);
  if (section) params.set("section_code", section);
  params.set("week_number", String(state.scheduleWeek));
  if (state.selectedTerm) params.set("term_code", state.selectedTerm);
  const revision = $("#schedule-revision").value;
  if (revision) params.set("revision_id", revision);
  return params;
}

function renderSchedule(items) {
  const container = $("#schedule-container");
  if (!items.length) {
    container.innerHTML = '<div class="empty-state schedule-empty"><h3>Không có buổi học phù hợp</h3></div>';
    $("#schedule-summary").classList.add("is-hidden");
    return;
  }
  const assigned = assignScheduleLanes(items);
  const byDay = Array.from({ length: 7 }, () => []);
  assigned.forEach((item) => byDay[item.iso_weekday - 1].push(item));
  const weekdays = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"];
  const headers = weekdays.map((day, index) => {
    const dateLabel = scheduleDateForWeekday(index + 1);
    return `<div><strong>${day}</strong><small>${dateLabel}</small></div>`;
  }).join("");
  const periods = Array.from({ length: 16 }, (_, index) => `<span class="period-label" style="top:${index * 72}px">Tiết ${index + 1}</span>`).join("");
  const tracks = byDay.map((dayItems) => `<div class="day-track">${dayItems.map(sessionCardHtml).join("")}</div>`).join("");
  container.innerHTML = `
    <div class="timetable">
      <div class="timetable-header"><div><strong>Tiết</strong><small>1–16</small></div>${headers}</div>
      <div class="timetable-body"><div class="period-axis">${periods}</div>${tracks}</div>
    </div>
  `;

  const lecturers = new Set(items.map((item) => item.lecturer_code));
  const sections = new Set(items.map((item) => item.section_code));
  $("#schedule-summary").classList.remove("is-hidden");
  $("#schedule-term").textContent = `${items[0].term_name} · ${items[0].term_code}`;
  $("#schedule-count").textContent = items.length;
  $("#schedule-lecturer-count").textContent = lecturers.size;
  $("#schedule-section-count").textContent = sections.size;
  container.querySelectorAll(".session-card").forEach((card) => {
    card.tabIndex = 0;
    card.setAttribute("role", "button");
    const item = items.find((row) => row.part_code === card.dataset.part && String(row.stability_group_no) === card.dataset.group);
    const open = () => window.openScheduleAdjustment && window.openScheduleAdjustment(item);
    card.addEventListener("click", open);
    card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); open(); } });
  });
}

function assignScheduleLanes(items) {
  const result = [];
  for (let weekday = 1; weekday <= 7; weekday += 1) {
    const dayItems = items
      .filter((item) => item.iso_weekday === weekday)
      .sort((a, b) => a.start_period - b.start_period || a.end_period - b.end_period || a.section_code.localeCompare(b.section_code));
    const laneEnds = [];
    const temporary = dayItems.map((item) => {
      let lane = laneEnds.findIndex((end) => end < item.start_period);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(item.end_period);
      } else {
        laneEnds[lane] = item.end_period;
      }
      return { ...item, lane };
    });
    const laneCount = Math.max(1, laneEnds.length);
    result.push(...temporary.map((item) => ({ ...item, laneCount })));
  }
  return result;
}

function sessionCardHtml(item) {
  const top = (item.start_period - 1) * 72 + 4;
  const height = (item.end_period - item.start_period + 1) * 72 - 8;
  const width = 100 / item.laneCount;
  const left = item.lane * width;
  const typeClass = item.location_type === "ONLINE" ? "online" : item.part_type === "PRACTICE" ? "practice" : "lecture";
  const typeName = item.part_type === "PRACTICE" ? "Thực hành" : "Lý thuyết";
  return `
    <article class="session-card ${typeClass}" data-part="${escapeHtml(item.part_code)}" data-group="${item.stability_group_no}" style="top:${top}px;height:${height}px;left:calc(${left}% + 4px);width:calc(${width}% - 8px)" title="${escapeHtml(item.course_name)} · ${escapeHtml(item.lecturer_name)} · Bấm để điều chỉnh">
      <strong>${escapeHtml(item.section_code)} · ${typeName}</strong>
      <span class="course-name">${escapeHtml(item.course_name)}</span>
      <span>Tiết ${item.start_period}–${item.end_period} · ${escapeHtml(item.location_code)}</span>
      <span>GV: ${escapeHtml(item.lecturer_name)}</span>
      <span>Tuần ${state.scheduleWeek}</span>
    </article>
  `;
}

function scheduleDateForWeekday(isoWeekday) {
  const term = state.terms.find((item) => item.term_code === state.selectedTerm);
  if (!term?.start_date) return "";
  const date = new Date(`${term.start_date}T00:00:00`);
  date.setDate(date.getDate() + (state.scheduleWeek - 1) * 7 + isoWeekday - 1);
  return new Intl.DateTimeFormat("vi-VN", {
    day: "2-digit", month: "2-digit", year: "numeric",
  }).format(date);
}

function formatWeeks(values) {
  const weeks = [...values].sort((a, b) => a - b);
  if (!weeks.length) return "—";
  const ranges = [];
  let start = weeks[0];
  let previous = weeks[0];
  for (let index = 1; index <= weeks.length; index += 1) {
    const current = weeks[index];
    if (current === previous + 1) {
      previous = current;
      continue;
    }
    ranges.push(start === previous ? `${start}` : `${start}–${previous}`);
    start = current;
    previous = current;
  }
  return ranges.join(", ");
}

function updateExportLinks(runId, params) {
  for (const [id, extension] of [["#export-csv", "csv"], ["#export-xlsx", "xlsx"]]) {
    const link = $(id);
    link.href = `/api/runs/${runId}/schedule.${extension}?${params.toString()}`;
    link.classList.remove("is-disabled");
  }
}

function disableExportLinks() {
  $("#export-csv").classList.add("is-disabled");
  $("#export-xlsx").classList.add("is-disabled");
}

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : null;
  if (!response.ok) throw new Error(errorMessage(payload?.detail, response.status));
  return payload;
}

function errorMessage(detail, status) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg || item.message || JSON.stringify(item)).join("; ");
  if (detail && typeof detail === "object") {
    if (detail.message) return detail.message;
    return JSON.stringify(detail);
  }
  return `Yêu cầu thất bại (HTTP ${status}).`;
}

function setResultBox(element, message, isError = false) {
  element.textContent = message;
  element.classList.remove("is-hidden");
  element.classList.toggle("error", isError);
}

function resultSummary(payload, title) {
  const counts = payload.entity_counts || {};
  const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
  return `${title}. Học kỳ ${payload.term_code || "—"}; ${formatNumber(total)} bản ghi nguồn.`;
}

function requireTerm() {
  if (state.selectedTerm) return true;
  toast("Hãy chọn học kỳ ở góc trên bên phải.", true);
  return false;
}

function toast(message, isError = false) {
  const item = document.createElement("div");
  item.className = `toast${isError ? " error" : ""}`;
  item.textContent = message;
  $("#toast-region").append(item);
  setTimeout(() => item.remove(), 5000);
}

function formatDate(value) {
  if (!value) return "—";
  const parts = String(value).slice(0, 10).split("-");
  return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : value;
}

function formatNumber(value) {
  return new Intl.NumberFormat("vi-VN").format(Number(value || 0));
}

function formatScore(value) {
  return value === null || value === undefined ? "—" : Number(value).toFixed(6);
}

function humanizeKey(value) {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = String(value ?? "");
  return element.innerHTML;
}
