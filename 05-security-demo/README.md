# Security Demo: Kata Containers vs Runc

This directory contains materials for demonstrating how Kata Containers protect against Kubernetes secret theft via AI-generated code.

## Overview

This demo shows:
- **With runc (vulnerable)**: AI-generated code can steal Kubernetes secrets from other pods
- **With Kata (protected)**: VM isolation blocks the same attack

## Quick Start

### 1. Deploy Victim Infrastructure

Create realistic secrets that can be stolen:

```bash
oc apply -f victim-infrastructure/secrets.yaml
```

This creates:
- `database-credentials` - DB passwords, Redis passwords, API keys
- `stripe-api-credentials` - Payment processing keys  
- `app-config` ConfigMap - Admin tokens and internal API keys

### 2. Deploy RBAC Configuration

Create service account with secret read permissions:

```bash
oc apply -f rbac/service-account.yaml
```

This creates:
- Service Account: `sandbox-demo-sa`
- Role: `secret-reader` (can read secrets, configmaps, pods)
- RoleBinding: Grants permissions to the service account

**Why**: Simulates a common configuration where apps need to read secrets.

### 3. Deploy Sandbox Templates

#### For Protected Demo (Kata):

```bash
oc apply -f sandbox-templates/kata-with-sa.yaml
oc apply -f sandbox-templates/kata-warmpool.yaml
```

#### For Vulnerable Demo (Runc):

```bash
oc apply -f sandbox-templates/runc-with-sa.yaml
oc apply -f sandbox-templates/runc-warmpool.yaml
```

### 4. Switch Default Warm Pool

#### To show VULNERABLE (runc):

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
