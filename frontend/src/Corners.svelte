<script>
  import { geometry } from './imaging.js';
  let {points=$bindable(),paired=false,rectangle=false,onchange=()=>{},disabled=false,label='Crop handles'}=$props();
  let drag=null,overlay;
  function move(index,x,y){
    if(disabled)return;
    let next=points.map(p=>[...p]);x=Math.max(0,Math.min(1,x));y=Math.max(0,Math.min(1,y));
    if(rectangle){
      let [l,t]=next[0],[r,b]=next[2];const left=index===0||index===3,top=index<2;
      if(left)l=Math.min(r-.001,x);else r=Math.max(l+.001,x);
      if(top)t=Math.min(b-.001,y);else b=Math.max(t+.001,y);
      next=[[l,t],[r,t],[r,b],[l,b]];
    }else if(paired)geometry.moveCorner(next,index,[x,y]);else next[index]=[x,y];
    points=next;onchange();
  }
  function pointer(e){if(drag===null)return;const r=overlay.getBoundingClientRect();move(drag,(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height);}
  function key(e,i){const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!delta)return;e.preventDefault();const step=e.shiftKey?.02:.002;move(i,points[i][0]+delta[0]*step,points[i][1]+delta[1]*step);}
</script>
<svg bind:this={overlay} class="corner-overlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" role="group" aria-label={label}
  onpointermove={pointer} onpointerup={()=>drag=null} onpointercancel={()=>drag=null} onlostpointercapture={()=>drag=null}>
  <polygon points={points.map(p=>p.map(v=>v*1000).join(',')).join(' ')} />
  {#each points as point,i}<g><circle cx={point[0]*1000} cy={point[1]*1000} r="17" tabindex={disabled?-1:0} role="button" aria-label={`Corner ${i+1}; arrow keys to adjust`} aria-disabled={disabled}
    onpointerdown={e=>{if(disabled)return;e.preventDefault();drag=i;overlay.setPointerCapture(e.pointerId);pointer(e);}} onkeydown={e=>key(e,i)}/><text x={point[0]*1000} y={point[1]*1000}>{i+1}</text></g>{/each}
</svg>
