#! /bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

function wait_for_deployment() {
    local deployment=$1
    local namespace=$2
    local timeout=600
    local interval=25
    local elapsed=0
    local ready=0

    while [ $elapsed -lt $timeout ]; do
        ready=$(oc get deployment -n "$namespace" "$deployment" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
        if [ "${ready:-0}" -ge 1 ]; then
            echo "Operator $deployment is ready"
            return 0
        fi
        echo "Operator $deployment is not yet ready, waiting another $interval seconds"
        sleep $interval
        elapsed=$((elapsed + interval))
    done
    echo "Operator $deployment is not ready after $timeout seconds"
    return 1
}

function wait_for_catalogsource() {
    local name=$1
    local namespace=$2
    local timeout=300
    local interval=10
    local elapsed=0
    local state=""

    while [ $elapsed -lt $timeout ]; do
        state=$(oc get catalogsource -n "$namespace" "$name" -o jsonpath='{.status.connectionState.lastObservedState}' 2>/dev/null || echo "")
        if [ "$state" == "READY" ]; then
            echo "CatalogSource $name is ready"
            return 0
        fi
        echo "CatalogSource $name is not yet ready (state: ${state:-unknown}), waiting another $interval seconds"
        sleep $interval
        elapsed=$((elapsed + interval))
    done
    echo "CatalogSource $name is not ready after $timeout seconds"
    return 1
}

echo "################################################"
echo "Starting the script. Many of the following commands"
echo "will periodically check on OCP for operations to"
echo "complete, so it's normal to see errors."
echo "If this scripts completes successfully, you will"
echo "see a final message confirming installation went"
echo "well."
echo "################################################"

echo ""
echo "############################ Configure image mirrors ########################"
oc apply -f "$SCRIPT_DIR/image-mirror-set.yaml"

echo "############################ Install catalog ########################"
oc apply -f "$SCRIPT_DIR/catalogsource.yaml"

echo "############################ Wait for catalog ########################"
wait_for_catalogsource agent-sandbox-operator-catalog openshift-marketplace || exit 1

echo "############################ Install Agent Sandbox Operator ########################"
oc apply -f-<<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: agent-sandbox-system
---
apiVersion: operators.coreos.com/v1
kind: OperatorGroup
metadata:
  name: agent-sandbox-operator
  namespace: agent-sandbox-system
spec: {}
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: agent-sandbox-operator
  namespace: agent-sandbox-system
spec:
  channel: preview-0.9
  installPlanApproval: Automatic
  name: agent-sandbox-operator
  source: agent-sandbox-operator-catalog
  sourceNamespace: openshift-marketplace
EOF

echo "############################ Wait for Agent Sandbox Operator ########################"
wait_for_deployment agent-sandbox-controller agent-sandbox-system || exit 1

echo "############################ Create sandbox router route ########################"
echo "Creating edge route agent-sandbox-router for sandbox-router-svc:8080 in agent-sandbox-system"
oc create route edge agent-sandbox-router \
  --service=sandbox-router-svc \
  --port=8080 \
  -n agent-sandbox-system
echo "Route agent-sandbox-router created successfully"

echo ""
echo "################################################"
echo "Agent Sandbox Operator installed successfully!"
echo "################################################"
