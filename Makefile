.PHONY: venv test install build-wheel publish-wheel wire-dev-up wire-dev-down wire-dev-status wire-dev-env \
	workflow-validate kustomize-build argo-install bootstrap-k8s \
	ensure-namespace ensure-registry-secret k8s-apply-dev set-dev-image-tag deploy-dev build-images build-pipeline-image \
	e2e-ingest-rag e2e-local-rag e2e-downstream test-infra-config test-wire-dev-config test-knowledge-binding-setup-config deploy-nebula verify-nebula teardown-nebula tune-node-inotify

VENV := .venv
PY := $(VENV)/bin/python3
UV := uv
REGISTRY ?= ghcr.io/yoosungung/path-graph
GHCR_USER ?= $(shell echo $(REGISTRY) | cut -d/ -f2)
NAMESPACE ?= path-graph
REF ?= main
IMAGE_TAG ?= $(shell ./scripts/resolve-image-tag.sh)
PUSH ?=

venv:
	@test -d $(VENV) || $(UV) venv $(VENV) --python 3.12

install: venv
	$(UV) pip install -e "pipeline/[dev]"

test: install
	cd pipeline && ../$(PY) -m pytest -q

build-wheel:
	cd pipeline && $(UV) build

publish-wheel: build-wheel
	@test -n "$(UV_PUBLISH_TOKEN)" \
		|| { echo "error: UV_PUBLISH_TOKEN required (e.g. gh auth token)" >&2; exit 1; }
	@version=$$($(PY) -c "import tomllib; print(tomllib.load(open('pipeline/pyproject.toml','rb'))['project']['version'])"); \
	GH_TOKEN=$(UV_PUBLISH_TOKEN) gh release upload "v$$version" pipeline/dist/*.whl --clobber

wire-dev-up:
	./scripts/wire-dev.sh up

wire-dev-down:
	./scripts/wire-dev.sh down

wire-dev-status:
	./scripts/wire-dev.sh status

wire-dev-env:
	./scripts/wire-dev.sh env

test-wire-dev-config:
	./scripts/test_wire_dev_config.sh

test-knowledge-binding-setup-config:
	chmod +x scripts/test_knowledge_binding_setup_config.sh
	./scripts/test_knowledge_binding_setup_config.sh

workflow-validate:
	kubectl apply --dry-run=client -k deploy/k8s/overlays/dev

kustomize-build:
	kubectl kustomize deploy/k8s/overlays/dev

argo-install:
	./scripts/install-argo.sh

ensure-namespace:
	@kubectl get ns $(NAMESPACE) >/dev/null 2>&1 \
		|| kubectl apply -f deploy/k8s/base/namespace.yaml

registry-secret:
	@test -n "$(GITHUB_USER)" -a -n "$(GITHUB_PAT)" \
		|| { echo "error: GITHUB_USER and GITHUB_PAT required" >&2; exit 1; }
	@kubectl create secret docker-registry registry-creds \
		--namespace $(NAMESPACE) \
		--docker-server=ghcr.io \
		--docker-username=$(GITHUB_USER) \
		--docker-password=$(GITHUB_PAT) \
		--dry-run=client -o yaml | kubectl apply -f -

ensure-registry-secret: ensure-namespace
	@kubectl -n $(NAMESPACE) get secret registry-creds >/dev/null 2>&1 \
		&& echo "registry-creds already exists in $(NAMESPACE), skipping" \
		|| $(MAKE) _bootstrap-registry-secret

_bootstrap-registry-secret:
	@set -e; \
	if kubectl -n runtime get secret registry-creds >/dev/null 2>&1; then \
		echo "Copying registry-creds from runtime → $(NAMESPACE)"; \
		kubectl get secret registry-creds -n runtime -o yaml \
			| sed 's/namespace: runtime/namespace: $(NAMESPACE)/' \
			| grep -v '^\s*resourceVersion:' \
			| grep -v '^\s*uid:' \
			| grep -v '^\s*creationTimestamp:' \
			| kubectl apply -f -; \
	elif [ -n "$(GITHUB_USER)" ] && [ -n "$(GITHUB_PAT)" ]; then \
		$(MAKE) registry-secret GITHUB_USER="$(GITHUB_USER)" GITHUB_PAT="$(GITHUB_PAT)"; \
	elif command -v gh >/dev/null 2>&1; then \
		token=$$(gh auth token --user $(GHCR_USER) 2>/dev/null || gh auth token 2>/dev/null || true); \
		if [ -n "$$token" ]; then \
			echo "Creating registry-creds from gh auth (user=$(GHCR_USER))"; \
			$(MAKE) registry-secret GITHUB_USER="$(GHCR_USER)" GITHUB_PAT="$$token"; \
		else \
			echo "WARNING: registry-creds missing. Push to GHCR first or set GITHUB_USER/GITHUB_PAT" >&2; \
			exit 1; \
		fi; \
	else \
		echo "WARNING: registry-creds missing. Set GITHUB_USER/GITHUB_PAT or install gh" >&2; \
		exit 1; \
	fi

set-dev-image-tag:
	chmod +x ./scripts/resolve-image-tag.sh ./scripts/set-dev-image-tag.sh
	./scripts/set-dev-image-tag.sh $(IMAGE_TAG)

k8s-apply-dev: ensure-registry-secret set-dev-image-tag
	./scripts/create-path-graph-secrets.sh
	./scripts/bootstrap-filestash.sh
	kubectl apply -k deploy/k8s/overlays/dev
	./scripts/patch-runtime-ingress-for-path-graph.sh

bootstrap-k8s: argo-install k8s-apply-dev
	@echo "Bootstrap complete (images: make build-images after git push)"

build-images:
	gh workflow run "Build and push images" --ref $(REF)
	@echo "Triggered. Watch: gh run list --workflow=build-images.yml --limit=1"

build-pipeline-image:
	chmod +x ./scripts/build-pipeline-image.sh ./scripts/resolve-image-tag.sh
	TAG=$(IMAGE_TAG) PUSH=$(PUSH) ./scripts/build-pipeline-image.sh

deploy-dev: build-pipeline-image k8s-apply-dev

e2e-ingest-rag: install
	./scripts/submit-ingest-rag-e2e.sh

e2e-local-rag: install test-wire-dev-config
	./scripts/run-local-rag-e2e.sh

e2e-downstream: install
	./scripts/submit-downstream-e2e.sh

test-infra-config:
	chmod +x scripts/test-nebula-config.sh scripts/test-nebula-studio-config.sh scripts/test-filestash-config.sh scripts/test-path-graph-secrets-config.sh deploy/k8s/base/render-filestash-config.sh scripts/render-filestash-config.sh
	./scripts/test-nebula-config.sh
	./scripts/test-nebula-studio-config.sh
	./scripts/test-filestash-config.sh
	./scripts/test-path-graph-secrets-config.sh

deploy-nebula:
	chmod +x scripts/deploy-nebula.sh
	./scripts/deploy-nebula.sh --force

verify-nebula:
	chmod +x scripts/verify-nebula.sh scripts/verify-nebula-studio.sh
	./scripts/verify-nebula.sh
	./scripts/verify-nebula-studio.sh

teardown-nebula:
	chmod +x scripts/teardown-nebula.sh
	./scripts/teardown-nebula.sh --force

tune-node-inotify:
	chmod +x ./scripts/tune-node-inotify.sh
	./scripts/tune-node-inotify.sh
