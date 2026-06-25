---
name: launch
description: Print the exact, copy-paste-ready commands to start the Self-Improving Local AI Agent and open it in the browser. Use whenever the user asks how to run, open, start, or launch the app / the AI model / the dashboard.
---

# Launch the app

When this skill is invoked, give the user the simplest possible way to start the
Self-Improving Local AI Agent and open it in their browser. Be concrete and minimal —
they just want commands they can paste (or, better, a file they can double-click).

## Always offer the zero-typing option first

The repo ships double-click launchers that install dependencies and open the browser:

- **Windows:** double-click **`run.bat`** in the project folder (`C:\Users\<you>\Ai-Improve`).
- **macOS / Linux:** run **`./run.sh`** from the project folder.

Tell them this first — it removes all terminal friction.

## Then give the manual paste commands

Default to **Windows PowerShell** (the primary user is on Windows). Give two commands,
one per line, no inline comments:

```powershell
cd C:\Users\Penns\Ai-Improve
python main.py
```

For macOS / Linux:

```bash
cd ~/Ai-Improve
python3 main.py
```

Then tell them: the browser opens automatically; if not, go to **http://localhost:8080**.

## Notes to include only if relevant

- If they hit "python is not recognized," they need Python 3.11+ from python.org
  (tick "Add to PATH" during install) and a fresh terminal.
- Chat needs Ollama running locally (`ollama pull qwen2.5-coder`); everything else —
  Run one iteration, the live graph, rollback — works without it.
- Keep the response short. Do not paste the whole README; just the launch path.
