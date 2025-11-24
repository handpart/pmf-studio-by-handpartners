PMF Studio by HandPartners - Final Deployable Package (v1)

Included files:
- app.py (Flask server)
- pmf_score_engine.py (PMF scoring engine)
- pdf_template_kor_v2.py (PDF generator)
- pdf_to_drive_reporter.py (Drive uploader supporting service account env var)
- Dockerfile, requirements.txt, render.yaml
- Google service account setup and Sentry monitoring guides
- Render and 1-hour quick-start guides (for non-developers)
- weights.json (editable weights)

Quick start:
1. Push this folder to a new GitHub repo.
2. Create a Render account and connect the repo. Add env var GOOGLE_SERVICE_ACCOUNT_JSON with your service account JSON.
3. Deploy (Free plan) and test /score and /report endpoints.
