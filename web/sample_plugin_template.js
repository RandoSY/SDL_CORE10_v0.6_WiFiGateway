/* Example add-on: optional synthetic pulse source. Include between comms.js and app.js */
window.SDLComms.register({
  id:'pulse-demo',
  name:'Plug-in example · pulse',
  description:'Demonstrates a new adapter adding itself without any dashboard changes.',
  fields:[{key:'hz',label:'Signal frequency (Hz)',default:'2'}],
  create(ctx,config){let timer=null,n=0;return {
    async connect(){ctx.onStatus('Sample plugin connected')},
    async disconnect(){this.stop();ctx.onStatus('Sample plugin disconnected')},
    start(){this.stop();n=0;let hz=Math.max(.1,Number(config.hz)||2);timer=setInterval(()=>{let t=n++*.025;ctx.onSample({x:t,y:Math.sin(2*Math.PI*hz*t)})},25)},
    stop(){if(timer)clearInterval(timer);timer=null}
  }}
});
