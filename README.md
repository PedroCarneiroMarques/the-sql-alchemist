# The SQL Alchemist

The SQL Alchemist is a local Business Intelligence assistant that turns natural language questions into DuckDB SQL over flight operations data.

It currently supports two interfaces:

- a terminal experience through `src/main.py` (or `main.py` at the project root)
- a Streamlit web app through `src/app.py`

Both interfaces share the same analytics engine in `src/core.py`.

The project uses local LLMs via Ollama to generate SQL, applies fallback logic when model output fails, and provides interactive analytics for airline performance, disruption cost, and operational quality.

## Project Structure

```text
chab_ai_engine/
├── data/
│   └── flights.csv
├── docs/
│   ├── images/
│   │   └── ... screenshots and supporting visuals ...
│   └── DEPENDENCIES.md
├── notebooks/
│   └── main.ipynb
├── src/
│   ├── core.py          # shared BI engine (ChatBI, analytics, explanations)
│   ├── main.py          # CLI interface
│   └── app.py           # Streamlit interface
├── tests/
│   ├── conftest.py
│   └── test_core.py
├── .github/
│   └── workflows/
│       └── ci.yml
├── config.py
├── main.py              # convenience CLI entry point
├── .env.example
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt
```

### Architecture

| Module | Responsibility |
|--------|----------------|
| `config.py` | Environment-based configuration (`OLLAMA_HOST`, `DATA_PATH`, model chain, costs) |
| `src/core.py` | DuckDB loading, Ollama SQL generation, fallback logic, watchdog, Airline Wars, KPI helpers |
| `src/main.py` | Terminal UI with Rich (`/dashboard`, `/wars`, `/suggest`, chat) |
| `src/app.py` | Streamlit dashboards, charts, chat, CSV export |
| `notebooks/main.ipynb` | Lightweight experimentation that imports from `src/core.py` |
| `tests/test_core.py` | Automated tests for core behavior |

## What the Project Does

The engine loads `data/flights.csv` into an in-memory DuckDB table named `flights`, then:

1. accepts a natural-language question
2. asks a local Ollama model to generate SQL
3. sanitizes and validates the SQL
4. executes the query against DuckDB
5. returns results in either CLI or Streamlit UI
6. falls back to keyword-based SQL when model generation fails

This makes the project usable even when a model is unavailable, returns invalid SQL, or cannot be reached locally.

## Interfaces

### 1. Terminal Interface

The CLI version in `src/main.py` provides a lightweight local chat workflow for asking flight-related questions directly in the terminal.

### 2. Streamlit Web App

The Streamlit app in `src/app.py` extends the project with:

- model fallback chain support
- KPI and chart-based analytics
- chat-based natural language exploration
- business impact estimation
- watchdog quality checks
- airline-vs-airline comparison
- result explanation logic
- suggested prompts for faster interaction
- CSV export for dashboard and chat results

## Data Model

The main dataset is stored in:

```text
data/flights.csv
```

The `flights` table contains these core fields:

- `flight_id`
- `airline`
- `origin`
- `destination`
- `departure_time`
- `arrival_time`
- `latency_minutes`
- `status`

Supported status values include:

- `On-Time`
- `Delayed`
- `Cancelled`

The dataset has been expanded with more realistic records to improve aggregate analysis, filtering, and routing comparisons.

## Main Features

### Natural Language to SQL

Users can ask questions in plain English, and the app uses a local Ollama model to convert the question into a DuckDB `SELECT` query.

### SQL Safety and Fallback

To improve reliability, generated SQL is sanitized and validated before execution. If generation fails or produces invalid output, the app falls back to intent-based SQL patterns such as average latency, cancellations, delays, or counts by status.

### Streamlit Analytics Layer

The web app includes:

- total flights, average latency, delayed flight KPIs
- latency visualizations
- estimated disruption cost by airline
- watchdog quality distribution
- filtered results table
- auto-charting for numeric chat results

### Business Impact Estimation

The Streamlit version estimates disruption cost using configurable business rules:

- delay cost = `latency_minutes × delay_cost_per_minute`
- cancellation cost = fixed `cancellation_cost`
- total cost = delay cost + cancellation cost

These values can be changed in the sidebar of the app.

### Watchdog Quality Layer

The app classifies records into operational quality groups:

- `Reliable`
- `Review`
- `High Risk`

This is based on airline-relative latency behavior using average, standard deviation, p95, and p99 thresholds.

### Airline Wars

The "Airline Wars" view compares two airlines on a selected destination using:

- average latency
- on-time rate
- cancellation rate
- total disruption cost
- ranking metrics

This provides a direct route-level rivalry view for operational benchmarking.

## Requirements

Before running the project, make sure you have:

- Python 3.10 or later
- Ollama installed locally
- at least one local Ollama model pulled
- a valid `config.py` in the project root
- the dataset available at the configured path

## Installation

From the project root:

```bash
git clone https://github.com/PedroCarneiroMarques/the-sql-alchemist.git
cd the-sql-alchemist
python3 -m pip install -r requirements.txt
```

## Ollama Setup

Start the Ollama server locally:

```bash
ollama serve
```

Pull at least one model. Example:

```bash
ollama pull mistral:7b
```

You can also pull additional models used in the fallback chain, such as:

```bash
ollama pull phi4:14b
ollama pull qwen2.5-coder:14b
ollama pull deepseek-r1:8b
```

## Configuration

Configuration lives in `config.py` at the project root. Values can be overridden with environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_PATH` | `data/flights.csv` | Path to the flights dataset |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `OLLAMA_TIMEOUT` | `180` | Request timeout in seconds |
| `DEFAULT_MODEL_CHAIN` | comma-separated model list | Fallback order for SQL generation |
| `DEFAULT_DELAY_COST_PER_MINUTE` | `50` | Delay cost per minute (€) |
| `DEFAULT_CANCELLATION_COST` | `200` | Fixed cancellation cost (€) |

Example:

```bash
cp .env.example .env
# edit .env as needed
```

Or export variables directly:

```bash
export DATA_PATH="data/flights.csv"
export OLLAMA_HOST="http://localhost:11434"
export DEFAULT_MODEL_CHAIN="mistral:7b,phi4:14b,qwen2.5-coder:14b"
```

## Running the CLI Version

Run from the project root:

```bash
python3 src/main.py
```

Or use the root entry point:

```bash
python3 main.py
```

In the terminal:

- ask questions in plain English
- use `/dashboard`, `/wars`, `/suggest`, `/models`, or `/help`
- type `quit`, `exit`, or `q` to leave

## Running the Streamlit App

Run from the project root:

```bash
streamlit run src/app.py
```

This matters because `config.py` is stored in the project root and the app expects the repository root to be part of the Python path.

The app will usually open at:

```text
http://localhost:8501
```

## Streamlit Features

The Streamlit app currently includes:

- installed-model detection from local Ollama
- fallback model execution chain
- generated SQL preview
- results table rendering
- automatic charting for numeric outputs
- suggested prompts
- business impact controls in the sidebar
- global airline filters
- route-level airline comparison
- in-session chat history
- CSV download buttons for filtered data, cost summaries, Airline Wars, and chat results

## Testing

Run the automated test suite from the project root:

```bash
python3 -m pytest tests/ -v
```

The tests cover SQL safety (including `sqlparse` guardrails), keyword fallback, few-shot prompts, watchdog logic, Airline Wars, explanations, and CSV export helpers. They do not require a running Ollama instance.

CI runs automatically on GitHub Actions for Python 3.11 and 3.12 on every push and pull request to `main`.

## Screenshots and Images

Project screenshots and supporting visuals should be stored in:

```text
docs/images/
```

Suggested naming convention:

- `docs/images/dashboard-overview.png`
- `docs/images/chat-analysis.png`
- `docs/images/airline-wars.png`
- `docs/images/project-structure.png`

After adding screenshots, reference them in the README with standard Markdown image syntax.

## Typical Questions to Ask

Examples:

- Which airlines have the highest average latency?
- How many flights were cancelled by airline?
- Show delayed flights ordered by latency.
- What is the distribution of flight statuses?
- Which routes have the highest average delay?
- What is the estimated total cost by airline?
- Which destinations have the most delayed flights?
- Which airlines have the best on-time performance?

## Reliability and Fallback Strategy

To improve stability:

- model output is sanitized before execution
- only `SELECT` / `WITH ... SELECT` queries are accepted
- table whitelist (`flights` only) and forbidden keywords (`UNION`, `DROP`, etc.)
- non-safe SQL is rejected
- invalid model output triggers keyword-based fallback SQL
- execution errors are surfaced in the UI
- result explanations attempt to summarize returned data safely

Recent improvements include:

- shared analytics engine in `src/core.py`
- removal of duplicated notebook logic
- safer explanation logic for result metrics
- CSV export from the Streamlit UI
- automated `pytest` coverage for core behavior

## Troubleshooting

### 1. `ModuleNotFoundError: No module named 'config'`

Make sure:

- `config.py` exists in the project root
- you run the app from the repository root, not from inside `src/`

Correct:

```bash
cd the-sql-alchemist
streamlit run src/app.py
```

### 2. Dataset not found

Check that `DATA_PATH` in `config.py` points to a real CSV file, for example:

```python
"DATA_PATH": "data/flights.csv"
```

### 3. Ollama connection errors

Make sure Ollama is running:

```bash
ollama serve
```

Also verify the host in `config.py`:

```python
"OLLAMA_HOST": "http://localhost:11434"
```

### 4. No local models available

List installed models:

```bash
ollama list
```

If needed, pull one:

```bash
ollama pull mistral:7b
```

### 5. Streamlit app runs but query generation fails

This usually means:

- Ollama is not running
- the selected model is not installed
- the model returned invalid SQL
- the prompt was too ambiguous

The app will try the configured fallback chain and then use keyword-based SQL if needed.

## Dependencies

Project dependencies are listed in:

```text
requirements.txt
```

Additional dependency notes are documented in:

```text
docs/DEPENDENCIES.md
```

Core libraries currently used include DuckDB, Ollama, Streamlit, Plotly, Pandas, Rich, and pytest.

## Notebook

The notebook imports the production modules instead of duplicating them:

```text
notebooks/main.ipynb
```

Use it to validate dataset loading, test fallback queries, and explore watchdog/cost outputs without launching the full CLI or Streamlit app.

## Current Status

The project currently includes:

- shared engine in `src/core.py`
- CLI interface in `src/main.py`
- Streamlit interface in `src/app.py`
- local LLM integration via Ollama
- DuckDB-powered local analytics
- fallback SQL behavior
- business impact estimation
- watchdog anomaly scoring
- airline rivalry comparison
- CSV export from the web UI
- automated tests in `tests/`

## Tech Stack

- Python
- DuckDB
- Streamlit
- Ollama
- Plotly
- Pandas
- Rich
- pytest

## Roadmap

Possible next improvements:

- richer SQL guardrails
- configurable model profiles
- better chart selection logic
- screenshot-rich documentation
- deployment-ready configuration management

## License

See the `LICENSE` file for project licensing details.