# Book-Be-Gone

Turn webcam photos of book pages into editable Markdown. Capture a page or a spread, proofread the transcript beside the scan, then export the book with its figures and page links.

Book-Be-Gone runs on your computer and saves ordinary files locally. Choose Codex, Ollama, llama.cpp or OpenRouter for OCR.

![Book-Be-Gone Read workspace with the scanned spread beside its editable transcript](https://raw.githubusercontent.com/MrScripty/MrScripty/edd3f0d95d6e636e913272d9f2c7e2b4cc157b9b/assets/book-be-gone_ocr.jpg)

*Existing public [portfolio capture](https://github.com/MrScripty/MrScripty/blob/edd3f0d95d6e636e913272d9f2c7e2b4cc157b9b/assets/book-be-gone_ocr.jpg), showing scan/transcript comparison. Provider and model choices shown are historical; this is not a newly tested build.*

## Run

You need Python 3.12+ and a browser with webcam support. From the repository directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

These commands use a POSIX shell. Codex OCR currently relies on POSIX process-group cleanup; use a POSIX environment for that provider.

Open [localhost:8765](http://localhost:8765) on the computer with the webcam. Leave the terminal running; Ctrl+C stops the server. The built interface is included, so normal use needs no Node installation.

For Codex OCR, install and sign in to the Codex CLI first. Other providers need a configured vision model or OpenRouter key. Choose one under **OCR settings**; the [provider guide](docs/guide.md#choose-an-ocr-provider) covers setup.

## Make your first book

1. Choose **+** beside the book selector, enter a title, then open **Capture**.
2. Start the camera and frame a page or spread. Put the four live-preview handles on its corners, then choose **Capture page**. The original and cropped, straightened photo are saved.
3. Return to **Read** and choose **More OCR actions → OCR selected capture**. Try one image before processing the whole book.
4. Compare the transcript with the scan and correct it in **Edit Markdown**. Highlighted `[illegible]` markers help you find unclear passages.
5. Choose **OCR remaining** to continue. Completed captures are saved and skipped when you resume.
6. Use **Book tools → Export book (.zip)** when all captures are complete. Keep the exported Markdown and image assets together.

**Redo selected capture** creates a comparison. Saved corrections stay in place until you choose **Save selected changes**; you can also discard the new OCR.

## Your pages

Capturing does not start OCR. OCR sends images and limited chapter context to your chosen provider; OpenRouter also sends them upstream and bills your account, while local processing depends on your server's configuration. Books stay in `data/<book-id>/` or `BOOK_BE_GONE_DATA`; back up the whole directory, including `.ocr/`.

OCR and generated figure descriptions need proofreading. See the [guide](docs/guide.md) for privacy, crops, links, recovery and current limits.

## Development

Python serves a Svelte 5/Vite interface. With Node 22.12+, run `npm ci` and `npm run build` in `frontend/`; keep `frontend/dist/` in sync. The guide includes development and test commands. The [OCR prompt](prompts/ocr.md) is editable.
