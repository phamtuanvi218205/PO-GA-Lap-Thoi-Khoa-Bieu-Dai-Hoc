"use strict";

const scheduleAdjustment = {runId:null, item:null, options:[], week:null, revision:null, optionRequest:0};
document.addEventListener("DOMContentLoaded", () => {
  $("#schedule-revision").addEventListener("change", loadSchedule);
  $("#reload-revisions").addEventListener("click", async () => {
    const runId = Number($("#schedule-run-id").value);
    if (runId) { await refreshScheduleRevisions(runId); await loadSchedule(); }
  });
  $("#adjustment-cancel").addEventListener("click",()=>$("#adjustment-dialog").close());
  $("#adjustment-form").addEventListener("submit", saveScheduleAdjustment);
  $("#adjustment-scope").addEventListener("change", loadAdjustmentOptions);
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
  const scoreNote=current?.preference_domain_mode==="OCCURRENCE" ? " Điểm mong muốn được tính theo miền từng buổi, không dùng so sánh benchmark." : "";
  $("#revision-description").textContent=current ? `Bản điều chỉnh ${current.revision_id}; Q_general=${current.general_quality_score.toFixed(6)}, Q_lecturer=${current.lecturer_preference_score.toFixed(6)}.${scoreNote} Kết quả thuật toán gốc không bị thay đổi.` : "Kết quả thuật toán gốc. Chọn buổi học để sửa riêng buổi đó hoặc toàn bộ các tuần hoạt động.";
}
async function openScheduleAdjustment(item) {
  if (!item) return;
  scheduleAdjustment.item=item;
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
  const scope=$("#adjustment-scope").value;
  const params=new URLSearchParams({part_code:item.part_code,stability_group_no:item.stability_group_no,scope});
  if(scheduleAdjustment.revision) params.set("revision_id",scheduleAdjustment.revision);
  if(scope==="SINGLE_SESSION") params.set("week_number",String(scheduleAdjustment.week));
  scheduleAdjustment.options=[];
  $("#adjustment-option").innerHTML="";
  $("#adjustment-result").classList.add("is-hidden");
  $("#adjustment-scope-description").textContent=scope==="SINGLE_SESSION" ? `Chỉ đổi buổi của tuần ${scheduleAdjustment.week} trong cùng tuần; các tuần khác giữ nguyên.` : "Đổi cùng thứ–tiết–phòng ở mọi tuần hoạt động của nhóm này, kể cả các buổi đã có ngoại lệ.";
  $("#save-adjustment").disabled=true;
  try {
    const payload=await apiJson(`/api/runs/${state.currentRunId}/adjustment-options?${params}`);
    if(requestId!==scheduleAdjustment.optionRequest) return;
    if(scope==="ALL_WEEKS") $("#adjustment-scope-description").textContent=`Đổi toàn bộ tuần ${formatWeeks(payload.active_week_numbers)}, kể cả buổi đã có ngoại lệ.`;
    scheduleAdjustment.options=payload.items;
    const days=["","Thứ Hai","Thứ Ba","Thứ Tư","Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ nhật"];
    $("#adjustment-option").innerHTML=payload.items.map((option,index)=>`<option value="${index}" ${option.iso_weekday===item.iso_weekday&&option.start_period===item.start_period&&option.location_id===item.location_id?"selected":""}>${days[option.iso_weekday]}${option.teaching_date?` ${option.teaching_date.split("-").reverse().join("/")}`:""} · Tiết ${option.start_period}–${option.end_period} · ${escapeHtml(option.location_code)}</option>`).join("");
    $("#save-adjustment").disabled=!payload.items.length;
  } catch(error) {if(requestId===scheduleAdjustment.optionRequest) setResultBox($("#adjustment-result"),error.message,true);}
}
async function saveScheduleAdjustment(event) {
  event.preventDefault();
  const option=scheduleAdjustment.options[Number($("#adjustment-option").value)];
  if(!option) return;
  const item=scheduleAdjustment.item;
  const revision=scheduleAdjustment.revision;
  const scope=$("#adjustment-scope").value;
  const request={part_code:item.part_code,stability_group_no:item.stability_group_no,iso_weekday:option.iso_weekday,start_period:option.start_period,location_id:option.location_id,scope,week_number:scope==="SINGLE_SESSION"?scheduleAdjustment.week:null,parent_revision_id:revision?Number(revision):null,note:$("#adjustment-note").value};
  $("#save-adjustment").disabled=true;
  $("#adjustment-scope").disabled=true;
  try {
    const result=await apiJson(`/api/runs/${state.currentRunId}/schedule-revisions`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(request)});
    await refreshScheduleRevisions(state.currentRunId);
    $("#schedule-revision").value=String(result.revision_id);
    $("#adjustment-dialog").close();
    await loadSchedule();
    toast(`Đã lưu bản điều chỉnh ${result.revision_id}; 0 vi phạm cứng.`);
  } catch(error) {setResultBox($("#adjustment-result"),error.message,true);}
  finally {$("#save-adjustment").disabled=false;$("#adjustment-scope").disabled=false;}
}
