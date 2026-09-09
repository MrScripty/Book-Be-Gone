<script>
  let {session, levels} = $props();
</script>

<details class="menu settings-menu">
  <summary aria-label="OCR settings">
    {#if session.provider==='codex'}
      {session.modelId.replace(/^gpt-/, '')||'Model'} <span class="muted">/ {levels[session.effort]}</span>
    {:else if session.provider==='openrouter'}
      OpenRouter <span class="muted">/ {session.modelId||'Choose model'}</span>
    {:else}
      {session.provider==='ollama'?'Ollama':'llama.cpp'} <span class="muted">/ {session.modelId||'Choose model'}</span>
    {/if}
    <span class="chevron">⌄</span>
  </summary>
  <div class="menu-content settings">
    <label>Provider
      <select aria-label="OCR provider" bind:value={session.provider} disabled={session.running||session.pending} onchange={()=>session.setProvider()}>
        <option value="codex">Codex</option><option value="ollama">Ollama</option><option value="llamacpp">llama.cpp</option><option value="openrouter">OpenRouter</option>
      </select>
    </label>
    {#if session.provider==='codex'}
      <label>Model<select aria-label="OCR model" bind:value={session.model} disabled={session.running||session.pending} onchange={()=>session.setModel()}>{#each session.models as model}<option value={model.id}>{model.name}</option>{/each}<option value="custom">Custom model…</option></select></label>
      {#if session.model==='custom'}<input aria-label="Custom OCR model identifier" placeholder="Model identifier" bind:value={session.custom} disabled={session.running||session.pending} onchange={()=>session.setModel()}/>{/if}
      <label>Thinking<select aria-label="Thinking level" bind:value={session.effort} disabled={session.running||session.pending} onchange={()=>session.setEffort()}>{#each session.efforts as effort}<option value={effort}>{levels[effort]||effort}</option>{/each}</select></label>
    {:else if session.provider==='openrouter'}
      <label>API key<input aria-label="OpenRouter API key" type="password" autocomplete="off" spellcheck="false" placeholder={session.status.openrouter_key_configured?'Using server key (optional override)':'OpenRouter API key'} bind:value={session.openrouterKey} disabled={session.running||session.pending}/></label>
      <p class="muted">Entered keys last until reload. To keep a key on the server, set OPENROUTER_API_KEY.</p>
      <button disabled={session.running||session.pending||(!session.openrouterKey&&!session.status.openrouter_key_configured)} onclick={()=>session.run(()=>session.loadOpenRouterModels())}>{session.pending?'Connecting…':'Load models'}</button>
      {#if session.connectionMessage}<p class="muted" role="status">{session.connectionMessage}</p>{/if}
      <label>Model<input aria-label="OpenRouter OCR model" list="openrouter-ocr-models" placeholder="provider/model" bind:value={session.openrouterModel} disabled={session.running||session.pending} onchange={()=>session.saveOpenRouterModel()}/></label>
      <datalist id="openrouter-ocr-models">{#each session.openrouterModels as model}<option value={model.id}>{model.name}</option>{/each}</datalist>
      <p class="muted">Pages are sent to OpenRouter and its model provider. Usage is billed to your OpenRouter account. Choose a vision model with structured output support.</p>
    {:else}
      <label>Server URL<input aria-label="Local server URL" type="url" bind:value={session.localConfig.url} disabled={session.running||session.pending} onchange={()=>session.saveLocalSettings(true)}/></label>
      <button disabled={session.running||session.pending||!session.localConfig.url.trim()} onclick={()=>session.run(()=>session.loadLocalModels())}>{session.pending?'Connecting…':'Load models'}</button>
      {#if session.connectionMessage}<p class="muted" role="status">{session.connectionMessage}</p>{/if}
      <label>Model<input aria-label="Local OCR model" list="local-ocr-models" placeholder="Choose or enter a vision model" bind:value={session.localConfig.model} disabled={session.running||session.pending} onchange={()=>session.saveLocalSettings()}/></label>
      <datalist id="local-ocr-models">{#each session.localModels as model}<option value={model.id}>{model.name}</option>{/each}</datalist>
      <p class="muted">Use a vision model with JSON output support. Pages are sent only to this server. Generation settings come from the server.</p>
    {/if}
  </div>
</details>

<style>
  .settings {width:320px;max-width:calc(100vw - 32px);max-height:70vh;overflow:auto;}
  .settings input,.settings select {width:100%;min-width:0;}
  .settings p {font-size:12px;line-height:1.45;margin:0;white-space:normal;}
</style>
