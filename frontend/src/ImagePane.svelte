<script>
  import { onMount } from 'svelte';
  let {session}=$props();
  let image=$state(),viewport,scale=$state(1),fitMode=true,pan=$state(null),loaded=$state(false);
  let row=$derived(session.selected);
  let source=$derived(row?`/api/photo/${session.book}/${row.capture}?v=${session.imageVersion}`:'');
  $effect(()=>{source;loaded=false;});
  function zoom(value,x=viewport.clientWidth/2,y=viewport.clientHeight/2){if(!image?.naturalWidth)return;const px=(viewport.scrollLeft+x)/scale,py=(viewport.scrollTop+y)/scale;scale=Math.max(.05,Math.min(8,value));image.style.width=image.naturalWidth*scale+'px';image.style.height=image.naturalHeight*scale+'px';viewport.scrollLeft=px*scale-x;viewport.scrollTop=py*scale-y;}
  function fit(){if(!viewport||!image?.naturalWidth)return;fitMode=true;zoom(Math.min(1,viewport.clientWidth/image.naturalWidth,viewport.clientHeight/image.naturalHeight),0,0);viewport.scrollLeft=viewport.scrollTop=0;}
  onMount(()=>{const observer=new ResizeObserver(()=>{if(fitMode)fit();});observer.observe(viewport);return()=>observer.disconnect();});
  function open(kind,figure){if(session.dirty){session.message='Save your Markdown corrections first.';return;}session.message='';session.crop={kind,book:session.book,row,figure};}
</script>
<section class="scan-pane">
  <div class="panelbar"><span class="eyebrow">SCAN</span>{#if row}<span class="small muted">{row.corrected?'Corrected':'Original'}</span>{/if}<span class="grow"></span>
    <button class="icon" aria-label="Zoom out" disabled={!loaded} onclick={()=>{fitMode=false;zoom(scale/1.25);}}>−</button><button class="zoom-value" title="Actual size" disabled={!loaded} onclick={()=>{fitMode=false;zoom(1);}}>{Math.round(scale*100)}%</button><button class="icon" aria-label="Zoom in" disabled={!loaded} onclick={()=>{fitMode=false;zoom(scale*1.25);}}>+</button><button disabled={!loaded} onclick={fit}>Fit</button>
    {#if row}<details class="menu"><summary aria-label="Image actions">•••</summary><div class="menu-content"><button disabled={session.running||session.pending||!!session.crop} onclick={e=>{e.currentTarget.closest('details').open=false;open('page');}}>Crop & straighten</button><a href={`/api/photo/${session.book}/${row.capture}`} download={`${row.capture}.jpg`}>Download image</a><a href={`/api/original/${session.book}/${row.capture}`} download={`${row.capture}-original.jpg`}>Download original</a></div></details>{/if}
  </div>
  <div class="image-viewport" bind:this={viewport} role="region" aria-label="Scanned page. Scroll to zoom, drag to pan" class:panning={!!pan}
    onwheel={e=>{e.preventDefault();fitMode=false;const r=viewport.getBoundingClientRect();zoom(scale*(e.deltaY<0?1.15:1/1.15),e.clientX-r.left,e.clientY-r.top);}}
    onpointerdown={e=>{if(e.button!==0||!loaded)return;e.preventDefault();pan={x:e.clientX,y:e.clientY,left:viewport.scrollLeft,top:viewport.scrollTop};viewport.setPointerCapture(e.pointerId);}}
    onpointermove={e=>{if(pan){viewport.scrollLeft=pan.left+pan.x-e.clientX;viewport.scrollTop=pan.top+pan.y-e.clientY;}}}
    onpointerup={()=>pan=null} onpointercancel={()=>pan=null} onlostpointercapture={()=>pan=null}>
    {#if source}<img bind:this={image} src={source} alt="Selected scanned book page" draggable="false" onload={()=>{loaded=true;fit();}} onerror={()=>session.message='Unable to load the scanned page.'}/>{:else}<div class="pane-empty">Your scanned page appears here.</div>{/if}
  </div>
  {#if row?.figures?.length&&!row.live}<div class="figure-strip"><span class="small muted">Figures</span>{#each row.figures as figure}<button class="small" title={figure.description} disabled={session.running||session.pending} onclick={()=>open('figure',figure)}>Edit crop · {figure.id.replace('figure-','')}</button>{/each}</div>{/if}
</section>
