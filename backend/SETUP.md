# Database Setup and Testing Guide

## Prerequisites

Make sure you have:
- Python 3.9+ installed
- Virtual environment activated (if using one)
- Dependencies installed: `pip install -r requirements.txt`

## Step-by-Step Setup

### 1. Initialize the Database

Create the SQLite database and all tables:

```bash
cd backend
python init_db.py
```

If the database already exists, it will ask if you want to recreate it. Type `yes` to recreate or `no` to keep existing data.

### 2. Import Functions from doc.json

Import all Strudel functions into the database:

```bash
python import_data.py
```

Expected output:
```
Loading functions from /path/to/doc.json...
=== Import Summary ===
Imported: 509 functions
Skipped: 58 functions
Import completed!
```

### 3. Validate the Import

Verify that all data was imported correctly:

```bash
python validate_import.py
```

Expected output should show all checks passing:
- ✓ All unique functions imported
- ✓ No duplicate function names
- ✓ Categories assigned
- ✓ All JSON fields are valid
- ✓ Examples, synonyms, and parameters preserved

### 4. Test the Database (Optional)

You can query the database directly using Python:

```bash
python -c "
from database import get_session, Function
session = get_session()
funcs = session.query(Function).limit(5).all()
for f in funcs:
    print(f'{f.name} ({f.category}): {f.description[:50]}...')
session.close()
"
```

## Running the Backend API

Once the database is set up, start the FastAPI server:

```bash
# From project root
python -m uvicorn backend.main:app --reload
```

The API will be available at `http://localhost:8000`

## Quick Test Script

To do everything in one go:

```bash
cd backend
python init_db.py <<< "yes"  # Recreate database
python import_data.py         # Import functions
python validate_import.py      # Validate import
```

## Troubleshooting

### Database file location
The database is created at: `backend/strudel_kb.db`

### If import fails
- Make sure `doc.json` exists in the project root
- Check that the database was initialized first
- Verify all dependencies are installed

### If validation fails
- Check the error messages in the validation output
- Re-run `init_db.py` to recreate the database
- Re-run `import_data.py` to re-import

