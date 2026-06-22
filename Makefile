.PHONY: venv test install wire-dev-up wire-dev-down wire-dev-status wire-dev-env

VENV := .venv
PY := $(VENV)/bin/python3
UV := uv

venv:
	$(UV) venv $(VENV) --python 3.12

install: venv
	$(UV) pip install -e "pipeline/[dev]"

test: install
	cd pipeline && ../$(PY) -m pytest -q

wire-dev-up:
	./scripts/wire-dev.sh up

wire-dev-down:
	./scripts/wire-dev.sh down

wire-dev-status:
	./scripts/wire-dev.sh status

wire-dev-env:
	./scripts/wire-dev.sh env

workflow-validate:
	kubectl apply --dry-run=client -k deploy/k8s/base
