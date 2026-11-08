"use strict";

const scheduleAdjustment = {runId:null, item:null, options:[], week:null, revision:null, optionRequest:0, previewRequest:0, previewKey:null, editRunId:null};
document.addEventListener("DOMContentLoaded", () => {
  $("#schedule-revision").addEventListener("change", loadSchedule);
  $("#reload-revisions").addEventListener("click", async () => {
    const runId = Number($("#schedule-run-id").value);
    if (runId) { await refreshScheduleRevisions(runId); await loadSchedule(); }
  });
  $("#adjustment-cancel").addEventListener("click",()=>{invalidateAdjustmentPreview(); $("#adjustment-dialog").close();});
  $("#adjustment-dialog").addEventListener("cancel", invalidateAdjustmentPreview);
  $("#adjustment-form").addEventListener("submit", saveScheduleAdjustment);
  $("#adjustment-scope").addEventListener("change", loadAdjustmentOptions);
  $("#adjustment-option").addEventListener("change", invalidateAdjustmentPreview);
  $("#preview-adjustment").addEventListener("click", previewScheduleAdjustment);
});
window.refreshScheduleRevisions = refreshScheduleRevisions;
window.openScheduleAdjustment = openScheduleAdjustment;

async function refreshScheduleRevisions(runId) {
  const select = $("#schedule-revision");
  const selected = scheduleAdjustment.runId===runId ? select.value : "";
  if (scheduleAdjustment.runId !== runId) select.value = "";
  const payload = await apiJson(`/api/runs/${runId}/schedule-revisions`);
  select.innerHTML = '<option value="">Kết quả thuật toán gốc</option>' + payload.items.map(item=>`<option value="${item.revision_id}">Bản ${item.revision_id} — ${escapeHtml(item.note)}</option>`).join("");
  if ([...select.options].some(option=>option.value===selected)) select.value=selected;
  scheduleAdjustment.runId=runId;
  const current=payload.items.find(item=>String(item.revision_id)===select.value);
  $("#revision-description").textContent=current ? `Bản điều chỉnh ${current.revision_id} · Q_general: ${current.general_quality_score.toFixed(6)} · Q_lecturer: ${current.lecturer_preference_score.toFixed(6)}` : "";
  $("#revision-description").classList.toggle("is-hidden", !current);
}
async function openScheduleAdjustment(item) {
  if (!item) return;
  scheduleAdjustment.item=item;
  scheduleAdjustment.editRunId=state.currentRunId;
  scheduleAdjustment.week=state.scheduleWeek;
  scheduleAdjustment.revision=$("#schedule-revision").value;
  $("#adjustment-scope").value="SINGLE_SESSION";
  $("#adjustment-title").textContent=`${item.section_code} — ${item.part_type==="PRACTICE"?"Thực hành":"Lý thuyết"} — tuần ${scheduleAdjustment.week}`;
  $("#adjustment-option").innerHTML="";
  $("#adjustment-note").value="";
  $("#adjustment-result").classList.add("is-hidden");
  $("#adjustment-dialog").showModal();
  await loadAdjustmentOptions();
}
async function loadAdjustmentOptions() {
  const item=scheduleAdjustment.item;
  if (!item) return;
  const requestId=++scheduleAdjustment.optionRequest;
  invalidateAdjustmentPreview();
  const scope=$("#adjustment-scope").value;
  const params=new URLSearchParams({part_code:item.part_code,stability_group_no:item.stability_group_no,scope});
  if(scheduleAdjustment.revision) params.set("revision_id",scheduleAdjustment.revision);
  if(scope==="SINGLE_SESSION") params.set("week_number",String(scheduleAdjustment.week));
  scheduleAdjustment.options=[];
  $("#adjustment-option").innerHTML="";
  $("#adjustment-result").classList.add("is-hidden");
  $("#adjustment-scope-description").textContent=scope==="SINGLE_SESSION" ? `Tuần ${scheduleAdjustment.week}` : "Toàn bộ tuần hoạt động, gồm các buổi đã điều chỉnh riêng";
  $("#save-adjustment").disabled=true;
  $("#preview-adjustment").disabled=true;
  try {
    const payload=await apiJson(`/api/runs/${state.currentRunId}/adjustment-options?${params}`);
    if(requestId!==scheduleAdjustment.optionRequest) return;
    if(scope==="ALL_WEEKS") $("#adjustment-scope-description").textContent=`Tuần ${formatWeeks(payload.active_week_numbers)} · gồm các buổi đã điều chỉnh riêng`;
    scheduleAdjustment.options=payload.items;
    const days=["","Thứ Hai","Thứ Ba","Thứ Tư","Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ nhật"];
    $("#adjustment-option").innerHTML=payload.items.map((option,index)=>`<option value="${index}" ${option.iso_weekday===item.iso_weekday&&option.start_period===item.start_period&&option.location_id===item.location_id?"selected":""}>${days[option.iso_weekday]}${option.teaching_date?` ${option.teaching_date.split("-").reverse().join("/")}`:""} · Tiết ${option.start_period}–${option.end_period} · ${escapeHtml(option.location_code)}</option>`).join("");
    $("#preview-adjustment").disabled=!payload.items.length;
  } catch(error) {if(requestId===scheduleAdjustment.optionRequest) setResultBox($("#adjustment-result"),error.message,true);}
}
function invalidateAdjustmentPreview() {
  ++scheduleAdjustment.previewRequest;
  scheduleAdjustment.previewKey=null;
  $("#save-adjustment").disabled=true;
  $("#adjustment-preview").innerHTML="";
  $("#preview-adjustment").disabled=!scheduleAdjustment.options.length;
}
function adjustmentRequest() {
  const option=scheduleAdjustment.options[Number($("#adjustment-option").value)];
  if(!option || !scheduleAdjustment.item) return null;
  const item=scheduleAdjustment.item;
  const revision=scheduleAdjustment.revision;
  const scope=$("#adjustment-scope").value;
  return {part_code:item.part_code,stability_group_no:item.stability_group_no,iso_weekday:option.iso_weekday,start_period:option.start_period,location_id:option.location_id,scope,week_number:scope==="SINGLE_SESSION"?scheduleAdjustment.week:null,parent_revision_id:revision?Number(revision):null,note:$("#adjustment-note").value};
}
function adjustmentKey(request) {
  if(!request) return null;
  const {note, ...proposal}=request;
  return JSON.stringify([scheduleAdjustment.editRunId, proposal]);
}
function describePreviewSession(item) {
  return `${escapeHtml(item.section_code)} / ${escapeHtml(item.part_code)} — ${escapeHtml(item.lecturer_code)}, tuần ${item.week_number}, ${escapeHtml(item.teaching_date)}, tiết ${item.start_period}–${item.end_period}, ${escapeHtml(item.location_code)}`;
}
function renderAdjustmentPreview(result) {
  let html=`<p><strong>${escapeHtml(result.message)}</strong></p>`;
  if(!result.is_valid) {
    html += (result.violations || []).map(v=>`<p><strong>${escapeHtml(v.code)}</strong>: ${escapeHtml(v.message)}<br>${v.sessions.map(describePreviewSession).join("<br>")}</p>`).join("");
    if(result.violation_count > 20) html += `<p>Hiển thị 20/${result.violation_count} vi phạm.</p>`;
    return html;
  }
  html += `<p>${result.changed_session_count} buổi thay đổi · 0 vi phạm cứng · Chế độ đánh giá: từng buổi học</p>`;
  const rows=[...["general_quality_score", "lecturer_preference_score"].map((code, i)=>({label:i===0?"Chất lượng chung":"Mong muốn và phù hợp giảng viên", before:result.before[code], after:result.after[code]})),
    ...result.before.general_components.map((row,i)=>({label:`Đóng góp: ${row.label}`, before:row.contribution, after:result.after.general_components[i].contribution})),
    ...result.before.lecturer_components.map((row,i)=>({label:`Đóng góp: ${row.label}`, before:row.contribution, after:result.after.lecturer_components[i].contribution}))];
  html += `<div class="quality-scroll"><table class="quality-table"><thead><tr><th>Tiêu chí</th><th>Trước</th><th>Sau</th><th>Chênh lệch</th></tr></thead><tbody>${rows.map(row=>`<tr><th scope="row">${escapeHtml(row.label)}</th><td>${qualityNumber(row.before)}</td><td>${qualityNumber(row.after)}</td><td>${qualityNumber(row.after-row.before)}</td></tr>`).join("")}</tbody></table></div>`;
  html += `<details><summary>Các buổi bị thay đổi</summary><div class="quality-scroll"><table class="quality-table"><thead><tr><th>Trước</th><th>Sau</th></tr></thead><tbody>${result.changes.map(change=>`<tr><td>${describePreviewSession(change.before)}</td><td>${describePreviewSession(change.after)}</td></tr>`).join("")}</tbody></table></div></details>`;
  return html;
}
async function previewScheduleAdjustment() {
  const request=adjustmentRequest();
  if(!request || state.currentRunId!==scheduleAdjustment.editRunId) return;
  invalidateAdjustmentPreview();
  const serial=scheduleAdjustment.previewRequest;
  const key=adjustmentKey(request);
  $("#adjustment-preview").textContent="Đang kiểm tra phương án…";
  $("#preview-adjustment").disabled=true;
  try {
    const result=await apiJson(`/api/runs/${scheduleAdjustment.editRunId}/adjustment-preview`,{method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...request,note:request.note.trim() || "Xem trước"})});
    if(serial!==scheduleAdjustment.previewRequest || key!==adjustmentKey(adjustmentRequest())) return;
    $("#adjustment-preview").innerHTML=renderAdjustmentPreview(result);
    scheduleAdjustment.previewKey=result.can_save ? key : null;
    $("#save-adjustment").disabled=!result.can_save;
  } catch(error) {
    if(serial===scheduleAdjustment.previewRequest) $("#adjustment-preview").textContent=`Không thể xem trước: ${error.message}`;
  } finally {
    if(serial===scheduleAdjustment.previewRequest) $("#preview-adjustment").disabled=!scheduleAdjustment.options.length;
  }
}
async function saveScheduleAdjustment(event) {
  event.preventDefault();
  const request=adjustmentRequest();
  if(!request) return;
  if(!scheduleAdjustment.previewKey || scheduleAdjustment.previewKey!==adjustmentKey(request) || state.currentRunId!==scheduleAdjustment.editRunId) {
    setResultBox($("#adjustment-result"), "Hãy xem trước đúng phương án hiện tại trước khi lưu.", true);
    return;
  }
  if(!request.note.trim()) {setResultBox($("#adjustment-result"), "Nhập lý do điều chỉnh trước khi lưu.", true); return;}
  const runId=scheduleAdjustment.editRunId;
  $("#save-adjustment").disabled=true;
  $("#adjustment-scope").disabled=true;
  $("#adjustment-option").disabled=true;
  $("#preview-adjustment").disabled=true;
  try {
    const result=await apiJson(`/api/runs/${runId}/schedule-revisions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(request)});
    if(state.currentRunId===runId) {
      await refreshScheduleRevisions(runId);
      $("#schedule-revision").value=String(result.revision_id);
      await loadSchedule();
    }
    $("#adjustment-dialog").close();
    toast(`Đã lưu bản điều chỉnh ${result.revision_id}; 0 vi phạm cứng.`);
  } catch(error) {setResultBox($("#adjustment-result"),error.message,true);}
  finally {invalidateAdjustmentPreview(); $("#adjustment-scope").disabled=false; $("#adjustment-option").disabled=false; $("#preview-adjustment").disabled=!scheduleAdjustment.options.length;}
}
