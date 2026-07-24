# Contributing to Atlas Trader

Thanks for your interest! Atlas Trader is a crypto funding-rate carry strategy with a DAG execution engine.

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
git checkout v7-dev
docker compose -f docker-compose.v4.yml up -d --build
```

## Development

- **API**: FastAPI on port 8000 — `v4/api/`
- **Dashboard**: Streamlit on port 8502 — `dashboard/streamlit_app.py`
- **Frontend**: Next.js on port 3000 — `v4/frontend/`
- **Strategy**: Funding carry nodes — `v7/`

## Pull Requests

1. Fork the repo and create a feature branch from `v7-dev`
2. Keep PRs focused — one feature or fix per PR
3. Logs must be in English
4. Add i18n keys to `utils/i18n.py` for any user-facing strings
5. Test with `docker compose -f docker-compose.v4.yml up -d --build`

## Code Style

- Python 3.11+, type hints recommended
- 4 spaces, no tabs
- Docstrings for public functions

## Issues

- Bug reports: include Docker logs and steps to reproduce
- Feature requests: explain the use case and expected behavior

## License

MIT — see [LICENSE](LICENSE)
