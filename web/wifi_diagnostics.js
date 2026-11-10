(function(){'use strict';
 const $=id=>document.getElementById(id);
 const num=(value,unit='',digits=1)=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits)+unit:'—';
 let lastMetrics=null, delivery=null;
 function show(){let m=lastMetrics;if(!m)return;
  const connected=m.connected===true;
  const dropped=delivery?.dropped_samples||0;
  const warning=m.logging_ok===false||dropped>0;
  $('diag-status').textContent=connected?(warning?'CONNECTED · CHECK WARNINGS':'CONNECTED · '+(m.node||'NODE')):'NODE DISCONNECTED';
  $('diag-status').className='diag-status '+(connected&&!warning?'healthy':'offline');
  $('diag-health').textContent=connected?num(m.app_link_health_score,'/100',0):'0/100';
  $('diag-rate').textContent=num(m.data_rate_samples_s,'',1);
  $('diag-throughput').textContent=num(m.throughput_kbit_s,' kb/s',2);
  $('diag-rtt').textContent=num(m.rtt_ms,' ms',2);
  $('diag-lag').textContent=num(m.estimated_upstream_lag_ms,' ms',2);
  $('diag-loss').textContent=Number.isFinite(m.missing_samples)?String(m.missing_samples):'—';
  $('diag-integrity').textContent=(m.crc_errors??'—')+' / '+(m.duplicate_samples??'—');
  $('diag-reconnect').textContent=String(m.reconnects??'—');
  const notes=[
   'Node '+m.node, m.samples_total+' accepted samples', 'age '+num(m.last_sample_age_s,' s',2),
   'RTT p95 '+num(m.rtt_p95_ms,' ms',2), 'upstream lag p95 '+num(m.estimated_upstream_p95_ms,' ms',2),
   'clock uncertainty ±'+num(m.clock_uncertainty_ms,' ms',2),
   'dashboard delivery '+num(m.ws_delivery_age_ms,' ms',1), 'upstream integrity '+num(m.integrity_pct,'%',2),
   'browser clients '+m.clients,
   'this browser dropped '+dropped+' samples / '+(delivery?.dropped_messages||0)+' messages',
   'node timeouts '+(m.node_timeouts||0),
   m.logging_ok===false?'LOGGING FAILED: '+m.last_log_error:'logging '+(m.logging_ok===true?'OK':'unknown')
  ];
  if(m.log_errors)notes.push(m.log_errors+' log errors this session; last: '+m.last_log_error);
  if(m.last_device_error)notes.push('last node error: '+m.last_device_error);
  $('diag-detail').textContent=notes.join(' · ');
 }
 window.addEventListener('sdl:metrics',e=>{lastMetrics=e.detail;show()});
 window.addEventListener('sdl:delivery',e=>{delivery=e.detail;show()});
 window.addEventListener('sdl:offline',()=>{$('diag-status').textContent='OFFLINE';$('diag-status').className='diag-status offline';});
 window.addEventListener('sdl:samplemeta',e=>{const msg=e.detail;if(msg?.payload?.simulated){$('live-trace-note').textContent='LIVE Python Gateway · SYNTHETIC TCP NODE · no physical sensor';}else $('live-trace-note').textContent='LIVE Python Gateway · TCP node readings (hardware provenance not independently verified)';});
})();
