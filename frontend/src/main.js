import { mount } from 'svelte';
import App from './App.svelte';
import './style.css';
// Carry existing preferences across the project rename on the same origin.
for (const key of ['book', 'model', 'effort', 'camera']) {
  const name = 'book-be-gone-' + key;
  const previous = localStorage.getItem('pagescribe-' + key);
  if (localStorage.getItem(name) === null && previous !== null) localStorage.setItem(name, previous);
}
mount(App,{target:document.getElementById('app')});
