# Book-Be-Gone

A personal utility for turning physical books into Markdown using a webcam and Codex. Small, local, and deliberately plain.

## Run

Requires Python 3.12+, a browser with webcam support, an installed, signed-in Codex CLI, and the dependencies in `requirements.txt`.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Open http://localhost:8765 on the computer with the webcam. Create or select a book, choose **Capture**, start the camera, choose the webcam, and capture one page or a two-page spread per photo. Keep the page flat, well lit, and large in the frame. Capture saves the original photo before any OCR occurs.

To test OCR first, choose a page or unread capture in the navigation toolbar and open the arrow beside **OCR remaining** and choose **OCR selected capture**. Only that image is processed; a photographed spread includes both printed pages. Review or edit the resulting Markdown before proceeding. **Redo selected capture** in the same menu lets you retry, with confirmation before replacing existing text.

Choose **OCR remaining** to transcribe saved pages sequentially. The default is `gpt-5.6-luna` with `model_reasoning_effort="low"` through `codex app-server`, using your existing Codex login and CLI configuration. Photos are sent to the model when you start OCR. Model access depends on your account. Open the model/thinking control next to **OCR remaining** to choose the OCR model before starting either OCR action. The selection is remembered in this browser and stays fixed throughout a job, including retries. The menu lists image-capable models from your local Codex cache; **Custom model…** accepts another model identifier. Choose **Thinking** in the same settings menu: Low (default), Medium, High, or Extra high, plus Max/Ultra when listed by Codex for that model. The thinking level is remembered in this browser and applied to both OCR actions and retries. Changing models does not reprocess completed captures. Set `BOOK_BE_GONE_MODEL` to change the default.

### Reading and proofreading

The **Read** workspace has one continuous book transcript beside one scanned-image pane. **Capture** opens the camera workspace. Book creation is under **+** beside the book selector; linking and export are in **Book tools (•••)**. Infrequent settings stay in menus, and editing/cropping controls appear only when needed. The shared toolbar provides previous/next page, a selector containing printed pages and unread captures, and a jump field for real printed page numbers. Scrolling the transcript updates the selected page and its image. There is no separate live viewer or grid of capture-status buttons.

Use **+**, **−**, **Fit**, or click the zoom percentage for **100%**; the mouse wheel zooms around the pointer, and dragging pans. Selecting another capture resets the image to fit. Switching between printed pages of the same spread keeps the zoom and pan position.

`[illegible]` markers are highlighted in the rendered book. Click a highlighted marker, or use **Next unclear** / **↑**, to open the relevant page in **Edit Markdown** with the marker selected. Type the replacement and choose **Save**. **Preview** shows unsaved edits; **Cancel** restores the saved text. Ctrl/Cmd+S saves Markdown corrections. Page number and chapter fields are under the editor's metadata disclosure.

Completed pages remain editable while OCR works on another capture. The active capture is protected. Background polling never replaces an unsaved draft, and a version check prevents a stale editor from overwriting newer corrections. Navigation asks before discarding unsaved edits. Saving a printed page preserves the other page of its spread.

Export concatenates completed printed pages in capture order; unfinished captures prevent export so they aren't silently omitted. OCR is fallible: proofread before treating the output as a faithful transcription.

### Live progress and resuming

**OCR remaining** skips every completed capture, including after a failure or server restart. Only an explicit **Redo selected capture** replaces a completed result. Corrected images that have changed remain pending until their text is reviewed or OCR is rerun.

Streamed Markdown appears directly in the continuous transcript. **Follow OCR** tracks the active printed page and its scan; manual navigation or scrolling turns following off so you can read or edit elsewhere. The status line shows the active capture, recognized printed page numbers, elapsed time, and completed/remaining counts. Polling refreshes about every 700 ms. Before Codex emits text, the pending page shows the current activity. Streamed drafts remain provisional until the final structured response is saved.

Restart the Python server after updating the application, then reload the browser. Refresh alone can load a newer interface against an older in-memory backend. The UI now detects that mismatch and explicitly requests a server restart instead of showing an empty stream. Completed OCR is persisted and is skipped when processing resumes.

Each capture now has a **900-second (15-minute) limit**, with one automatic retry after a timeout or transient connection failure. Set `BOOK_BE_GONE_OCR_TIMEOUT` (seconds) before starting the server to change the limit. A repeat failure stops with a concise message; completed captures stay saved, and the remaining button resumes from the unfinished capture. The Codex child process group is terminated on timeout so a retry cannot leave the previous worker running.

The integration uses the installed CLI's [app-server streaming protocol](https://learn.chatgpt.com/docs/app-server), with an ephemeral read-only thread per capture, the selected model and thinking level, structured page output, and only the previous chapter as context. It displays assistant transcription deltas, not reasoning text.

### OCR transcription rules

The prompt is editable in [prompts/ocr.md](prompts/ocr.md). It preserves visible printed page numbers, running headers and footers, heading hierarchy, paragraphs, emphasis, lists, tables, captions, and footnotes as Markdown allows. Exact fonts, margins, and positioning are not represented in Markdown.

For a two-page spread, it transcribes the left page first, then the right, into separate Markdown files. The export ZIP contains one Markdown file per printed page, a combined `book.md`, and an `assets/` folder. Spreads in the combined file have a `---` separator. Printed page numbers stay at the top or bottom as shown; capture filenames are not book page numbers. Unreadable printed marks become `[illegible]` instead of a guess. A sentence that continues onto another page is preserved as a readable fragment, without a false illegibility marker or invented ending. Restart the server after editing the prompt. Existing transcriptions are unchanged; retry OCR to replace them using the new prompt.

### Links between printed pages

OCR marks contents/index locators and explicit references such as “see page 44” as page links. The app resolves them to relative links to the actual printed-page Markdown files as those pages become available. Links continue to work when chapter corrections rename the files. Range endpoints preserve their printed labels: “239–40” links to pages 239 and 240. Roman numerals are supported.

For existing OCR, open **Book tools (•••)** in the header and choose **Link page references**. This runs locally without a model call and updates completed pages, preserving their text, figures, and formatting. It recognizes contents/index sections and explicit “page”, “pages”, “p.”, or “pp.” references; it leaves ordinary numbers, code, and authored external links alone. Missing or ambiguous targets stay unlinked. OCR-provided hints to unread pages remain temporary `page:` links until their targets are known; clicking one in the viewer reports that the page is unavailable. The detector is conservative: unusual layouts or implicit references may need a manually edited Markdown link. Earlier text is backed up in `.ocr/history/`.

Click an internal link in the continuous Markdown viewer to select its page and scan. Book/page bookmarks support opening a link in another tab and browser back/forward. Images remain inline in the same viewer. Exported page links are ordinary relative `.md` links; keep all page files and the `assets/` folder together after extracting the ZIP.

### Figures and illustrations

New OCR saves each detected figure as a PNG crop and inserts a relative Markdown image link at its position in the text. Each crop is accompanied by a short generated description and a generated text representation: Mermaid source for suitable simple diagrams, or a fenced plain-text account for plots, photographs, and other figures. Printed captions remain separate. The representations are labeled as generated and supplement the original crop; the prompt forbids inventing data or unreadable details. Mermaid is displayed as editable code in this utility and can be rendered by Markdown tools that support Mermaid.

Choose **Edit crop · N** below the selected scan. Drag the four handles, use arrow keys on a handle, or adjust the percentage fields. The preview updates as you move. **Save crop** writes a new PNG and updates its Markdown link without OCR or changes to your text corrections. Cancel leaves the saved crop unchanged. Crop adjustments use an immutable copy of the image originally sent to OCR, even if you later readjust the page photo. Finish OCR before adjusting figure crops. Use **Edit Markdown** to correct the generated description or representation.

Assets live in `markdown/assets/`; immutable OCR source images live in `.ocr/sources/`. Earlier crop versions are retained for history. **Book tools (•••) → Export book (.zip)** downloads a ZIP containing the page Markdown, combined `book.md`, and referenced assets; keep the assets folder alongside the Markdown when extracting or copying files. Existing completed OCR is unchanged and remains skipped. Redo a selected capture to detect its figures with the new prompt (this replaces that capture's text).

Figure identification, crop boundaries, descriptions, and representations are model estimates and should be reviewed against the original scan. A figure's crop appears after that capture finishes; streamed text may show its temporary `{{figure-1}}` marker until then.

### Crop and camera tilt

In **Capture**, the **live camera preview** shows four numbered handles as soon as the camera starts. Position them on the page corners before capturing. Handles 1–2 share a vertical position, as do 3–4: moving either handle vertically moves its partner, keeping the top and bottom edges level. This also applies to keyboard movement and the saved-photo adjustment editor. **Capture page** saves the full original and a cropped, perspective-corrected version for OCR. The handles stay in place for subsequent captures during the session, so you can turn pages without repeating the setup. Open **Framing** to reset corners or disable **Crop & straighten** when capturing full frames. You can also focus a handle and use arrow keys, with Shift for larger steps. The width / height field in **Framing** controls the corrected page proportions. Camera framing is remembered between sessions. Space captures a page when focus is outside a control.

Select a captured page in **Read**, open **Image actions (•••)** above the scan, and choose **Crop & straighten**. Drag the four numbered handles onto the page corners in clockwise order from the top left (or edit their X/Y coordinates). Choose **Preview**, then **Save crop**. This crops out the surroundings and corrects the perspective of a flat page photographed at an angle, including small rotational tilt.

The page proportions are estimated from its visible edges. For accurate proportions, enter the physical page width divided by its height, in any matching units. Perspective correction cannot flatten a curved page near a book spine.

Adjustments always start from the original photo; **Restore original** removes the correction. Adjusted JPEGs live in the book's `corrected/` directory and become the OCR input. Changing the image marks the page pending again and blocks export until you rerun OCR or review and save its text. Previous Markdown is preserved in the meantime. Finish OCR before adjusting photos. Adjustments apply to individual pages.

## Storage and scope

Each book lives in `data/<book-id>/`:

- Numbered `.jpg` files are the original captures.
- `corrected/` contains adjusted images used for OCR.
- `markdown/` contains **one file per printed page**, for example `page-0302__chapter-10__000153-1.md`. The printed number and chapter lead the name; the capture/side suffix prevents collisions. Roman numerals are retained. Missing numbers use `unnumbered`, and unknown chapters use `unknown-chapter`.
- `.ocr/` stores capture-to-page metadata and chapter evidence so processing can resume. Prior OCR/edit versions are backed up in `.ocr/history/`.
- `book.json` holds the title.

Batch OCR runs in numeric capture order (printed page numbers are discovered during OCR). Only the preceding capture's known chapter is passed to the next model call; no growing transcript or chat history is sent. Visible chapter evidence updates that context. Missing, unread, or stale preceding captures reset it to unknown rather than guessing. Completing earlier captures later updates inherited chapter labels and filenames without retranscribing later pages. A chapter transition within a spread can give each page a different label.

The model returns structured page metadata plus Markdown through `prompts/ocr.schema.json`; `.md` files contain only the Markdown. UI edits and direct edits to the generated Markdown are preserved when labels are recalculated. Use the UI to change metadata. Earlier capture-level `.md` files remain untouched as backups; startup copies any remaining legacy transcription into `markdown/` with unknown labels until it is rerun or labelled. Legacy captures should be rerun to discover separate physical pages and their metadata; existing text is not silently rewritten.

The former `PAGESCRIBE_DATA`, `PAGESCRIBE_MODEL`, and `PAGESCRIBE_OCR_TIMEOUT` environment variables remain supported; `BOOK_BE_GONE_*` values take precedence. Saved browser preferences migrate automatically.

Data is ignored by Git; back up the entire book directory, including `.ocr/`, separately. Set `BOOK_BE_GONE_DATA` to store it elsewhere.

No accounts, database, cloud storage, or publishing. The server binds to loopback only. Camera capture requires a browser on this computer. The initial version processes photos in capture order; automatic corner detection, curved-page dewarping, image spread splitting, deletion, and reordering are outside this version.

## Development

Python standard library server, markdown-it-py for formatted previews, and a Svelte 5 UI built with Vite. [Svelte components](https://svelte.dev/docs/svelte/overview) own the interface and reactive session state; the UI does not load the former DOM-based scripts. Pillow crops saved figures. The renderer disables raw HTML and permits only locally saved figure images, following the [markdown-it-py guidance](https://markdown-it-py.readthedocs.io/en/latest/security.html). The checked-in `frontend/dist/` build is served by Python, so normal use needs no Node server. To edit the UI, use Node 22.12+:

```bash
cd frontend
npm ci
npm run build
```

Commit updated `frontend/dist/` files with UI changes. For frontend development, run `npm run dev` with `python3 app.py` running separately on port 8765. The Vite development server proxies local API requests. Source components are in `frontend/src/`: `App.svelte` lays out the workspace; `session.svelte.js` owns shared state; `Transcript`, `ImagePane`, `Capture`, `Corners`, and `CropEditor` own their respective interactions. `geometry.js` remains the shared, tested perspective correction implementation.

Run checks from the repository root:

```bash
python3 -m unittest discover -s tests -v
node tests/test_geometry.cjs
```

The real-browser regression test uses a synthetic webcam and a local Codex protocol fixture. It exercises the built Svelte UI through DOM interactions: camera capture and paired handles, live OCR, model/thinking settings, editing during OCR, continuous reading, zoom/pan, figure and page crops, links, bookmarks, ZIP export, and narrow-screen layout:

```bash
node tests/test_browser.cjs
```

This test requires Node 22+, Python, and Brave at `/opt/brave.com/brave/brave`, or a Chromium executable supplied through `BROWSER`. It uses temporary data and an isolated browser profile. New captures are selected in the shared viewer unless there are unsaved edits.

The structured prompt was also checked with a real Luna low call on sample capture 000153: it returned printed pages 302 and 303 separately and preserved the trailing sentence fragment without an illegibility marker. Live camera quality still depends on the webcam setup.
