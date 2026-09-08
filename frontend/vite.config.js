import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
export default defineConfig({
  plugins:[svelte()], build:{outDir:'dist'},
  server:{host:'127.0.0.1',strictPort:true,fs:{allow:['..']},proxy:{'/api':{
    target:'http://127.0.0.1:8765',changeOrigin:true,
    configure(proxy){proxy.on('proxyReq',(out,req)=>{
      if(req.headers.origin===`http://${req.headers.host}`)out.setHeader('Origin','http://127.0.0.1:8765');
    });}
  }}}
});
