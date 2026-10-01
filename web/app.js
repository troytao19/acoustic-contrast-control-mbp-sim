'use strict';
const $=id=>document.getElementById(id),token=document.querySelector('meta[name="acc-token"]').content;
let scene,solution=null,hardware=null,dataset={records:[],validations:[],feedback:[]},zone='bright',variant='optimized',plane='xz',dirty=true,busy=false,serial=0,solveTimer=null;
let ctxAudio=null,micStream=null,meter=null,micSource=null,micReadings=[],measuring=false,cancelled=false,micIdentity='',pointIndex=0,playTimer=null;
let camera={az:-.65,el:.36,zoom:1},sliceBox=null;
const colors={bright:'#8de1c3',dark:'#ffb16d'},axes=['x','y','z'];
async function api(path,body){const r=await fetch('/api/'+path,{method:'POST',headers:{'Content-Type':'application/json','X-ACC-Token':token},body:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d;}
function status(text,kind=''){ $('status').textContent=text;$('status').className=kind; }
function clone(x){return JSON.parse(JSON.stringify(x));}
function vectorInputs(id,values,change,step=.01){const root=$(id);root.replaceChildren();values.forEach((v,i)=>{const input=document.createElement('input');input.type='number';input.step=step;input.value=v;input.setAttribute('aria-label',id+' '+(axes[i]||i));input.addEventListener('change',()=>change(i,Number(input.value)));root.append(input);});}
function markDirty(){dirty=true;serial++;try{localStorage.setItem('macbook-acc-scene',JSON.stringify(scene));}catch{}if(typeof invalidateBand==='function')invalidateBand();$('contrast').textContent='—';$('trainingContrast').textContent='—';$('actualContrast').textContent='Unverified';$('actualDetails').textContent='Current scene is not yet solved';$('play').disabled=true;api('stop',{}).catch(()=>{});$('play').textContent='▶ Play';status('Scene changed · recalculating…');clearTimeout(solveTimer);solveTimer=setTimeout(solve,200);draw();}
function syncZones(){const z=scene[zone];$('selectBright').classList.toggle('active',zone==='bright');$('selectDark').classList.toggle('active',zone==='dark');$('zoneTitle').textContent=(zone==='bright'?'Bright':'Dark')+' center / m';vectorInputs('zoneCenter',z.center,(i,v)=>{z.center[i]=v;markDirty();});vectorInputs('zoneSize',z.size,(i,v)=>{z.size[i]=v;markDirty();});}
function syncUI(){
  ['frequency','temperature','order','directivity','regularization','spacing','mode','session'].forEach(id=>$(id).value=scene[id]);$('frequencySlider').value=scene.frequency;$('sliceHeight').value=scene.slice_z;
  vectorInputs('laptopInputs',scene.laptop,(i,v)=>{scene.laptop[i]=v;markDirty();});
  vectorInputs('angleInputs',[scene.yaw,scene.pitch,scene.roll],(i,v)=>{scene[['yaw','pitch','roll'][i]]=v;markDirty();},1);
  vectorInputs('roomInputs',scene.room,(i,v)=>{scene.room[i]=v;markDirty();},.1);
  vectorInputs('reflectionInputs',scene.reflection,(i,v)=>{scene.reflection[i]=v;markDirty();},.05);
  $('deskEnabled').checked=scene.desk.enabled;$('deskFields').hidden=!scene.desk.enabled;
  ['height','width','depth','reflection'].forEach(k=>$('desk'+k[0].toUpperCase()+k.slice(1)).value=scene.desk[k]);
  vectorInputs('deskCenter',scene.desk.center,(i,v)=>{scene.desk.center[i]=v;markDirty();},.1);
  syncZones();
}
async function solve(){
  if(measuring)return;
  if(busy){clearTimeout(solveTimer);solveTimer=setTimeout(solve,150);return;}
  const version=serial;busy=true;$('solve').disabled=true;
  try{const result=await api('solve',{config:scene});if(version!==serial)return;solution=result;scene=result.config;dirty=false;renderResults();status('Ready · '+scene.frequency+' Hz · '+(scene.mode==='model'?'approximate model':'measured-point optimization'),'success');}
  catch(e){status(e.message,'error');dirty=true;$('play').disabled=true;}
  finally{busy=false;$('solve').disabled=false;draw();}
}
const fmt=(n,d=1)=>Number(n).toFixed(d);
function renderResults(){
  const s=solution;if(s.hardware){hardware.selected_output=s.hardware.id;const muted=s.hardware.muted||s.hardware.volume_scalar?.[0]===0;$('hardwareBadge').textContent=muted?'CORE AUDIO · MUTED':'CORE AUDIO · 2 CH';$('hardwareBadge').classList.toggle('error',muted);$('routeLabel').textContent=muted?'System speakers muted: set volume, then Optimize contrast':'Native AUHAL → '+s.hardware.name;}$('contrast').textContent=fmt(s.model_validation.contrast_db)+' dB';$('baselineMetric').textContent='Equal drive '+fmt(s.model_baseline.contrast_db)+' dB';$('trainingContrast').textContent=fmt(s.training.contrast_db)+' dB';$('trainingMode').textContent=scene.mode==='measured'?'Accepted measured training points':'Model samples · independent finer-grid check';
  renderActual(s.actual_validation);$('warnings').replaceChildren();s.warnings.forEach(w=>{const li=document.createElement('li');li.textContent=w;$('warnings').append(li);});
  $('play').disabled=!hardware?.selected_output||dirty;$('weights').replaceChildren();s.weights.forEach((w,i)=>{const item=document.createElement('span');const amp=Math.hypot(...w),phase=Math.atan2(w[1],w[0])*180/Math.PI;item.textContent=(i?'R':'L')+'  amplitude '+fmt(amp,3)+'  /  phase '+fmt(phase)+'°';$('weights').append(item);});const deltas=document.createElement('span');deltas.textContent='Model vs equal drive: bright '+fmt(10*Math.log10(Math.max(s.model_validation.bright_power,1e-30)/Math.max(s.model_baseline.bright_power,1e-30)))+' dB / dark '+fmt(10*Math.log10(Math.max(s.model_validation.dark_power,1e-30)/Math.max(s.model_baseline.dark_power,1e-30)))+' dB';$('weights').append(deltas);renderRecords();if(typeof updateBandMetrics==='function')updateBandMetrics();
}
function renderActual(a){
  if(a?.optimized_db!==undefined){$('actualContrast').textContent=fmt(a.optimized_db)+' dB';$('actualDetails').textContent=`${a.verified?'Sampled verification':'Preliminary'} · B/D ${a.counts.join('/')} points · improvement ${fmt(a.improvement_db)} dB`;}
  else{$('actualContrast').textContent='Unverified';$('actualDetails').textContent='Measure held-out positions in both zones';}
}
function renderRecords(){
  const sig=solution?.signature;const rows=dataset.records.filter(r=>r.signature===sig);let counts={train:[0,0],holdout:[0,0]};
  for(const r of rows){['bright','dark'].forEach((z,i)=>{if(inside(r.position,scene[z]))counts[r.role][i]++;});}
  const held=solution?.measured_holdout;const heldText=held?' Held-out transfer prediction: '+fmt(held.optimized.contrast_db)+' dB (not an actual playback test).':'';
  $('recordSummary').textContent=`This setup: ${counts.train[0]} bright / ${counts.train[1]} dark training records; ${counts.holdout[0]} bright / ${counts.holdout[1]} dark transfer holdouts. ${dataset.validations.length} saved A/B records across sessions. ${dataset.records.length} total calibration records. Repeated coordinates count once in the optimizer.`+heldText;
}
function inside(p,z){return p.every((v,i)=>Math.abs(v-z.center[i])<=z.size[i]/2+1e-8);}
function rotation(){const a=scene.yaw*Math.PI/180,b=scene.pitch*Math.PI/180,c=scene.roll*Math.PI/180;const ca=Math.cos(a),sa=Math.sin(a),cb=Math.cos(b),sb=Math.sin(b),cc=Math.cos(c),sc=Math.sin(c);return [[ca*cb,ca*sb*sc-sa*cc,ca*sb*cc+sa*sc],[sa*cb,sa*sb*sc+ca*cc,sa*sb*cc-ca*sc],[-sb,cb*sc,cb*cc]];}
function localToWorld(p){const r=rotation();return r.map((row,i)=>scene.laptop[i]+row.reduce((s,v,j)=>s+v*p[j],0));}
function setupCanvas(canvas){const dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;if(canvas.width!==Math.round(w*dpr)||canvas.height!==Math.round(h*dpr)){canvas.width=Math.round(w*dpr);canvas.height=Math.round(h*dpr);}const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);return {ctx,w,h};}
function rgb(db){const stops=[[22,45,84],[40,105,134],[82,191,186],[217,219,125],[239,149,100]],v=Math.max(0,Math.min(.9999,(db+50)/50))*4,i=Math.floor(v),t=v-i;return stops[i].map((a,j)=>Math.round(a*(1-t)+stops[i+1][j]*t));}
function boxCorners(center,size){return Array.from({length:8},(_,i)=>center.map((v,j)=>v+((i>>j)&1?.5:-.5)*size[j]));}
const edges=[[0,1],[0,2],[0,4],[1,3],[1,5],[2,3],[2,6],[3,7],[4,5],[4,6],[5,7],[6,7]];
function drawSpace(){
  if(!scene)return;const {ctx,w,h}=setupCanvas($('space'));const focus=scene.laptop,scale=Math.min(w,h)/scene.view_span*.85*camera.zoom;
  function proj(p){let x=p[0]-focus[0],y=p[1]-focus[1],z=p[2]-focus[2];const ca=Math.cos(camera.az),sa=Math.sin(camera.az),ce=Math.cos(camera.el),se=Math.sin(camera.el);let u=ca*x-sa*y,d=sa*x+ca*y;return [w/2+u*scale,h*.56-(z*ce-d*se)*scale,d*ce+z*se];}
  function line(a,b,color,width=1){const p=proj(a),q=proj(b);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();}
  function box(c,size,color,fill=false){const corners=boxCorners(c,size);if(fill){const path=[0,1,3,2].map(i=>proj(corners[i]));ctx.fillStyle=color+'18';ctx.beginPath();path.forEach((p,i)=>i?ctx.lineTo(...p.slice(0,2)):ctx.moveTo(...p.slice(0,2)));ctx.closePath();ctx.fill();}edges.forEach(([a,b])=>line(corners[a],corners[b],color,1.3));}
  // Room boundary and a floor grid remain in world coordinates as the Mac rotates.
  box(scene.room.map(x=>x/2),scene.room,'#3b4a50');
  for(let x=0;x<=scene.room[0];x+=1)line([x,0,0],[x,scene.room[1],0],'#253138');
  for(let y=0;y<=scene.room[1];y+=1)line([0,y,0],[scene.room[0],y,0],'#253138');
  if(((solution&&!dirty)||(typeof hasBandField==='function'&&hasBandField()))&&$('cloudVisible').checked){
    const cloud=(typeof displayedField==='function'?displayedField():solution).cloud;const pts=cloud.points.map((p,i)=>({p:proj(p),db:cloud[variant][i]})).sort((a,b)=>a.p[2]-b.p[2]);
    for(const {p,db} of pts){if(db<-45)continue;ctx.fillStyle=`rgba(${rgb(db).join(',')},${.12+Math.max(0,db+50)/50*.3})`;ctx.beginPath();ctx.arc(p[0],p[1],Math.max(1,Math.min(2.5,scale*.01)),0,2*Math.PI);ctx.fill();}
  }
  if(scene.desk.enabled){const d=scene.desk;box([d.center[0],d.center[1],d.height],[d.width,d.depth,.025],'#71858d',true);}
  const chassis=boxCorners([0,0,.0084],[.3557,.2481,.0168]).map(localToWorld);edges.forEach(([a,b])=>line(chassis[a],chassis[b],'#d3dde0',1.7));
  // Visual lid: nominal 100° opening, contextual only; its scattering is not simulated.
  const lid=[[ -.17785,-.124,.0168],[.17785,-.124,.0168],[.17785,-.168,.264],[-.17785,-.168,.264]].map(localToWorld);
  lid.forEach((p,i)=>line(p,lid[(i+1)%4],'#667b83',1));
  [-.15,.15].forEach((x,i)=>{const p=proj(localToWorld([x,0,.0168]));ctx.fillStyle='#c5f5e0';ctx.beginPath();ctx.arc(p[0],p[1],5,0,2*Math.PI);ctx.fill();ctx.font='10px monospace';ctx.fillText(i?'R':'L',p[0]+7,p[1]-5);});
  const origin=localToWorld([0,0,.0168]),tip=localToWorld([0,0,.43]);line(origin,tip,'#8de1c3',2);const tp=proj(tip);ctx.fillStyle='#8de1c3';ctx.beginPath();ctx.arc(tp[0],tp[1],3,0,2*Math.PI);ctx.fill();ctx.font='10px monospace';ctx.fillText('top face',tp[0]+7,tp[1]);
  ['bright','dark'].forEach(z=>{box(scene[z].center,scene[z].size,colors[z],true);const p=proj(scene[z].center);ctx.fillStyle=colors[z];ctx.font='11px monospace';ctx.fillText(z.toUpperCase(),p[0]+9,p[1]-9);});
  if(micStream){const p=proj(micPosition());ctx.strokeStyle='#fff';ctx.beginPath();ctx.arc(p[0],p[1],5,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#fff';ctx.fillText('MIC',p[0]+9,p[1]);}
  const triad=[w-58,h-42];for(let i=0;i<3;i++){const a=proj(focus),v=focus.slice();v[i]+=.2;const b=proj(v),dx=b[0]-a[0],dy=b[1]-a[1],n=Math.hypot(dx,dy)||1;ctx.strokeStyle=['#d58f78','#8de1c3','#92b7f0'][i];ctx.beginPath();ctx.moveTo(...triad);ctx.lineTo(triad[0]+dx/n*24,triad[1]+dy/n*24);ctx.stroke();ctx.fillStyle=ctx.strokeStyle;ctx.fillText(axes[i],triad[0]+dx/n*32,triad[1]+dy/n*32);}
  if(dirty&&!(typeof hasBandField==='function'&&hasBandField())){ctx.fillStyle='#ffb16d';ctx.font='11px monospace';ctx.fillText('Previous field · scene not solved',15,h-15);}
}
function drawSlice(){
  const field=typeof displayedField==='function'?displayedField():solution;
  if(!scene||!field)return;const {ctx,w,h}=setupCanvas($('slice')),s=field.slices[plane],dims=s.dims,margin={l:44,r:18,t:18,b:32},availW=w-margin.l-margin.r,availH=h-margin.t-margin.b;
  const rangeU=s.u.at(-1)-s.u[0],rangeV=s.v.at(-1)-s.v[0],scale=Math.min(availW/rangeU,availH/rangeV),width=rangeU*scale,height=rangeV*scale,left=margin.l+(availW-width)/2,top=margin.t+(availH-height)/2;
  const toPixel=p=>[left+(p[dims[0]]-s.u[0])*scale,top+height-(p[dims[1]]-s.v[0])*scale];sliceBox={left,top,width,height,scale,s};
  const buffer=document.createElement('canvas');buffer.width=s.u.length;buffer.height=s.v.length;const b=buffer.getContext('2d'),img=b.createImageData(buffer.width,buffer.height),values=s[variant];
  for(let y=0;y<buffer.height;y++)for(let x=0;x<buffer.width;x++){const i=(y*buffer.width+x)*4,db=values[(buffer.height-1-y)*buffer.width+x],color=rgb(db);img.data.set([...color,255],i);}b.putImageData(img,0,0);ctx.imageSmoothingEnabled=false;ctx.globalAlpha=dirty&&!(typeof hasBandField==='function'&&hasBandField())?.35:1;ctx.drawImage(buffer,left,top,width,height);ctx.globalAlpha=1;
  ctx.font='9px monospace';ctx.textAlign='center';for(let i=0;i<=4;i++){const x=left+i/4*width,y=top+i/4*height;ctx.strokeStyle='#c7e3de22';ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,top+height);ctx.moveTo(left,y);ctx.lineTo(left+width,y);ctx.stroke();ctx.fillStyle='#99aeb4';ctx.fillText(fmt(s.u[0]+rangeU*i/4,2),x,top+height+16);ctx.textAlign='right';ctx.fillText(fmt(s.v.at(-1)-rangeV*i/4,2),left-6,y+3);ctx.textAlign='center';}ctx.fillText(axes[dims[0]]+' / m',left+width/2,h-3);ctx.textAlign='left';ctx.fillText(axes[dims[1]]+' / m',4,12);
  ['bright','dark'].forEach(z=>{const a=scene[z],p=toPixel(a.center),zw=a.size[dims[0]]*scale,zh=a.size[dims[1]]*scale;const fixedAxis=[0,1,2].find(i=>!dims.includes(i));const intersects=Math.abs(a.center[fixedAxis]-s.fixed)<=a.size[fixedAxis]/2;
    ctx.strokeStyle=colors[z];ctx.lineWidth=zone===z?2.5:1.5;ctx.setLineDash(intersects?[]:[4,3]);ctx.strokeRect(p[0]-zw/2,p[1]-zh/2,zw,zh);ctx.setLineDash([]);ctx.fillStyle=colors[z];ctx.font='10px monospace';ctx.fillText(z.toUpperCase()+(intersects?'':' · projected'),p[0]+zw/2+5,p[1]-5);
  });
  [-.15,.15].forEach((x,i)=>{const p=toPixel(localToWorld([x,0,.0168]));ctx.fillStyle='#fff';ctx.beginPath();ctx.arc(...p,3.5,0,2*Math.PI);ctx.fill();ctx.fillText(i?'R':'L',p[0]+5,p[1]+4);});
  const mp=toPixel(micPosition());if(micStream){ctx.strokeStyle='#fff';ctx.beginPath();ctx.arc(...mp,5,0,2*Math.PI);ctx.stroke();}
  $('planeLabel').textContent='at '+axes[[0,1,2].find(i=>!dims.includes(i))]+' = '+fmt(s.fixed,2)+' m';
}
function draw(){drawSpace();drawSlice();}
// Orbit the scene; dragging a projected zone edits the displayed pair of world axes.
let orbit=null,drag=null;
$('space').addEventListener('pointerdown',e=>{orbit=[e.clientX,e.clientY,camera.az,camera.el];$('space').setPointerCapture(e.pointerId);});
$('space').addEventListener('pointermove',e=>{if(!orbit)return;camera.az=orbit[2]+(e.clientX-orbit[0])*.008;camera.el=Math.max(-1.2,Math.min(1.2,orbit[3]+(e.clientY-orbit[1])*.008));drawSpace();});
$('space').addEventListener('pointerup',()=>orbit=null);$('space').addEventListener('pointercancel',()=>orbit=null);
$('space').addEventListener('wheel',e=>{e.preventDefault();camera.zoom=Math.max(.3,Math.min(4,camera.zoom*Math.exp(-e.deltaY*.001)));drawSpace();},{passive:false});
$('slice').addEventListener('pointerdown',e=>{if(!sliceBox||measuring)return;const rect=$('slice').getBoundingClientRect(),x=e.clientX-rect.left,y=e.clientY-rect.top,{left,top,height,scale,s}=sliceBox;let selected=null;for(const z of ['bright','dark']){const a=scene[z],px=left+(a.center[s.dims[0]]-s.u[0])*scale,py=top+height-(a.center[s.dims[1]]-s.v[0])*scale;if(Math.abs(x-px)<Math.max(12,a.size[s.dims[0]]*scale/2)&&Math.abs(y-py)<Math.max(12,a.size[s.dims[1]]*scale/2))selected=z;}if(selected){zone=selected;syncZones();drag={x,y,center:scene[zone].center.slice(),dims:s.dims.slice(),scale};$('slice').setPointerCapture(e.pointerId);}});
$('slice').addEventListener('pointermove',e=>{if(!drag)return;const rect=$('slice').getBoundingClientRect(),delta=[e.clientX-rect.left-drag.x,-(e.clientY-rect.top-drag.y)];drag.dims.forEach((d,i)=>{scene[zone].center[d]=Math.round((drag.center[d]+delta[i]/drag.scale)*1000)/1000;});syncZones();markDirty();});
$('slice').addEventListener('pointerup',()=>drag=null);$('slice').addEventListener('pointercancel',()=>drag=null);
window.addEventListener('resize',draw);
function micPosition(){return Array.from($('micPosition').querySelectorAll('input')).map(i=>Number(i.value));}
function setMicPosition(p){vectorInputs('micPosition',p,()=>draw());draw();}
function download(name,data){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function bindControls(){
  ['frequency','temperature','order','directivity','regularization','spacing'].forEach(id=>$(id).addEventListener('change',()=>{scene[id]=Number($(id).value);if(id==='frequency')$('frequencySlider').value=scene.frequency;markDirty();}));
  ['mode','session'].forEach(id=>$(id).addEventListener('change',()=>{scene[id]=$(id).value;markDirty();}));
  $('frequencySlider').oninput=()=>{scene.frequency=Number($('frequencySlider').value);$('frequency').value=scene.frequency;markDirty();};
  document.querySelectorAll('[data-freq]').forEach(b=>b.onclick=()=>{scene.frequency=Number(b.dataset.freq);syncUI();markDirty();});
  $('selectBright').onclick=()=>{zone='bright';syncZones();draw();};$('selectDark').onclick=()=>{zone='dark';syncZones();draw();};
  $('flat').onclick=()=>{scene.yaw=scene.pitch=scene.roll=0;syncUI();markDirty();};$('upright').onclick=()=>{scene.yaw=0;scene.pitch=0;scene.roll=-90;syncUI();markDirty();};
  $('frontBack').onclick=()=>{scene.bright.center=localToWorld([0,0,.5]);scene.dark.center=localToWorld([0,0,-.5]);syncZones();markDirty();};
  $('offsetFrontBack').onclick=()=>{scene.bright.center=localToWorld([-.25,0,.5]);scene.dark.center=localToWorld([.25,0,-.5]);syncZones();markDirty();};
  $('deskEnabled').onchange=()=>{scene.desk.enabled=$('deskEnabled').checked;$('deskFields').hidden=!scene.desk.enabled;markDirty();};
  ['height','width','depth','reflection'].forEach(k=>$('desk'+k[0].toUpperCase()+k.slice(1)).onchange=e=>{scene.desk[k]=Number(e.target.value);markDirty();});
  $('sliceHeight').onchange=()=>{scene.slice_z=Number($('sliceHeight').value);markDirty();};$('plane').onchange=()=>{plane=$('plane').value;drawSlice();};
  $('focusView').onclick=()=>{scene.view_span=2.4;camera.zoom=1;markDirty();};$('roomView').onclick=()=>{scene.view_span=Math.min(20,Math.max(...scene.room)*1.6);camera.zoom=.8;markDirty();};$('cloudVisible').onchange=drawSpace;
  $('showOptimized').onclick=()=>setVariant('optimized');$('showBaseline').onclick=()=>setVariant('baseline');
  $('solve').onclick=()=>{dirty=true;solve();};$('saveScene').onclick=()=>download('macbook-scene.json',{schema:1,config:scene});$('loadScene').onclick=()=>$('sceneFile').click();
  $('sceneFile').onchange=async e=>{try{const raw=JSON.parse(await e.target.files[0].text());const result=await api('solve',{config:raw.config||raw});scene=result.config;solution=result;dirty=false;serial++;if(typeof invalidateBand==='function')invalidateBand();syncUI();renderResults();draw();status('Scene loaded','success');}catch(err){status(err.message,'error');}};
  $('play').onclick=async()=>{try{if(dirty||!solution)throw Error('Wait for the current solution.');await api('play',{id:solution.id,variant,peak:Number($('peak').value),seconds:Number($('duration').value)});$('play').textContent='● Playing';status('Playing '+variant+' through native Core Audio','success');clearTimeout(playTimer);playTimer=setTimeout(()=>$('play').textContent='▶ Play',Number($('duration').value)*1000+150);}catch(e){status(e.message,'error');}};
  $('stop').onclick=()=>{cancelled=true;api('stop',{}).catch(e=>status(e.message,'error'));$('play').textContent='▶ Play';};
  $('peak').onchange=()=>{api('stop',{});$('play').textContent='▶ Play';status('Drive changed. Use a new measurement session if calibration already exists.');};
  $('connectMic').onclick=()=>connectMic().catch(e=>status(e.message,'error'));
  $('microphone').onchange=()=>connectMic($('microphone').value).catch(e=>status(e.message,'error'));
  $('micBright').onclick=()=>setMicPosition(scene.bright.center);$('micDark').onclick=()=>setMicPosition(scene.dark.center);
  $('nextPoint').onclick=()=>{const offsets=$('role').value==='train'?[[-.3,-.3,-.3],[.3,.3,-.3],[-.3,.3,.3],[.3,-.3,.3],[0,0,0],[.3,.3,.3]]:[[.2,-.2,.2],[-.2,.2,-.2],[.2,.2,.2],[-.2,-.2,-.2]];const o=offsets[pointIndex++%offsets.length],z=scene[zone];setMicPosition(z.center.map((v,i)=>Math.round((v+o[i]*z.size[i])*1000)/1000));};
  $('newSession').onclick=()=>{scene.session='session-'+Date.now();$('session').value=scene.session;$('fixedGain').checked=false;markDirty();};
  $('calibrate').onclick=()=>measure(false);$('validate').onclick=()=>measure(true);$('cancelMeasurement').onclick=()=>{cancelled=true;api('stop',{}).catch(()=>{});};
  $('exportData').onclick=()=>download('macbook-measurements.json',dataset);$('exportResult').onclick=()=>solution&&download('macbook-solution.json',solution);
  $('saveFeedback').onclick=async()=>{try{const r=await api('feedback',{config:scene,note:$('feedback').value});status(r.next_step,'success');$('feedback').value='';}catch(e){status(e.message,'error');}};
}
function setVariant(v){variant=v;api('stop',{}).catch(()=>{});$('play').textContent='▶ Play';$('showOptimized').classList.toggle('active',v==='optimized');$('showBaseline').classList.toggle('active',v==='baseline');$('playLabel').textContent=v==='optimized'?'Optimized stereo tone':'Equal-drive stereo tone';draw();}
async function connectMic(deviceId){
  if(measuring)throw Error('Finish or cancel measurement first.');
  if(!navigator.mediaDevices?.getUserMedia)throw Error('Microphone access requires a browser with getUserMedia on localhost. Open this URL in Chrome or Safari.');
  if(micStream)micStream.getTracks().forEach(t=>t.stop());if(ctxAudio)await ctxAudio.close();
  micStream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:deviceId?{exact:deviceId}:undefined,channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
  const track=micStream.getAudioTracks()[0],settings=track.getSettings();
  if(settings.echoCancellation||settings.noiseSuppression||settings.autoGainControl){track.stop();throw Error('Browser enabled microphone processing. Use an input/browser that permits raw capture.');}
  ctxAudio=new AudioContext();await ctxAudio.resume();await ctxAudio.audioWorklet.addModule('/meter.js');meter=new AudioWorkletNode(ctxAudio,'tone-meter');micSource=ctxAudio.createMediaStreamSource(micStream);micSource.connect(meter);meter.connect(ctxAudio.destination);meter.port.onmessage=e=>{micReadings.push({...e.data,received:performance.now()});if(micReadings.length>256)micReadings.shift();};meter.port.postMessage({frequency:scene.frequency});
  const devices=await navigator.mediaDevices.enumerateDevices();$('microphone').replaceChildren();devices.filter(d=>d.kind==='audioinput').forEach(d=>{const o=document.createElement('option');o.value=d.deviceId;o.textContent=d.label||'Microphone';$('microphone').append(o);});$('microphone').value=settings.deviceId;
  micIdentity=track.label+' | '+settings.deviceId;$('micStatus').textContent=track.label+' · '+ctxAudio.sampleRate+' Hz · processing requested off. Confirm hardware gain is fixed. The browser cannot verify hardware AGC.';$('connectMic').textContent='Reconnect microphone';draw();
}
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function collect(settle,capture){
  await wait(settle*1000);if(cancelled)throw Error('Measurement cancelled.');micReadings=[];const started=performance.now();await wait(capture*1000);if(cancelled)throw Error('Measurement cancelled.');
  const rows=micReadings.filter(r=>r.received>started+150);if(rows.length<6)throw Error('Not enough microphone frames. Keep this tab active and microphone connected.');if(rows.some(r=>r.peak>=.98))throw Error('Microphone clipping. Reduce input gain and restart the measurement session.');
  const ps=rows.map(r=>r.power),mean=ps.reduce((a,b)=>a+b,0)/ps.length,sd=Math.sqrt(ps.reduce((a,b)=>a+(b-mean)**2,0)/ps.length);return {power:mean,scatter:sd};
}
function lockMeasurement(on){
  measuring=on;document.body.classList.toggle('measuring',on);
  const keep=new Set(['cancelMeasurement','stop']);document.querySelectorAll('button,input,select,textarea').forEach(el=>{if(on){el.dataset.previousDisabled=String(el.disabled);if(!keep.has(el.id))el.disabled=true;}else if(el.dataset.previousDisabled!==undefined){el.disabled=el.dataset.previousDisabled==='true';delete el.dataset.previousDisabled;}});
}
async function measure(validation){
  if(measuring)return;
  try{
    if(!meter||ctxAudio.state!=='running')throw Error('Connect and enable the microphone first.');if(!hardware.selected_output)throw Error('Built-in speakers unavailable. Launch from Terminal.');if(!$('fixedGain').checked)throw Error('Confirm fixed gain and unchanged setup before measuring.');if(dirty||!solution)throw Error('Wait for the current solution.');
    const position=micPosition();if(!inside(position,scene.bright)&&!inside(position,scene.dark))throw Error('Move the microphone coordinates inside the bright or dark zone.');
    const settle=Number($('settleTime').value),capture=Number($('captureTime').value);if(!Number.isFinite(settle)||!Number.isFinite(capture)||settle<.5||capture<1||Math.max(settle,capture)>5)throw Error('Settle time must be 0.5–5 s; capture time must be 1–5 s.');
    const cfg=clone(scene),id=solution.id,peak=Number($('peak').value),role=$('role').value,microphone=micIdentity;cancelled=false;lockMeasurement(true);meter.port.postMessage({frequency:cfg.frequency});await api('stop',{});
    const powers=[],scatter=[],steps=validation?5:12;$('progress').max=steps;$('progress').value=0;
    for(let i=0;i<steps;i++){
      if(cancelled)throw Error('Measurement cancelled.');
      const name=validation?['Background','Equal drive','Optimized','Optimized repeat','Equal-drive repeat'][i]:['Background','Left only','Right only',...Array.from({length:8},(_,j)=>'L + R at '+j*45+'°'),'Left repeat'][i];
      $('measureProgress').textContent=`${i+1}/${steps} · ${name}. Keep microphone still at ${position.map(v=>fmt(v,3)).join(', ')} m.`;
      if(i===0)await api('stop',{});else if(validation)await api('play',{id,variant:(i===1||i===4)?'baseline':'optimized',peak,seconds:settle+capture+1});else await api('probe',{id,config:cfg,index:i,peak,seconds:settle+capture+1});
      const r=await collect(settle,capture);powers.push(r.power);scatter.push(r.scatter);await api('stop',{});$('progress').value=i+1;
    }
    if(cancelled)throw Error('Measurement cancelled.');
    const r=await api(validation?'validate':'calibrate',{id,config:cfg,position,role,peak,powers,scatter,microphone,fixed_gain_confirmed:true});dataset=r.data;
    if(validation){solution.actual_validation=r.summary;renderActual(r.summary);$('measureProgress').textContent='A/B playback measurement saved. Repeat at other held-out positions in each zone.';}else{$('measureProgress').textContent='Accepted · SNR '+fmt(r.record.quality.snr_db)+' dB · fit error '+fmt(r.record.quality.relative_residual*100)+'%. Move to another position.';}
    renderRecords();status(validation?'Actual playback measurement saved.':'Calibration saved. Select measured optimization once both zones have enough points.','success');
  }catch(e){$('measureProgress').textContent=e.message;status(e.message,'error');}
  finally{await api('stop',{}).catch(()=>{});if(measuring)lockMeasurement(false);$('play').textContent='▶ Play';}
}
window.addEventListener('pagehide',()=>{fetch('/api/stop',{method:'POST',headers:{'Content-Type':'application/json','X-ACC-Token':token},body:'{}',keepalive:true});if(micStream)micStream.getTracks().forEach(t=>t.stop());});
(async()=>{try{const r=await fetch('/api/state');const state=await r.json();scene=state.default;try{const saved=localStorage.getItem('macbook-acc-scene');if(saved)scene=JSON.parse(saved);}catch{}hardware=state.hardware;dataset=state.data;const selected=hardware.devices.find(d=>d.id===hardware.selected_output);$('hardwareBadge').textContent=selected?'CORE AUDIO · '+selected.output_channels+' CH':'AUDIO UNAVAILABLE';$('hardwareBadge').classList.toggle('error',!selected);$('routeLabel').textContent=selected?'Native AUHAL → '+selected.name:hardware.error;syncUI();setMicPosition(scene.bright.center);bindControls();if(typeof initBand==='function')initBand(state.audio_sources||[]);await solve();}catch(e){status(e.message,'error');}})();
