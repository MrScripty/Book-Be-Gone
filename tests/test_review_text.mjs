import assert from 'node:assert/strict';
import {pageSegments,inlineSegments} from '../frontend/src/review-text.js';
const old='Opening context\n\nOld wording\n\nUnchanged middle\nDeleted line\nClosing context';
const updated='Opening context\n\nNew wording\n\nUnchanged middle\nClosing context';
const review={old:{pages:[{markdown:old}]},new:{pages:[{markdown:updated}]},changes:[
  {id:'0',page:0,field:'markdown',start:2,end:3,old:'Old wording\n',new:'New wording\n'},
  {id:'1',page:0,field:'markdown',start:5,end:6,old:'Deleted line\n',new:''}
]};
for(const side of ['old','new']){
  const segments=pageSegments(review,0,side);
  assert.equal(segments.map(s=>s.text).join(''),review[side].pages[0].markdown);
  assert.equal(segments.filter(s=>s.change).length,2);
  assert.ok(segments.some(s=>!s.change&&s.text.includes('Unchanged middle')));
}
const insert={old:{pages:[{markdown:'End\n'}]},new:{pages:[{markdown:'Start\nEnd\n'}]},changes:[{id:'0',page:0,field:'markdown',start:0,end:0,old:'',new:'Start\n'}]};
for(const side of ['old','new'])assert.equal(pageSegments(insert,0,side).map(s=>s.text).join(''),insert[side].pages[0].markdown);
review.changes=[];
assert.equal(pageSegments(review,0,'old').map(s=>s.text).join(''),old);
review.changes=[{id:'0',field:'capture'}];
assert.equal(pageSegments(review,0,'new').map(s=>s.text).join(''),updated);
assert.deepEqual(pageSegments(review,1,'new'),[]);
console.log('PASS: full-page diff retains context, whitespace, insertions, deletions, and whole-page replacements');
for(const [before,after,removed,added] of [
  ['The reader will know the guiding value.','The reader will understand the guiding value.','know','understand'],
  ['Hello, reader.','Hello; reader.',',',';'],
  ['One old word and another bad word.','One new word and another good word.','oldbad','newgood'],
  ['The café is open.','The café is closed.','open','closed'],
  ['One word.','One extra word.','','extra '],
  ['One extra word.','One word.','extra ',''],
  ['same','same','','']
]){
  const diff=inlineSegments(before,after,{id:'0'});
  assert.equal(diff.old.map(s=>s.text).join(''),before);
  assert.equal(diff.new.map(s=>s.text).join(''),after);
  assert.equal(diff.old.filter(s=>s.change).map(s=>s.text).join(''),removed);
  assert.equal(diff.new.filter(s=>s.change).map(s=>s.text).join(''),added);
}
console.log('PASS: only changed words, punctuation and inserted/deleted text are highlighted');
const separate={format:2,old:{pages:[{markdown:'😀 old and bad.'}]},new:{pages:[{markdown:'😀 new and good.'}]},changes:[
  {id:'0',page:0,field:'markdown',start:2,end:5,old:'old',new:'new'},
  {id:'1',page:0,field:'markdown',start:10,end:13,old:'bad',new:'good'}
]};
for(const side of ['old','new']){
  const segments=pageSegments(separate,0,side);
  assert.equal(segments.map(s=>s.text).join(''),separate[side].pages[0].markdown);
  assert.deepEqual(segments.filter(s=>s.change).map(s=>s.change.id),['0','1']);
}
console.log('PASS: independent selection IDs and Unicode codepoint offsets');
