<script>
  import { tick } from 'svelte';
  import { pageLabel,parseHash } from './session.svelte.js';
  let {session}=$props();
  let pane,textarea=$state(),scrolling=false,frame=null;
  let rows=$derived(session.viewRows),editing=$derived(session.edit&&!session.edit.reading);
  let current=$derived(session.selected);
  function content(node,html){
    function update(value){node.innerHTML=value||'';const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);let ordinal=0;for(const text of nodes){const matches=[...text.textContent.matchAll(/\[illegible\]/gi)];if(!matches.length)continue;let start=0;const fragment=document.createDocumentFragment();for(const m of matches){fragment.append(document.createTextNode(text.textContent.slice(start,m.index)));const mark=document.createElement('mark');mark.textContent=m[0];mark.dataset.issue=ordinal++;mark.tabIndex=0;mark.setAttribute('role','button');mark.title='Correct unclear text';fragment.append(mark);start=m.index+m[0].length;}fragment.append(document.createTextNode(text.textContent.slice(start)));text.replaceWith(fragment);}}
    update(html);return {update};
  }
  function scroll(key,bottom=false){
    const article=pane?.querySelector(`[data-key="${key}"]`);if(!article)return;
    scrolling=true;const offset=article.getBoundingClientRect().top-pane.getBoundingClientRect().top+pane.scrollTop;
    pane.scrollTop=bottom?offset+article.offsetHeight-pane.clientHeight:offset;
    requestAnimationFrame(()=>scrolling=false);
  }
  $effect(()=>{const request=session.scrollRequest;if(request)tick().then(()=>{if(session.scrollRequest===request)scroll(request.key,request.bottom);});});
  $effect(()=>{const request=session.issueRequest;if(request)tick().then(()=>selectIssue(request.index));});
  function selectIssue(index){
    if(!textarea)return;const match=[...textarea.value.matchAll(/\[illegible\]/gi)][index];if(!match)return;
    textarea.focus();textarea.setSelectionRange(match.index,match.index+match[0].length);
    const mirror=document.createElement('div'),style=getComputedStyle(textarea);
    Object.assign(mirror.style,{position:'fixed',visibility:'hidden',whiteSpace:'pre-wrap',overflowWrap:'break-word',width:textarea.clientWidth+'px',padding:style.padding,font:style.font,lineHeight:style.lineHeight});mirror.textContent=textarea.value.slice(0,match.index);const marker=document.createElement('span');marker.textContent='|';mirror.append(marker);document.body.append(mirror);textarea.scrollTop=Math.max(0,marker.getBoundingClientRect().top-mirror.getBoundingClientRect().top-textarea.clientHeight/2);mirror.remove();
  }
  function clicked(e){
    const mark=e.target.closest('[data-issue]');if(mark){session.startEdit(mark.closest('article').dataset.key,Number(mark.dataset.issue));return;}
    const link=e.target.closest('a');if(!link||e.button!==0||e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;const hash=link.getAttribute('href');if(parseHash(hash)){e.preventDefault();session.run(()=>session.navigate(hash,true));}
  }
  function takeControl(){scrolling=false;session.scrollRequest=null;session.follow=false;}
  function syncScroll(){if(scrolling||frame||session.edit||session.crop||session.follow)return;frame=requestAnimationFrame(()=>{frame=null;if(!pane)return;const top=pane.getBoundingClientRect().top+35;const node=[...pane.querySelectorAll('article')].find(n=>n.getBoundingClientRect().bottom>top);if(node)session.select(node.dataset.key,{scroll:false});});}
  function issue(direction){session.jumpIssue(direction,editing?(direction>0?textarea?.selectionEnd:textarea?.selectionStart):null);}
</script>
<section class="transcript-pane">
  <div class="panelbar"><span class="eyebrow">{editing?'EDIT MARKDOWN':'TRANSCRIPT'}</span><span class="grow"></span>
    {#if session.edit}<button disabled={session.pending} onclick={()=>session.edit.reading?session.startEdit():session.run(()=>session.previewEdit())}>{session.edit.reading?'Edit':'Preview'}</button><button disabled={session.pending} onclick={()=>session.cancelEdit()}>Cancel</button><button class="primary" disabled={!session.dirty||session.pending||session.busyCapture(session.edit.capture)} onclick={()=>session.run(()=>session.saveEdit())}>Save</button>
    {:else}<button disabled={!current?.has_text||current?.live||session.pending||session.busyCapture(current?.capture)} onclick={()=>session.startEdit()}>Edit Markdown</button>{/if}
  </div>
  {#if session.issues.length}<div class="issuebar"><span>{session.issues.length} unclear {session.issues.length===1?'passage':'passages'}</span><span class="grow"></span><button aria-label="Previous unclear passage" onclick={()=>issue(-1)}>↑</button><button aria-label="Next unclear passage" onclick={()=>issue(1)}>Next unclear ↓</button></div>{/if}
  {#if editing}
    <div class="markdown-editor"><textarea bind:this={textarea} aria-label="Edit page Markdown" spellcheck="false" bind:value={session.edit.text} readonly={session.busyCapture(session.edit.capture)} oninput={()=>session.edit.preview=null}></textarea>
      <details class="metadata"><summary>Page & chapter</summary><div><label>Printed page<input aria-label="Printed page number" maxlength="200" bind:value={session.edit.number}/></label><label>Chapter<input aria-label="Chapter" maxlength="200" bind:value={session.edit.chapter}/></label></div></details>
    </div>
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions (Focusable reading region delegates links and correction controls.) -->
  <div class="book-scroll" class:hidden={editing} bind:this={pane} role="region" aria-label="Continuous book Markdown" tabindex="0" onclick={clicked}
    onkeydown={e=>{if(e.key==='Enter'&&e.target.matches('[data-issue]')){e.preventDefault();session.startEdit(e.target.closest('article').dataset.key,Number(e.target.dataset.issue));}}}
    onwheel={takeControl} ontouchstart={takeControl} onpointerdown={takeControl} onscroll={syncScroll}>
    {#each rows as row(row.key)}
      <article data-key={row.key} data-live={!!row.live} class:selected={session.active===row.key}>
        <div class="page-heading"><button onclick={()=>session.select(row.key,{scroll:false})}>{pageLabel(row)}</button><span class="small muted">{row.live?'Transcribing…':!row.done?'Awaiting OCR':row.chapter||''}</span></div>
        <div class="page-content" use:content={session.edit?.key===row.key&&session.edit.preview!==null?session.edit.preview:row.html}></div>
        {#if !row.markdown}<p class="muted">{row.live?(session.status.phase||'Reading page')+'…':row.has_text?'Blank page':'Ready to transcribe.'}</p>{/if}
      </article>
    {:else}<div class="pane-empty">Capture a page to begin.</div>{/each}
  </div>
  {#if current}<footer class="pane-footer" title={current.filename||''}>{pageLabel(current)}<span class="grow"></span>{session.edit?(session.dirty?'Unsaved changes':'Saved'):`Capture ${current.capture}`}</footer>{/if}
</section>
<svelte:window onkeydown={e=>{if((e.ctrlKey||e.metaKey)&&e.key==='s'&&session.edit){e.preventDefault();if(session.dirty&&!session.pending)session.run(()=>session.saveEdit());}}}/>
