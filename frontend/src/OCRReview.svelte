<script>
  import { pageSegments } from './review-text.js';
  let {session}=$props();
  let dialog;
  let source=$state(false);
  let review=$derived(session.review);
  let pages=$derived(Array.from({length:Math.max(review.old.pages.length,review.new.pages.length)},(_,i)=>i));
  $effect(()=>{if(review&&dialog&&!dialog.open)dialog.showModal();});
  function toggle(id){const group=review.changes.find(c=>c.id===id)?.group||[id];review.selected=review.selected.includes(id)?review.selected.filter(x=>!group.includes(x)):[...new Set([...review.selected,...group])];}
  function label(field){return field==='page_number'?'Page number':field==='chapter_seen'?'Chapter':field==='capture'?'Entire capture':'Entire page (including figures)';}
  function rendered(node,value){
    let previous;
    function update({html,selected}){
      if(html!==previous){node.innerHTML=html;previous=html;}
      for(const mark of node.querySelectorAll('[data-change]')){
        const accepted=selected.includes(mark.dataset.change);
        mark.classList.toggle('accepted',accepted);mark.setAttribute('aria-checked',String(accepted));
        mark.setAttribute('aria-label',`${accepted?'Keep saved version of':'Accept'} change ${Number(mark.dataset.change)+1}`);
      }
    }
    function click(e){const mark=e.target.closest('[data-change]');if(mark){e.preventDefault();toggle(mark.dataset.change);}else if(e.target.closest('a'))e.preventDefault();}
    function key(e){if((e.key==='Enter'||e.key===' ')&&e.target.closest('[data-change]')){e.preventDefault();toggle(e.target.closest('[data-change]').dataset.change);}}
    node.addEventListener('click',click);node.addEventListener('keydown',key);update(value);
    return {update,destroy(){node.removeEventListener('click',click);node.removeEventListener('keydown',key);}};
  }
</script>
<dialog bind:this={dialog} onclose={()=>session.review=null}>
  <header><h2>Review OCR changes</h2><button onclick={()=>dialog.close()}>Close</button></header>
  <p>Red highlights show old text; green highlights show new text. Click either highlight to accept that change, or click again to keep the saved version. Matching Markdown formatting is selected together to preserve valid formatting. Outlined changes are selected. Nothing is saved until you choose Save.</p>
  <div class="review-tools"><button onclick={()=>review.selected=review.changes.map(c=>c.id)}>Select all</button><button onclick={()=>review.selected=[]}>Select none</button><span aria-live="polite">{review.selected.length} of {review.changes.length} changes selected</span></div>
  <label><input type="checkbox" aria-label="Show Markdown source" bind:checked={source}/> Show Markdown source</label>
  {#each pages as index}
    <section class="page-review" aria-label={`Compare page ${index+1}`}>
      <h3>Page {index+1} of capture</h3>
      <div class="metadata-changes">
        {#each review.changes.filter(c=>(c.page===index||c.page===null&&index===0)&&c.field!=='markdown') as change}
          <label data-field={change.field}><input type="checkbox" checked={review.selected.includes(change.id)} onchange={()=>toggle(change.id)}/> Accept {label(change.field)}{#if change.field==='page_number'||change.field==='chapter_seen'}: <del>{change.old??'(none)'}</del> → <ins>{change.new??'(none)'}</ins>{/if}</label>
          {#if change.field==='page'||change.field==='capture'}<p class="small muted">Figures or a changed page count require accepting the whole {change.field} together.</p>{/if}
        {/each}
      </div>
      <div class="comparison">
        {#each ['old','new'] as side}
          {@const page=review[side].pages[index]}
          <div class="version" data-side={side}>
            <h4>{side==='old'?'Saved OCR':'New OCR'} <span>{page?.page_number?`· Page ${page.page_number}`:''}</span></h4>
            <p class="chapter">{page?.chapter_seen||page?.chapter||'No chapter identified'}</p>
            {#if page}
              {#if !source && review.rendered?.[side]?.[index]}
                {@const view=review.rendered[side][index]}
                <div class="full-page rendered-markdown" use:rendered={{html:view.html,selected:review.selected}}></div>
                {#if view.hidden_ids.length}<details class="hidden-changes"><summary>Formatting / non-visible changes ({view.hidden_ids.length})</summary><div class="hidden-change-list">{#each view.hidden_ids as id}{@const change=review.changes.find(c=>c.id===id)}<button data-hidden-change={id} aria-pressed={review.selected.includes(id)} onclick={()=>toggle(id)}>Change {Number(id)+1}: <code>{change.old||'∅'}</code> → <code>{change.new||'∅'}</code>{review.selected.includes(id)?' ✓':''}</button>{/each}</div></details>{/if}
              {:else}<div class="full-page">{#each pageSegments(review,index,side) as segment}{#if segment.change}<button class="highlight" class:accepted={review.selected.includes(segment.change.id)} data-change={segment.change.id} role="checkbox" aria-checked={review.selected.includes(segment.change.id)} aria-label={`${review.selected.includes(segment.change.id)?'Keep saved version of':'Accept'} change ${Number(segment.change.id)+1}`} title={`Change ${Number(segment.change.id)+1} · click to toggle acceptance`} onclick={()=>toggle(segment.change.id)}>{segment.text||'∅'}</button>{:else}{segment.text}{/if}{/each}</div>{/if}
            {:else}<p class="muted">No corresponding page.</p>{/if}
          </div>
        {/each}
      </div>
    </section>
  {/each}
  {#if !review.changes.length}<p>No changes found.</p>{/if}
  <footer><button disabled={session.pending} onclick={()=>session.run(()=>session.resolveReview(true))}>Discard new OCR</button><button class="primary" disabled={session.pending} onclick={()=>session.run(()=>session.resolveReview())}>Save selected changes</button></footer>
  {#if session.message}<p role="alert">{session.message}</p>{/if}
</dialog>
<style>
  .rendered-markdown{white-space:normal}.rendered-markdown :global(mark.highlight){cursor:pointer;color:inherit;border-radius:2px;background:#fde2e2}.version[data-side=new] .rendered-markdown :global(mark.highlight){background:#dcf3df}.rendered-markdown :global(mark.accepted){outline:2px solid #267956;outline-offset:1px}.rendered-markdown :global(mark:focus-visible){outline:3px solid #296da8}.rendered-markdown :global(pre){white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f5f1;padding:12px}.rendered-markdown :global(img){max-width:100%;height:auto}.rendered-markdown :global(table){border-collapse:collapse;display:block;overflow:auto}.rendered-markdown :global(td),.rendered-markdown :global(th){border:1px solid #ddd;padding:6px}.rendered-markdown :global(blockquote){border-left:3px solid #ccd4c9;padding-left:12px;margin-left:0}.hidden-changes{font-size:12px;margin-bottom:12px}.hidden-changes button{display:block;max-width:100%;white-space:pre-wrap;overflow-wrap:anywhere;text-align:left;margin-top:6px}.hidden-changes button[aria-pressed=true]{outline:2px solid #267956}
  dialog{width:min(1400px,96vw);max-height:94dvh;border:1px solid #ccd4c9;border-radius:10px;padding:24px;overflow:auto}dialog::backdrop{background:#0006}header,footer{display:flex;justify-content:space-between;gap:12px}.review-tools{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.page-review{margin-top:24px}.metadata-changes{display:grid;gap:8px;margin-bottom:12px}.comparison{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px}.version{min-width:0;border:1px solid #dce1d8;border-radius:6px;padding:20px;background:#fff}.version h4{margin:0 0 8px}.version h4 span,.chapter{font-size:12px;color:#657066}.full-page{white-space:pre-wrap;overflow-wrap:anywhere;font:16px/1.8 Georgia,'Times New Roman',serif}.highlight{display:inline;white-space:inherit;overflow-wrap:inherit;font:inherit;text-align:inherit;color:inherit;border:0;border-radius:2px;padding:0;min-height:0;box-decoration-break:clone;background:#fde2e2}.highlight:hover{background:#f9caca}.highlight.accepted{outline:2px solid #267956;outline-offset:1px}[data-side=new] .highlight{background:#dcf3df}[data-side=new] .highlight:hover{background:#bfe8c5}.highlight:focus-visible{outline:3px solid #296da8;outline-offset:2px}del{background:#fde2e2}ins{background:#dcf3df;text-decoration:none}footer{position:sticky;bottom:-24px;padding:16px 0;background:white;border-top:1px solid #ddd;margin-top:24px}input{min-height:0}@media(max-width:600px){dialog{padding:12px}.comparison{gap:8px}.version{padding:8px}.full-page{font-size:13px;line-height:1.7}footer{bottom:-12px}}
  .full-page.rendered-markdown{white-space:normal}
  .hidden-changes{margin-top:20px;border-top:1px solid #dce1d8;padding-top:12px}.hidden-change-list{max-height:240px;overflow:auto;overscroll-behavior:contain;padding:3px}
</style>
