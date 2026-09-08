<script>
  import { onMount } from 'svelte';
  import Corners from './Corners.svelte';
  import { correctedImage } from './imaging.js';
  import { api } from './session.svelte.js';
  let {session}=$props();
  let video,stream=$state(null),devices=$state([]),device=$state(''),enabled=$state(true),ratio=$state('');
  let points=$state([[.05,.05],[.95,.05],[.95,.95],[.05,.95]]),options=$state(false),last=$state(''),starting=$state(false),disposed=false;
  onMount(()=>{try{const saved=JSON.parse(localStorage.getItem('book-be-gone-camera')||'null');if(saved){points=saved.points;ratio=saved.ratio;enabled=saved.enabled;device=saved.device||'';}}catch{}return()=>{disposed=true;stream?.getTracks().forEach(t=>t.stop());};});
  function remember(){localStorage.setItem('book-be-gone-camera',JSON.stringify({points,ratio,enabled,device}));}
  async function start(){
    if(starting)return;starting=true;
    try{stream?.getTracks().forEach(t=>t.stop());stream=null;const next=await navigator.mediaDevices.getUserMedia({video:{...(device?{deviceId:{exact:device}}:{}),width:{ideal:3840},height:{ideal:2160}},audio:false});if(disposed){next.getTracks().forEach(t=>t.stop());return;}stream=next;video.srcObject=next;await video.play();devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');device=stream.getVideoTracks()[0].getSettings().deviceId||'';remember();}finally{starting=false;}
  }
  async function capture(){
    if(!stream||!video.videoWidth||video.readyState<2)throw Error('Start the camera first.');
    const book=session.book,images=correctedImage(video,enabled?points:null,ratio);
    const payload={book,image:images.original.split(',')[1]};if(images.corrected)payload.corrected=images.corrected.split(',')[1];
    const result=await api('/api/capture',payload);remember();last=result.page;
    if(session.book===book){await session.loadDocument();session.select(`${result.page}:0`,{scroll:false});}
  }
</script>
<section class="capture-workspace">
  <div class="panelbar"><span class="eyebrow">CAMERA</span><span class="grow"></span>
    {#if stream}<button onclick={()=>{stream.getTracks().forEach(t=>t.stop());stream=null;}}>Stop camera</button>{:else}<button onclick={()=>session.run(start)} disabled={session.pending||starting}>Start camera</button>{/if}
    {#if devices.length>1}<select aria-label="Camera" bind:value={device} onchange={()=>session.run(start)}>{#each devices as d}<option value={d.deviceId}>{d.label||'Camera'}</option>{/each}</select>{/if}
    <button aria-expanded={options} onclick={()=>options=!options}>Framing</button>
  </div>
  {#if options}<div class="settings-strip"><label><input type="checkbox" bind:checked={enabled} onchange={remember}/> Crop & straighten</label><label>Width / height <input aria-label="Capture aspect ratio" type="number" min="0.1" max="10" step="0.01" placeholder="Auto" bind:value={ratio} onchange={remember}/></label><button onclick={()=>{points=[[.05,.05],[.95,.05],[.95,.95],[.05,.95]];remember();}}>Reset corners</button></div>{/if}
  <div class="camera-area"><div class="camera-stage" class:inactive={!stream}><video bind:this={video} autoplay playsinline muted aria-label="Live camera preview"></video>{#if stream&&enabled}<Corners bind:points paired onchange={remember} label="Live page crop"/>{/if}</div>
    {#if !stream}<div class="camera-empty"><span class="empty-icon">▣</span><h2>Ready for the next page</h2><p>Start your camera and frame the book.</p></div>{/if}
  </div>
  <div class="capture-footer"><span>{session.captures.length} captures{last?` · Saved ${last}`:''}</span><span class="grow"></span><button class="primary capture-button" disabled={!stream||session.pending||!session.book} onclick={()=>session.run(capture)}>Capture page <kbd>Space</kbd></button></div>
</section>
<svelte:window onkeydown={e=>{if(e.code==='Space'&&!e.repeat&&!['INPUT','SELECT','TEXTAREA','BUTTON'].includes(document.activeElement?.tagName)&&!session.pending&&stream){e.preventDefault();session.run(capture);}}}/>
