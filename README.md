# The SQL Alchemist — Local AI Business Intelligence Assistant for DuckDB and Ollama

The SQL Alchemist is a local-first Business Intelligence assistant that converts natural-language questions into DuckDB SQL over flight operations data.

It supports two interfaces:

- A terminal CLI in `src/main.py`
- A Streamlit web app in `src/app.py`

The project uses local Ollama models for NL-to-SQL generation and includes validation plus keyword-based fallback logic when model output is invalid or unavailable.

---

## Why DuckDB?

DuckDB is a strong fit for this project because it is an in-process SQL OLAP database designed for analytical workloads, with no separate server to manage.

That makes it ideal for:

- local analytics
- CSV-based workflows
- fast exploratory querying
- lightweight deployment
- private data processing without a database server

For this project, DuckDB keeps the whole stack simple: load a CSV, query it with SQL, and surface results immediately.

---

## Architecture Overview

The system follows a simple but robust flow:

```text
User Question
    ↓
Prompt Builder
    ↓
Ollama Model
    ↓
SQL Sanitizer / Validator
    ↓
Fallback Engine (if invalid)
    ↓
DuckDB Execution
    ↓
Result Formatter / Charts / Explanations
```

This design keeps the project easy to understand while adding a practical reliability layer for real-world use.

### Core design goals

- Local-first execution.
- Defensive SQL validation.
- Clear separation between CLI, Streamlit UI, and analytics logic.
- Simple extension points for new analysis modules.

---

## SQL Safety and Reliability

The project already protects execution by sanitizing and validating generated SQL before running it.

Current protections include:

- Only `SELECT` statements are accepted.
- Generated SQL is sanitized before execution.
- Invalid outputs trigger keyword-based fallback SQL.
- Fallback reasons are visible in the UI and CLI.

Recommended additional protections:

- No multi-statement execution.
- Block `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, and `CREATE`.
- Enforce query timeouts where possible.
- Inject a default `LIMIT` when the query is unrestricted.

This is especially valuable if the project is used as a portfolio demo or expanded for broader use.

---

## Project Structure

```text
chab_ai_engine/
├── .gitignore
├── README.md
├── LICENSE
├── requirements.txt
├── config.py
├── data/
│   └── flights.csv
├── notebooks/
│   └── main.ipynb
├── src/
│   ├── app.py
│   └── main.py
└── docs/
    └── DEPENDENCIES.md
```

This layout keeps runtime code in `src/`, documentation in `docs/`, and notebook material in `notebooks/`, while preserving the dataset path expected by the app: `data/flights.csv`.

---

## What the Project Does

The engine loads `flights.csv` into an in-memory DuckDB table named `flights`, then:

1. accepts a natural-language question
2. asks a local Ollama model to produce SQL
3. sanitizes and validates the SQL
4. executes the query and returns results

If generation fails, the system applies intent-based fallback SQL using keywords such as:

- average latency
- delayed/cancelled flights
- counts/totals by status

This avoids always returning the same default query shape.

---

## Analysis Layers

The named business layers add personality and analytical depth beyond simple querying.

### Watchdog

Detects operational anomalies, suspicious latency spikes, and data-quality inconsistencies.

Use it when you want a quick view of risky or unusual flights.

### Airline Wars

Compares airlines using rankings, percentiles, and window-function analysis.

Use it when you want competitive benchmarking between carriers or routes.

### Cost of Chaos

Estimates operational disruption costs caused by delays and cancellations.

Use it when you want a financial view of operational problems.

### Result Explanation

Uses LLM summarization to convert SQL results into executive-style narratives.

Use it when you want a plain-English interpretation of query results.

---

## Data Model

The `flights` table (from `data/flights.csv`) contains:

- `flight_id`
- `airline`
- `origin`
- `destination`
- `departure_time`
- `arrival_time`
- `latency_minutes`
- `status` (`On-Time`, `Delayed`, `Cancelled`)

The dataset has been expanded with many randomized but realistic records to improve query quality and aggregate analyses.

### Dataset notes

- Designed for local analytical exploration.
- Suitable for ranking, aggregation, and anomaly detection.
- Works well with DuckDB because the entire CSV can be queried directly.

---

## Example Outputs

### CLI example

```text
> Which airlines have the highest average latency?

Generated SQL:
SELECT airline, AVG(latency_minutes) AS avg_latency
FROM flights
GROUP BY airline
ORDER BY avg_latency DESC
LIMIT 200;
```

### Result example

```text
+-----------+-------------+
| airline   | avg_latency |
+-----------+-------------+
| SkyJet    | 42.5        |
| AeroLink  | 37.2        |
+-----------+-------------+
```

### Streamlit example

Add a screenshot here once uploaded to the repository:

```md

```

You can also add a CLI screenshot if you want to show both interfaces.

---

## Requirements

- Python 3.10+
- Ollama installed locally
- At least one local Ollama model, for example `qwen3.6:27b`

Python dependencies used by the project include `duckdb`, `rich`, `ollama`, `streamlit`, `plotly`, and `pandas`.

---

## Installation

From the project root:

```bash
python3 -m pip install -r requirements.txt
```

Optional Ollama setup:

```bash
ollama pull qwen3.6:27b
ollama serve
```

This project is designed for local execution and does not require a cloud dependency for NL-to-SQL behavior.

---

## Run the CLI

From the project root:

```bash
python3 src/main.py
```

Inside the terminal experience, you can ask questions in plain English and exit with `quit`, `exit`, or `q`.

Example questions:

- Which airlines have the highest average latency?
- How many flights were cancelled by airline?
- Show delayed flights ordered by latency.
- What is the distribution of flight statuses?

---

## Run the Streamlit app

From the project root:

```bash
python3 -m streamlit run src/app.py
```

The Streamlit app supports installed-model picking, manual model input fallback, generated SQL preview, results rendering, optional charting, session history, SQL replay, and export to JSON or CSV.

---

## Configuration

The shared `config.py` controls core runtime settings.

Typical values include:

- Ollama host
- Ollama timeout
- CSV path
- delay cost per minute
- cancellation cost
- default model chain

Example:

```python
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_TIMEOUT = 180
DATA_PATH = "data/flights.csv"
DEFAULT_DELAY_COST_PER_MINUTE = 50
DEFAULT_CANCELLATION_COST = 200
DEFAULT_MODEL_CHAIN = [...]
```

---

## Reliability

To improve stability, the project sanitizes model output, accepts only `SELECT` queries, and applies keyword-based fallback SQL when generated output is invalid or unavailable.

That means the app remains usable even when the local model is unavailable or returns malformed SQL.

---

## Example Advanced Questions

- Which destinations have the highest cancellation rates?
- Compare average latency by airline and destination.
- Show rolling 7-day delay trends.
- Which routes contribute most to disruption cost?
- Which carriers have the best on-time performance?
- What flights are flagged as high risk by the Watchdog?

---

## Testing

A small test suite would strengthen credibility and make future refactors safer.

Suggested layout:

```text
tests/
├── test_sql_validation.py
├── test_fallback_logic.py
├── test_prompt_builder.py
└── test_duckdb_execution.py
```

Run with:

```bash
pytest
```

---

## Roadmap

Possible future improvements:

- Multi-table joins
- Schema-aware prompting
- Query caching
- User-uploaded CSV datasets
- Dashboard generation
- RAG-based business definitions
- Role-based access controls
- Better chart templates
- More advanced SQL safety checks

---

## Troubleshooting

### `model ... not found (404)`

Select an installed model in the Streamlit dropdown or pull the model with Ollama.

### `Could not fetch local Ollama models`

The app will still work via manual model input. Ensure `ollama serve` is running and retry.

### `File does not exist: src/app.py`

Run commands from the `chab_ai_engine` folder.

### `ModuleNotFoundError` for dependencies

Reinstall dependencies with:

```bash
python3 -m pip install -r requirements.txt
```

---

## Notes

- This project is designed for local execution.
- No cloud dependency is required for NL-to-SQL.
- Query quality depends on both the model quality and prompt specificity.
