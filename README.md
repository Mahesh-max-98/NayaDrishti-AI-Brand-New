# NayaDrishti AI

A new implementation built independently from the ground up.

## Stage 1: Foundation
- Responsive landing page
- Flask application
- Health-check endpoint at `/health`

## Run locally
```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`.

## Production start
```bash
gunicorn --workers 1 --threads 8 app:app
```

News collection, AI assistance, editorial review, admin tools and publishing integrations are planned for later stages. They are not enabled in this foundation release.
