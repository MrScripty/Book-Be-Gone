/* Projective mapping from a unit rectangle to clockwise page corners. */
(function(root){
  function moveCorner(points,index,position){
    points[index]=[...position];
    points[index ^ 1][1]=position[1];
  }
  function transform(points){
    if(points.length!==4 || points.some(p=>p.length!==2 || p.some(v=>!Number.isFinite(v))))
      throw Error('Choose four page corners');
    for(let i=0;i<4;i++){
      const a=points[i], b=points[(i+1)%4], c=points[(i+2)%4];
      if((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0])<=1e-6)
        throw Error('Corners must outline a non-crossing page: top left, top right, bottom right, bottom left');
    }
    const [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]=points;
    const dx1=x1-x2, dx2=x3-x2, dx3=x0-x1+x2-x3;
    const dy1=y1-y2, dy2=y3-y2, dy3=y0-y1+y2-y3;
    const det=dx1*dy2-dx2*dy1;
    if(Math.abs(det)<1e-9)throw Error('Page selection is too narrow');
    const g=(dx3*dy2-dx2*dy3)/det, h=(dx1*dy3-dx3*dy1)/det;
    return (u,v)=>{
      const d=g*u+h*v+1;
      return [((x1-x0+g*x1)*u+(x3-x0+h*x3)*v+x0)/d,
              ((y1-y0+g*y1)*u+(y3-y0+h*y3)*v+y0)/d];
    };
  }
  function warp(source,points,ratio){
    const map=transform(points);
    const distance=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
    let width=Math.max(distance(points[0],points[1]),distance(points[3],points[2]));
    let height=Math.max(distance(points[0],points[3]),distance(points[1],points[2]));
    if(ratio!==null){
      if(!Number.isFinite(ratio)||ratio<0.1||ratio>10)throw Error('Width / height must be between 0.1 and 10');
      width=Math.max(width,height*ratio);height=width/ratio;
    }
    const scale=Math.min(1,4096/Math.max(width,height));
    width=Math.round(width*scale);height=Math.round(height*scale);
    if(width<16||height<16)throw Error('Select a larger page area');
    const data=new Uint8ClampedArray(width*height*4), src=source.data;
    for(let y=0;y<height;y++)for(let x=0;x<width;x++){
      let [sx,sy]=map(x/(width-1),y/(height-1));
      sx=Math.max(0,Math.min(source.width-1,sx));sy=Math.max(0,Math.min(source.height-1,sy));
      const ix=Math.floor(sx),iy=Math.floor(sy),fx=sx-ix,fy=sy-iy;
      const a=(iy*source.width+ix)*4,b=(iy*source.width+Math.min(ix+1,source.width-1))*4;
      const c=(Math.min(iy+1,source.height-1)*source.width+ix)*4,d=(Math.min(iy+1,source.height-1)*source.width+Math.min(ix+1,source.width-1))*4;
      for(let k=0;k<3;k++)data[(y*width+x)*4+k]=(src[a+k]*(1-fx)+src[b+k]*fx)*(1-fy)+(src[c+k]*(1-fx)+src[d+k]*fx)*fy;
      data[(y*width+x)*4+3]=255;
    }
    return {data,width,height};
  }
  root.PageGeometry={transform,warp,moveCorner};
})(typeof module==='object'?module.exports:globalThis);
