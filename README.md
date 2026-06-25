# Ai-Improve

A small, self-contained AI you can **teach**, **ask**, and **connect to the internet** —
all from a clean single-page UI.

The AI is an online text classifier (multinomial Naive Bayes, written from
scratch) that learns incrementally: every example you give it is folded into
the model immediately and persisted to disk, so it keeps improving over time.
It also has live internet access and can train itself directly from web results.

## Run

```bash
./run.sh            # installs deps and starts the server
# or
pip install -r requirements.txt && python3 app.py
```

Then open <http://localhost:8000>.

## What you can do

- **Teach** — give the AI an example (`text` + `label`); it learns instantly.
- **Ask** — give it new text; it predicts the most likely label with confidence.
- **Internet** — search the web, fetch any URL as readable text, or
  *Learn from web*: search a topic and train the AI on the results in one click.

## API

| Method | Endpoint           | Body                          | Purpose                          |
|--------|--------------------|-------------------------------|----------------------------------|
| POST   | `/api/train`       | `{text, label}`               | Teach one example                |
| POST   | `/api/train-batch` | `{examples:[{text,label}]}`   | Teach many at once               |
| POST   | `/api/predict`     | `{text}`                      | Classify text                    |
| GET    | `/api/stats`       | —                             | Model stats                      |
| POST   | `/api/reset`       | —                             | Wipe learned data                |
| POST   | `/api/web/search`  | `{query, limit?}`             | Web search (Wikipedia + DuckDuckGo) |
| POST   | `/api/web/fetch`   | `{url}`                       | Fetch a URL as text              |
| POST   | `/api/web/learn`   | `{query, label?, limit?}`     | Search the web and train on it   |

## Project layout

```
app.py            # stdlib HTTP server + JSON API
core/model.py     # incremental Naive Bayes classifier (persisted)
core/web.py       # internet access: search + URL fetch
static/           # clean single-page UI (HTML/CSS/JS)
```

Dependencies: just `requests` (everything else is the Python standard library).
