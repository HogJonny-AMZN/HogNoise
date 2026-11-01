# Makefile: the task dispatcher.
#
# Rationale, and the rule this file exists to obey: Docs/standards/tooling.md
#
#   HARD RULE: every recipe is a single `uv` invocation.
#
# No conditionals, no loops, no OS branching, no multi-command sequences. All of that lives in Python under tools/, where
# it is cross-platform by construction and can be tested; tests/test_tooling.py enforces this. Keep this file a
# dispatcher and losing make costs typing, nothing more:
#
#   make check    ==    uv run python tools/check.py
#
# Compatible with GNU Make 3.81 (the build commonly found on Windows and macOS): no .ONESHELL, no $(file ...), no
# .RECIPEPREFIX.

.DEFAULT_GOAL := help

.PHONY: help sync check fast test lint format docs adapters journal board hooks hooks-check

help:
	@echo Every task is a thin wrapper over uv. Without make, each is one uv command, and Docs/standards/tooling.md lists them
	@echo   make sync        - install the dependencies, dev group included
	@echo   make check       - the full gate, every check CI runs in the same order. Run this before pushing
	@echo   make fast        - the fast stages only, which is what the pre-commit hook runs
	@echo   make test        - the tests only
	@echo   make lint        - ruff check
	@echo   make format      - ruff format, writes changes
	@echo   make docs        - the documentation checks only
	@echo   make adapters    - generate the adapters and skills mirrors of the enabled harnesses
	@echo   make journal     - render the journal index page, which is git-ignored and never committed
	@echo   make board       - render the board page from its row files, which is git-ignored and never committed
	@echo   make hooks       - install the git hooks in this clone, once
	@echo   make hooks-check - say whether the git hooks are installed

sync:
	uv sync --group dev

check:
	uv run python tools/check.py

fast:
	uv run python tools/check.py --fast

test:
	uv run pytest -q

lint:
	uv run ruff check .

format:
	uv run ruff format .

docs:
	uv run python tools/check_docs.py

adapters:
	uv run python tools/sync_adapters.py --write

journal:
	uv run python tools/render_journal_index.py

board:
	uv run python tools/render_board.py

hooks:
	uv run python tools/install_hooks.py

hooks-check:
	uv run python tools/install_hooks.py --check
