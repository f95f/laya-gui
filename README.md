# Laya Decision Chat

Local decision chat with a FastAPI backend, Angular frontend, and SQLite history. The original `laya_gui.py` and `test_laya.py` remain available.

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

Open http://localhost:4200. The first decision may take longer because Laya loads its checkpoint. Subsequent requests reuse the Router in the backend process.

The app currently uses the English Laya checkpoint. The displayed probabilities are model estimates; the checkpoint may report uncalibrated confidence values, so evaluate it on your own decision data before automating consequential actions.

The active schema is in `config/laya-config.json` and can be edited through the Config page. Conversations and config versions are stored in `data/laya_history.db`. A response contains the selected choice, its probability, detailed model metadata, and the exact config used for that request.

Run backend checks with `python -m unittest backend.test_main` from the project root. The frontend builds with `npm run build` inside `frontend`. For frontend tests on Windows with Edge installed, set `CHROME_BIN` to the Edge executable before running `npm test -- --watch=false --browsers=ChromeHeadless`.
