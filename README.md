# Laya Decision Chat

Local decision chat with a FastAPI backend, Angular frontend, SQLite history, reusable decision configs, and selectable local model providers. The original `laya_gui.py` and `test_laya.py` remain available.

## Run

From this folder in PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.main:app --reload --port 8000
```

In another PowerShell window:

```powershell
cd frontend
npm install
npm start
```

Open http://localhost:4200. The first Laya decision may take longer because Laya loads its checkpoint. Subsequent requests reuse the Router in the backend process.

The app includes the English Laya checkpoint and local Ollama model options. By default the Ollama options are `granite4.2:3b`, `qwen3.5:0.8b`, and `qwen3.5:4b`; override the list with `OLLAMA_MODEL_IDS`, for example:

```powershell
$env:OLLAMA_MODEL_IDS="granite4.2:3b,qwen3.5:0.8b,qwen3.5:4b"
$env:OLLAMA_BASE_URL="http://localhost:11434"
uvicorn backend.main:app --reload --port 8000
```

Do not confuse `OLLAMA_MODEL_IDS` with Ollama's own `OLLAMA_MODELS` variable, which controls where Ollama stores downloaded model files.

The displayed probabilities and confidence values are model estimates; evaluate them on your own decision data before automating consequential actions.

The first startup migrates `config/laya-config.json` into a SQLite config profile. Use the Config page to create, duplicate, activate, and edit profiles, and to choose each profile's default model. Conversations, config profiles, config versions, and responses are stored in `data/laya_history.db`. A response contains the selected choice, its probability/confidence, detailed model metadata, and the exact config used for that request.

Run backend checks with `python -m unittest backend.test_main` from the project root. The frontend builds with `npm run build` inside `frontend`. For frontend tests on Windows with Edge installed, set `CHROME_BIN` to the Edge executable before running `npm test -- --watch=false --browsers=ChromeHeadless`.
