SHELL := /bin/bash

RESOURCE_GROUP ?= rg-opensandbox-kata
LOCATION ?= eastus
AKS_NAME ?= osb-kata-aks
ACR_NAME ?=
NODE_VM_SIZE ?= Standard_D4s_v3
NODE_COUNT ?= 3
ASSIGN_ACR_PULL_ROLE ?= true
ACR_ADMIN_USER_ENABLED ?= false
OPEN_SANDBOX_NAMESPACE ?= opensandbox
OPEN_SANDBOX_CONTROLLER_VERSION ?= 0.1.0
SERVER_IMAGE_NAME ?= opensandbox-kata-server
SERVER_IMAGE_TAG ?= latest
SANDBOX_IMAGE ?= python:3.12-slim
SERVER_PORT ?= 8080

ACR_LOGIN_SERVER := $(ACR_NAME).azurecr.io
SERVER_IMAGE := $(ACR_LOGIN_SERVER)/$(SERVER_IMAGE_NAME):$(SERVER_IMAGE_TAG)

.PHONY: all check-tools check-vars check-api-key infra-deploy aks-credentials acr-login image-build image-push controller-install k8s-deploy smoke-test status clean-k8s infra-delete

all: check-tools check-api-key infra-deploy aks-credentials acr-login image-build image-push controller-install k8s-deploy smoke-test

check-tools:
	@command -v az >/dev/null || (echo "az is required"; exit 1)
	@command -v kubectl >/dev/null || (echo "kubectl is required"; exit 1)
	@command -v helm >/dev/null || (echo "helm is required"; exit 1)
	@command -v docker >/dev/null || (echo "docker is required"; exit 1)
	@command -v python3 >/dev/null || (echo "python3 is required"; exit 1)
	@command -v curl >/dev/null || (echo "curl is required"; exit 1)

check-vars:
	@test -n "$(ACR_NAME)" || (echo "ACR_NAME is required and must be globally unique"; exit 1)
	@if [ "$(ASSIGN_ACR_PULL_ROLE)" = "false" ] && [ "$(ACR_ADMIN_USER_ENABLED)" != "true" ]; then \
		echo "ACR_ADMIN_USER_ENABLED=true is required when ASSIGN_ACR_PULL_ROLE=false"; \
		exit 1; \
	fi

check-api-key:
	@test -n "$${OPEN_SANDBOX_API_KEY}" || (echo "OPEN_SANDBOX_API_KEY is required"; exit 1)

infra-deploy: check-vars
	az group create --name "$(RESOURCE_GROUP)" --location "$(LOCATION)"
	az deployment group create \
		--resource-group "$(RESOURCE_GROUP)" \
		--template-file infra/main.bicep \
		--parameters aksName="$(AKS_NAME)" acrName="$(ACR_NAME)" location="$(LOCATION)" nodeVmSize="$(NODE_VM_SIZE)" nodeCount=$(NODE_COUNT) assignAcrPullRole=$(ASSIGN_ACR_PULL_ROLE) acrAdminUserEnabled=$(ACR_ADMIN_USER_ENABLED)

aks-credentials:
	az aks get-credentials --resource-group "$(RESOURCE_GROUP)" --name "$(AKS_NAME)" --overwrite-existing

acr-login: check-vars
	az acr login --name "$(ACR_NAME)"

image-build: check-vars
	docker build -t "$(SERVER_IMAGE)" -f examples/opensandbox-kata/server.Dockerfile .

image-push: check-vars
	docker push "$(SERVER_IMAGE)"

controller-install:
	helm upgrade --install opensandbox-controller \
		https://github.com/opensandbox-group/OpenSandbox/releases/download/helm/opensandbox-controller/$(OPEN_SANDBOX_CONTROLLER_VERSION)/opensandbox-controller-$(OPEN_SANDBOX_CONTROLLER_VERSION).tgz \
		--namespace opensandbox-system \
		--create-namespace
	kubectl wait --for=condition=Established crd/batchsandboxes.sandbox.opensandbox.io --timeout=180s
	kubectl wait --for=condition=Established crd/pools.sandbox.opensandbox.io --timeout=180s
	kubectl wait --for=condition=ready pod -l control-plane=controller-manager -n opensandbox-system --timeout=180s
	kubectl get runtimeclass kata-vm-isolation

k8s-deploy: check-vars check-api-key
	kubectl create namespace "$(OPEN_SANDBOX_NAMESPACE)" --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n "$(OPEN_SANDBOX_NAMESPACE)" create serviceaccount opensandbox-server --dry-run=client -o yaml | kubectl apply -f -
	kubectl -n "$(OPEN_SANDBOX_NAMESPACE)" create secret generic opensandbox-server \
		--from-literal=api-key="$${OPEN_SANDBOX_API_KEY}" \
		--dry-run=client -o yaml | kubectl apply -f -
	@if [ "$(ASSIGN_ACR_PULL_ROLE)" = "false" ] && [ "$(ACR_ADMIN_USER_ENABLED)" = "true" ]; then \
		set -euo pipefail; \
		password=$$(az acr credential show --name "$(ACR_NAME)" --query 'passwords[0].value' -o tsv); \
		test -n "$$password"; \
		kubectl delete secret acr-pull -n "$(OPEN_SANDBOX_NAMESPACE)" --ignore-not-found; \
		printf '%s' "$$password" | REGISTRY="$(ACR_LOGIN_SERVER)" USERNAME="$(ACR_NAME)" NAMESPACE="$(OPEN_SANDBOX_NAMESPACE)" python3 -c 'import base64,json,os,sys; u=os.environ["USERNAME"]; p=sys.stdin.read(); r=os.environ["REGISTRY"]; ns=os.environ["NAMESPACE"]; auth=base64.b64encode(f"{u}:{p}".encode()).decode(); cfg={"auths":{r:{"username":u,"password":p,"auth":auth}}}; data=base64.b64encode(json.dumps(cfg,separators=(",",":")).encode()).decode(); print(f"apiVersion: v1\nkind: Secret\nmetadata:\n  name: acr-pull\n  namespace: {ns}\ntype: kubernetes.io/dockerconfigjson\ndata:\n  .dockerconfigjson: {data}\n")' | kubectl create -f -; \
		kubectl -n "$(OPEN_SANDBOX_NAMESPACE)" patch serviceaccount opensandbox-server \
			--type merge \
			--patch '{"imagePullSecrets":[{"name":"acr-pull"}]}'; \
	fi
	sed \
		-e 's|__NAMESPACE__|$(OPEN_SANDBOX_NAMESPACE)|g' \
		examples/opensandbox-kata/config/sandbox.toml | kubectl -n "$(OPEN_SANDBOX_NAMESPACE)" create configmap opensandbox-server-config \
		--from-file=sandbox.toml=/dev/stdin \
		--dry-run=client -o yaml | kubectl apply -f -
	sed \
		-e 's|__SERVER_IMAGE__|$(SERVER_IMAGE)|g' \
		-e 's|__NAMESPACE__|$(OPEN_SANDBOX_NAMESPACE)|g' \
		examples/opensandbox-kata/k8s/opensandbox-server.yaml | kubectl apply -f -
	kubectl rollout status deployment/opensandbox-server -n "$(OPEN_SANDBOX_NAMESPACE)" --timeout=180s

smoke-test: check-api-key
	kubectl -n "$(OPEN_SANDBOX_NAMESPACE)" port-forward svc/opensandbox-server $(SERVER_PORT):8080 >/tmp/opensandbox-kata-port-forward.log 2>&1 & echo $$! > /tmp/opensandbox-kata-port-forward.pid
	set -e; \
		trap 'kill $$(cat /tmp/opensandbox-kata-port-forward.pid) >/dev/null 2>&1 || true' EXIT; \
		for i in {1..30}; do curl -fsS http://localhost:$(SERVER_PORT)/health >/dev/null && break || sleep 1; done; \
		curl -fsS http://localhost:$(SERVER_PORT)/health >/dev/null; \
		python3 -m venv .venv; \
		. .venv/bin/activate; \
		pip install -q -r examples/opensandbox-kata/requirements.txt; \
		OPEN_SANDBOX_DOMAIN=localhost:$(SERVER_PORT) OPEN_SANDBOX_API_KEY="$${OPEN_SANDBOX_API_KEY}" SANDBOX_IMAGE="$(SANDBOX_IMAGE)" VERIFY_KATA_WITH_KUBECTL=1 OPEN_SANDBOX_NAMESPACE="$(OPEN_SANDBOX_NAMESPACE)" python examples/opensandbox-kata/app.py

status:
	kubectl get runtimeclass
	kubectl get pods -n opensandbox-system
	kubectl get pods -n "$(OPEN_SANDBOX_NAMESPACE)" -o wide
	kubectl get batchsandboxes -n "$(OPEN_SANDBOX_NAMESPACE)" || true

clean-k8s:
	kubectl delete namespace "$(OPEN_SANDBOX_NAMESPACE)" --ignore-not-found
	helm uninstall opensandbox-controller -n opensandbox-system || true
	kubectl delete namespace opensandbox-system --ignore-not-found

infra-delete:
	az group delete --name "$(RESOURCE_GROUP)" --yes --no-wait
