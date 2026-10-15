# Bê Rào Checklist (be-rao)

Ready to deploy on Render (PostgreSQL) or run locally with .env.

See README in package for instructions.

## SolarWeb at /solar

The same deploy also serves **SolarWeb** (the `solarweb/` package) at `/solar`. `wsgi.py` sends `/solar/*` to SolarWeb and everything else to be-rao. The two apps share the Postgres database, and SolarWeb's tables are all prefixed `sw_`. They have separate logins and separate cookies.

- **Run both locally:** `venv/Scripts/python wsgi.py`. be-rao is at http://127.0.0.1:5000/ and SolarWeb at http://127.0.0.1:5000/solar/.
- **Render start command:** `gunicorn wsgi:app`
- **SolarWeb settings:** these use the `SOLARWEB_` prefix (see `.env.example`).
- **Tests:** `venv/Scripts/pip install -r requirements-dev.txt`, then `venv/Scripts/python -m pytest`.

See [solarweb/README.md](solarweb/README.md) for SolarWeb itself, including how to move it to its own domain later.
