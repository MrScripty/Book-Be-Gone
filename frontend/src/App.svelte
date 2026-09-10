<script>
  import { onMount } from 'svelte';
  import { Session,pageLabel } from './session.svelte.js';
  import ImagePane from './ImagePane.svelte';
  import Transcript from './Transcript.svelte';
  import Capture from './Capture.svelte';
  import CropEditor from './CropEditor.svelte';
  import OCRSettings from './OCRSettings.svelte';
  import OCRReview from './OCRReview.svelte';
  const session=new Session();
  let title=$state(''),creating=$state(false),jump=$state('');
  let index=$derived(session.viewRows.findIndex(r=>r.key===session.active));
  let levels={low:'Low',medium:'Medium',high:'High',xhigh:'Extra high',max:'Max',ultra:'Ultra'};
  onMount(()=>{session.initialize();return()=>session.destroy();});
  function mode(value){if(session.mode===value)return;if(!session.discard())return;session.edit=null;session.mode=value;}
  function closeMenu(e){const details=e.target.closest('details');if(details)details.open=false;}
  async function create(){await session.create(title);title='';creating=false;}
  function jumpPage(){const row=session.viewRows.find(r=>r.page_number?.toLowerCase()===jump.trim().toLowerCase());if(row)session.select(row.key);else session.message='That printed page has not been identified yet.';}
</script>
<svelte:document onpointerdown={e=>{document.querySelectorAll('details.menu[open]').forEach(menu=>{if(!menu.contains(e.target))menu.open=false;});}}/>
<svelte:window onkeydown={e=>{if(e.key==='Escape')document.querySelectorAll('details.menu[open]').forEach(menu=>menu.open=false);}} onhashchange={()=>session.run(()=>session.navigate(location.hash))} onbeforeunload={e=>{if(session.dirty||session.crop){e.preventDefault();e.returnValue='';}}}/>
{#if session.warning}<main class="startup"><div class="brand"><span class="brand-symbol">▤</span> Book-Be-Gone</div><p role="alert">{session.warning}</p><button onclick={()=>location.reload()}>Reload</button></main>
{:else if !session.ready}<main class="startup"><div class="brand"><span class="brand-symbol">▤</span> Book-Be-Gone</div><p>Opening your library…</p></main>
{:else}
<div class="app-shell">
  <header class="app-header">
    <div class="brand"><span class="brand-symbol">▤</span><span>Book-Be-Gone</span></div>
    <div class="book-picker"><select aria-label="Book" value={session.book} disabled={session.pending||!!session.crop} onchange={e=>{const value=e.target.value;e.target.value=session.book;session.run(()=>session.changeBook(value));}}><option value="" disabled>Choose a book</option>{#each session.books as book}<option value={book.id}>{book.title}</option>{/each}</select><button class="icon" aria-label="New book" onclick={()=>creating=!creating} disabled={session.pending||!!session.crop}>+</button></div>
    <div class="grow"></div>
    <nav class="mode-switch" aria-label="Workspace"><button aria-pressed={session.mode==='read'} onclick={()=>mode('read')}>Read</button><button aria-pressed={session.mode==='capture'} disabled={!session.book} onclick={()=>mode('capture')}>Capture</button></nav>
    <details class="menu book-menu"><summary aria-label="Book tools">•••</summary><div class="menu-content"><button disabled={!session.book||session.pending||session.running||session.dirty||!!session.crop} onclick={e=>{closeMenu(e);session.run(()=>session.linkPages());}}>Link page references</button><button disabled={!session.book||session.pending||session.dirty||!!session.crop||session.remaining>0||!session.captures.length} onclick={e=>{closeMenu(e);session.run(()=>session.export());}}>Export book (.zip)</button></div></details>
  </header>
  {#if creating}<form class="new-book" onsubmit={e=>{e.preventDefault();session.run(create);}}><input aria-label="New book title" placeholder="Book title" maxlength="200" bind:value={title}/><button type="submit" class="primary" disabled={!title.trim()||session.pending}>Create book</button><button type="button" onclick={()=>creating=false}>Cancel</button></form>{/if}
  {#if session.message}<div class="notice" role="alert"><span>{session.message}</span><button aria-label="Dismiss message" onclick={()=>session.message=''}>✕</button></div>{/if}
  {#if !session.book}<main class="library-empty"><span class="empty-icon">▤</span><h1>A book, one page at a time.</h1><p>Create a book to start capturing.</p><button class="primary" onclick={()=>creating=true}>New book</button></main>
  {:else}
    <div class="workflow-bar">
      {#if session.mode==='read'}<div class="page-navigation"><button class="icon" aria-label="Previous page" disabled={index<=0||!!session.crop} onclick={()=>session.select(session.viewRows[index-1]?.key)}>←</button><select aria-label="Book page" value={session.active} disabled={!session.viewRows.length||!!session.crop} onchange={e=>{const value=e.target.value;e.target.value=session.active;session.select(value);}}>{#if !session.viewRows.length}<option>No pages yet</option>{/if}{#each session.viewRows as row}<option value={row.key}>{pageLabel(row)}{row.chapter?' · '+row.chapter:''}{row.live?' · live':!row.done?' · pending':''}</option>{/each}</select><button class="icon" aria-label="Next page" disabled={index<0||index>=session.viewRows.length-1||!!session.crop} onclick={()=>session.select(session.viewRows[index+1]?.key)}>→</button><form class="page-jump" onsubmit={e=>{e.preventDefault();jumpPage();}}><input aria-label="Jump to printed page" placeholder="Page #" bind:value={jump}/><button aria-label="Go to printed page" type="submit">↵</button></form></div>{:else}<span class="muted">{session.captures.length} captures · {session.remaining} to transcribe</span>{/if}
      <span class="grow"></span>
      <div class="ocr-controls"><OCRSettings {session} {levels}/>
      <div class="split-button"><button class="primary" disabled={session.running||session.pending||!!session.crop||session.dirty||!session.remaining} onclick={()=>session.run(()=>session.ocr())}>{session.running?'Transcribing…':session.remaining?`OCR remaining · ${session.remaining}`:'OCR complete'}</button><details class="menu"><summary class="primary" aria-label="More OCR actions">⌄</summary><div class="menu-content"><button disabled={!session.selected||session.running||session.pending||!!session.crop||session.dirty} onclick={e=>{closeMenu(e);session.run(()=>session.ocr(true));}}>{session.selected?.has_text?'Redo selected capture':'OCR selected capture'}</button></div></details></div></div>
    </div>
    {#if session.mode==='capture'}<Capture {session}/>{:else}<main class="reading-workspace"><ImagePane {session}/><Transcript {session}/></main>{/if}
  {/if}
  <footer class="statusbar" aria-live="polite"><span class:working={session.running} class="status-dot"></span>
    {#if session.status.error}<span class="error">{session.status.error}</span>{:else if session.running}<span class="status-copy">{session.status.phase} · Capture {session.status.page||'…'}{session.status.live_pages?.some(p=>p.page_number)?' · page '+session.status.live_pages.map(p=>p.page_number).filter(Boolean).join(', '):''} · {session.status.elapsed||0}s</span>{:else}<span>{session.book?`${session.captures.filter(p=>p.done).length} / ${session.captures.length} captures transcribed`:'Ready'}</span>{/if}
    <span class="grow"></span>{#if session.running}<label><input type="checkbox" bind:checked={session.follow}/> Follow OCR</label>{/if}
  </footer>
</div>
{#if session.crop}{#key session.crop}<CropEditor {session}/>{/key}{/if}
{#if session.review}<OCRReview {session}/>{/if}
{/if}
