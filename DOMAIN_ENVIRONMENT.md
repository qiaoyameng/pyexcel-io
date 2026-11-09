# Reproducible authoring environment

Upstream: https://github.com/pyexcel/pyexcel-io
Upstream commit: 37b06118b05087454d67045a954fc4f1fd52013f
Verified runtime: 3.13.14 (tags/v3.13.14:fd17997, Jun 10 2026, 13:03:48) [MSC v.1944 64 bit (AMD64)]
Verified platform: win32

Use an isolated virtual environment. Install the pinned dependencies with
`python -m pip install -r requirements-domain.lock`, then `python -m pip install -e .`.
Set the following environment variables before installation and testing:

```text
PYTHONUTF8=1
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
```

Core baseline:

```text
python -m pytest -q -o addopts= tests/test_new_csv_book.py tests/test_new_csvz_book.py tests/test_sheet.py tests/test_filter.py
```

Measured pytest process time: 0.298 seconds on the authoring host.
CSV/TSV and CSVZ/TSVZ only. chardet 5.2.0 is a pure Python dependency; Excel, SQL and Django plugins are not installed.

All documented checks use in-memory fixtures or local temporary files. No production
accounts, data services, credentials or external network endpoints are required after setup.
Reset by making a fresh checkout of this seed and creating a new virtual environment.
Test fixtures remain under their upstream repository license.
