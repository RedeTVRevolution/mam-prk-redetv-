.PHONY: instalar verificar testar-afk

instalar:
	uv sync --locked
	npm ci --prefix web
	git config core.hooksPath .githooks

verificar:
	uv run --locked ruff check
	uv run --locked ruff format --check
	uv run --locked mypy api
	uv run --locked pytest
	npm run --prefix web lint
	npm run --prefix web typecheck
	npm run --prefix web test
	npm run --prefix web build

testar-afk:
	shellcheck scripts/afk/*.sh
	scripts/afk/testes.sh
