"use strict";

// Biểu mẫu chỉ chuyển dữ liệu nhập thành SemesterInputBundle. Mọi quy tắc
// nghiệp vụ và kiểm tra tham chiếu vẫn do API dùng chung với Excel thực hiện.
const manualEditor = { schema: null, section: "term", row: null };
const inputSectionLabels = {
  term: "Học kỳ", campuses: "Cơ sở", courses: "Môn học", lecturers: "Giảng viên",
  lecturer_capabilities: "Năng lực giảng dạy", rooms: "Phòng học", online_locations: "Lớp trực tuyến",
  equipment: "Thiết bị", room_equipment: "Thiết bị phòng", course_sections: "Lớp học phần mở",
  course_teaching_structures: "Cấu trúc môn học", course_structure_equipment: "Thiết bị môn học",
  lecturer_availability: "Lịch bận và mong muốn giảng viên", room_availability: "Lịch bận phòng",
};
const inputFieldLabels = {
  term_code: "Mã học kỳ", term_name: "Tên học kỳ", start_date: "Ngày bắt đầu (thứ Hai)",
  number_of_weeks: "Số tuần", status: "Trạng thái", campus_code: "Mã cơ sở", campus_name: "Tên cơ sở",
  address: "Địa chỉ", is_active: "Đang sử dụng", course_code: "Mã môn học", course_name: "Tên môn học",
  credits: "Số tín chỉ", lecturer_code: "Mã giảng viên", full_name: "Họ tên", email: "Email",
  home_campus_code: "Cơ sở chính", max_teaching_periods: "Tổng tiết tối đa trong kỳ",
  can_teach_lecture: "Có thể dạy lý thuyết", can_teach_practice: "Có thể dạy thực hành",
  suitability_score: "Mức phù hợp (0–1)", room_code: "Mã phòng", room_name: "Tên phòng",
  room_type: "Loại phòng", capacity: "Sức chứa", location_code: "Mã lớp trực tuyến",
  location_name: "Tên lớp trực tuyến", platform_name: "Nền tảng", meeting_note: "Thông tin lớp",
  equipment_code: "Mã thiết bị", equipment_name: "Tên thiết bị", quantity: "Số lượng",
  section_code: "Mã lớp học phần", section_name: "Tên lớp học phần", expected_enrollment: "Sĩ số dự kiến",
  part_type: "Loại phần", total_periods: "Tổng số tiết", required_location_type: "Hình thức học",
  required_room_type: "Loại phòng yêu cầu", max_sessions_per_week: "Số buổi tối đa mỗi tuần",
  allows_intensive: "Cho phép học tập trung", max_candidate_plans: "Số phương án tổ chức tối đa",
  note: "Ghi chú", minimum_quantity: "Số lượng tối thiểu", scope_type: "Lịch theo ngày hay thứ",
  calendar_date: "Ngày cụ thể", iso_weekday: "Thứ ISO (1=Thứ Hai, 7=Chủ nhật)",
  start_period: "Tiết bắt đầu", end_period: "Tiết kết thúc", availability_type: "Loại khả dụng",
  preference_weight: "Mức độ mong muốn / hạn chế",
};
const enumLabels = {
  PLANNING: "Dự kiến", APPROVED: "Đưa vào xếp lịch", CANCELLED: "Hủy lớp",
  ACTIVE: "Đang hoạt động", CLOSED: "Đã kết thúc", LECTURE: "Lý thuyết", PRACTICE: "Thực hành",
  PHYSICAL_ROOM: "Tại phòng", ONLINE: "Trực tuyến", DATE: "Ngày cụ thể", WEEKDAY: "Lặp theo thứ",
  UNAVAILABLE: "Không thể dạy / sử dụng", PREFERRED: "Mong muốn", DISCOURAGED: "Hạn chế sử dụng",
  LECTURE_ROOM: "Phòng lý thuyết", COMPUTER_LAB: "Phòng máy tính",
};

document.addEventListener("DOMContentLoaded", async () => {
  $("#new-manual").addEventListener("click", () => {
    if ($("#manual-json").value.trim() && !confirm("Tạo gói học kỳ mới? Dữ liệu chưa lưu trong biểu mẫu sẽ bị thay thế.")) return;
    $("#manual-json").value = JSON.stringify({ term: {term_code: "", term_name: "", start_date: "", number_of_weeks: 15, status: "PLANNING"} });
    manualEditor.section = "term";
    renderManualEditor();
  });
  $("#manual-row-cancel").addEventListener("click", () => $("#manual-row-dialog").close());
  $("#manual-row-form").addEventListener("submit", saveManualRow);
  $("#format-json").addEventListener("click", renderManualEditor);
  $("#reload-constraints").addEventListener("click", loadConstraintSettings);
  $("#save-constraints").addEventListener("click", saveConstraintSettings);
  try {
    manualEditor.schema = await apiJson("/api/input-data/form-schema");
    if (!$("#manual-json").value.trim()) $("#manual-json").value = JSON.stringify({term: {term_code: "", term_name: "", start_date: "", number_of_weeks: 15, status: "PLANNING"}});
    renderManualEditor();
  } catch (error) { $("#manual-editor").textContent = error.message; }
  await loadConstraintSettings();
});

window.renderManualEditor = renderManualEditor;
function manualBundle() { return JSON.parse($("#manual-json").value || "{}"); }
function sectionSchema(section) {
  const definition = manualEditor.schema.properties[section];
  const ref = section === "term" ? definition.$ref : definition.items.$ref;
  return manualEditor.schema.$defs[ref.split("/").pop()];
}
function renderManualEditor() {
  if (!manualEditor.schema) return;
  const bundle = manualBundle();
  const section = manualEditor.section;
  const rows = section === "term" ? [bundle.term || {}] : (bundle[section] || []);
  $("#manual-editor").innerHTML = `
    <label>Nhóm dữ liệu<select id="manual-section">${Object.entries(inputSectionLabels).map(([key,label]) => `<option value="${key}" ${key===section?"selected":""}>${label}</option>`).join("")}</select></label>
    <div class="button-row"><button class="secondary-button" id="add-manual-row" type="button">${section === "term" ? "Nhập thông tin học kỳ" : "Thêm bản ghi"}</button><span>${rows.length} bản ghi trong gói nhập</span></div>
    <div class="manual-records">${rows.map((row,index) => `<div class="manual-record"><span>${escapeHtml(Object.values(row).filter(v => v!==null && typeof v!=="boolean").slice(0,4).join(" · ") || "Chưa nhập thông tin")}</span><button type="button" class="text-button" data-edit="${index}">Sửa</button>${section!=="term"?`<button type="button" class="text-button" data-remove="${index}">Bỏ khỏi gói</button>`:""}</div>`).join("") || "Chưa có bản ghi."}</div>`;
  $("#manual-section").addEventListener("change", event => {manualEditor.section = event.target.value; renderManualEditor();});
  $("#add-manual-row").addEventListener("click", () => openManualRow(section === "term" ? 0 : null));
  $$("#manual-editor [data-edit]").forEach(button => button.addEventListener("click", () => openManualRow(Number(button.dataset.edit))));
  $$("#manual-editor [data-remove]").forEach(button => button.addEventListener("click", () => {
    if (!confirm("Bỏ dòng khỏi gói đang nhập? Thao tác này không xóa bản ghi đã lưu trong database. Để ngừng xếp một lớp đã lưu, đổi trạng thái lớp thành Hủy lớp.")) return;
    const value = manualBundle(); value[section].splice(Number(button.dataset.remove),1);
    $("#manual-json").value = JSON.stringify(value,null,2); renderManualEditor();
  }));
}
function openManualRow(index) {
  const section = manualEditor.section;
  const schema = sectionSchema(section);
  const bundle = manualBundle();
  const row = section === "term" ? bundle.term || {} : (index === null ? {} : bundle[section][index]);
  manualEditor.row = index;
  $("#manual-dialog-title").textContent = inputSectionLabels[section];
  $("#manual-row-fields").innerHTML = Object.entries(schema.properties).map(([key, definition]) => {
    const property = definition.anyOf ? definition.anyOf.find(value => value.type !== "null") : definition;
    const value = row[key] ?? definition.default ?? "";
    const required = (schema.required || []).includes(key);
    let field;
    if (property.type === "boolean") {
      field = `<select name="${key}" data-kind="boolean"><option value="true" ${value===true?"selected":""}>Có</option><option value="false" ${value!==true?"selected":""}>Không</option></select>`;
    } else if (property.enum) {
      field = `<select name="${key}" data-kind="string" ${required?"required":""}>${!required?'<option value="">Không khai báo</option>':""}${property.enum.map(v=>`<option value="${escapeHtml(v)}" ${v===value?"selected":""}>${escapeHtml(enumLabels[v]||v)}</option>`).join("")}</select>`;
    } else {
      const numeric = ["integer","number"].includes(property.type) || property.anyOf?.some(v=>["integer","number"].includes(v.type));
      const type = property.format === "date" ? "date" : numeric ? "number" : "text";
      const min = property.minimum ?? (property.exclusiveMinimum !== undefined ? property.exclusiveMinimum + (property.type === "integer" ? 1 : 0.0001) : null);
      field = `<input name="${key}" data-kind="${numeric?"number":"string"}" type="${type}" value="${escapeHtml(String(value))}" ${required?"required":""} ${numeric?'step="any"':""} ${min!==null?`min="${min}"`:""} ${property.maximum!==undefined?`max="${property.maximum}"`:""} ${property.maxLength?`maxlength="${property.maxLength}"`:""}>`;
    }
    return `<label>${escapeHtml(inputFieldLabels[key]||key)}${required?" *":""}${field}</label>`;
  }).join("");
  $("#manual-row-dialog").showModal();
}
function saveManualRow(event) {
  event.preventDefault();
  const bundle = manualBundle();
  const row = {};
  $$("#manual-row-fields [name]").forEach(input => {
    if (input.value === "") return;
    row[input.name] = input.dataset.kind === "boolean" ? input.value === "true" : input.dataset.kind === "number" ? Number(input.value) : input.value.trim();
  });
  if (manualEditor.section === "term") bundle.term = row;
  else {
    bundle[manualEditor.section] ||= [];
    if (manualEditor.row === null) bundle[manualEditor.section].push(row);
    else bundle[manualEditor.section][manualEditor.row] = row;
  }
  $("#manual-json").value = JSON.stringify(bundle,null,2);
  $("#manual-row-dialog").close(); renderManualEditor();
}

let constraintChecksum = null;
async function loadConstraintSettings() {
  try {
    const payload = await apiJson("/api/constraint-settings");
    constraintChecksum = payload.checksum;
    $("#constraint-editor").innerHTML = [2,3].map(tier=>`<h3>${tier===2?"Q_general — chất lượng chung":"Q_lecturer — mong muốn và phù hợp giảng viên"}</h3>${payload.settings.filter(item=>item.priority_tier===tier).map(item=>`<div class="constraint-row" data-code="${item.constraint_code}"><label>${escapeHtml(item.name)}<input class="criterion-weight" type="number" min="0.0001" max="1" step="0.0001" value="${item.weight}"></label>${item.threshold_value!==null?`<label>Ngưỡng tiết liên tục<input class="criterion-threshold" type="number" min="1" max="16" step="1" value="${item.threshold_value}"></label>`:""}</div>`).join("")}`).join("");
  } catch(error) { setResultBox($("#constraint-result"),error.message,true); }
}
async function saveConstraintSettings() {
  if (!constraintChecksum) return;
  const settings = $$(".constraint-row").map(row=>({constraint_code:row.dataset.code,weight:Number(row.querySelector(".criterion-weight").value),threshold_value:row.querySelector(".criterion-threshold")?Number(row.querySelector(".criterion-threshold").value):null}));
  try {
    const payload = await apiJson("/api/constraint-settings",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({expected_checksum:constraintChecksum,settings})});
    constraintChecksum = payload.checksum;
    setResultBox($("#constraint-result"),"Đã lưu. Các snapshot được tạo từ lần chạy tiếp theo sử dụng cấu hình này; kết quả cũ được giữ nguyên.");
  } catch(error) { setResultBox($("#constraint-result"),error.message,true); }
}
