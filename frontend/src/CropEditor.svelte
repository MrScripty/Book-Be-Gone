<script>
  import { onMount, untrack } from 'svelte';
  import Corners from './Corners.svelte';
  import { correctedImage } from './imaging.js';
  import { api } from './session.svelte.js';
  let {session}=$props();
  const task=untrack(()=>session.crop);
  const figure=task.kind==='figure';
  let disposed=false;
  let dialog,source,loaded=$state(false),preview=$state(''),ratio=$state(''),coordinates=$state(false);
  let points=$state(figure?[[task.figure.bbox[0],task.figure.bbox[1]],[task.figure.bbox[2],task.figure.bbox[1]],[task.figure.bbox[2],task.figure.bbox[3]],[task.figure.bbox[0],task.figure.bbox[3]]]:[[0,0],[1,0],[1,1],[0,1]]);
  const url=figure?`/api/figure-source/${task.book}/${task.figure.source}`:`/api/original/${task.book}/${task.row.capture}`;
  onMount(()=>{dialog.showModal();source.decode().then(()=>{if(disposed)return;loaded=true;if(figure)draw();}).catch(e=>{if(!disposed)session.message=e.message;});return()=>{disposed=true;};});
  function draw(){
    if(!loaded)return;if(!figure){preview='';return;}
    const [l,t]=points[0],[r,b]=points[2],canvas=document.createElement('canvas');
    const x=Math.floor(l*source.naturalWidth),y=Math.floor(t*source.naturalHeight),w=Math.ceil(r*source.naturalWidth)-x,h=Math.ceil(b*source.naturalHeight)-y;
    const factor=Math.min(1,1000/Math.max(w,h));canvas.width=Math.max(1,Math.round(w*factor));canvas.height=Math.max(1,Math.round(h*factor));canvas.getContext('2d').drawImage(source,x,y,w,h,0,0,canvas.width,canvas.height);preview=canvas.toDataURL('image/png');
  }
  function field(i,j,value){
    const v=Math.max(0,Math.min(1,Number(value)/100));let next=points.map(p=>[...p]);
    if(figure){const l=i===0||i===3,t=i<2;if(j===0){if(l){next[0][0]=next[3][0]=Math.min(next[2][0]-.001,v);}else next[1][0]=next[2][0]=Math.max(next[0][0]+.001,v);}else if(t)next[0][1]=next[1][1]=Math.min(next[2][1]-.001,v);else next[2][1]=next[3][1]=Math.max(next[0][1]+.001,v);}
    else{next[i][j]=v;if(j===1)next[i^1][1]=v;}
    points=next;draw();
  }
  async function save(reset=false){
    if(figure)await api('/api/figure',{book:task.book,page:task.row.capture,printed_index:task.row.index,revision:task.row.revision,figure:task.figure.id,bbox:[...points[0],...points[2]]});
    else await api('/api/adjust',{book:task.book,page:task.row.capture,...(reset?{reset:true}:{image:preview.split(',')[1]})});
    session.crop=null;session.imageVersion++;await session.loadDocument();session.message=figure?'Figure crop saved.':'Page correction saved. Ready for OCR.';
  }
</script>
<dialog bind:this={dialog} class="crop-dialog" oncancel={e=>{e.preventDefault();if(!session.pending)session.crop=null;}} aria-label={figure?'Edit figure crop':'Crop and straighten page'}>
  <header class="dialog-header"><div><span class="eyebrow">{figure?'FIGURE CROP':'PAGE CORRECTION'}</span><h2>{figure?task.figure.id:'Crop & straighten'}</h2></div><button aria-label="Close crop editor" disabled={session.pending} onclick={()=>session.crop=null}>✕</button></header>
  {#if session.message}<div class="notice" role="alert"><span>{session.message}</span><button aria-label="Dismiss crop message" onclick={()=>session.message=''}>✕</button></div>{/if}
  <div class="crop-columns"><div class="crop-source-stage"><img bind:this={source} src={url} alt="Crop source page"/>{#if loaded}<Corners bind:points paired={!figure} rectangle={figure} onchange={draw} disabled={session.pending}/>{/if}</div><div class="crop-result">{#if preview}<img src={preview} alt="Crop preview"/>{:else}<span>Drag corners, then preview.</span>{/if}</div></div>
  <div class="settings-strip"><button aria-expanded={coordinates} onclick={()=>coordinates=!coordinates}>Coordinates</button>{#if !figure}<label>Width / height <input aria-label="Page aspect ratio" type="number" min="0.1" max="10" step="0.01" placeholder="Auto" bind:value={ratio} oninput={()=>preview=''}/></label><button disabled={!loaded||session.pending} onclick={()=>session.run(()=>preview=correctedImage(source,points,ratio).corrected)}>Preview</button>{/if}</div>
  {#if coordinates}<div class="coordinate-grid">{#each points as point,i}<label>Corner {i+1}<input aria-label={`Corner ${i+1} X percent`} type="number" min="0" max="100" step=".1" value={+(point[0]*100).toFixed(2)} onchange={e=>field(i,0,e.target.value)}/><input aria-label={`Corner ${i+1} Y percent`} type="number" min="0" max="100" step=".1" value={+(point[1]*100).toFixed(2)} onchange={e=>field(i,1,e.target.value)}/></label>{/each}</div>{/if}
  <footer class="dialog-footer">{#if !figure}<button class="quiet" disabled={session.pending} onclick={()=>session.run(()=>save(true))}>Restore original</button>{/if}<span class="grow"></span><button disabled={session.pending} onclick={()=>session.crop=null}>Cancel</button><button class="primary" disabled={!preview||!loaded||session.pending} onclick={()=>session.run(()=>save())}>Save crop</button></footer>
</dialog>
