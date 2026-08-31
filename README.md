# NFL Results Dashboard V1.5 - Internet Deployment Version

This version is prepared for deployment to Render.

## Local testing

From PowerShell in this folder:

    python app.py

Open:

    http://127.0.0.1:5000

Draft Team Pool:

    http://127.0.0.1:5000/draft

## Render deployment

This package includes:
- gunicorn in requirements.txt
- render.yaml
- /health endpoint
- support for Render's PORT environment variable
- SQLite database storage at /var/data/nfl_results.db when deployed
- a 1 GB persistent disk definition in render.yaml

Important:
Render persistent disks require a paid web service. Without a persistent disk,
SQLite changes can be lost when the service restarts or redeploys.

Recommended Render setup:
Build command:
    pip install -r requirements.txt

Start command:
    gunicorn app:app

Health check path:
    /health

Database environment variable:
    NFL_DB=/var/data/nfl_results.db

Persistent disk mount path:
    /var/data
