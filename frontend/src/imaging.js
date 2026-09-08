import geometryModule from '../../geometry.js';
export const geometry=geometryModule.PageGeometry;
export function correctedImage(image,points,ratio){
  const canvas=document.createElement('canvas');canvas.width=image.videoWidth||image.naturalWidth||image.width;canvas.height=image.videoHeight||image.naturalHeight||image.height;
  const context=canvas.getContext('2d');context.drawImage(image,0,0);
  const original=canvas.toDataURL('image/jpeg',.95);
  if(!points)return {original};
  const transformed=geometry.warp(context.getImageData(0,0,canvas.width,canvas.height),points.map(([x,y])=>[x*(canvas.width-1),y*(canvas.height-1)]),ratio===''||ratio==null?null:Number(ratio));
  canvas.width=transformed.width;canvas.height=transformed.height;canvas.getContext('2d').putImageData(new ImageData(transformed.data,canvas.width,canvas.height),0,0);
  return {original,corrected:canvas.toDataURL('image/jpeg',.95)};
}
