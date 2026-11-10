/* Reproducible physical-stream measurement. Node 22+, Python + pyserial.
 * node scripts/measure_accelerometer.cjs [firmware-label]
 * node scripts/measure_accelerometer.cjs --history
 */
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const crypto=require('node:crypto');
const root=path.resolve(__dirname,'..'),history=path.join(root,'experiments','atom-performance.jsonl');
if(process.argv.includes('--history')){
 if(fs.existsSync(history))for(const line of fs.readFileSync(history,'utf8').trim().split('\n')){
  const r=JSON.parse(line);console.log(JSON.stringify({at:r.at,label:r.label,kind:r.kind||'timed_sample_measurement',counter_scope:r.counter_scope||'measurement window',
   passed:r.passed,device_hz:r.device_rate_hz,received_hz:r.receiver_rate_hz??r.received_hz_final_window,
   gaps:r.sequence_gaps??r.sequence_gaps_during_deliberate_disconnect,queue_dropped:r.queue_dropped??r.queue_dropped_delta,sampler_skipped:r.sampler_skipped}));
 }
 process.exit(0);
}
function serialStatus(){
 try{return execFileSync('py',['-3','-B','-c','from scripts.check_atom_node import observe_serial; print(observe_serial("COM30",0.4))'],{cwd:root,encoding:'utf8',timeout:5000})}
 catch{return 'USB timing status unavailable'}
}
function counter(text,key){const matches=[...text.matchAll(new RegExp(key+'=(\\d+)','g'))];return matches.length?Number(matches.at(-1)[1]):null}
function delta(before,after,key){const a=counter(before,key),b=counter(after,key);return a===null||b===null?null:b-a}
function store(result){fs.mkdirSync(path.dirname(history),{recursive:true});fs.appendFileSync(history,JSON.stringify(result)+'\n')}
const elements=new Map(),sockets=[],timers=[];
function get(id){if(!elements.has(id))elements.set(id,{textContent:'',className:'',getBoundingClientRect:()=>({width:0,height:0})});return elements.get(id)}
class LiveSocket extends WebSocket{constructor(url){super(url);sockets.push(this)}}
const window={addEventListener(){}};
const context=vm.createContext({window,document:{getElementById:get,createElement:()=>({click(){}})},WebSocket:LiveSocket,
 location:{protocol:'http:',host:'127.0.0.1:8799'},setInterval(fn,ms){const t=setInterval(fn,ms);timers.push(t);return t},setTimeout,Blob,
 URL:{createObjectURL(){return 'blob:test'},revokeObjectURL(){}}});
(async()=>{
 const before=serialStatus(),started=Date.now();let result;
 try{
  vm.runInContext(fs.readFileSync(path.join(root,'web/accelerometer.js'),'utf8'),context);
  await new Promise(resolve=>setTimeout(resolve,15000));
  window.SDLAccelerometer.refresh();
  const state=window.SDLAccelerometer.getState(),rows=state.points,elapsed=(Date.now()-started)/1000;
  const intervals=rows.slice(1).map((p,i)=>p.device_ms-rows[i].device_ms).sort((a,b)=>a-b);
  const gaps=rows.slice(1).reduce((sum,p,i)=>sum+Math.max(0,p.seq-rows[i].seq-1),0);
  const hash=file=>crypto.createHash('sha256').update(fs.readFileSync(path.join(root,file))).digest('hex');
  result={at:new Date().toISOString(),label:process.argv[2]||'current',samples:rows.length,elapsed_s:elapsed,
   node:state.metrics?.node,boot_id:rows[0]?.boot_id,nominal_ms:state.metrics?.nominal_interval_ms,
   device_rate_hz:rows.length>1?(rows.length-1)*1000/(rows.at(-1).device_ms-rows[0].device_ms):0,
   receiver_rate_hz:rows.length/elapsed,rolling_gateway_hz:state.metrics?.data_rate_samples_s,
   median_interval_ms:intervals[Math.floor(intervals.length/2)],p95_interval_ms:intervals[Math.floor(intervals.length*.95)],max_interval_ms:intervals.at(-1),
   sequence_gaps:gaps,browser_dropped_samples:state.runDropped,crc_errors:state.metrics?.crc_errors,parse_errors:state.metrics?.parse_errors,
   rssi_dbm:state.metrics?.rssi_dbm,rtt_ms:state.metrics?.rtt_ms,rest_check:get('rest').textContent,
   source_sha256:hash('arduino/SDL_ATOM_Gateway_Node/SDL_ATOM_Gateway_Node.ino'),binary_sha256:hash('artifacts/atom-bin/SDL_ATOM_Gateway_Node.ino.bin'),
   verification:'Actual physical WebSocket stream processed by monitor JS with DOM substitutes; no graphical rendering claim.'};
 }finally{for(const s of sockets){s.onclose=null;s.close()}for(const t of timers)clearInterval(t)}
 const after=serialStatus();result.serial_before=before;result.serial_after=after;
 result.queue_dropped=delta(before,after,'queue_dropped');result.sampler_skipped=delta(before,after,'sampler_skipped');
 result.passed=result.nominal_ms===20&&result.device_rate_hz>=49&&result.device_rate_hz<=51&&result.receiver_rate_hz>=48
  &&result.sequence_gaps===0&&result.browser_dropped_samples===0&&result.crc_errors===0&&result.parse_errors===0
  &&result.queue_dropped===0&&result.sampler_skipped===0;
 store(result);console.log(JSON.stringify(result,null,2));if(!result.passed)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
