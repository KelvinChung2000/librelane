all: dist
.PHONY: dist
dist:
	uv build

.PHONY: mount
mount:
	@echo "make mount is not needed in LibreLane. You may simply call 'librelane --dockerized'."

.PHONY: pdk pull-openlane pull-librelane
pdk pull-openlane pull-librelane:
	@echo "LibreLane will automatically pull PDKs and/or Docker containers when it needs them."

.PHONY: openlane librelane
librelane openlane:
	@echo "make librelane is deprecated. Please use make docker-image."
	@echo "----"
	@$(MAKE) docker-image

.PHONY: docker-image
docker-image:
	cat $(shell nix build --no-link --print-out-paths .#librelane-docker -L --verbose) | docker load

# double-installing is still fast
.PHONY: docs
docs:
	uv run --group docs $(MAKE) -C docs html

.PHONY: host-docs
host-docs:
	uv run python3 -m http.server --directory ./docs/build/html
	
.PHONY: watch-docs
watch-docs:
	pymon\
		-d\
		-w '*.md'\
		-w '*.css'\
		-i "*docs/build/*"\
		-i "*docs/source/reference/*_vars.md"\
		-i "*docs/source/reference/flows.md"\
		-x "$(MAKE) docs && python3 -m http.server --directory docs/build/html"

.PHONY: lint
lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy .

.PHONY: coverage-infrastructure
coverage-infrastructure:
	uv run pytest -n auto \
		--cov=librelane --cov-config=.coveragerc --cov-report html:htmlcov_infra --cov-report term

.PHONY: coverage-steps
coverage-steps:
	uv run pytest -n auto \
		--cov=librelane.steps --cov-config=.coveragerc-steps --cov-report html:htmlcov_steps --cov-report term \
		-k test_all_steps

.PHONY: check-license
check-license: venv
	uv pip freeze > ./requirements.frz.txt
	docker run -v `pwd`:/volume \
		-it --rm pilosus/pip-license-checker \
		java -jar app.jar \
		--requirements '/volume/requirements.frz.txt'

.PHONY: venv
venv:
	uv sync --all-groups
	@echo ">> Environment prepared. Use 'uv run <command>'."

.PHONY: veryclean
veryclean: clean
	rm -rf .venv/

.PHONY: clean
clean:
	rm -rf build/
	rm -rf logs/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf designs/*/runs
	rm -rf test_data/designs/*/runs
	rm -rf test/designs/*/runs
