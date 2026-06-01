# nse_trader — Claude Code instructions

## Python virtual environment (always use it)

This project has a dedicated venv at:

```
D:\dev\venvs\nse_trader_venv
```

**Always run Python through this venv** — never the bare `python` on PATH.
Because shell state does not persist between tool calls, activate it *inside the
same command*. In PowerShell:

```powershell
& "D:\dev\venvs\nse_trader_venv\Scripts\Activate.ps1"; python -m src.strategies.three_supertrends_screener
```

Or call the venv interpreter directly (equivalent, no activation needed):

```powershell
& "D:\dev\venvs\nse_trader_venv\Scripts\python.exe" -m src.strategies.three_supertrends_screener
```

This applies to every Python invocation: the screener, `main.py`,
`check_connection.py`, and `pytest`.

## Common commands

- Pre-market screener: `python -m src.strategies.three_supertrends_screener`
- Run bot (paper): `python main.py --dry-run`
- Run bot (live): `python main.py`
- Tests: `pytest tests/ -v --cov=src`

(Each prefixed with the venv activation shown above.)
