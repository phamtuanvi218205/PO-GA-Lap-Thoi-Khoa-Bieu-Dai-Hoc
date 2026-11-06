const assert = require('node:assert/strict');
const {test}=require('node:test');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

function harness() {
  const elements=new Map(),timers=new Map(); let id=0,now=0;
  const query=key=>{if(!elements.has(key)) elements.set(key,{textContent:'',innerHTML:'',disabled:false,style:{},value:'',classList:{add(){},remove(){}}}); return elements.get(key)};
  class FakeDate extends Date {static now(){return now}}
  const c=vm.createContext({console,Date:FakeDate,document:{addEventListener(){},querySelector:query},window:{},
    setInterval(fn){timers.set(++id,fn); return id},clearInterval(key){timers.delete(key)}});
  vm.runInContext(readFileSync(path.resolve(__dirname,'../../src/gapo_timetabling/application/web/app.js'),'utf8'),c);
  return {c,query,timers,tick(ms){now+=ms; for(const fn of [...timers.values()]) fn()}};
}

function job(changes={}) {return {job_id:'run-8',run_id:8,status:'RUNNING',fitness_evaluations:75,max_fitness_evaluations:3060,
  completed_iterations:0,max_iterations:50,elapsed_seconds:65,candidate_attempts:110,decode_failed_count:35,
  best_general_quality_score:.1,best_lecturer_preference_score:.2,iteration_history:[{iteration:0,fitness_evaluations:60,new_fitness_evaluations:60,
    elapsed_seconds:60,duration_seconds:60,best_general_quality_score:.1,best_lecturer_preference_score:.2}],...changes}}

test('hiện vòng đang chạy và nhật ký vòng thật dù Q không đổi',()=>{
  const h=harness(); h.c.renderRun(job());
  assert.match(h.query('#run-iteration').textContent,/Đang vòng 1\/50/);
  assert.equal(h.query('#run-elapsed').textContent,'01:05');
  assert.match(h.query('#run-attempts').textContent,/110.*35/);
  assert.match(h.query('#run-rounds').innerHTML,/Khởi tạo/);
  h.c.renderRun(job({completed_iterations:2,fitness_evaluations:180}));
  assert.match(h.query('#run-iteration').textContent,/Đang vòng 3\/50/);
  assert.match(h.query('#run-general').textContent,/0\.1/);
});

test('đồng hồ nhích thật nhưng không tự tạo FE hoặc vòng và dừng khi kết thúc',()=>{
  const h=harness(); h.c.renderRun(job());
  const fe=h.query('#run-fe-label').textContent,round=h.query('#run-rounds').innerHTML;
  h.tick(5000); assert.equal(h.query('#run-elapsed').textContent,'01:10');
  assert.equal(h.query('#run-fe-label').textContent,fe); assert.equal(h.query('#run-rounds').innerHTML,round);
  h.c.renderRun(job({status:'COMPLETED',completed_iterations:50,elapsed_seconds:100}));
  assert.equal(h.timers.size,0); h.tick(5000); assert.equal(h.query('#run-elapsed').textContent,'01:40');
});

test('khởi tạo, pending và dữ liệu cũ không bị bịa vòng hoặc số lần thử',()=>{
  const h=harness(); h.c.renderRun(job({max_iterations:0,iteration_history:[]}));
  assert.match(h.query('#run-iteration').textContent,/khởi tạo/);
  h.c.renderRun(job({status:'PENDING',candidate_attempts:null,iteration_history:[]}));
  assert.equal(h.timers.size,0); assert.equal(h.query('#run-attempts').textContent,'—');
  assert.match(h.query('#run-rounds').innerHTML,/Chưa có/);
});

test('poll không chồng request và không ghi phản hồi của phiên cũ',async()=>{
  const h=harness(); let resolve; h.c.apiJson=()=>new Promise(r=>{resolve=r});
  const pending=h.c.pollJob('run-8');
  vm.runInContext('state.pollVersion+=1',h.c);
  resolve(job()); await pending;
  assert.equal(h.query('#run-status').textContent,''); assert.equal(h.timers.size,0);
});

test('poll lỗi lần đầu không khởi động vòng polling vô tận',async()=>{
  const h=harness(); h.c.apiJson=async()=>{throw Error('network')};
  await h.c.pollJob('run-8'); assert.equal(h.timers.size,0);
  assert.equal(h.query('#run-error').textContent,'network');
});
