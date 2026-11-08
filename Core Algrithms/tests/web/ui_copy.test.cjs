const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const web=path.resolve(__dirname,'../../src/gapo_timetabling/application/web');
const html=fs.readFileSync(path.join(web,'index.html'),'utf8');
function harness(){
  const elements=new Map();
  const query=s=>{
    if(!elements.has(s))elements.set(s,{value:'',textContent:'',innerHTML:'',disabled:false,
      style:{},classList:{add(){},remove(){},toggle(){}},options:[]});
    return elements.get(s);
  };
  const c=vm.createContext({console,URLSearchParams,clearInterval(){},document:{addEventListener(){},querySelector:query},window:{}});
  for(const file of ['app.js','schedule_quality.js','schedule_adjustment.js'])vm.runInContext(fs.readFileSync(path.join(web,file),'utf8'),c);
  c.toast=()=>{};
  return {c,query};
}
test('bỏ hướng dẫn dài, giữ nút và cấu trúc tiến độ',()=>{
  assert.doesNotMatch(html,/FE là|Không cần nhập điểm|Demo tự phân bổ|Chọn buổi học để sửa|Ghi sau khi kết thúc/);
  assert.doesNotMatch(html,/id="run-activity"/);
  assert.match(html,/id="reset-semester">Xóa dữ liệu xếp lịch/);
  for(const id of ['run-iteration','run-fe-label','run-rounds','adjustment-scope','preview-adjustment','save-adjustment'])assert.ok(html.includes(`id="${id}"`));
});
test('hủy xác nhận xóa không gửi DELETE',async()=>{
  const {c}=harness();let confirmText='';
  vm.runInContext("state.selectedTerm='TERM_TEST';state.terms=[{term_code:'TERM_TEST',term_name:'Học kỳ thử'}]",c);
  c.window.confirm=t=>{confirmText=t;return false};
  c.apiJson=()=>{throw Error('DELETE forbidden')};
  await c.clearSemesterSchedulingData();
  assert.match(confirmText,/Học kỳ thử \(TERM_TEST\)/);
  assert.match(confirmText,/phiên bản điều chỉnh/);
  assert.match(confirmText,/dữ liệu đầu vào/i);
  assert.match(confirmText,/không thể hoàn tác/);
});
test('xác nhận xóa vẫn dùng endpoint dữ liệu xếp lịch của học kỳ đã chọn',async()=>{
  const {c,query}=harness();let request;
  vm.runInContext("state.selectedTerm='TERM_TEST';state.terms=[]",c);
  c.window.confirm=()=>true;c.updateScenarioSelect=()=>{};
  c.apiJson=async(url,options)=>{request={url,options};return {deleted_counts:{optimization_runs:2}}};
  await c.clearSemesterSchedulingData();
  assert.equal(request.url,'/api/input-data/terms/TERM_TEST/scheduling-data');
  assert.equal(request.options.method,'DELETE');
  assert.match(query('#reset-result').innerHTML||query('#reset-result').textContent,/2/);
});
test('chất lượng giữ phạm vi và chế độ đánh giá mà không kèm hướng dẫn',()=>{
  const {c}=harness();
  const value={session_count:486,general_quality_score:.1,lecturer_preference_score:.2,
    general_components:[],lecturer_components:[],lecturer_details:[],preference_domain_mode:'RECURRING'};
  const rendered=c.renderScheduleQuality(value);
  assert.match(rendered,/Toàn học kỳ: 486/);
  assert.match(rendered,/mẫu lịch lặp/);
  assert.doesNotMatch(rendered,/không phải|Thuật toán ưu tiên|Không so trực tiếp/);
  assert.match(c.renderScheduleQuality({...value,preference_domain_mode:'OCCURRENCE'}),/từng buổi học/);
});
