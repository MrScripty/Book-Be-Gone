# Using Book-Be-Gone

[Back to the README](../README.md)

## Choose an OCR provider

Open **OCR settings** beside **OCR remaining** before starting a job. The provider and model remain fixed throughout that job, including retries. Changing the selection does not reprocess completed captures.

### Codex

Install and sign in to the Codex CLI. Book-Be-Gone starts `codex app-server` with your existing login and CLI configuration. The default model is `gpt-5.6-luna` with Low thinking; `BOOK_BE_GONE_MODEL` changes the default. Model access depends on your account.

The model menu lists image-capable entries from your local Codex cache. **Custom model…** accepts another identifier. Thinking offers the levels advertised for the selected model; the browser remembers your model and thinking choices.

The integration uses an ephemeral read-only thread per capture and displays transcription deltas, not reasoning text. Photos go to the provider when OCR starts.

### Ollama and llama.cpp

Select **Ollama** or **llama.cpp**, enter the server URL, choose **Load models**, then select or enter a model name. The defaults are:

- Ollama: `http://127.0.0.1:11434`
- llama.cpp: `http://127.0.0.1:8080`

URLs ending in `/api` for Ollama or `/v1` for llama.cpp also work. Python makes this connection: localhost means the computer running Book-Be-Gone. A LAN server is possible. HTTP and HTTPS are supported, without authentication.

Use a vision model with structured JSON output support. A model listing may include text-only models; listing alone does not establish image support. Load the matching multimodal projector for llama.cpp when the model requires one. Local generation settings come from the server.

Loading models checks connectivity without sending a book photograph. OCR sends images only to your selected server and never falls back to Codex. Verify that the server runs the model locally if you want to avoid cloud processing.

### OpenRouter

Select **OpenRouter**, enter an API key, choose **Load models**, then select or enter an identifier such as `provider/model`. The catalog is filtered for image input, text output and structured outputs.

The model choice is remembered. An entered password-field key stays only in the current page's memory and is cleared on reload. You can instead set `OPENROUTER_API_KEY` before starting Python; an entered key overrides it for that request. Keys are not stored in book files, browser storage or status responses.

The fixed endpoint is `https://openrouter.ai/api/v1`. Pages and prompts go to OpenRouter and the selected upstream provider, and usage is billed to your OpenRouter account. Loading the catalog sends no book images and runs no inference.

Invalid credentials, insufficient credits, rate limits, malformed output and generation failures stop the job while preserving saved text. Provider content restrictions still apply; changing providers cannot guarantee that a filtered passage will be transcribed.

## Capture and straighten pages

Choose **Capture**, start the camera, select the webcam and place a page or spread in good light. Keep it flat and large in the frame.

Four numbered handles control the crop. The top pair share a vertical position, as do the bottom pair. Set them once, then turn pages and capture successive photos. Focus a handle and use the arrow keys for small movements, or Shift+arrows for larger ones. Space captures when focus is outside a control.

**Framing** can reset corners, turn off **Crop & straighten**, or set the physical page's width/height ratio. Framing is remembered between sessions. A capture saves the full original before OCR and, when enabled, a corrected JPEG for OCR.

To adjust a saved photo, select it in **Read**, open **Image actions → Crop & straighten**, and put the corners clockwise from the top left. Preview, then save. **Restore original** removes the correction. Adjustments always start from the original image.

Changing an image makes its transcription pending again and blocks export until you rerun OCR or review and save the text. Earlier text is preserved in the meantime. Wait for OCR to finish before adjusting photos or figures. Perspective correction handles a flat tilted page; it cannot flatten the curve near a book spine.

## Read and proofread

**Read** puts one continuous transcript beside the selected scan. Use the previous/next controls, page selector or printed-page jump field to navigate. Roman numerals are supported. Scrolling the transcript also updates the selected scan.

Use **+**, **−**, **Fit**, or the percentage for 100% image size. The wheel zooms around the pointer; dragging pans. A different capture resets the view to fit. Moving between the two printed pages of one spread keeps the view.

Click a highlighted `[illegible]` marker, or choose **Next unclear**, to open its page in **Edit Markdown** with the marker selected. Correct it and save. **Preview** shows unsaved edits; **Cancel** restores saved text. Ctrl/Cmd+S saves. Page number and chapter fields are inside the metadata disclosure.

Completed pages can be edited while a different capture is processing. The active/queued capture is protected, unsaved drafts are retained during polling, and a revision check prevents a stale editor from overwriting newer corrections. Navigation asks before discarding edits. Saving one printed page preserves the other side of its spread.

## Retry OCR without losing corrections

The arrow beside **OCR remaining** offers **OCR selected capture** for an unread image and **Redo selected capture** for an existing transcription.

A successful redo creates a pending comparison rather than replacing saved text. Open **Review OCR changes** to compare the saved and new versions. Red highlights show old text; green highlights show new text. Click either highlight to select a change. **Select all**, **Select none** and **Show Markdown source** help with review. Formatting groups are selected together; changed figures or page counts can require accepting an entire page or capture.

Choose **Save selected changes** to apply your selection, or **Discard new OCR** to keep the saved transcription. Closing the comparison leaves it pending. Resolve or discard it before retranscribing that capture again. A failed or incomplete redo does not overwrite saved text.

## Progress and recovery

**OCR remaining** processes captures in numeric capture order and skips completed work. Streamed Markdown is provisional until the final structured result is validated and saved. **Follow OCR** tracks the active page; manual navigation or scrolling turns following off.

A capture has a default 900-second limit, with one automatic retry after a timeout or transient connection failure. `BOOK_BE_GONE_OCR_TIMEOUT` changes that limit. Once text starts, 120 seconds without new transcription progress stops the attempt without automatic retry; `BOOK_BE_GONE_OCR_PROGRESS_TIMEOUT` changes that limit. Reasoning events do not count as transcription progress.

Content-filter failures stop immediately. Partial streams are not marked complete. Completed captures remain saved; use **OCR remaining** to resume unfinished work.

After updating the application, restart Python and reload the browser so the backend and interface match. Restart after editing the OCR prompt too. Existing transcriptions do not change until you explicitly redo them.

## Printed pages, figures and links

The [OCR prompt](../prompts/ocr.md) asks for visible page numbers, headers/footers, heading hierarchy, paragraphs, emphasis, lists, tables, captions and footnotes. Exact fonts and page layout are outside Markdown's scope. Unreadable marks become `[illegible]`; sentence fragments continuing onto another page should remain fragments.

A spread is transcribed left page first, then right, into separate Markdown files. Each printed page has its own page/chapter metadata.

Detected figures become PNG crops with relative Markdown image links. Generated descriptions and text representations supplement the crop: Mermaid for suitable diagrams, or plain text for other figures. They are estimates and need review against the original. Mermaid remains editable code in this app.

Use **Edit crop · N** under the scan to adjust a figure without another OCR request. Drag handles, use the arrow keys or edit percentage fields, then save. Figure crops use an immutable copy of the image sent to OCR, even after later photo adjustments. Earlier crop versions are retained.

OCR can mark contents/index entries and explicit page references. Targets become relative links when their printed pages are available. **Book tools → Link page references** adds conservative links locally without a model call, preserving the text and figures. Missing or ambiguous targets stay unlinked; unusual layouts may need manual links. Temporary `page:` targets to unread pages report that the target is unavailable.

## Export and backup

**Book tools → Export book (.zip)** requires all captures to be complete. It includes individual printed-page Markdown files, combined `book.md` and referenced `assets/`. Keep the Markdown and assets together after extraction. The combined book follows capture order, with a separator between spread pages.

A book directory contains:

- Numbered JPEGs: original captures
- `corrected/`: adjusted OCR images
- `markdown/`: one file per printed page, plus figure assets
- `.ocr/`: resumable metadata, immutable OCR source images, pending comparisons and version history
- `book.json`: the title

Files begin with printed-page and chapter labels; a capture/side suffix prevents collisions. Unknown labels stay explicit. Only the preceding capture's known chapter is passed as context; the app does not send a growing book transcript or chat history. Corrected chapter labels can update filenames without retranscribing later pages.

Back up the whole book directory, including `.ocr/`. Data is ignored by Git. `BOOK_BE_GONE_DATA` changes the storage directory. The older `PAGESCRIBE_DATA`, `PAGESCRIBE_MODEL` and `PAGESCRIBE_OCR_TIMEOUT` names remain supported, with `BOOK_BE_GONE_*` taking precedence.

Legacy transcription files remain as backups. Legacy text copied into the current structure can have unknown labels; rerun OCR when you need separate physical-page metadata.

## Current limits and preview safety

The app processes photos in capture order. Automatic corner detection, curved-page dewarping, image spread splitting, deletion and reordering are outside this version. It has no accounts, database, cloud storage or publishing service; the server binds to loopback and camera capture needs a browser on that computer.

Markdown previews disable raw HTML and allow only locally saved figure images. See the [markdown-it-py security guidance](https://markdown-it-py.readthedocs.io/en/latest/security.html). OCR output still needs review against the scan.

## Development checks

Python serves the included `frontend/dist/` build. To edit the interface, use Node 22.12+, run `npm ci` in `frontend/`, then `npm run build`. Include the rebuilt distribution with source changes.

For hot reload, keep the Python server running on port 8765 and run `npm run dev` in `frontend/`; Vite proxies local API requests.

From the repository root:

```sh
python3 -m unittest discover -s tests -v
node tests/test_geometry.cjs
node tests/test_review_text.mjs
node tests/test_browser.cjs
```

The browser test uses temporary data, an isolated profile, a synthetic webcam and local provider fixtures. It needs Node 22+, Python and Brave at `/opt/brave.com/brave/brave`, or a Chromium executable supplied through `BROWSER`. Fixture success does not establish real webcam or model quality.
