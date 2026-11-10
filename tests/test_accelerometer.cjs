const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

function monitor(){
 const elements=new Map(),sockets=[];
 const get=id=>{
  if(!elements.has(id))elements.set(id,{textContent:'',className:'',getBoundingClientRect:()=>({width:0,height:0}),click(){}});
  return elements.get(id);
 };
 class WebSocket{
  static OPEN=1;
  constructor(){this.readyState=1;sockets.push(this)}
  message(m){this.onmessage({data:JSON.stringify(m)})}
 }
 let exported;
 const window={addEventListener(){}};
 const context=vm.createContext({window,document:{getElementById:get,createElement:()=>({click(){}})},WebSocket,
  location:{protocol:'http:',host:'127.0.0.1:8799'},setInterval(){},setTimeout(){},Blob,
  URL:{createObjectURL(blob){exported=blob;return 'blob:test'},revokeObjectURL(){}}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/accelerometer.js'),'utf8'),context);
 const socket=sockets[0];socket.onopen();
 socket.message({type:'sdl.metrics',payload:{connected:true,node:'atom-matrix-imu',logging_ok:true,data_rate_samples_s:50,nominal_interval_ms:20}});
 return {get,socket,api:window.SDLAccelerometer,exported:()=>exported};
}
const point=(x,y=1010,extra={})=>({x,y,seq:Math.round(x/20),node_id:'atom-matrix-imu',boot_id:'a',simulated:false,unit:'mg',channel:'acceleration_magnitude',...extra});

test('physical data retains milliseconds/mg and drives stationary check',()=>{
 const m=monitor();
 for(let i=1;i<=11;i++)m.socket.message({type:'sdl.sample',payload:point(i*500)});
 m.api.refresh();
 assert.equal(m.api.getState().points.length,11);
 assert.equal(m.api.getState().points[0].device_ms,500);
 assert.equal(m.api.getState().points[0].magnitude_mg,1010);
 assert.match(m.get('rest').textContent,/REST CHECK OK/);
 assert.match(m.get('identity').textContent,/5500 ms/);
 m.socket.message({type:'sdl.sample',payload:point(6000,1500)});
 m.api.refresh();
 assert.match(m.get('rest').textContent,/MOTION/);
});
test('synthetic or wrongly labelled values never enter the physical capture',()=>{
 const m=monitor();
 for(const extra of [{simulated:true},{unit:'g'},{channel:'mass'}])m.socket.message({type:'sdl.sample',payload:point(500,1010,extra)});
 assert.equal(m.api.getState().points.length,0);
 assert.match(m.get('notice').textContent,/Source rejected/);
});
test('CSV/JSON exports preserve raw data, identity and delivery warnings',async()=>{
 const m=monitor();
 m.socket.message({type:'sdl.sample',delivery:{dropped_samples:2},payload:point(500)});
 m.get('json').onclick();
 const data=JSON.parse(await m.exported().text());
 assert.equal(data.unit,'mg');assert.equal(data.time_unit,'ms');assert.equal(data.browser_dropped_samples,2);
 assert.equal(data.samples[0].simulated,false);assert.equal(data.samples[0].node_id,'atom-matrix-imu');
 m.get('csv').onclick();
 const csv=await m.exported().text();
 assert.match(csv,/device_ms,magnitude_mg/);assert.match(csv,/"500","1010"/);
});
test('pause and restarts retain previous rows in separate plot segments',()=>{
 const m=monitor();
 m.socket.message({type:'sdl.sample',payload:point(500)});
 m.get('pause').onclick();
 m.socket.message({type:'sdl.sample',payload:point(1000)});
 assert.equal(m.api.getState().points.length,1);
 m.get('pause').onclick();
 m.socket.message({type:'sdl.sample',payload:point(1500)});
 m.socket.message({type:'sdl.sample',payload:point(500,1000,{boot_id:'b'})});
 const rows=m.api.getState().points;
 assert.equal(rows.length,3);assert.notEqual(rows[0].segment,rows[1].segment);assert.notEqual(rows[1].segment,rows[2].segment);
 m.get('clear').onclick();assert.equal(m.api.getState().points.length,0);
});
test('50 Hz capture retains every sample while rest check waits five seconds',()=>{
 const m=monitor();
 for(let i=1;i<=100;i++)m.socket.message({type:'sdl.sample',payload:point(i*20)});
 m.api.refresh();
 assert.equal(m.api.getState().points.length,100);
 assert.match(m.get('rest').textContent,/Collecting/);
 for(let i=101;i<=251;i++)m.socket.message({type:'sdl.sample',payload:point(i*20)});
 m.api.refresh();
 assert.equal(m.api.getState().points.length,251);
 assert.match(m.get('rest').textContent,/REST CHECK OK/);
});
test('capture buffer evictions are counted rather than silently discarded',()=>{
 const m=monitor();
 for(let i=1;i<=4200;i++)m.socket.message({type:'sdl.sample',payload:point(i*20)});
 assert.equal(m.api.getState().points.length,4096);
 assert.equal(m.api.getState().retainedOut,104);
 assert.equal(m.api.metadata().evicted_samples,104);
});
