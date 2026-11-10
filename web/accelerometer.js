(function(){'use strict';
 const $=id=>document.getElementById(id), MAX=4096;
 let points=[],recording=true,metrics=null,socket=null,lastSample=null,retainedOut=0;
 let dropped=0,runDropped=0,lastDelivery=0,boot=null,segment=0,runStarted=new Date().toISOString();
 let message='Waiting for the gateway. Synthetic or incompatible sources will not be plotted.',lastView=0;
 const number=(v,d=1)=>Number.isFinite(v)?v.toFixed(d):'—';
 function note(text){message=text;$('notice').textContent=text}
 function redraw(){
  const canvas=$('plot'),box=canvas.getBoundingClientRect();
  if(box.width<1)return;
  const ratio=Math.min(window.devicePixelRatio||1,2),w=box.width,h=box.height;
  canvas.width=Math.round(w*ratio);canvas.height=Math.round(h*ratio);
  const c=canvas.getContext('2d');c.scale(ratio,ratio);c.clearRect(0,0,w,h);
  const end=points.at(-1)?.device_ms||0;
  const data=points.filter(p=>p.segment===segment&&p.device_ms>=end-60000);
  const left=64,top=18,pw=w-left-18,ph=h-top-44;
  const first=data[0]?.device_ms||0;
  let span=Math.max(1000,(data.at(-1)?.device_ms||first)-first);
  let low=800,high=1200;
  for(const p of data){low=Math.min(low,p.magnitude_mg-40);high=Math.max(high,p.magnitude_mg+40)}
  const x=p=>left+(p.device_ms-first)/span*pw,y=v=>top+(high-v)/(high-low)*ph;
  c.font='11px system-ui';c.lineWidth=1;
  for(let i=0;i<=4;i++){
   const xx=left+i*pw/4,yy=top+i*ph/4;
   c.strokeStyle='#e1eaf1';c.beginPath();c.moveTo(left,yy);c.lineTo(left+pw,yy);c.moveTo(xx,top);c.lineTo(xx,top+ph);c.stroke();
   c.fillStyle='#667e92';c.textAlign='right';c.fillText(number(high-i*(high-low)/4,0),left-9,yy+4);
   c.textAlign='center';c.fillText(number(i*span/4,0),xx,top+ph+17);
  }
  c.strokeStyle='#269177';c.setLineDash([5,5]);c.beginPath();c.moveTo(left,y(1000));c.lineTo(left+pw,y(1000));c.stroke();c.setLineDash([]);
  c.strokeStyle='#1678be';c.fillStyle='#1678be';c.lineWidth=2;c.beginPath();
  data.forEach((p,i)=>{if(i)c.lineTo(x(p),y(p.magnitude_mg));else c.moveTo(x(p),y(p.magnitude_mg))});c.stroke();
  for(const p of data){c.beginPath();c.arc(x(p),y(p.magnitude_mg),2,0,2*Math.PI);c.fill()}
  c.fillStyle='#425f77';c.textAlign='center';c.fillText('Elapsed time (ms)',left+pw/2,h-4);
  c.save();c.translate(14,top+ph/2);c.rotate(-Math.PI/2);c.fillText('Magnitude (mg)',0,0);c.restore();
 }
 function status(){
  if(lastSample){$('magnitude').textContent=number(lastSample.magnitude_mg,0)+' mg';$('identity').textContent=number(lastSample.device_ms,0)+' ms / '+lastSample.seq}
  const connected=socket?.readyState===WebSocket.OPEN&&metrics?.connected===true;
  const stale=!lastSample||Date.now()-lastSample.received_ms>3000;
  const bad=dropped>0||metrics?.logging_ok===false;
  $('connection').textContent=connected?(stale?'CONNECTED · WAITING / STALE':bad?'CONNECTED · CHECK WARNINGS':'LIVE · PHYSICAL NODE'):'GATEWAY / NODE OFFLINE';
  $('connection').className='badge '+(connected&&!stale&&!bad?'ok':'warn');
  $('rate').textContent=number(metrics?.data_rate_samples_s)+' Hz';
  $('rtt').textContent=number(metrics?.rtt_ms,2)+' ms';
  $('node').textContent=metrics?.node||'—';
  $('errors').textContent=(metrics?.crc_errors??'—')+' / '+(metrics?.parse_errors??'—');
  $('integrity').textContent=(metrics?.missing_samples??'—')+' / '+(metrics?.duplicate_samples??'—')+' / '+(metrics?.out_of_order??'—');
  $('delivery').textContent=dropped+' samples this connection; '+runDropped+' reported during capture';
  $('logging').textContent=metrics?.logging_ok===true?'OK':metrics?.logging_ok===false?'ERROR: '+metrics.last_log_error:'—';
  $('radio').textContent=number(metrics?.rssi_dbm,0)+' dBm / '+(metrics?.reconnects??'—');
  $('count').textContent=String(points.length);
  $('capture-state').textContent=(recording?'Recording':'Paused')+' · '+retainedOut+' older samples evicted';
  const current=points.filter(p=>p.segment===segment),end=current.at(-1)?.device_ms||0;
  const recent=current.filter(p=>p.device_ms>=end-5000),duration=current.length?end-current[0].device_ms:0;
  if(!connected||stale)$('rest').textContent='Waiting for fresh physical samples';
  else if(!recording)$('rest').textContent='Capture paused';
  else if(recent.length<10||duration<5000)$('rest').textContent='Collecting '+number(Math.min(duration,5000)/1000,1)+' / 5 seconds';
  else{
   const mean=recent.reduce((s,p)=>s+p.magnitude_mg,0)/recent.length;
   const sd=Math.sqrt(recent.reduce((s,p)=>s+(p.magnitude_mg-mean)**2,0)/(recent.length-1));
   const ok=recent.every(p=>p.magnitude_mg>=900&&p.magnitude_mg<=1100)&&sd<=20;
   $('rest').textContent=(ok?'REST CHECK OK':'MOTION / OUTSIDE REST BAND')+' · mean '+number(mean)+' mg · SD '+number(sd)+' mg';
  }
 }
 function renderView(force=false){
  const now=Date.now();
  if(!force&&now-lastView<100)return; // Capture every sample; paint at most 10 times/second.
  lastView=now;status();redraw();
 }
 function sample(p){
  if(p.simulated!==false||p.channel!=='acceleration_magnitude'||p.unit!=='mg'||!Number.isFinite(p.x)||!Number.isFinite(p.y)||!Number.isSafeInteger(p.seq)){
   note('Source rejected: this monitor requires physical acceleration_magnitude samples in mg.');return;
  }
  const restarted=boot!==null&&p.boot_id!==boot;
  if(restarted){segment++;note('Node restarted: a new graph segment has begun. Earlier capture rows remain available for export.')}
  boot=p.boot_id;
  lastSample={device_ms:p.x,magnitude_mg:p.y,seq:p.seq,node_id:p.node_id,boot_id:p.boot_id,
   simulated:false,segment,received_ms:Date.now()};
  if(recording){points.push(lastSample);if(points.length>MAX){points.shift();retainedOut++}}
  renderView();
 }
 function connect(){
  socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/telemetry');
  socket.onopen=()=>{metrics=null;lastSample=null;lastDelivery=0;dropped=0;note('Connected to the gateway. Waiting for physical acceleration samples.');status()};
  socket.onmessage=event=>{
   try{
    const m=JSON.parse(event.data),lost=m.delivery?.dropped_samples;
    if(Number.isSafeInteger(lost)&&lost>=0){if(recording)runDropped+=Math.max(0,lost-lastDelivery);lastDelivery=dropped=lost}
    if(m.type==='sdl.metrics'){const was=metrics?.connected;metrics=m.payload;if(was===true&&!metrics.connected)segment++;status()}
    else if(m.type==='sdl.hello'&&m.payload.mode!=='EXTERNAL')note('Synthetic gateway detected. Switch this instance to the physical ATOM.');
    else if(m.type==='sdl.sample'){
     if(message.startsWith('Connected to'))note('Live physical magnitude · raw device timestamps in ms · capture/export uses mg.');
     sample(m.payload);
    }
   }catch(error){note('Invalid gateway message: '+error.message)}
  };
  socket.onclose=()=>{metrics=null;lastSample=null;segment++;note('Gateway connection lost. Retrying in 2 seconds; capture rows are retained.');status();setTimeout(connect,2000)};
  socket.onerror=()=>note('Gateway unavailable. Start START_ACCELEROMETER.bat.');
 }
 function download(name,text,type){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([text],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
 function metadata(){return {experiment:'atom_accelerometer',started:runStarted,unit:'mg',time_unit:'ms',browser_dropped_samples:runDropped,evicted_samples:retainedOut,check:'Latest 5 seconds: 900..1100 mg, SD <=20 mg; functional check only',samples:points}}
 $('pause').onclick=()=>{recording=!recording;$('pause').textContent=recording?'Pause capture':'Resume capture';if(recording)segment++;status()};
 $('clear').onclick=()=>{points=[];retainedOut=runDropped=0;recording=true;$('pause').textContent='Pause capture';segment++;runStarted=new Date().toISOString();note('New capture started. Gateway acquisition continues.');status();redraw()};
 $('csv').onclick=()=>{const columns=['device_ms','magnitude_mg','seq','node_id','boot_id','simulated','segment','received_ms'];const quote=v=>'"'+String(v??'').replaceAll('"','""')+'"';download('ATOM_accelerometer.csv',[columns.join(',')+',browser_dropped_samples,evicted_samples',...points.map(p=>columns.map(k=>quote(p[k])).join(',')+','+runDropped+','+retainedOut)].join('\n'),'text/csv')};
 $('json').onclick=()=>download('ATOM_accelerometer.json',JSON.stringify(metadata(),null,2),'application/json');
 window.addEventListener('resize',redraw);setInterval(status,1000);connect();redraw();
 window.SDLAccelerometer={sample,getState:()=>({recording,points:[...points],metrics,runDropped,retainedOut}),metadata,refresh:()=>renderView(true)};
})();
