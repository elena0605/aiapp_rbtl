# Azure Production Deployment Plan

This guide outlines the recommended Azure components and deployment steps for RBTL GraphRAG production deployment using **Docker containers**.

## Overview

The application is deployed as **two Docker containers** on Azure Container Apps:
- **Backend**: FastAPI application (from `backend/Dockerfile`)
- **Frontend**: Next.js application (from `frontend/Dockerfile`)

Both containers are built locally or via CI/CD, pushed to Azure Container Registry (ACR), and deployed to Azure Container Apps for auto-scaling and high availability.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Azure Cloud                              │
│                                                                   │
│  ┌──────────────────┐         ┌──────────────────┐            │
│  │  Frontend        │         │  Backend API      │            │
│  │  (Next.js)       │◄───────►│  (FastAPI)       │            │
│  │                  │  HTTPS  │                   │            │
│  │  Azure Static    │  REST   │  Azure Container │            │
│  │  Web Apps        │  +      │  Apps             │            │
│  │  (CDN)           │  WS/SSE │  (Auto-scaling)   │            │
│  └──────────────────┘         └─────────┬─────────┘            │
│                                          │                       │
│                                          ▼                       │
│  ┌──────────────────────────────────────────────────┐           │
│  │         Azure Services                           │           │
│  │  • Azure OpenAI (or OpenAI API)                │           │
│  │  • Neo4j Aura (managed)                         │           │
│  │  • Azure Cosmos DB (MongoDB API)                │           │
│  │  • Azure Key Vault (secrets)                    │           │
│  │  • Azure Application Insights (monitoring)       │           │
│  │  • Azure Container Registry (ACR)               │           │
│  └──────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

## Recommended Azure Components

| Component | Service | Purpose |
|-----------|---------|---------|
| **Frontend Hosting** | Azure Container Apps | Run Next.js frontend Docker container with auto-scaling |
| **Backend Hosting** | Azure Container Apps | Run FastAPI backend Docker container with auto-scaling |
| **Container Registry** | Azure Container Registry (ACR) | Store and version Docker images |
| **Secrets Management** | Azure Key Vault | Secure storage for API keys and credentials |
| **Database** | Azure Cosmos DB (MongoDB API) | Knowledge base storage |
| **Monitoring** | Azure Application Insights | Application performance and error tracking |
| **CI/CD** | GitHub Actions | Automated Docker build and deployment pipeline |

### External Services

- **Neo4j Aura** (managed Neo4j)
- **OpenAI API** (or Azure OpenAI)
- **Langfuse** (cloud or self-hosted)

## Prerequisites

- Azure Subscription
- Azure CLI installed (`az login`)
- Docker installed locally
- GitHub repository access

## Deployment Phases

### Phase 1: Infrastructure Setup

#### 1.1 Create Resource Group

```bash
az group create \
  --name rg-rbtl-graphrag-prod \
  --location westeurope
```

#### 1.2 Create Azure Container Registry (ACR)

```bash
az acr create \
  --resource-group rg-rbtl-graphrag-prod \
  --name acrrbtlgraphrag \
  --sku Basic \
  --admin-enabled true
```

#### 1.3 Create Azure Key Vault

```bash
az keyvault create \
  --name kv-rbtl-graphrag-prod \
  --resource-group rg-rbtl-graphrag-prod \
  --location westeurope \
  --sku standard
```

#### 1.4 Create Azure Container Apps Environment

```bash
az containerapp env create \
  --name env-rbtl-graphrag-prod \
  --resource-group rg-rbtl-graphrag-prod \
  --location westeurope
```

#### 1.5 Frontend Container App

The frontend will be deployed as a Container App using the dockerized Next.js image. Both frontend and backend use the same Container Apps platform for consistency.

#### 1.6 Create Azure Cosmos DB (MongoDB API)

```bash
az cosmosdb create \
  --name cosmos-rbtl-graphrag-prod \
  --resource-group rg-rbtl-graphrag-prod \
  --kind MongoDB \
  --locations regionName=westeurope failoverPriority=0
```

### Phase 2: Secrets Configuration

#### 2.1 Store Secrets in Key Vault

```bash
# Neo4j credentials
az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "NEO4J-URI" \
  --value "neo4j+s://your-db-id.databases.neo4j.io"

az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "NEO4J-USER" \
  --value "neo4j"

az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "NEO4J-PASSWORD" \
  --value "your-secure-password"

# OpenAI
az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "OPENAI-API-KEY" \
  --value "sk-proj-..."

# Langfuse
az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "LANGFUSE-HOST" \
  --value "https://cloud.langfuse.com"

az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "LANGFUSE-PUBLIC-KEY" \
  --value "pk-lf-..."

az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "LANGFUSE-SECRET-KEY" \
  --value "sk-lf-..."

# MongoDB (Cosmos DB)
az keyvault secret set \
  --vault-name kv-rbtl-graphrag-prod \
  --name "MONGODB-URI" \
  --value "$(az cosmosdb keys list \
    --name cosmos-rbtl-graphrag-prod \
    --resource-group rg-rbtl-graphrag-prod \
    --type connection-strings \
    --query 'connectionStrings[0].connectionString' -o tsv)"
```

#### 2.2 Grant Container Apps Access to Key Vault

```bash
# Get managed identity (will be created with container app)
# Then grant access:
az keyvault set-policy \
  --name kv-rbtl-graphrag-prod \
  --object-id <container-app-identity-id> \
  --secret-permissions get list
```

### Phase 3: Backend Docker Container Deployment

#### 3.1 Build and Push Docker Image

The backend uses the `backend/Dockerfile` to create a production-ready container:

```bash
# Login to ACR
az acr login --name acrrbtlgraphrag

# Build backend Docker image from backend/Dockerfile
docker build -f backend/Dockerfile -t acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:latest .

# Tag with commit SHA for versioning
docker tag acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:latest \
  acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:$(git rev-parse --short HEAD)

# Push both tags to ACR
docker push acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:latest
docker push acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:$(git rev-parse --short HEAD)
```

**What the Dockerfile does:**
- Uses Python 3.13-slim base image
- Installs all dependencies from `backend/requirements.txt`
- Copies application code (backend, ai, utils directories)
- Exposes port 8000
- Runs FastAPI with uvicorn

#### 3.2 Create Container App for Backend

```bash
az containerapp create \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --environment env-rbtl-graphrag-prod \
  --image acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:latest \
  --target-port 8000 \
  --ingress external \
  --registry-server acrrbtlgraphrag.azurecr.io \
  --registry-username $(az acr credential show --name acrrbtlgraphrag --query username -o tsv) \
  --registry-password $(az acr credential show --name acrrbtlgraphrag --query passwords[0].value -o tsv) \
  --min-replicas 1 \
  --max-replicas 5 \
  --cpu 1.0 \
  --memory 2.0Gi \
  --env-vars \
    NEO4J_URI="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/NEO4J-URI/)" \
    NEO4J_USER="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/NEO4J-USER/)" \
    NEO4J_PASSWORD="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/NEO4J-PASSWORD/)" \
    OPENAI_API_KEY="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/OPENAI-API-KEY/)" \
    LANGFUSE_HOST="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/LANGFUSE-HOST/)" \
    LANGFUSE_PUBLIC_KEY="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/LANGFUSE-PUBLIC-KEY/)" \
    LANGFUSE_SECRET_KEY="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/LANGFUSE-SECRET-KEY/)" \
    MONGODB_URI="@Microsoft.KeyVault(SecretUri=https://kv-rbtl-graphrag-prod.vault.azure.net/secrets/MONGODB-URI/)" \
    MONGODB_DATABASE=graphrag \
    OPENAI_MODEL=gpt-4o \
    PROMPT_LABEL=production \
    ENABLE_ANALYTICS_AGENT=false
```

#### 3.3 Get Backend URL

```bash
BACKEND_URL=$(az containerapp show \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Backend URL: https://$BACKEND_URL"
```

### Phase 4: Frontend Docker Container Deployment

#### 4.1 Build and Push Frontend Docker Image

The frontend uses the `frontend/Dockerfile` to create a production-ready Next.js container:

```bash
# Get backend URL first (from Phase 3.3)
BACKEND_URL=$(az containerapp show \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --query properties.configuration.ingress.fqdn -o tsv)

# Build frontend Docker image from frontend/Dockerfile
# Pass backend URL as build argument for NEXT_PUBLIC_API_URL
docker build -f frontend/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://$BACKEND_URL \
  -t acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:latest .

# Tag with commit SHA for versioning
docker tag acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:latest \
  acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:$(git rev-parse --short HEAD)

# Push both tags to ACR
docker push acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:latest
docker push acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:$(git rev-parse --short HEAD)
```

**What the Dockerfile does:**
- Uses Node.js 18-alpine base image
- Multi-stage build (deps → builder → runner)
- Builds Next.js with standalone output mode
- Creates optimized production image
- Exposes port 3000

#### 4.2 Create Container App for Frontend

```bash
az containerapp create \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod \
  --environment env-rbtl-graphrag-prod \
  --image acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:latest \
  --target-port 3000 \
  --ingress external \
  --registry-server acrrbtlgraphrag.azurecr.io \
  --registry-username $(az acr credential show --name acrrbtlgraphrag --query username -o tsv) \
  --registry-password $(az acr credential show --name acrrbtlgraphrag --query passwords[0].value -o tsv) \
  --min-replicas 1 \
  --max-replicas 3 \
  --cpu 0.5 \
  --memory 1.0Gi \
  --env-vars \
    NEXT_PUBLIC_API_URL=https://$BACKEND_URL
```

#### 4.3 Get Frontend URL

```bash
FRONTEND_URL=$(az containerapp show \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Frontend URL: https://$FRONTEND_URL"
```

### Phase 5: CI/CD Pipeline Setup

The GitHub Actions workflow (`.github/workflows/azure-deploy.yml`) fully automates the Docker build and deployment process:

**Automated Steps:**
1. **Backend**: 
   - Builds Docker image from `backend/Dockerfile`
   - Pushes to Azure Container Registry (ACR)
   - Updates Container App with new image
   
2. **Frontend**:
   - Gets backend URL from deployed backend
   - Builds Docker image from `frontend/Dockerfile` with backend URL
   - Pushes to ACR
   - Updates Container App with new image

**Workflow triggers on:**
- Pushes to `main` branch (changes to backend, frontend, ai, utils, or Dockerfiles)
- Manual trigger via GitHub Actions UI

#### 5.1 Configure GitHub Secrets

Add these secrets in GitHub repository settings:

- `AZURE_CREDENTIALS`: Service principal credentials (create with `az ad sp create-for-rbac`)
- `NEXT_PUBLIC_API_URL`: Your backend Container App URL (e.g., `https://ca-rbtl-graphrag-backend.xxx.azurecontainerapps.io`)

### Phase 6: Monitoring & Observability

#### 6.1 Enable Application Insights

```bash
az monitor app-insights component create \
  --app ai-rbtl-graphrag-prod \
  --location westeurope \
  --resource-group rg-rbtl-graphrag-prod \
  --application-type web
```

#### 6.2 Configure Logging

Add to Container App environment variables:

```bash
APPLICATIONINSIGHTS_CONNECTION_STRING="<from-app-insights>"
```

#### 6.3 Set Up Alerts

```bash
az monitor metrics alert create \
  --name alert-backend-errors \
  --resource-group rg-rbtl-graphrag-prod \
  --scopes /subscriptions/<sub-id>/resourceGroups/rg-rbtl-graphrag-prod/providers/Microsoft.App/containerApps/ca-rbtl-graphrag-backend \
  --condition "count ExceptionRate > 5" \
  --window-size 5m \
  --evaluation-frequency 1m
```

### Phase 7: Post-Deployment Verification

#### 7.1 Health Check

```bash
BACKEND_URL=$(az containerapp show \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --query properties.configuration.ingress.fqdn -o tsv)

curl https://$BACKEND_URL/api/health
```

#### 7.2 Test Endpoints

```bash
# Test chat endpoint
curl -X POST https://$BACKEND_URL/api/chat \
  -H "Content-Type: application/json" \
  -d '{"question": "Return 5 Person nodes"}'

# Test graph info
curl https://$BACKEND_URL/api/graph-info
```

#### 7.3 Verify Frontend

```bash
FRONTEND_URL=$(az containerapp show \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod \
  --query properties.configuration.ingress.fqdn -o tsv)

echo "Frontend URL: https://$FRONTEND_URL"
```

1. Visit the frontend Container App URL
2. Test chat interface
3. Verify API connectivity
4. Check browser console for errors

## Rollback Procedures

### Backend Rollback

```bash
# List revisions
az containerapp revision list \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod

# Activate previous revision
az containerapp revision activate \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --revision <previous-revision-name>
```

### Frontend Rollback

```bash
# List revisions
az containerapp revision list \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod

# Activate previous revision
az containerapp revision activate \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod \
  --revision <previous-revision-name>
```

## Security Checklist

- [ ] All secrets stored in Azure Key Vault
- [ ] HTTPS enforced on all endpoints
- [ ] CORS configured correctly
- [ ] Container images scanned for vulnerabilities
- [ ] Managed identity used for Key Vault access
- [ ] Network security groups configured (if using VNet)
- [ ] Application Insights logging enabled
- [ ] Regular security updates scheduled

## Maintenance

### Regular Tasks

1. **Weekly**: Review Application Insights for errors and performance
2. **Monthly**: Update dependencies and container images
3. **As needed**: Rotate API keys and secrets

### Updates

```bash
# Update backend
az containerapp update \
  --name ca-rbtl-graphrag-backend \
  --resource-group rg-rbtl-graphrag-prod \
  --image acrrbtlgraphrag.azurecr.io/rbtl-graphrag-backend:latest

# Update frontend
az containerapp update \
  --name ca-rbtl-graphrag-frontend \
  --resource-group rg-rbtl-graphrag-prod \
  --image acrrbtlgraphrag.azurecr.io/rbtl-graphrag-frontend:latest

# Or rebuild and push new images, then update (handled automatically by GitHub Actions)
```

## Troubleshooting

### Backend Not Starting

1. Check Container App logs: Azure Portal → Container App → Log stream
2. Verify Key Vault secrets are accessible
3. Check environment variables are correctly set
4. Review Application Insights for errors

### Frontend Can't Connect to Backend

1. Verify `NEXT_PUBLIC_API_URL` is set correctly
2. Check CORS settings in backend
3. Verify backend Container App is running
4. Check network connectivity

## Next Steps

After successful deployment:

1. Set up **staging environment** for testing before production
2. Configure **backup strategies** for Cosmos DB
3. Implement **disaster recovery** plan
4. Set up **performance testing** in CI/CD
5. Document **runbooks** for common issues

