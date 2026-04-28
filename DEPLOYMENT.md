# BankingBuddy — Azure Deployment Guide

End-to-end guide to deploy BankingBuddy to **Azure Container Apps** using Terraform
and the provided lifecycle scripts.

---

## Prerequisites

| Tool | Install |
|------|---------|
| Azure CLI ≥ 2.60 | https://learn.microsoft.com/cli/azure/install-azure-cli |
| Terraform ≥ 1.5 | https://developer.hashicorp.com/terraform/install |
| Docker | (optional — only needed for local builds; ACR has cloud build) |
| Bash | macOS/Linux/WSL |

You also need:

- **Azure subscription** with **Contributor** and **User Access Administrator**
  roles (required to create resources and assign managed-identity RBAC).
- **Azure OpenAI access** — the GPT-5.1 model must be available in your
  chosen region (`eastus` recommended).
- An **Entra ID account** signed into the Azure CLI (`az login`).

---

## Architecture

```
┌──────┐      ┌─────────────────┐      ┌──────────────────────────────┐      ┌──────────────────┐
│ User │─────▶│ Streamlit (ACA) │─────▶│ Agent Framework + PII Shield │─────▶│ Azure OpenAI     │
└──────┘      └─────────────────┘      └──────────────────────────────┘      │ (GPT-5.1)        │
                     │                                                        └──────────────────┘
                     ▼
              ┌──────────────┐
              │ App Insights │
              └──────────────┘
```

Terraform provisions: Resource Group, ACR, Container Apps Environment,
Log Analytics, Application Insights, and Azure OpenAI (GPT-5.1 deployment).

---

## 1. Bootstrap Terraform state storage (run once)

```bash
cd infra/scripts
./00-bootstrap-state.sh
```

Override the default region with `--location`:

```bash
./00-bootstrap-state.sh --location eastus
```

The script creates a dedicated resource group, storage account, and blob
container for state files. It also registers all required Azure resource
providers. **Save the `terraform init` command it prints at the end.**

---

## 2. Configure Terraform variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
```

Open `terraform.tfvars` and set your subscription ID:

```hcl
subscription_id = "<your-subscription-id>"

# Prefix for all resources (3-16 lowercase alphanumeric chars).
# A random 5-char suffix is auto-appended to globally-unique resources.
project_name = "bankingbuddy"

# Azure region (eastus recommended for Azure OpenAI model availability)
location = "eastus"
```

All resource names are derived from `project_name`:

| Resource | Name pattern |
|----------|--------------|
| Resource group | `<project_name>-rg` |
| Container Apps env | `<project_name>-env` |
| Log Analytics | `<project_name>-logs` |
| Application Insights | `<project_name>-insights` |
| ACR | `<project_name>acr<suffix>` |
| Azure OpenAI | `<project_name>-openai-<suffix>` |

> **Tip:** Set `name_suffix = "prod01"` in tfvars for reproducible,
> deterministic resource names across re-deploys.

---

## 3. Initialize Terraform

Use the `-backend-config` flags printed by `00-bootstrap-state.sh`:

```bash
terraform init \
  -backend-config="resource_group_name=bankingbuddy-tfstate-rg" \
  -backend-config="storage_account_name=bankingbuddytfabcde" \
  -backend-config="container_name=tfstate" \
  -backend-config="key=bankingbuddy.terraform.tfstate" \
  -backend-config="use_azuread_auth=true"
```

---

## 4. Apply Terraform

```bash
terraform plan
terraform apply
```

This provisions:

- Resource Group
- Azure Container Registry (Basic SKU)
- Container Apps Environment + Log Analytics workspace
- Azure OpenAI account + GPT-5.1 deployment (10K TPM)
- Application Insights (workspace-based)

> Provisioning typically completes in 3-5 minutes.

---

## 5. Build and push the Docker image

```bash
cd ../scripts
./01-build-push.sh
```

Uses ACR cloud build — no local Docker required. Override the image tag:

```bash
./01-build-push.sh --tag v1.0.0
```

Build takes ~5-7 minutes the first time (downloads ONNX model).

---

## 6. Deploy the container app

```bash
./02-deploy-apps.sh
```

The script reads Terraform outputs and:

1. Creates a container app (`bankingbuddy`) running Streamlit on port 8501
2. Enables system-assigned managed identity
3. Assigns the **Cognitive Services OpenAI User** role to the managed identity

Override defaults via env vars:

```bash
APP_NAME=my-app IMAGE_TAG=v1.0.0 NLP_ENGINE=onnx ./02-deploy-apps.sh
```

| Setting | Default | Description |
|---------|---------|-------------|
| `APP_NAME` | `bankingbuddy` | Container app name |
| `IMAGE_TAG` | `latest` | Docker image tag |
| `NLP_ENGINE` | `onnx` | PII Shield NLP engine |

---

## 7. Verify the deployment

```bash
./03-verify.sh
```

Expected output:

```
[PASS] BankingBuddy root (HTTP 200)
[PASS] BankingBuddy /healthz (HTTP 200)
```

---

## Tear down

Container apps are created out-of-band (not tracked in Terraform state),
so they must be deleted **before** running `terraform destroy`.

```bash
# 1. Delete container apps
cd infra/scripts
./05-teardown-apps.sh

# 2. Destroy Terraform-managed infrastructure
cd ../terraform
terraform destroy -auto-approve

# 3. (Optional) Remove the state backend
cd ../scripts
./00-teardown-state.sh
```

> ⚠️ `00-teardown-state.sh` permanently deletes Terraform state files.
> Only run this after confirming all infrastructure is destroyed.

---

## Configuration reference

### Environment variables

Set via `.env` for local development or injected by `02-deploy-apps.sh` for Azure.

| Variable | Default | Purpose |
|----------|---------|---------|
| `FOUNDRY_PROJECT_ENDPOINT` | — | Azure OpenAI endpoint URL |
| `FOUNDRY_MODEL` | `gpt-5.1` | OpenAI model deployment name |
| `NLP_ENGINE` | `onnx` | PII NER backend: `onnx`, `spacy`, `transformers`, `stanza` |
| `TRANSFORMERS_MODEL` | `protectai/bert-base-NER-onnx` | HuggingFace model for transformers/onnx |
| `TRANSFORMERS_SPACY_MODEL` | `en_core_web_sm` | spaCy tokenizer model |
| `QUANTIZED_MODEL_DIR` | `models/onnx-int8` | Local path to quantized ONNX model |
| `ENCRYPTION_BACKEND` | `pqc` | `pqc` (ML-KEM-768) or `fernet` |
| `STREAMLIT_PORT` | `8501` | Streamlit server port |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | — | App Insights connection string (set by deploy script) |

### Terraform variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `subscription_id` | `string` | — | Azure subscription ID (**required**) |
| `project_name` | `string` | `bankingbuddy` | Prefix for all resource names (3-16 lowercase alphanum) |
| `name_suffix` | `string` | `""` (auto) | Explicit suffix for globally-unique names |
| `location` | `string` | `eastus` | Azure region |
| `tags` | `map(string)` | `{project="bankingbuddy", managed_by="terraform"}` | Tags applied to all resources |
| `acr_sku` | `string` | `Basic` | ACR SKU tier |
| `openai_sku` | `string` | `S0` | Azure Cognitive Services SKU |
| `openai_model_name` | `string` | `gpt-5.1` | OpenAI model to deploy |
| `openai_model_version` | `string` | `2025-11-13` | Model version string |
| `openai_deployment_capacity` | `number` | `10` | TPM in thousands |

### Terraform outputs

| Output | Description |
|--------|-------------|
| `resource_group_name` | Resource group name |
| `acr_login_server` | ACR login server URL |
| `acr_name` | ACR resource name |
| `aca_env_name` | Container Apps Environment name |
| `aca_env_id` | Container Apps Environment resource ID |
| `openai_endpoint` | Azure OpenAI endpoint URL |
| `openai_deployment_name` | Deployed model name |
| `app_insights_connection_string` | App Insights connection string (sensitive) |
| `app_insights_name` | App Insights resource name |

---

## Troubleshooting

### Azure OpenAI quota exceeded

GPT-5.1 has per-region TPM quotas. If `terraform apply` fails with a quota
error, either request a quota increase in the Azure portal or reduce
`openai_deployment_capacity` in `terraform.tfvars`.

### Model not available in region

GPT-5.1 is not available in all Azure regions. Use `eastus` (recommended) or
check [Azure OpenAI model availability](https://learn.microsoft.com/azure/ai-services/openai/concepts/models)
for current region support.

### Managed identity RBAC propagation delay

After `02-deploy-apps.sh` assigns the **Cognitive Services OpenAI User** role,
it can take 1-5 minutes for the role to propagate. If the app returns
`401 Unauthorized` errors immediately after deploy, wait a few minutes and retry.

### `terraform init` fails with backend authentication error

Ensure you are signed in (`az login`) as a user with **Storage Blob Data
Contributor** on the state storage account. The bootstrap script grants
this automatically; if you ran it as a different user, assign manually:

```bash
az role assignment create \
  --role "Storage Blob Data Contributor" \
  --assignee <your-object-id> \
  --scope <storage-account-resource-id>
```

### `terraform destroy` fails with `ManagedEnvironmentHasContainerApps`

Container apps are created outside of Terraform. Run
`./05-teardown-apps.sh` **before** `terraform destroy` to delete them first.

### Cold-start latency on first request

The ONNX engine loads its model on first request. Set `--min-replicas 1`
(instead of 0) in `02-deploy-apps.sh` to keep one replica warm.
