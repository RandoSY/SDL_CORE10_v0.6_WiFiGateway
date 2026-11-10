/* SDL communications plugin host. No firmware assumptions; transports deliver normalized samples. */
(function(){'use strict';const registered=new Map();
 function register(manifest){if(!manifest||typeof manifest.id!=='string'||typeof manifest.create!=='function')throw Error('Plugin needs id and create()');if(registered.has(manifest.id))throw Error('Duplicate adapter: '+manifest.id);registered.set(manifest.id,manifest)}
 function parseFrame(raw, preferred='y'){
   if(raw instanceof ArrayBuffer)raw=new TextDecoder().decode(raw);
   const lines=String(raw).trim().split(/\r?\n/);let result=[];
   for(let line of lines){line=line.trim();if(!line)continue;let p;
     if(line[0]==='{'){try{p=JSON.parse(line)}catch{continue}}
     else if(line.includes(',')){const tokens=line.split(',').map(Number);if(tokens.length>=2&&tokens.slice(0,2).every(Number.isFinite))p={x:tokens[0],y:tokens[1]}}
     else if(Number.isFinite(Number(line)))p={y:Number(line)};
     if(!p||typeof p!=='object')continue;
     let field=p[preferred]!==undefined?preferred:['y','value','temperature_c','mass_g','pressure_kpa','accel_g','distance_mm','voltage_v','absorbance','field_ut'].find(k=>p[k]!==undefined);
     let y=Number(p[field]);if(!Number.isFinite(y))continue;
     let x=p.x!==undefined?Number(p.x):p.t_ms!==undefined?Number(p.t_ms)/1000:p.t_s!==undefined?Number(p.t_s):p.t!==undefined?Number(p.t):null;
     result.push({x:Number.isFinite(x)?x:null,y,unit:p.unit||null,channel:p.channel||field,device:p.device||null})
   }return result
 }
 register({id:'sim',name:'Simulation / replay',description:'Local generated data. Works offline in every modern browser; no hardware connection.',fields:[],create(ctx,config={}){let timer=null,count=0;return {async connect(){ctx.onStatus('Simulator ready')},async disconnect(){this.stop()},start(){this.stop();count=0;timer=setInterval(()=>{const p=ctx.nextDemoSample(count++);if(p)ctx.onSample(p);else{this.stop();ctx.onStatus('Demo replay complete')}},Math.max(10,Number(config.interval_ms)||35));ctx.onStatus('Demo acquisition running')},stop(){if(timer){clearInterval(timer);timer=null}}}}});
 register({id:'ws',name:'WebSocket LAN',description:'Receive newline-delimited JSON, CSV or numeric frames from an ESP32/ATOM bridge over ws:// or wss://. Endpoint and message schema must match deployed firmware.',fields:[{key:'url',label:'WebSocket URL',default:'ws://192.168.0.125/ws'}],create(ctx,config){let ws=null;return {async connect(){return await new Promise((resolve,reject)=>{try{ws=new WebSocket(config.url);ws.onopen=()=>{ctx.onStatus('WebSocket connected');resolve()};ws.onmessage=e=>ctx.ingest(e.data);ws.onerror=()=>ctx.onStatus('WebSocket error — check endpoint or firewall');ws.onclose=()=>ctx.onStatus('WebSocket closed');setTimeout(()=>{if(ws&&ws.readyState===WebSocket.CONNECTING){ws.close();reject(Error('WebSocket connection timed out'))}},5000)}catch(e){reject(e)}})},async disconnect(){if(ws)ws.close();ws=null},start(){ctx.onStatus('Listening for WebSocket frames')},stop(){ctx.onStatus('WebSocket connected (paused locally)')}}}});
 register({id:'serial',name:'USB Web Serial',description:'Receive 115200 baud (configurable) lines. Requires a Chromium-compatible secure context and a device that emits numeric/CSV/JSON text.',fields:[{key:'baud',label:'Baud rate',default:'115200'}],create(ctx,config){let port=null,reader=null,active=false;return {async connect(){if(!('serial'in navigator))throw Error('Web Serial unavailable in this browser. Use Chrome/Edge on localhost.');port=await navigator.serial.requestPort();await port.open({baudRate:Number(config.baud)||115200});active=true;ctx.onStatus('USB Serial connected');(async()=>{const decoder=new TextDecoder();let pending='';try{while(active&&port?.readable){reader=port.readable.getReader();try{while(active){const {value,done}=await reader.read();if(done)break;if(!value)continue;pending+=decoder.decode(value,{stream:true});const lines=pending.split(/\r?\n/);pending=lines.pop()||'';for(const ln of lines)ctx.ingest(ln)}}finally{reader.releaseLock();reader=null}}}catch(e){if(active)ctx.onError('Serial read: '+e.message)}})()},async disconnect(){active=false;try{if(reader)await reader.cancel()}catch{}try{if(port)await port.close()}catch{}port=null;ctx.onStatus('Serial disconnected')},start(){ctx.onStatus('Listening for USB serial samples')},stop(){ctx.onStatus('Serial source paused locally')}}}});
 register({id:'ble',name:'Bluetooth NUS (BLE)',description:'BLE Nordic UART Service notifications. Only compatible firmware; browser requires Web Bluetooth permission and a secure context.',fields:[],create(ctx){const svc='6e400001-b5a3-f393-e0a9-e50e24dcca9e',tx='6e400003-b5a3-f393-e0a9-e50e24dcca9e';let device=null,char=null,listener=null;return {async connect(){if(!('bluetooth'in navigator))throw Error('Web Bluetooth unavailable. Use Chrome/Edge on localhost/HTTPS.');device=await navigator.bluetooth.requestDevice({acceptAllDevices:true,optionalServices:[svc]});const server=await device.gatt.connect(),service=await server.getPrimaryService(svc);char=await service.getCharacteristic(tx);let pending='';listener=e=>{pending+=new TextDecoder().decode(e.target.value);let lines=pending.split(/\r?\n/);pending=lines.pop()||'';for(let ln of lines)ctx.ingest(ln)};char.addEventListener('characteristicvaluechanged',listener);await char.startNotifications();ctx.onStatus('Bluetooth NUS connected: '+(device.name||'device'))},async disconnect(){if(char&&listener){try{await char.stopNotifications()}catch{}char.removeEventListener('characteristicvaluechanged',listener)}if(device?.gatt?.connected)device.gatt.disconnect();char=null;device=null;ctx.onStatus('Bluetooth disconnected')},start(){ctx.onStatus('Listening for BLE NUS notifications')},stop(){ctx.onStatus('BLE source paused locally')}}}});

 register({id:'gateway',name:'Python SDL Wi-Fi Gateway · live',description:'Working Python WebSocket bridge on port 8788. Live telemetry, link integrity, throughput and lag; independent demo node or compatible SDL-NDJSON/1 firmware.',fields:[{key:'url',label:'Gateway WebSocket',default:'ws://127.0.0.1:8788/ws/telemetry'}],create(ctx,config){
   let ws=null,active=false,connected=false,lastDroppedSamples=0;
   function announce(status){ctx.onStatus(status)}
   function cmd(name,params={}){if(ws?.readyState===WebSocket.OPEN)ws.send(JSON.stringify({type:'sdl.command',command:name,...params}));}
   return {async connect(){await new Promise((resolve,reject)=>{let done=false;try{
     lastDroppedSamples=0;
     ws=new WebSocket(config.url);ws.onopen=()=>{done=true;connected=true;announce('Python Gateway connected · waiting for live acquisition');resolve()};
     ws.onmessage=e=>{try{let msg=JSON.parse(e.data);
       if(msg.delivery){
         const dropped=msg.delivery.dropped_samples;
         if(Number.isSafeInteger(dropped)&&dropped>=0){
           const delta=Math.max(0,dropped-lastDroppedSamples);
           lastDroppedSamples=dropped;
           if(active&&delta)ctx.onDeliveryLoss?.(delta);
         }
         window.dispatchEvent(new CustomEvent('sdl:delivery',{detail:msg.delivery}));
       }
       if(msg.type==='sdl.metrics'){window.dispatchEvent(new CustomEvent('sdl:metrics',{detail:{...msg.payload,ws_delivery_age_ms:Math.max(0,Date.now()-(msg.sent_unix_ms||Date.now()))}}));return;}
       if(msg.type==='sdl.hello'){window.dispatchEvent(new CustomEvent('sdl:hello',{detail:msg.payload}));return}
       if(msg.type==='sdl.sample'){window.dispatchEvent(new CustomEvent('sdl:samplemeta',{detail:msg}));if(active)ctx.ingest(JSON.stringify(msg.payload));return}
       if(msg.type==='sdl.ack'||msg.type==='sdl.command_result'){window.dispatchEvent(new CustomEvent('sdl:command',{detail:msg}));return}
       if(msg.type==='sdl.error'){announce(msg.message||'Gateway command rejected');return}
     }catch(err){announce('Invalid Gateway message: '+err.message)}};
     ws.onerror=()=>{announce('Python Gateway unavailable: run START_DEMO.bat');if(!done){done=true;reject(Error('Gateway WebSocket unavailable'))}};
     ws.onclose=()=>{connected=false;active=false;window.dispatchEvent(new CustomEvent('sdl:offline'));announce('Python Gateway disconnected');};
     setTimeout(()=>{if(!done){done=true;ws?.close();reject(Error('Gateway connection timeout'))}},5000)
   }catch(e){reject(e)}})},
   async disconnect(){active=false;connected=false;ws?.close();ws=null;window.dispatchEvent(new CustomEvent('sdl:offline'))},
   start(){active=true;announce('Receiving live Python Gateway samples')},stop(){active=false;announce('Gateway connected; graph capture paused')},
   selectExperiment(experiment){cmd('select_experiment',{experiment})}
 }}});
 window.SDLComms={register,all:()=>Array.from(registered.values()),get:id=>registered.get(id),parseFrame};
})();
