# LLM Agent Sandbox Demo

An end-to-end demo on OpenShift that lets you chat with an LLM through Open WebUI. When you ask it to write code, it automatically executes that code in isolated sandbox pods running on the `kata-remote` runtime via the [Agent Sandbox Operator](https://github.com/openshift/kubernetes-sigs-agent-sandbox).

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  Open WebUI │────▶│  Agent Backend   │────▶│  vLLM (Granite)  │
│  (Browser)  │◀────│  (FastAPI proxy) │◀────│  OpenShift AI    │
└─────────────┘     └───────┬──────────┘     └──────────────────┘
                            │
                   execute_code tool call
                            │
                    ┌───────▼──────────┐
                    │  Sandbox Claim   │
                    │  (kata-remote)   │
                    │                  │
                    │  ┌────────────┐  │
                    │  │ Python pod │  │  ◀── from Warm Pool (2 ready)
                    │  └────────────┘  │
                    └──────────────────┘
```

**Flow:**
1. User chats in Open WebUI
2. Messages go to the Agent Backend (OpenAI-compatible API proxy)
3. Agent Backend forwards to vLLM with an `execute_code` tool definition
4. When the LLM generates code and calls the tool, the Agent Backend:
   - Claims a pre-warmed sandbox pod from the warm pool
   - Writes and runs the code inside the sandbox
   - Returns stdout/stderr back to the LLM
5. The LLM incorporates the execution results and responds to the user

## Components

| Component | Description |
|-----------|-------------|
| **OpenShift AI** | Operator that provides model serving via KServe + vLLM |
| **vLLM + Granite 3.1 2B** | Code-capable LLM with tool-calling support, CPU-only, pulled from HuggingFace |
| **Agent Backend** | Python FastAPI service that proxies chat requests and handles sandbox code execution |
| **Agent Sandbox Operator** | Creates and manages isolated sandbox pods (pre-installed) |
| **Warm Pool** | 2 pre-warmed `kata-remote` pods ready for instant code execution |
| **Open WebUI** | ChatGPT-like web interface exposed via OpenShift Route |

## Prerequisites

- OpenShift 4.14+ cluster (no GPU required — runs on CPU)
- `oc` CLI logged into the cluster as cluster-admin
- Red Hat Build of Agent Sandbox Operator already installed
- `kata-remote` RuntimeClass available (via OpenShift Sandboxed Containers operator with peer pods)
- HuggingFace model access (Granite 3.1 2B Instruct is open-weight)

## Deploy

```bash
./deploy.sh
```

The script will:
1. Install the OpenShift AI operator and create a DataScienceCluster
2. Deploy a vLLM serving runtime with Granite 3.1 2B Instruct (CPU-only)
3. Create a SandboxTemplate (kata-remote) and WarmPool (2 replicas)
4. Build and deploy the Agent Backend
5. Deploy Open WebUI with an OpenShift Route

## Manual Deployment

If you prefer to deploy step-by-step:

```bash
# 1. OpenShift AI
oc apply -f 01-openshift-ai/namespace.yaml
oc create namespace redhat-ods-operator --dry-run=client -o yaml | oc apply -f -
oc apply -f 01-openshift-ai/operator-group.yaml
oc apply -f 01-openshift-ai/subscription.yaml
# Wait for operator CSV to succeed, then:
oc apply -f 01-openshift-ai/dsc.yaml

# 2. Model Server
oc apply -f 02-model-server/serving-runtime.yaml
oc apply -f 02-model-server/inference-service.yaml

# 3. Sandbox Warm Pool
oc apply -f 03-sandbox/sandbox-template.yaml
oc apply -f 03-sandbox/warm-pool.yaml

# 4. Agent Backend (build image first)
oc new-build --name=agent-backend --binary --strategy=docker \
  --to=agent-backend:latest -n llm-sandbox-demo
oc start-build agent-backend --from-dir=04-agent-backend -n llm-sandbox-demo --follow
# Update image ref in deployment.yaml, then:
oc apply -f 04-agent-backend/deployment.yaml

# 5. Open WebUI
oc apply -f 05-open-webui/deployment.yaml
```

## Configuration

### Changing the Model

Edit `02-model-server/inference-service.yaml` and update `storageUri`:

```yaml
storageUri: hf://mistralai/Mistral-7B-Instruct-v0.3
```

Then update `VLLM_BASE_URL` and `MODEL_NAME` in `04-agent-backend/deployment.yaml`.

### Warm Pool Size

Edit `03-sandbox/warm-pool.yaml`:

```yaml
spec:
  replicas: 5  # increase for higher concurrency
```

### Sandbox Resources

Edit `03-sandbox/sandbox-template.yaml` to adjust CPU, memory, installed packages, or the container image.

## Usage

1. Open the URL printed at the end of `deploy.sh` (or run `oc get route open-webui -n llm-sandbox-demo`)
2. Select the **code-llm** model
3. Try prompts like:
   - "Write a Python script that calculates the first 20 Fibonacci numbers"
   - "Create a bash script that shows system information"
   - "Write a Python program that generates a random maze and solves it"
   - "Run this code: `print(sum(range(1, 101)))`"

The assistant will generate the code, execute it in a sandbox, and show you the results.

## Troubleshooting

```bash
# Check all pods
oc get pods -n llm-sandbox-demo

# Check model server logs
oc logs -n llm-sandbox-demo -l serving.kserve.io/inferenceservice=code-llm

# Check agent backend logs
oc logs -n llm-sandbox-demo -l app=agent-backend

# Check warm pool status
oc get sandboxwarmpools -n llm-sandbox-demo
oc get sandboxes -n llm-sandbox-demo

# Check Open WebUI logs
oc logs -n llm-sandbox-demo -l app=open-webui
```
