# Dependencies

This project runs locally and uses a small set of Python dependencies.

## Core runtime

- `duckdb` — in-memory analytical SQL engine for querying `flights.csv`.
- `pandas` — dataframe handling and tabular transformations.
- `streamlit` — web UI for the interactive analytics app.
- `plotly` — charts and visual analytics in the Streamlit app.
- `ollama` — local LLM client for natural-language-to-SQL generation.
- `rich` — improved terminal output for the CLI version.

## Python version

Recommended:
- Python 3.10 or newer

## Local model requirement

The app is designed to work with local Ollama models. A recommended model chain is configured in `config.py`.

Example models:
- `mistral:7b`
- `phi4:14b`
- `qwen2.5-coder:14b`
- `gemma4:26b`
- `qwen3.6:27b`
- `qwen3.6:35b-a3b`
- `deepseek-r1:8b`

## Development / testing

- `pytest` — automated test suite (`pip install -e ".[dev]"` or `requirements-dev.txt`).

## Installation

Runtime only (CLI, Streamlit, Docker):

```bash
python3 -m pip install -r requirements.txt
```

Development with tests:

```bash
python3 -m pip install -r requirements-dev.txt
```

Or install directly from `pyproject.toml`:

```bash
python3 -m pip install -e ".[dev]"
```

## Optional Ollama setup

```bash
ollama pull qwen3.6:27b
ollama serve
```

## Notes

- The project is local-first and does not require a cloud database.
- The Streamlit interface and CLI share the same analytical foundation.
- The CSV dataset is loaded into DuckDB for fast analytical queries.