# The SQL Alchemist

The SQL Alchemist is a local Business Intelligence assistant that converts natural-language questions into DuckDB SQL over flight operations data.[file:1126]

It supports two interfaces:[file:1126]

- A terminal CLI in `src/main.py`.[file:1126]
- A Streamlit web app in `src/app.py`.[file:1126]

The project uses local Ollama models for NL-to-SQL generation and includes validation plus keyword-based fallback logic when model output is invalid or unavailable.[file:1126]

---

## Features

- Natural language to SQL over a local DuckDB dataset.[file:1126]
- Shared configuration through `config.py`.[file:1126]
- Streamlit UI with model selection, SQL preview, result rendering, history export, and replay.[file:1126]
- CLI experience with rich terminal formatting.[file:1127]
- Business analysis layers:
  - Watchdog, for anomaly and data-quality style detection.
  - Airline Wars, for ranking and window-function comparisons.
  - Cost of Chaos, for disruption cost estimation.
  - Result Explanation, for automatic narrative summaries.
- Keyword fallback SQL when model generation fails.[file:1126]

---

## Project structure

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

This structure keeps the runtime code in `src/`, documentation in `docs/`, and notebook material in `notebooks/`, while preserving the dataset path expected by the app: `data/flights.csv`.[file:1126]

---

## Data model

The dataset is loaded into an in-memory DuckDB table named `flights`.[file:1126]

Expected columns:[file:1126]

- `flight_id`
- `airline`
- `origin`
- `destination`
- `departure_time`
- `arrival_time`
- `latency_minutes`
- `status`

The `status` field is expected to contain values such as `On-Time`, `Delayed`, and `Cancelled`.[file:1126]

---

## Requirements

- Python 3.10+.[file:1126]
- Ollama installed locally.[file:1126]
- At least one local model available, for example `qwen3.6:27b`.[file:1126]

Python dependencies used by the project include `duckdb`, `rich`, `ollama`, `streamlit`, `plotly`, and `pandas`.[file:1127][file:1128]

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

This project is designed for local execution and does not require a cloud dependency for NL-to-SQL behavior.[file:1126]

---

## Run the CLI

From the project root:

```bash
python3 src/main.py
```

Inside the terminal experience, you can ask questions in plain English and exit with `quit`, `exit`, or `q`.[file:1126]

Example questions:[file:1126]

- `Which airlines have the highest average latency?`
- `How many flights were cancelled by airline?`
- `Show delayed flights ordered by latency.`
- `What is the distribution of flight statuses?`

---

## Run the Streamlit app

From the project root:

```bash
python3 -m streamlit run src/app.py
```

The Streamlit app supports installed-model picking, manual model input fallback, generated SQL preview, results rendering, optional charting, session history, SQL replay, and export to JSON or CSV.[file:1126]

---

## Reliability

To improve stability, the project sanitizes model output, accepts only `SELECT` queries, and applies keyword-based fallback SQL when generated output is invalid or unavailable.[file:1126]

This avoids always returning the same default query shape and makes the app more robust during local model failures.[file:1126]

---

## Troubleshooting

### Model not found

If you get `model ... not found (404)`, pull the model locally with Ollama or choose an installed model from the Streamlit interface.[file:1126]

### Could not fetch local Ollama models

Ensure `ollama serve` is running locally.[file:1126]

### File does not exist

Run commands from the project root so paths like `src/app.py` and `data/flights.csv` resolve correctly.[file:1126]

### ModuleNotFoundError

Reinstall dependencies:

```bash
python3 -m pip install -r requirements.txt
```

---

## Notes

- This project is intended for local execution.[file:1126]
- Query quality depends on both model quality and prompt specificity.[file:1126]
- The notebook version in `notebooks/main.ipynb` documents the CLI architecture and analysis layers discussed during development.

---

## License

Add your preferred open-source license here, for example MIT.