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

## Running the full app (backend + website in the browser)

From the **project root** (`/strudel`):

### 1. Backend (Python)

```bash
# Create and activate a virtual environment (once)
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install backend dependencies (once)
pip install -r backend/requirements.txt

# Set your OpenAI API key (once)
# Create backend/.env with: OPENAI_API_KEY=sk-...
# Or export: export OPENAI_API_KEY=sk-...
```

**Optional – for RAG and KB validation** (recommended so the copilot uses the knowledge base):

```bash
# Create DB and tables (once)
cd backend && python init_db.py && cd ..

# Import functions from doc.json (once)
cd backend && python import_data.py && cd ..

# Index into vector store (once; needs OPENAI_API_KEY)
python -m backend.indexing
```

**Start the backend:**

```bash
# From project root, with venv activated
python -m uvicorn backend.main:app --reload --port 8000
```

Leave this terminal running. API: `http://localhost:8000`

### 2. Frontend (website)

In a **second terminal**, from the project root:

```bash
# Install JS dependencies (once)
pnpm install

# Start the website dev server
pnpm run start
```

Website: `http://localhost:4321` (or the port shown in the terminal).

### 3. Use in the browser

Open **http://localhost:4321** and use the copilot sidebar. It will call the backend at `http://localhost:8000/api/copilot/chat`.

## Testing

From the project root, with dependencies installed:

```bash
PYTHONPATH=. python -m unittest discover -s backend/tests -p "test_*.py" -v
```

