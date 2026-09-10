// Compare words, whitespace and punctuation independently within each saved hunk.
export function inlineSegments(before, after, change) {
  const tokens = text => text.match(/[\p{L}\p{N}\p{M}_]+|\s+|[^\p{L}\p{N}\p{M}_\s]/gu) || [];
  const a=tokens(before), b=tokens(after), result={old:[],new:[]};
  function emit(side,text,changed=false){
    const list=result[side], last=list.at(-1);
    if(last && Boolean(last.change)===changed)last.text+=text;
    else list.push(changed?{text,change}:{text});
  }
  let start=0, endA=a.length, endB=b.length;
  while(start<endA&&start<endB&&a[start]===b[start])start++;
  while(endA>start&&endB>start&&a[endA-1]===b[endB-1]){endA--;endB--;}
  emit('old',a.slice(0,start).join(''));emit('new',b.slice(0,start).join(''));
  const n=endA-start,m=endB-start;
  // Bound memory/work for exceptionally large, completely rewritten pages.
  if(n*m>2_000_000){
    emit('old',a.slice(start,endA).join(''),true);
    emit('new',b.slice(start,endB).join(''),true);
  }else{
    const width=m+1, scores=new Uint32Array((n+1)*width);
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)
      scores[i*width+j]=a[start+i]===b[start+j]?1+scores[(i+1)*width+j+1]:Math.max(scores[(i+1)*width+j],scores[i*width+j+1]);
    let i=0,j=0;
    while(i<n||j<m){
      if(i<n&&j<m&&a[start+i]===b[start+j]){
        emit('old',a[start+i++]);emit('new',b[start+j++]);
      }else if(i<n&&(j===m||scores[(i+1)*width+j]>=scores[i*width+j+1])){
        emit('old',a[start+i++],true);
      }else emit('new',b[start+j++],true);
    }
  }
  // Empty-side markers allow accepting pure insertions/deletions from either pane.
  if(before!==after){
    if(!result.old.some(s=>s.change))emit('old','',true);
    if(!result.new.some(s=>s.change))emit('new','',true);
  }
  emit('old',a.slice(endA).join(''));emit('new',b.slice(endB).join(''));
  return result;
}

// Retain all unchanged context and whitespace around selectable changes.
export function pageSegments(review, index, side) {
  const page = review[side].pages[index];
  if (!page) return [];
  const whole = review.changes.find(c => c.field === 'capture' || c.page === index && c.field === 'page');
  if (whole) return inlineSegments(review.old.pages[index]?.markdown||'',review.new.pages[index]?.markdown||'',whole)[side];
  if(review.format>=2){
    const text=Array.from(review.old.pages[index].markdown), result=[];
    let cursor=0;
    for(const change of review.changes.filter(c=>c.page===index&&c.field==='markdown')){
      result.push({text:text.slice(cursor,change.start).join('')});
      result.push({text:change[side],change});
      cursor=change.end;
    }
    result.push({text:text.slice(cursor).join('')});
    return result;
  }
  const lines = review.old.pages[index].markdown.match(/[^\n]*\n|[^\n]+$/g) || [];
  const result = [];
  let cursor = 0;
  for (const change of review.changes.filter(c => c.page === index && c.field === 'markdown')) {
    result.push({text: lines.slice(cursor, change.start).join('')});
    result.push(...inlineSegments(change.old,change.new,change)[side]);
    cursor = change.end;
  }
  result.push({text: lines.slice(cursor).join('')});
  return result;
}
