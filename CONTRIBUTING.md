# Contributing to Atlas Trader

Thanks for your interest! Atlas Trader is a crypto funding-rate carry strategy: short perpetual + long spot, delta-neutral, collecting the funding rate premium.

## Quick Start

```bash
git clone https://github.com/eletec/atlas-trader.git
cd atlas-trader
docker compose -f docker-compose.v4.yml up -d --build
```

All work happens on `main` — there is no development branch.

## Development

- **API**: FastAPI on port 8000 — `v4/api/`
- **Dashboard**: Streamlit on port 8502 — `dashboard/streamlit_app.py`
- **Strategy**: funding-carry node and cycle — `v7/`
- **Config**: `config/carry_assets.yaml` is the single source of truth for the
  strategy. Live code, the monitor and the backtests all read it, so a backtest
  always tests the strategy that is actually running.

### Running the tests

```bash
# on the host (needs pytest)
python -m pytest v7/tests/test_carry_accounting.py -v
```

`pytest` is intentionally **not** in the production image.

Before opening a PR, a quick static check catches most real bugs — note that
`compileall` alone does not detect undefined names:

```bash
python -m compileall -q dashboard v4 v7 utils storage
python -m pyflakes    dashboard v4 v7 utils storage
```

## Pull Requests

1. Fork the repo and create a feature branch from `main`
2. Keep PRs focused — one feature or fix per PR
3. Logs must be in English
4. **Never hardcode a user-facing string**: add an i18n key to `utils/i18n.py`
   (`t("your_key")`), with all 8 languages. Check that every `t("…")` you use
   exists, and that you are not redefining an existing key — duplicate keys in
   `_TRANSLATIONS` are silently overridden by the last definition.
5. Do not reintroduce hardcoded strategy parameters: read them from
   `carry_assets.yaml` via `v7.core.asset_config`.
6. Test with `docker compose -f docker-compose.v4.yml up -d --build`

## Code Style

- Python 3.11+, type hints recommended
- 4 spaces, no tabs
- Docstrings for public functions

## Issues

- Bug reports: include Docker logs and steps to reproduce
- Feature requests: explain the use case and expected behavior

## License

MIT — see [LICENSE](LICENSE)
