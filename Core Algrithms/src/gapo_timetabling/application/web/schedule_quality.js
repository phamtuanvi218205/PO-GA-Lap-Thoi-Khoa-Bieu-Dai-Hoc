"use strict";

let qualityRequest = 0;
const qualityCache = new Map();
function qualityNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(6) : "—";
}
function qualityRows(items) {
  return items.map(row=>`<tr><th scope="row">${escapeHtml(row.label)}</th><td>${qualityNumber(row.value)}</td><td>${qualityNumber(row.weight)}</td><td>${qualityNumber(row.contribution)}</td></tr>`).join("");
}
function qualityTable(items) {
  return `<div class="quality-scroll"><table class="quality-table"><thead><tr><th>Tiêu chí</th><th>Điểm thành phần</th><th>Trọng số</th><th>Đóng góp vào điểm tổng</th></tr></thead><tbody>${qualityRows(items)}</tbody></table></div>`;
}
function renderScheduleQuality(payload) {
  const people = payload.lecturer_details || [];
  return `<p>Chất lượng của <strong>toàn bộ lịch, toàn học kỳ</strong>, không chỉ các buổi đang lọc. Đủ ${payload.session_count} buổi; 0 vi phạm cứng.</p>
    <p>Điểm nhỏ hơn là tốt hơn. Đây là điểm phạt đã chuẩn hóa, không phải số lỗi hay phần trăm hài lòng. Các giá trị hiển thị được làm tròn.</p>
    <p>Thuật toán ưu tiên chất lượng chung; chỉ xét tầng mong muốn và phù hợp giảng viên khi chất lượng chung bằng nhau.</p>
    <h3>Chất lượng chung: ${qualityNumber(payload.general_quality_score)}</h3>${qualityTable(payload.general_components)}
    <h3>Mong muốn và phù hợp giảng viên: ${qualityNumber(payload.lecturer_preference_score)}</h3>${qualityTable(payload.lecturer_components)}
    <p class="section-note">Mong muốn được đối chiếu trong ${payload.preference_domain_mode === "RECURRING" ? "miền mẫu lặp toàn kỳ của lịch gốc" : "miền từng buổi của bản điều chỉnh"}. Không so trực tiếp điểm mong muốn giữa hai chế độ. Trọng số 0 nghĩa là tiêu chí không tham gia điểm tổng.</p>
    <details><summary>Chi tiết mong muốn theo giảng viên</summary><p>Phần phạt bên dưới chưa chuẩn hóa; không cộng trực tiếp thành điểm tổng. Chỉ gồm những giảng viên có cơ hội cải thiện mong muốn trong miền lựa chọn.</p>
    <div class="quality-scroll"><table class="quality-table"><thead><tr><th>Giảng viên</th><th>Buổi có cơ hội cải thiện</th><th>Bỏ lỡ khung mong muốn</th><th>Khung hạn chế có thể tránh</th></tr></thead><tbody>${people.map(p=>`<tr><th scope="row">${escapeHtml(p.lecturer_code)} — ${escapeHtml(p.lecturer_name)}</th><td>${p.evaluated_session_count}</td><td>${qualityNumber(p.missed_preferred_penalty)}</td><td>${qualityNumber(p.discouraged_overlap_penalty)}</td></tr>`).join("") || '<tr><td colspan="4">Không có cơ hội cải thiện mong muốn thời gian trong miền đang xét.</td></tr>'}</tbody></table></div></details>`;
}
async function loadScheduleQuality(runId, revision) {
  const request = ++qualityRequest;
  const target = $("#schedule-quality");
  target.textContent = "Đang đánh giá chất lượng lịch…";
  const key = `${runId}:${revision || "original"}`;
  try {
    let payload = qualityCache.get(key);
    if (!payload) {
      const query = revision ? `?revision_id=${encodeURIComponent(revision)}` : "";
      payload = await apiJson(`/api/runs/${runId}/schedule-quality${query}`);
      if (request !== qualityRequest) return;
      // Keep only the currently viewed immutable schedule, not an unbounded cache.
      qualityCache.clear(); qualityCache.set(key, payload);
    }
    if (request === qualityRequest) target.innerHTML = renderScheduleQuality(payload);
  } catch (error) {
    if (request === qualityRequest) target.textContent = `Không thể đánh giá chất lượng: ${error.message}`;
  }
}
function clearScheduleQuality() {
  ++qualityRequest;
  $("#schedule-quality").textContent = "Chưa có lịch hợp lệ để đánh giá chất lượng.";
}
window.loadScheduleQuality = loadScheduleQuality;
window.clearScheduleQuality = clearScheduleQuality;
