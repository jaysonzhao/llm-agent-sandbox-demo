#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="llm-sandbox-demo"
OPEN_WEBUI_NAMESPACE="open-webui"
AGENT_IMAGE="${AGENT_IMAGE:-quay.io/llm-sandbox-demo/agent-backend:latest}"

info()  { echo -e "\033[1;34m[INFO]\033[0m  $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m  $*"; }
error() { echo -e "\033[1;31m[ERROR]\033[0m $*"; exit 1; }

wait_for_resource() {
    local kind="$1" name="$2" ns="$3" condition="${4:-condition=Available}" timeout="${5:-300s}"
    info "Waiting for $kind/$name ($condition) ..."
    oc wait "$kind/$name" -n "$ns" --for="$condition" --timeout="$timeout" 2>/dev/null || true
}

wait_for_inference_service() {
    local name="$1" ns="$2" timeout="${3:-900s}"
    info "Waiting for InferenceService/$name to be ready (model download may take several minutes) ..."
    if oc wait "inferenceservice/$name" -n "$ns" --for=condition=Ready --timeout="$timeout" 2>/dev/null; then
        info "Model server is ready"
    else
        warn "Timed out waiting for model server - check: oc get pods -n $ns -l serving.kserve.io/inferenceservice=$name"
    fi
}

wait_for_warm_pool() {
    local name="$1" ns="$2" timeout_secs="${3:-600}"
    local desired ready
    desired=$(oc get sandboxwarmpool "$name" -n "$ns" -o jsonpath='{.spec.replicas}' 2>/dev/null || echo "0")
    info "Waiting for SandboxWarmPool/$name ($desired ready replicas) ..."
    for i in $(seq 1 $(( timeout_secs / 5 ))); do
        ready=$(oc get sandboxwarmpool "$name" -n "$ns" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "${ready:-0}" -ge "${desired:-0}" ] && [ "${desired:-0}" -gt 0 ]; then
            info "Sandbox warm pool is ready ($ready/$desired replicas)"
            return 0
        fi
        [ "$i" -eq $(( timeout_secs / 5 )) ] && warn "Timed out waiting for warm pool - check: oc get sandboxes -n $ns"
        sleep 5
    done
}

# ── Step 0: Preflight ──────────────────────────────────────────────
info "Checking prerequisites ..."
command -v oc   >/dev/null || error "'oc' CLI not found"
oc whoami       >/dev/null || error "Not logged in to an OpenShift cluster"

# ── Step 1: Install OpenShift AI Operator ──────────────────────────
info "=== Step 1: Installing OpenShift AI Operator ==="

oc apply -f "$SCRIPT_DIR/01-openshift-ai/namespace.yaml"

oc create namespace redhat-ods-operator --dry-run=client -o yaml | oc apply -f -
oc apply -f "$SCRIPT_DIR/01-openshift-ai/operator-group.yaml"
oc apply -f "$SCRIPT_DIR/01-openshift-ai/subscription.yaml"

info "Waiting for OpenShift AI operator to be ready ..."
for i in $(seq 1 60); do
    if oc get csv -n redhat-ods-operator 2>/dev/null | grep -q Succeeded; then
        info "OpenShift AI operator is ready"
        break
    fi
    [ "$i" -eq 60 ] && warn "Timed out waiting for operator - continuing anyway"
    sleep 10
done

info "Waiting for DataScienceCluster CRD to be registered ..."
for i in $(seq 1 60); do
    if oc get crd datascienceclusters.datasciencecluster.opendatahub.io &>/dev/null; then
        info "DataScienceCluster CRD is available"
        break
    fi
    [ "$i" -eq 60 ] && error "Timed out waiting for DataScienceCluster CRD"
    sleep 5
done

oc apply -f "$SCRIPT_DIR/01-openshift-ai/dsc.yaml"
info "DataScienceCluster created"

# ── Step 2: Deploy Model Server ────────────────────────────────────
info "=== Step 2: Deploying Model Server (vLLM + Granite) ==="

info "Waiting for KServe CRDs to be registered (from DataScienceCluster) ..."
for crd in servingruntimes.serving.kserve.io inferenceservices.serving.kserve.io; do
    for i in $(seq 1 90); do
        if oc get crd "$crd" &>/dev/null; then
            info "CRD $crd is available"
            break
        fi
        [ "$i" -eq 90 ] && error "Timed out waiting for CRD $crd"
        sleep 10
    done
done

oc apply -f "$SCRIPT_DIR/02-model-server/serving-runtime.yaml"
oc apply -f "$SCRIPT_DIR/02-model-server/inference-service.yaml"

info "Model server resources applied (readiness checked after Open WebUI starts)."

# ── Step 3: Set Up Sandbox Warm Pool ──────────────────────────────
info "=== Step 3: Setting Up Sandbox Warm Pool ==="
info "(Assumes agent-sandbox operator is already installed)"

oc apply -f "$SCRIPT_DIR/03-sandbox/sandbox-template.yaml"
oc apply -f "$SCRIPT_DIR/03-sandbox/warm-pool.yaml"

info "Sandbox warm pool resources applied (readiness checked after Open WebUI starts)."

# ── Step 4: Build & Deploy Agent Backend ──────────────────────────
info "=== Step 4: Deploying Agent Backend ==="

# Build the image using OpenShift BuildConfig if no pre-built image
if ! oc get is agent-backend -n "$NAMESPACE" &>/dev/null; then
    info "Creating build for agent-backend ..."
    oc new-build \
        --name=agent-backend \
        --binary \
        --strategy=docker \
        --to="agent-backend:latest" \
        -n "$NAMESPACE" \
        --dry-run -o yaml | oc apply -f -

    info "Waiting for BuildConfig to be available ..."
    for i in $(seq 1 30); do
        oc get bc agent-backend -n "$NAMESPACE" &>/dev/null && break
        [ "$i" -eq 30 ] && error "Timed out waiting for BuildConfig"
        sleep 2
    done

    oc start-build agent-backend \
        --from-dir="$SCRIPT_DIR/04-agent-backend" \
        -n "$NAMESPACE" \
        --follow

    # Patch deployment to use ImageStream
    AGENT_IMAGE="image-registry.openshift-image-registry.svc:5000/$NAMESPACE/agent-backend:latest"
fi

# Update image reference and apply
sed "s|image: quay.io/llm-sandbox-demo/agent-backend:latest|image: $AGENT_IMAGE|" \
    "$SCRIPT_DIR/04-agent-backend/deployment.yaml" | oc apply -f -

wait_for_resource deployment agent-backend "$NAMESPACE"

# ── Step 5: Deploy Open WebUI ─────────────────────────────────────
info "=== Step 5: Deploying Open WebUI ==="

oc apply -f "$SCRIPT_DIR/05-open-webui/deployment.yaml"
wait_for_resource deployment open-webui "$OPEN_WEBUI_NAMESPACE"

# ── Step 6: Wait for Model Server & Warm Pool ─────────────────────
info "=== Step 6: Waiting for Model Server and Warm Pool ==="

wait_for_inference_service code-llm "$NAMESPACE"
wait_for_warm_pool code-sandbox-pool "$NAMESPACE"

# ── Done ──────────────────────────────────────────────────────────
info "=== Deployment Complete ==="

ROUTE=$(oc get route open-webui -n "$OPEN_WEBUI_NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "pending")
echo ""
info "Open WebUI:     https://$ROUTE"
info "Agent Backend:  http://agent-backend.$NAMESPACE.svc:8000"
info "Model Server:   http://code-llm-predictor.$NAMESPACE.svc:8080"
echo ""
info "Next steps:"
info "  1. Open https://$ROUTE in your browser"
info "  2. Select the 'code-llm' model and start chatting"
info "  3. Ask the assistant to write and run code - it will execute in sandboxes!"
