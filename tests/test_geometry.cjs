const assert=require('node:assert/strict');
const {transform,warp}=require('../geometry.js').PageGeometry;
function near(a,b){a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-7,`${a} != ${b}`))}
const corners=[[10,20],[150,40],[130,180],[30,160]];
const map=transform(corners);
[[0,0],[1,0],[1,1],[0,1]].forEach((p,i)=>near(map(...p),corners[i]));
// A projective map preserves straight lines, including interior text baselines.
const a=map(0,.4),b=map(.5,.4),c=map(1,.4);
assert.ok(Math.abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))<1e-7);
assert.throws(()=>transform([[0,0],[30,30],[30,0],[0,30]]));
assert.throws(()=>transform([[0,0],[0,0],[30,30],[0,30]]));
const source={width:32,height:32,data:new Uint8ClampedArray(32*32*4)};
for(let y=0;y<32;y++)for(let x=0;x<32;x++)source.data.set([x*8,y*8,100,255],(y*32+x)*4);
const result=warp(source,[[4,4],[27,4],[27,27],[4,27]],null);
assert.equal(result.width,23);assert.equal(result.height,23);
assert.deepEqual([...result.data.slice(0,4)],[32,32,100,255]);
assert.deepEqual([...result.data.slice(-4)],[216,216,100,255]);
const ratio=warp(source,[[0,0],[31,0],[31,31],[0,31]],.5);
assert.equal(ratio.width/ratio.height,.5);
assert.throws(()=>warp(source,corners,0));
console.log('Perspective mapping, crop pixels, invalid corners, and aspect ratio passed');
