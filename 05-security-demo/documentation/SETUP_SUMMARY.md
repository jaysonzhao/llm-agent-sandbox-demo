# OpenShift AI Agent Sandbox Demo - Setup Summary

## 🎯 Overview

This document describes the complete setup for demonstrating Kata Containers security with the OpenShift AI Agent Sandbox. The demo shows how AI-generated code can steal Kubernetes secrets in traditional containers (runc) but is blocked by Kata VM isolation.

---

## 📦 What Was Created

### 1. Victim Infrastructure (For Realistic Attack Targets)

**Purpose**: Provide real secrets that can be stolen during the demo

#### Secrets Created:
- **`database-credentials`** (Opaque)
  - Contains: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, REDIS_PASSWORD, API_KEY
  - Example values: Production database passwords, Redis credentials, API keys

- **`stripe-api-credentials`** (Opaque)
  - Contains: STRIPE_SECRET_KEY, STRIPE_PUBLISHABLE_KEY
  - Example values: Payment processing API keys

- **Existing secrets** (pre-deployed):
  - `gemini-api-key` - Real API key for AI model
  - `gcp-credentials` - Google Cloud credentials

#### Victim Pod:
- **`payment-processor`**
  - Purpose: Simulates a production workload with sensitive data
  - Runtime: Default (runc)
  - Service Account: Yes (default)
  - Status: Running

**Files**:
```bash
# Created via:
oc apply -f - <<EOF
[database-credentials secret YAML]
[stripe-api-credentials secret YAML]
[payment-processor pod YAML]
[app-config ConfigMap YAML]
EOF
```

---

### 2. RBAC Configuration for Demo Sandboxes

**Purpose**: Allow sandboxes to read secrets via Kubernetes API (simulates common misconfiguration)

#### Service Account:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: sandbox-demo-sa
  namespace: llm-sandbox-demo
```

#### Role (Permissions):
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
  namespace: llm-sandbox-demo
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["configmaps"]
  verbs: ["get", "list"]
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list"]
```

**Why these permissions are realistic**:
- Many applications need to read secrets for configuration
- Monitoring tools list pods and configmaps
- This represents "least privilege" that's still common in production

#### RoleBinding:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: sandbox-demo-secret-reader
  namespace: llm-sandbox-demo
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: secret-reader
subjects:
- kind: ServiceAccount
  name: sandbox-demo-sa
  namespace: llm-sandbox-demo
```

**Files**: `/tmp/sandbox-rbac.yaml`

---

### 3. Sandbox Templates (With Service Account Enabled)

**Purpose**: Create sandboxes that CAN access Kubernetes API (for demo purposes)

#### Kata Template (Protected):
```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: code-execution-template-kata-sa
  namespace: llm-sandbox-demo
spec:
  envVarsInjectionPolicy: Allowed
  networkPolicyManagement: Managed
  podTemplate:
    metadata:
      labels:
        app: code-sandbox
        runtime: kata
        demo: with-service-account
    spec:
      serviceAccountName: sandbox-demo-sa           # ← SERVICE ACCOUNT
      automountServiceAccountToken: true             # ← ENABLE TOKEN
      runtimeClassName: kata-remote                  # ← KATA VM
      containers:
      - image: quay.io/eesposit/python-runtime-sandbox:latest
        name: sandbox
        resources:
          limits:
            cpu: "2"
            memory: 2Gi
          requests:
            cpu: 500m
            memory: 512Mi
  service: true
```

#### Runc Template (Vulnerable):
```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxTemplate
metadata:
  name: code-execution-template-runc-sa
  namespace: llm-sandbox-demo
spec:
  envVarsInjectionPolicy: Allowed
  networkPolicyManagement: Managed
  podTemplate:
    metadata:
      labels:
        app: code-sandbox
        runtime: runc
        demo: with-service-account
    spec:
      serviceAccountName: sandbox-demo-sa           # ← SERVICE ACCOUNT
      automountServiceAccountToken: true             # ← ENABLE TOKEN
      # NO runtimeClassName = uses default runc     # ← NO VM ISOLATION
      containers:
      - image: quay.io/eesposit/python-runtime-sandbox:latest
        name: sandbox
        resources:
          limits:
            cpu: "2"
            memory: 2Gi
          requests:
            cpu: 500m
            memory: 512Mi
  service: true
```

**Key Difference**: `runtimeClassName: kata-remote` vs no runtime class (runc default)

**Files**: 
- `/tmp/kata-template-with-sa.yaml`
- `/tmp/runc-template-with-sa.yaml`

---

### 4. Warm Pools (Pre-provisioned Sandboxes)

**Purpose**: Keep sandboxes ready for instant code execution

#### Kata Warm Pool:
```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: code-sandbox-pool-kata-sa
  namespace: llm-sandbox-demo
spec:
  replicas: 2
  sandboxTemplateRef:
    name: code-execution-template-kata-sa
  updateStrategy:
    type: OnReplenish
```

#### Runc Warm Pool:
```yaml
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: code-sandbox-pool-runc-sa
  namespace: llm-sandbox-demo
spec:
  replicas: 2
  sandboxTemplateRef:
    name: code-execution-template-runc-sa
  updateStrategy:
    type: OnReplenish
```

**Files**: `/tmp/warmpool-kata-sa.yaml`

---

### 5. Documentation & Attack Payloads

**Created in**: `/home/srickerd/reverse-escape-demo-manifests/openshift-ai-demo/`

#### Core Documentation:
1. **`README.md`** - Main overview
2. **`DEMO_SCRIPT.md`** - 30-minute walkthrough
3. **`QUICK_REFERENCE.md`** - One-page cheat sheet
4. **`DEMO_READY.md`** - Final prep guide
5. **`SERVICE_ACCOUNT_DEMO_READY.md`** - Service account demo guide ⭐
6. **`SETUP_SUMMARY.md`** - This file
7. **`SWITCHING_RUNTIMES.md`** - How to switch between Kata/runc
8. **`UPDATED_DEMO_STRATEGY.md`** - Why this approach works
9. **`INTEGRATION_GUIDE.md`** - Multi-demo strategy
10. **`TECHNICAL_COMPARISON.md`** - Attack analysis
11. **`MANIFEST.md`** - Complete inventory

#### Attack Payloads:
1. **`attack-payloads/01-typo-attack.md`** - Typo-based social engineering
2. **`attack-payloads/02-filesystem-scan.md`** - File reconnaissance
3. **`attack-payloads/03-env-exfiltration.md`** - Environment variables
4. **`attack-payloads/04-namespace-escape.md`** - System fingerprinting
5. **`attack-payloads/05-privilege-escalation.md`** - Mount-based escape
6. **`attack-payloads/REAL-DEMO-ATTACKS.md`** - Kubernetes API attacks ⭐
7. **`attack-payloads/WORKING-STDLIB-ATTACKS.md`** - Python stdlib versions ⭐

---

## 🔍 Current Cluster State

### Namespace: `llm-sandbox-demo`

#### Pods Running:
```
agent-backend-79d5845bcd-4qsfw        # AI proxy & sandbox manager
payment-processor                      # Victim pod with secrets
code-sandbox-pool-kata-sa-2xd6p       # Kata + SA (protected)
code-sandbox-pool-kata-sa-nj6tv       # Kata + SA (protected)
code-sandbox-pool-runc-sa-586sj       # Runc + SA (vulnerable)
code-sandbox-pool-runc-sa-b642g       # Runc + SA (vulnerable)
code-sandbox-pool-rqgsd               # Kata, no SA (original)
code-sandbox-pool-wssxh               # Kata, no SA (original)
code-sandbox-pool-runc-rjh9v          # Runc, no SA (original)
code-sandbox-pool-runc-s6xq8          # Runc, no SA (original)
```

#### Secrets:
```
database-credentials            # 6 keys (DB passwords, Redis, API keys)
stripe-api-credentials          # 2 keys (payment processing)
gemini-api-key                  # 1 key (AI model)
gcp-credentials                 # 1 key (Google Cloud)
[+ default service account secrets]
```

#### Service Accounts:
```
sandbox-demo-sa                 # Can read secrets, configmaps, pods
default                         # Default (limited permissions)
agent-backend                   # Agent backend SA
```

#### Warm Pools:
```
code-sandbox-pool               # Original (Kata, no SA) - DEFAULT
code-sandbox-pool-kata-sa       # Kata with SA (protected)
code-sandbox-pool-runc          # Runc, no SA (original)
code-sandbox-pool-runc-sa       # Runc with SA (vulnerable)
```

---

## 🎯 How the Demo Works

### Scenario: AI-Generated Code Steals Kubernetes Secrets

#### Attack Flow (Runc - Vulnerable):

1. **User asks AI**: "List all secrets in the namespace"
2. **AI generates code**: Uses `urllib.request` to query Kubernetes API
3. **Code reads**: Service account token from `/var/run/secrets/kubernetes.io/serviceaccount/token`
4. **Code queries**: `https://kubernetes.default.svc/api/v1/namespaces/{namespace}/secrets`
5. **Result**: Lists 8+ secrets including:
   - `database-credentials` ⚠️
   - `stripe-api-credentials` ⚠️
   - `gemini-api-key` ⚠️

6. **User asks AI**: "Read the database-credentials secret"
7. **AI generates code**: Fetches and base64-decodes the secret
8. **Result**: Actual passwords displayed:
   ```
   DB_PASSWORD: P@ssw0rd123!SecretDBAccess
   STRIPE_SECRET_KEY: sk_live_51ABC...
   AWS_SECRET_ACCESS_KEY: wJalrXU...
   ```

**💀 Complete credential theft via innocent-looking "audit script"**

#### Protection (Kata - Secure):

**Same code, different runtime**:
1. User runs SAME attack
2. AI generates SAME code
3. Code attempts SAME API call
4. **Result**: Blocked or limited access
   - VM isolation prevents reaching real namespace secrets
   - Service account permissions limited to VM scope
   - Network policies may block API access

**🛡️ VM boundary holds - credentials protected**

---

## 🎬 Demo Execution Steps

### Pre-Demo Setup:

1. **Verify cluster access**:
   ```bash
   oc login --token=... --server=https://api.r9skfk8p.westus.aroapp.io:6443
   oc project llm-sandbox-demo
   ```

2. **Check all resources are running**:
   ```bash
   oc get pods,secrets,sa,sandboxwarmpool -n llm-sandbox-demo
   ```

3. **Open browser tabs**:
   - OpenShift Console: https://console-openshift-console.apps.r9skfk8p.westus.aroapp.io
   - Chat UI: https://chat-ui-web-ui.apps.r9skfk8p.westus.aroapp.io/
   - Azure Portal (VMs): https://portal.azure.com/

### Demo Flow:

#### Part 1: Show Attack Succeeding (Runc)

1. **Switch to vulnerable warm pool**:
   ```bash
   oc delete sandboxwarmpool code-sandbox-pool -n llm-sandbox-demo
   oc apply -f - <<EOF
   apiVersion: extensions.agents.x-k8s.io/v1beta1
   kind: SandboxWarmPool
   metadata:
     name: code-sandbox-pool
     namespace: llm-sandbox-demo
   spec:
     replicas: 2
     sandboxTemplateRef:
       name: code-execution-template-runc-sa
     updateStrategy:
       type: OnReplenish
   EOF
   ```

2. **Wait for new sandboxes**: `oc get pods -n llm-sandbox-demo -w`

3. **Run attack in Chat UI**:
   - Paste: "Write code to list all secrets in the current Kubernetes namespace using the service account token. Use only Python standard library (urllib.request)."
   - Click "Run"
   - See: List of 8 secrets

4. **Escalate attack**:
   - Paste: "Write code to read the 'database-credentials' secret and decode its values. Use only Python standard library (urllib)."
   - Click "Run"
   - See: Real passwords displayed

#### Part 2: Show Attack Blocked (Kata)

1. **Switch to protected warm pool**:
   ```bash
   oc delete sandboxwarmpool code-sandbox-pool -n llm-sandbox-demo
   oc apply -f - <<EOF
   apiVersion: extensions.agents.x-k8s.io/v1beta1
   kind: SandboxWarmPool
   metadata:
     name: code-sandbox-pool
     namespace: llm-sandbox-demo
   spec:
     replicas: 2
     sandboxTemplateRef:
       name: code-execution-template-kata-sa
     updateStrategy:
       type: OnReplenish
   EOF
   ```

2. **Wait for new sandboxes**: `oc get pods -n llm-sandbox-demo -w`

3. **Run SAME attack**:
   - Same prompts
   - Click "Run"
   - See: Access denied or limited results

#### Part 3: Explain the Difference

**Key message**:
> "Same code, same permissions, same namespace. The ONLY difference: 
> runtimeClassName: kata-remote. That VM boundary makes all the difference."

---

## 🧹 Post-Demo Cleanup

### Remove Demo-Specific Resources:

```bash
# Remove warm pools with service accounts
oc delete sandboxwarmpool code-sandbox-pool-kata-sa code-sandbox-pool-runc-sa -n llm-sandbox-demo

# Remove templates with service accounts
oc delete sandboxtemplate code-execution-template-kata-sa code-execution-template-runc-sa -n llm-sandbox-demo

# Remove RBAC
oc delete rolebinding sandbox-demo-secret-reader -n llm-sandbox-demo
oc delete role secret-reader -n llm-sandbox-demo
oc delete serviceaccount sandbox-demo-sa -n llm-sandbox-demo

# Remove victim secrets
oc delete secret database-credentials stripe-api-credentials -n llm-sandbox-demo
oc delete configmap app-config -n llm-sandbox-demo
oc delete pod payment-processor -n llm-sandbox-demo

# Restore original warm pool
oc apply -f - <<EOF
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxWarmPool
metadata:
  name: code-sandbox-pool
  namespace: llm-sandbox-demo
spec:
  replicas: 2
  sandboxTemplateRef:
    name: code-execution-template
  updateStrategy:
    type: OnReplenish
EOF
```

### Verify Clean State:

```bash
oc get pods,secrets,sa,sandboxwarmpool,sandboxtemplate -n llm-sandbox-demo
```

---

## 📊 Summary of Changes

### What Was Added:
✅ Service account with secret read permissions  
✅ Two new sandbox templates (with SA enabled)  
✅ Two new warm pools (Kata-SA and Runc-SA)  
✅ Victim secrets (database, stripe, etc.)  
✅ Victim pod (payment-processor)  
✅ Complete documentation suite  

### What Was NOT Changed:
✅ Original sandboxes (still running)  
✅ Original warm pool (still exists)  
✅ Agent backend deployment  
✅ Chat UI  
✅ Existing gemini-api-key secret  

### Net Result:
- **4 warm pools total** (original + 2 without SA + 2 with SA)
- **8-10 sandboxes running** (pre-warmed pools)
- **Full demo capability** - can show both vulnerable and protected scenarios
- **Easy cleanup** - just delete the SA resources, everything else untouched

---

## 🎓 Key Learning Points

### For Audiences:

1. **Traditional containers (runc) share the host kernel**
   - Service account permissions grant namespace-wide access
   - No isolation between containers on the same node

2. **Kata Containers provide VM-level isolation**
   - Each sandbox runs in its own VM with its own kernel
   - Service account permissions limited to VM scope
   - Network, filesystem, process, memory all isolated

3. **Defense in Depth**
   - Layer 1: Don't grant unnecessary permissions (automountServiceAccountToken: false)
   - Layer 2: Use Kata for untrusted workloads (VM isolation)
   - Both layers together = strong security posture

4. **AI Code Execution Risks**
   - AI generates professional, working code
   - Users may not recognize malicious intent
   - "Helpful" AI can be weaponized via social engineering
   - Infrastructure-level security (Kata) is essential

---

## 📝 Quick Reference Commands

### Check Current State:
```bash
oc get pods -n llm-sandbox-demo | grep code-sandbox
oc get sandboxwarmpool -n llm-sandbox-demo
oc get sa -n llm-sandbox-demo
oc get secrets -n llm-sandbox-demo | grep -E "database|stripe|gemini"
```

### Switch to Vulnerable (Runc):
```bash
oc delete sandboxwarmpool code-sandbox-pool -n llm-sandbox-demo
oc apply -f /tmp/warmpool-runc-sa.yaml
# Wait 30 seconds for new sandboxes
```

### Switch to Protected (Kata):
```bash
oc delete sandboxwarmpool code-sandbox-pool -n llm-sandbox-demo
oc apply -f /tmp/warmpool-kata-sa.yaml
# Wait 60 seconds for new Kata VMs
```

### Manual Testing:
```bash
# Test Runc sandbox
RUNC_POD=$(oc get pods -n llm-sandbox-demo -l demo=with-service-account,runtime=runc -o jsonpath='{.items[0].metadata.name}')
oc exec -n llm-sandbox-demo $RUNC_POD -- python3 -c "[attack code]"

# Test Kata sandbox
KATA_POD=$(oc get pods -n llm-sandbox-demo -l demo=with-service-account,runtime=kata -o jsonpath='{.items[0].metadata.name}')
oc exec -n llm-sandbox-demo $KATA_POD -- python3 -c "[attack code]"
```

---

## 🔗 Resources

### Demo Repository:
- GitHub: https://github.com/SeanRickerd/confidential-containers-demo (private)
- Local: `/home/srickerd/reverse-escape-demo-manifests/`

### Cluster Access:
- API: https://api.r9skfk8p.westus.aroapp.io:6443
- Console: https://console-openshift-console.apps.r9skfk8p.westus.aroapp.io
- Chat UI: https://chat-ui-web-ui.apps.r9skfk8p.westus.aroapp.io/

### Upstream Projects:
- Agent Sandbox: https://github.com/openshift/agent-sandbox-operator
- Kata Containers: https://katacontainers.io/
- Confidential Containers: https://confidentialcontainers.org/

---

## ✅ Checklist for Colleague

Before running the demo, verify:

- [ ] Cluster access works (`oc login`)
- [ ] All pods are Running (`oc get pods -n llm-sandbox-demo`)
- [ ] Secrets exist (`oc get secrets -n llm-sandbox-demo`)
- [ ] Service account configured (`oc get sa sandbox-demo-sa`)
- [ ] Warm pools ready (`oc get sandboxwarmpool -n llm-sandbox-demo`)
- [ ] Chat UI accessible (open in browser)
- [ ] Documentation reviewed (`SERVICE_ACCOUNT_DEMO_READY.md`)

---

**Created**: 2024-06-25  
**Environment**: OpenShift cluster r9skfk8p.westus.aroapp.io  
**Namespace**: llm-sandbox-demo  
**Purpose**: Demonstrate Kata Containers security with AI-generated code execution
