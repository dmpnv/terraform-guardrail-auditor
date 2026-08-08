# Root conftest (Saturday finding 2): bare `pytest` from a fresh clone must
# work. Pytest prepends the directory of the topmost conftest.py to sys.path
# (default importmode=prepend), which puts the repo root — and therefore the
# `app` package — on the path. No code needed; verified from a fresh clone
# with both `pytest -q` and `python -m pytest -q`.
