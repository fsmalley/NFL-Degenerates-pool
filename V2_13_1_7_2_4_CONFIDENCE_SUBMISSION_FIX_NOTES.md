# V2.13.1.7.2.4 — Confidence Submission Fix

Focused fix built from V2.13.1.7.2.3.

- Confidence POST submission now validates against the already-stored weekly schedule instead of synchronously calling NFL/ESPN again during Submit.
- This removes a redundant external-network operation from the save path that could cause Render/Gunicorn to return an HTML timeout/error response while the browser expected JSON.
- Confidence database save exceptions are logged server-side and returned to the browser as JSON errors.
- The Confidence frontend now checks the response content type before parsing JSON, so an upstream/server HTML error is shown as a useful status message rather than `Unexpected token '<'`.
- No database migration, scoring change, Draft change, Survivor change, member-account change, or health-check change.
