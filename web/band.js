'use strict';
let bandResult=null,bandJob=null,bandDisplay=false,bandStale=true,bandVersion=0,audioSources=[],bandPlayTimer=null;
function hasBandField(){return bandDisplay&&!!bandResult&&!bandStale;}
function displayedField(){return bandDisplay&&bandResult&&!bandStale?bandResult.field:solution;}
function updateBandMetrics(){
  if(!bandDisplay||!bandResult||bandStale)return;
  $('contrast').textContent=fmt(bandResult.optimized.contrast_db)+' dB';$('baselineMetric').textContent='Audio equal drive '+fmt(bandResult.baseline.contrast_db)+' dB';$('trainingContrast').textContent=fmt(bandResult.training.contrast_db)+' dB';$('trainingMode').textContent='Rendered audio · model training samples';$('actualContrast').textContent='Unverified';$('actualDetails').textContent='Broadband requires independent microphone validation';
}
function invalidateBand(){
  bandStale=true;bandDisplay=false;bandVersion++;
  for(const id of ['playBandOptimized','playBandBaseline','showBandField'])$(id).disabled=true;
  if(bandJob){api('broadband-cancel',{id:bandJob}).catch(()=>{});bandJob=null;}
  if(bandResult){$('bandStatus').textContent='Settings changed. Re-optimize the audio band before playback.';$('bandContrast').textContent='—';$('bandBaseline').textContent='—';$('bandImprovement').textContent='Previous render is stale';}
  const tag=document.querySelector('.floating-tag');if(tag)tag.textContent='ESTIMATED SINGLE-TONE FIELD';
}
function bandOptions(){return {low:Number($('bandLow').value),high:Number($('bandHigh').value),control:$('bandControl').value,fft_size:Number($('bandFFT').value),spatial_method:$('bandSpatialMethod').value,spatial_samples:Number($('bandSamples').value)};}
function bandResolution(){
  const device=hardware?.devices?.find(d=>d.id===hardware.selected_output),rate=device?.sample_rate||44100,n=Number($('bandFFT').value);
  $('bandResolution').textContent=fmt(rate/n,3)+' Hz bin spacing · '+fmt(1000*n/2/rate,1)+' ms shared filter delay · '+rate+' Hz output rate. '+(rate*.49<20000?'This output rate cannot support 20 kHz; choose at least 44.1 kHz in Audio MIDI Setup.':'');
  $('bandSamples').disabled=$('bandSpatialMethod').value==='grid';
}
function refreshAudioSources(rows){
  const previous=$('audioSource').value;audioSources=rows;$('audioSource').replaceChildren();
  for(const s of rows){const option=document.createElement('option');option.value=s.id;option.textContent=s.name+(s.available===false?' · unavailable':'');option.disabled=s.available===false;$('audioSource').append(option);}
  if(rows.some(s=>s.id===previous))$('audioSource').value=previous;
  audioCredit();
}
function audioCredit(){
  const item=audioSources.find(s=>s.id===$('audioSource').value);$('audioCredit').replaceChildren();if(!item)return;
  $('audioCredit').append(document.createTextNode(item.credit+' '));
  if(item.source?.startsWith('https://')){const a=document.createElement('a');a.href=item.source;a.target='_blank';a.rel='noreferrer';a.textContent='Source ↗';$('audioCredit').append(a);}
}
function setBandView(show){
  bandDisplay=show&&!!bandResult&&!bandStale;
  document.querySelector('.floating-tag').textContent=bandDisplay?'ESTIMATED AUDIO-BAND RMS FIELD':'ESTIMATED SINGLE-TONE FIELD';
  if(solution)renderResults();updateBandMetrics();
  if(bandDisplay)status('Ready · '+bandResult.options.low+'–'+bandResult.options.high+' Hz audio band · approximate model','success');
  draw();
}
async function optimizeAudio(){
  if(measuring)return status('Finish microphone capture before starting an audio render.','error');
  const version=++bandVersion,cfg=clone(scene);bandStale=true;bandDisplay=false;
  $('optimizeBand').disabled=true;for(const id of ['playBandOptimized','playBandBaseline','showBandField'])$(id).disabled=true;
  try{
    await api('stop',{});
    const job=await api('broadband-start',{config:cfg,options:bandOptions(),audio_id:$('audioSource').value});
    if(version!==bandVersion){await api('broadband-cancel',{id:job.id});return;}
    bandJob=job.id;
    while(version===bandVersion){
      const r=await api('broadband-status',{id:job.id});if(version!==bandVersion)break;
      $('bandProgress').value=r.progress;$('bandStatus').textContent=Math.round(r.progress*100)+'% · '+r.message;
      if(r.status==='ready'){
        bandResult=r.result;bandStale=false;bandJob=null;showBandResult();setBandView(true);break;
      }
      if(r.status==='error'||r.status==='cancelled')throw Error(r.message);
      await wait(350);
    }
  }catch(e){$('bandStatus').textContent=e.message;status(e.message,'error');}
  finally{$('optimizeBand').disabled=false;bandJob=null;}
}
function showBandResult(){
  const r=bandResult;$('bandContrast').textContent=fmt(r.optimized.contrast_db)+' dB';$('bandBaseline').textContent=fmt(r.baseline.contrast_db)+' dB';$('bandRetained').textContent=fmt(r.input_band_energy_percent)+'%';
  $('bandImprovement').textContent='Gain over equal drive: '+fmt(r.improvement_db)+' dB · unverified';
  const change=key=>10*Math.log10(Math.max(r.optimized[key],1e-30)/Math.max(r.baseline[key],1e-30));
  $('bandLevels').textContent='Bright '+fmt(change('bright_power'))+' dB / dark '+fmt(change('dark_power'))+' dB';
  $('bandLatency').textContent=r.fir_taps+' taps · '+fmt(r.common_delay_ms)+' ms shared delay';
  $('bandStatus').textContent='Ready · '+fmt(r.duration,2)+' s · '+r.sample_rate+' Hz · '+r.frequencies.length+' bins ('+fmt(r.frequency_step_hz,2)+' Hz) · '+(r.options.control==='phase'?'phase-only target':'amplitude + phase');
  const integration=r.spatial_integration;
  $('bandConvergence').textContent=integration?'Volume integration: '+[...new Set(integration.methods)].join(' / ')+' · training B/D '+integration.points.slice(0,2).map(v=>v.toLocaleString()).join('/')+' · independent validation B/D '+integration.points.slice(2).map(v=>v.toLocaleString()).join('/')+'. Training/validation difference '+fmt(integration.training_validation_difference_db,3)+' dB'+(integration.half_to_full_validation_difference_db===null?'':'; half/full validation difference '+fmt(integration.half_to_full_validation_difference_db,3)+' dB')+'. Active-bin 95th-percentile difference '+fmt(integration.active_bin_difference_p95_db,2)+' dB. These are numerical convergence checks, not microphone validation.':'';
  $('bandWarnings').replaceChildren();for(const warning of r.warnings){const li=document.createElement('li');li.textContent=warning;$('bandWarnings').append(li);}
  $('bandDownloads').replaceChildren();for(const [name,file] of [['Optimized WAV','optimized.wav'],['Equal-drive WAV','baseline.wav'],['FIR filters (NPZ)','filters.npz']]){const a=document.createElement('a');a.href='/api/broadband-file/'+r.id+'/'+file;a.textContent=name;a.download=file;$('bandDownloads').append(a,document.createTextNode('  ·  '));}
  for(const id of ['playBandOptimized','playBandBaseline','showBandField','exportBand'])$(id).disabled=false;
  drawBandChart();
}
async function playAudio(v){
  try{
    if(measuring)throw Error('Finish microphone capture first.');if(!bandResult||bandStale)throw Error('Optimize the current audio band first.');
    await api('stop',{});
    const r=await api('broadband-play',{id:bandResult.id,variant:v,config:scene,peak:Number($('bandPeak').value)});
    variant=v;$('showOptimized').classList.toggle('active',v==='optimized');$('showBaseline').classList.toggle('active',v==='baseline');setBandView(true);
    $('bandStatus').textContent='Playing '+(v==='optimized'?'optimized':'equal-drive')+' audio through native Core Audio · '+fmt(r.duration,1)+' s';
    clearTimeout(bandPlayTimer);bandPlayTimer=setTimeout(()=>{$('bandStatus').textContent='Playback complete. Compare the other version at the same gain.';},r.duration*1000+150);
  }catch(e){$('bandStatus').textContent=e.message;status(e.message,'error');}
}
function drawBandChart(){
  const canvas=$('bandChart');if(!canvas||!bandResult)return;const {ctx,w,h}=setupCanvas(canvas),r=bandResult,f=r.frequencies,left=45,right=w-15,top=27,bottom=h-24,mid=top+(bottom-top)*.6;
  const x=v=>left+(v-f[0])/(f.at(-1)-f[0])*(right-left);
  ctx.font='10px monospace';ctx.fillStyle='#94a5aa';ctx.fillText('CONTRAST / dB · optimized / equal drive',left,12);
  for(let db=-10;db<=30;db+=10){const y=mid-(db+10)/40*(mid-top);ctx.strokeStyle='#334148';ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();ctx.fillText(String(db),6,y+3);}
  // Source power curve uses its own -60..0 dB scale as background context.
  ctx.fillStyle='#8de1c31a';ctx.beginPath();ctx.moveTo(left,mid);f.forEach((v,i)=>ctx.lineTo(x(v),mid-Math.max(0,r.input_spectrum_db[i]+60)/60*(mid-top)));ctx.lineTo(right,mid);ctx.closePath();ctx.fill();
  function curve(values,color,ylow,yhigh,min,max){ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.beginPath();values.forEach((v,i)=>{const y=yhigh-(Math.max(min,Math.min(max,v))-min)/(max-min)*(yhigh-ylow);if(i===0||(values===r.relative_phase_deg&&Math.abs(v-values[i-1])>180))ctx.moveTo(x(f[i]),y);else ctx.lineTo(x(f[i]),y);});ctx.stroke();}
  curve(r.optimized.curve_db,'#8de1c3',top,mid,-10,30);curve(r.baseline.curve_db,'#ffb16d',top,mid,-10,30);
  ctx.fillStyle='#94a5aa';ctx.fillText('REALIZED R−L PHASE / ±180°',left,mid+19);curve(r.relative_phase_deg,'#92b7f0',mid+27,bottom,-180,180);
  for(let i=0;i<=4;i++){const v=f[0]+(f.at(-1)-f[0])*i/4;ctx.fillText(Math.round(v)+' Hz',x(v)-15,h-5);}
}
async function uploadWav(file){
  if(!file)return;if(file.size>24000000)throw Error('Choose a WAV smaller than 24 MB and no longer than 30 seconds.');
  const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode(...bytes.subarray(i,i+8192));
  const result=await api('audio-upload',{name:file.name,data:btoa(binary)});refreshAudioSources(result.sources);$('audioSource').value=result.source.id;audioCredit();invalidateBand();$('bandStatus').textContent='WAV imported. Optimize the audio band.';
}
function initBand(rows){
  refreshAudioSources(rows);
  for(const id of ['audioSource','bandLow','bandHigh','bandControl','bandFFT','bandSpatialMethod','bandSamples'])$(id).addEventListener('change',()=>{invalidateBand();api('stop',{}).catch(()=>{});audioCredit();bandResolution();if(solution)renderResults();draw();});
  $('fullHearingBand').onclick=()=>{$('bandLow').value=20;$('bandHigh').value=20000;$('bandFFT').value='65536';invalidateBand();bandResolution();api('stop',{}).catch(()=>{});if(solution)renderResults();draw();};
  bandResolution();
  $('optimizeBand').onclick=optimizeAudio;
  $('cancelBand').onclick=()=>{if(bandJob)api('broadband-cancel',{id:bandJob}).catch(e=>status(e.message,'error'));};
  $('playBandOptimized').onclick=()=>playAudio('optimized');$('playBandBaseline').onclick=()=>playAudio('baseline');
  $('stopBand').onclick=()=>{clearTimeout(bandPlayTimer);api('stop',{}).catch(()=>{});$('bandStatus').textContent='Playback stopped.';};
  $('bandPeak').onchange=()=>{api('stop',{}).catch(()=>{});$('bandStatus').textContent='Playback gain updated equally for both versions.';};
  $('showBandField').onclick=()=>setBandView(true);$('showToneField').onclick=()=>setBandView(false);
  $('exportBand').onclick=()=>bandResult&&download('broadband-report.json',bandResult);
  $('uploadAudio').onclick=()=>$('audioFile').click();$('audioFile').onchange=e=>uploadWav(e.target.files[0]).catch(e=>status(e.message,'error'));
  window.addEventListener('resize',drawBandChart);
}
