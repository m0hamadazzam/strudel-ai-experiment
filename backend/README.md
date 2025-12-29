# Strudel AI Copilot Backend

FastAPI backend for the Strudel AI Copilot feature.

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and add your API keys:
```bash
cp .env.example .env
# Edit .env with your keys
```

4. Run the server (from project root):
```bash
# From the project root directory
python -m uvicorn backend.main:app --reload --port 8000
```

Or if running from the backend directory:
```bash
cd backend
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

