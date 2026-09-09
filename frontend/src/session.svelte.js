export const API_VERSION = 9;
export async function api(url, body) {
  const response = await fetch(url, body === undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Request failed');
  return result;
}
export function pageLabel(row) { return row?.page_number ? `Page ${row.page_number}` : row?.has_text ? 'Unnumbered page' : `Capture ${row?.capture || ''}`; }
export function parseHash(hash) {
  const m = /^#book-([a-f0-9]{12})\/(?:page-([0-9]{6})-([12])|number-([0-9ivxlcdm]+))$/i.exec(hash);
  return m ? {book:m[1],key:m[2]?`${m[2]}:${Number(m[3])-1}`:null,number:m[4]} : null;
}
export class Session {
  ready=$state(false); warning=$state(''); message=$state(''); pending=$state(false);
  books=$state([]); book=$state(''); rows=$state.raw([]); captures=$state.raw([]); active=$state('');
  status=$state.raw({running:false,live_pages:[]}); follow=$state(true); mode=$state('read');
  models=$state([]); model=$state(''); custom=$state(''); effort=$state('low');
  provider=$state('codex'); localModels=$state([]); connectionMessage=$state('');
  openrouterModel=$state(''); openrouterKey=$state(''); openrouterModels=$state([]);
  localProfiles=$state({ollama:{url:'http://127.0.0.1:11434',model:''},llamacpp:{url:'http://127.0.0.1:8080',model:''}});
  edit=$state(null); crop=$state(null); imageVersion=$state(0); scrollRequest=$state(null); issueRequest=$state(null);
  checkpoint=''; polling=false; timer=null; disposed=false;
  get running(){return this.status.running;}
  get remaining(){return this.captures.filter(p=>!p.done).length;}
  get dirty(){return Boolean(this.edit && (this.edit.text!==this.edit.original || this.edit.number!==this.edit.oldNumber || this.edit.chapter!==this.edit.oldChapter));}
  get selected(){return this.viewRows.find(r=>r.key===this.active);}
  get localConfig(){return this.localProfiles[this.provider];}
  get modelId(){return this.provider==='openrouter'?this.openrouterModel.trim():this.provider==='codex'?(this.model==='custom'?this.custom.trim():this.model):this.localConfig.model.trim();}
  get efforts(){return this.models.find(m=>m.id===this.model)?.efforts || ['low','medium','high','xhigh','max','ultra'];}
  get viewRows(){
    let rows=this.rows;
    if(this.status.book===this.book && this.status.page && this.running){
      const originals=rows.filter(r=>r.capture===this.status.page);
      const live=this.status.live_pages?.length?this.status.live_pages:[{markdown:'',html:'',page_number:null}];
      rows=[...rows.filter(r=>r.capture!==this.status.page),...live.map((r,i)=>({...originals[i],...r,key:`${this.status.page}:${i}`,index:i,capture:this.status.page,live:true,done:false,has_text:false,chapter:originals[i]?.chapter,page_number:r.page_number||originals[i]?.page_number}))];
      rows.sort((a,b)=>a.capture.localeCompare(b.capture)||a.index-b.index);
    }
    return rows;
  }
  get issues(){return this.viewRows.flatMap(row=>row.has_text&&!row.live?[...(this.edit?.key===row.key?this.edit.text:row.markdown).matchAll(/\[illegible\]/gi)].map((m,i)=>({key:row.key,offset:m.index,index:i})):[]);}
  busyCapture(capture){return this.running && this.status.book===this.book && (!this.status.page || this.status.page===capture);}
  async run(fn){if(this.pending)return;this.pending=true;this.message='';try{return await fn();}catch(e){this.message=e.message||String(e);}finally{this.pending=false;}}
  discard(){if(this.crop){this.message='Save or cancel the crop first.';return false;}return !this.dirty||confirm('Discard unsaved Markdown corrections?');}
  setModel(){localStorage.setItem('book-be-gone-model',this.modelId);if(!this.efforts.includes(this.effort))this.effort=this.efforts.includes('low')?'low':this.efforts[0];}
  setEffort(){localStorage.setItem('book-be-gone-effort',this.effort);}
  setProvider(){localStorage.setItem('book-be-gone-provider',this.provider);this.localModels=[];this.connectionMessage='';}
  saveOpenRouterModel(){localStorage.setItem('book-be-gone-openrouter-model',this.openrouterModel.trim());}
  async loadOpenRouterModels(){
    this.connectionMessage='';this.openrouterModels=[];
    const result=await api('/api/openrouter-models',{api_key:this.openrouterKey});
    if(this.provider!=='openrouter')return;
    this.openrouterModels=result.models;
    this.connectionMessage=result.models.length?`${result.models.length} vision models with structured output available`:'No compatible vision models found';
  }
  saveLocalSettings(clearModels=false){localStorage.setItem('book-be-gone-local-profiles',JSON.stringify(this.localProfiles));if(clearModels){this.localModels=[];this.connectionMessage='';}}
  async loadLocalModels(){
    const provider=this.provider,url=this.localConfig.url.trim();
    this.connectionMessage='';this.localModels=[];
    const result=await api('/api/local-models',{provider,server_url:url});
    if(this.provider!==provider||this.localConfig.url.trim()!==url)return;
    this.localModels=result.models;
    if(!this.localConfig.model&&result.models.length){this.localConfig.model=result.models[0].id;this.saveLocalSettings();}
    this.connectionMessage=result.models.length?`Connected · ${result.models.length} models available`:'Connected · no models loaded';
  }
  async initialize(){
    try{
      const status=await api('/api/status');
      if(status.api_version!==API_VERSION){this.warning='Server update needed. Restart Book-Be-Gone, then reload. Completed OCR is saved.';return;}
      this.status=status;
      const [books,catalog]=await Promise.all([api('/api/books'),api('/api/models')]);
      this.books=books;this.models=catalog.models;
      const model=localStorage.getItem('book-be-gone-model')||catalog.default;
      this.model=this.models.some(m=>m.id===model)?model:'custom';this.custom=this.model==='custom'?model:'';
      const effort=localStorage.getItem('book-be-gone-effort')||'low';this.effort=this.efforts.includes(effort)?effort:this.efforts[0];
      const provider=localStorage.getItem('book-be-gone-provider');if(['ollama','llamacpp','openrouter'].includes(provider))this.provider=provider;
      this.openrouterModel=localStorage.getItem('book-be-gone-openrouter-model')||'';
      try{const profiles=JSON.parse(localStorage.getItem('book-be-gone-local-profiles')||'{}');for(const key of ['ollama','llamacpp'])for(const field of ['url','model'])if(typeof profiles?.[key]?.[field]==='string')this.localProfiles[key][field]=profiles[key][field];}catch{}
      const saved=parseHash(location.hash)?.book||localStorage.getItem('book-be-gone-book');
      this.book=books.find(b=>b.id===saved)?.id||books[0]?.id||'';
      await this.loadDocument();this.ready=true;
      await this.navigate(location.hash);await this.poll();
      if(!this.disposed)this.timer=setInterval(()=>this.poll().catch(e=>this.message=e.message),700);
    }catch(e){this.warning='Unable to load Book-Be-Gone: '+e.message;}
  }
  destroy(){this.disposed=true;clearInterval(this.timer);}
  async loadDocument(){
    const book=this.book;if(!book){this.rows=[];this.captures=[];this.active='';return;}
    const result=await api('/api/document/'+book);if(this.book!==book||this.disposed)return;
    this.rows=result.pages;this.captures=result.captures;
    if(!this.viewRows.some(r=>r.key===this.active))this.active=this.viewRows[0]?.key||'';
  }
  async changeBook(book){if(book&&!this.books.some(b=>b.id===book))throw Error('Book not found.');if(book===this.book)return true;if(!this.discard())return false;this.edit=null;this.book=book;this.active='';this.checkpoint='';localStorage.setItem('book-be-gone-book',book);await this.loadDocument();return true;}
  async create(title){if(!this.discard())return;const result=await api('/api/books',{title});this.books=await api('/api/books');await this.changeBook(result.id);this.mode='capture';}
  select(key,{scroll=true,manual=true}={}){
    if(!this.viewRows.some(r=>r.key===key))return false;
    if(key!==this.active&&!this.discard())return false;
    if(key!==this.active)this.edit=null;this.active=key;if(manual)this.follow=false;
    if(scroll)this.scrollRequest={key,stamp:Date.now()};return true;
  }
  async navigate(hash,push=false){
    const target=parseHash(hash);if(!target)return;
    const old=this.active.split(':'),source=`#book-${this.book}/page-${old[0]}-${Number(old[1])+1}`;
    if(!await this.changeBook(target.book))return;
    const matches=this.viewRows.filter(r=>target.key?r.key===target.key:r.page_number?.toLowerCase()===target.number.toLowerCase());
    if(matches.length!==1){this.message=matches.length?'That printed number matches more than one page.':'That printed page has not been identified yet.';return;}
    if(this.select(matches[0].key)){this.mode='read';if(push){if(parseHash(source)&&location.hash!==source)history.replaceState(null,'',source);history.pushState(null,'',hash);}}
  }
  startEdit(key=this.active,occurrence=null){
    if(this.crop||!this.select(key))return;
    const row=this.selected;if(!row?.has_text||row.live||this.busyCapture(row.capture))return;
    if(!this.edit||this.edit.key!==key)this.edit={key,capture:row.capture,index:row.index,revision:row.revision,text:row.markdown,original:row.markdown,number:row.page_number||'',oldNumber:row.page_number||'',chapter:row.chapter||'',oldChapter:row.chapter||'',preview:null,reading:false};
    this.edit.reading=false;
    if(occurrence!==null)this.issueRequest={index:occurrence,stamp:Date.now()};
  }
  jumpIssue(direction,offset=null){
    const issues=this.issues;if(!issues.length)return;
    const position=this.viewRows.findIndex(r=>r.key===this.active),at=offset??(direction>0?-1:Infinity);
    const same=issues.filter(i=>i.key===this.active&&(direction>0?i.offset>=at:i.offset<at));
    const later=issues.filter(i=>direction>0?this.viewRows.findIndex(r=>r.key===i.key)>position:this.viewRows.findIndex(r=>r.key===i.key)<position);
    const target=direction>0?same[0]||later[0]||issues[0]:same.at(-1)||later.at(-1)||issues.at(-1);
    this.startEdit(target.key,target.index);this.mode='read';
  }
  async previewEdit(){const edit=this.edit;if(!edit)return;const text=edit.text;const result=await api('/api/render',{book:this.book,text});if(this.edit===edit&&edit.text===text){edit.preview=result.html;edit.reading=true;this.scrollRequest={key:edit.key,stamp:Date.now()};}}
  async saveEdit(){
    const e=this.edit;if(!e)return;
    const body={book:this.book,page:e.capture,printed_index:e.index,revision:e.revision,markdown:e.text,page_number:e.number.trim()||null};
    if(e.chapter!==e.oldChapter)body.chapter_seen=e.chapter.trim()||null;
    await api('/api/save',body);this.edit=null;await this.loadDocument();this.scrollRequest={key:this.active,stamp:Date.now()};this.message='Corrections saved.';
  }
  cancelEdit(){if(this.discard()){this.edit=null;this.scrollRequest={key:this.active,stamp:Date.now()};}}
  async ocr(single=false){
    if(!this.book||!this.modelId)throw Error('Choose a book and OCR model.');
    if(this.dirty||this.crop)throw Error('Save or cancel your edits first.');
    if(single&&this.selected?.has_text&&!confirm('Replace the text for this entire capture with new OCR?'))return;
    const body={book:this.book,model:this.modelId,provider:this.provider};
    if(this.provider==='codex')body.effort=this.effort;
    else if(this.provider==='openrouter'){body.api_key=this.openrouterKey;this.saveOpenRouterModel();}
    else{body.server_url=this.localConfig.url.trim();this.saveLocalSettings();}
    if(single){if(!this.selected)return;body.page=this.selected.capture;}
    await api('/api/ocr',body);this.edit=null;this.follow=true;this.mode='read';await this.poll();
  }
  async linkPages(){if(this.dirty||this.crop||this.running)throw Error('Finish OCR and save or cancel edits first.');const result=await api('/api/link-pages',{book:this.book});this.edit=null;await this.loadDocument();this.message=`Linked references on ${result.changed_pages} pages.`;}
  async export(){
    if(this.dirty||this.crop)throw Error('Save or cancel edits before exporting.');
    const response=await fetch('/api/export/'+this.book);if(!response.ok)throw Error((await response.json()).error);
    const url=URL.createObjectURL(await response.blob()),a=document.createElement('a');a.href=url;a.download=(this.books.find(b=>b.id===this.book)?.title.replace(/[^a-z0-9 _-]/gi,'_')||'book')+'.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async poll(){
    if(this.polling||this.disposed)return;this.polling=true;
    try{
      const status=await api('/api/status');if(this.disposed)return;
      if(status.api_version!==API_VERSION){this.warning='Server update needed. Restart Book-Be-Gone and reload.';this.ready=false;return;}
      this.status=status;const checkpoint=`${status.book}:${status.completed}:${status.running}:${status.last_saved?.capture}`;
      if(checkpoint!==this.checkpoint){await this.loadDocument();this.checkpoint=checkpoint;}
      if(status.book===this.book&&status.page&&status.running&&this.follow&&!this.edit&&!this.crop){const target=this.viewRows.filter(r=>r.capture===status.page).at(-1);if(target){this.select(target.key,{scroll:false,manual:false});this.scrollRequest={key:target.key,bottom:!!target.markdown,stamp:Date.now()};}}
    }finally{this.polling=false;}
  }
}
