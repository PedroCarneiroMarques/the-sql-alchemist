# Dependencies Documentation

This project uses the Python packages listed in `requirements.txt`.

## Core Runtime

- `duckdb`  
  In-memory analytics engine used to load and query `data/flights.csv` with SQL.

- `ollama`  
  Python client used to call local LLMs that convert natural language prompts into SQL and support model escalation.

- `pandas`  
  Used for dataframe handling, query results, notebook-friendly inspection, and chart preparation.

## Interface Layers

- `rich`  
  Provides styled CLI output for the terminal chat experience in `src/main.py`.

- `streamlit`  
  Powers the web UI in `src/app.py`, including filters, chat history, metrics, and query display.

- `plotly`  
  Generates charts in Streamlit for latency trends and airline impact views.

## Why These Dependencies Exist

The project now has three execution surfaces:

1. **CLI** — natural language to SQL in terminal mode with Rich tables.
2. **Streamlit app** — interactive dashboard and chat UI.
3. **Notebook** — reference document with markdown + code blocks and notebook-friendly query execution.

Because of this, the dependency set supports:

- local analytics via DuckDB
- local model inference via Ollama
- dataframe manipulation via pandas
- CLI rendering via Rich
- web UI via Streamlit
- charting via Plotly

## Installation

From the `chab_ai_engine` folder:

```bash
python3 -m pip install -r requirements.txt
```

## Ollama Requirement

An Ollama server must be available locally, and at least one model must be pulled.

Example:

```bash
ollama pull mistral:7b
ollama serve
```

The system is designed to work best when several local models are available, because it can escalate from faster/smaller models to stronger ones when needed.