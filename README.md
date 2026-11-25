# Synaptiq

Synaptiq is a desktop study app that imports course materials, creates flashcards
with Gemini, and schedules review using a spaced-repetition model.

## Requirements

- Python 3.10 or later
- Tk support for your Python installation (`python-tk` on some Linux distributions)
- A Gemini API key to generate flashcards and process images, scanned PDFs, and
  audio/video. Plain-text documents and searchable PDFs can be imported without a key.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

## Run

Set `GEMINI_API_KEY` in the environment to enable Gemini features:

```bash
export GEMINI_API_KEY="your-api-key"
synaptiq
```

Alternatively, run `python -m synaptiq.main`. The application also reads a key
from the operating system keychain when the environment variable is not set.

The SQLite database is stored at `~/.synaptiq/synaptiq.db`. Add supported
materials using **Add files**, choose a lecture scope, then generate and review
flashcards. Supported extensions include PDF, TXT, Markdown, DOCX, PPTX, common
image formats, and common audio/video formats.

## Tests

```bash
python -m pytest
```

## Browser demo

The `docs/` directory contains a static interactive showcase with sample cards.
It runs entirely in the browser and does not send files or API keys to a server.
The demo illustrates the review flow; importing text in the showcase creates an
example card locally and does not call Gemini.

To publish it, merge the project to the default branch and set **Settings →
Pages → Build and deployment → Source** to **GitHub Actions**. The included
workflow deploys on changes to `docs/`. The public URL will be
`https://regan2327.github.io/study1/` after Pages is enabled and the deployment
workflow succeeds.
