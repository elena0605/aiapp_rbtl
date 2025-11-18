# Frontend Architecture - Chat with Data UI

## Recommended Architecture for Azure Deployment

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Azure Cloud                              │
│                                                                   │
│  ┌──────────────────┐         ┌──────────────────┐            │
│  │  Frontend         │         │  Backend API      │            │
│  │  (React/Next.js)  │◄───────►│  (FastAPI)       │            │
│  │                   │  REST   │                   │            │
│  │  Azure Static     │  +      │  Azure Container  │            │
│  │  Web Apps         │  WS/SSE │  Apps              │            │
│  └──────────────────┘         └─────────┬─────────┘            │
│                                          │                       │
│                                          ▼                       │
│  ┌──────────────────────────────────────────────────┐           │
│  │         Azure Services                           │           │
│  │  • Azure OpenAI (or OpenAI API)                 │           │
│  │  • Neo4j Aura (or self-hosted)                  │           │
│  │  • Langfuse (self-hosted or cloud)              │           │
│  │  • Azure Key Vault (secrets)                     │           │
│  │  • Azure Application Insights (monitoring)     │           │
│  └──────────────────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────────────┘
```

## Technology Stack

### Frontend
- **Framework**: Next.js 14+ (React) with App Router
- **UI Library**: shadcn/ui + Tailwind CSS (modern, customizable)
- **State Management**: React Context + Zustand (for chat state)
- **Real-time**: WebSockets or Server-Sent Events (SSE) for streaming
- **HTTP Client**: Axios or Fetch API
- **Deployment**: Azure Static Web Apps or Azure App Service

### Backend API
- **Framework**: FastAPI (Python, async support)
- **WebSockets**: FastAPI WebSocket support for streaming
- **Authentication**: Azure AD B2C or API keys
- **Deployment**: Azure Container Apps or Azure App Service
- **Container**: Docker with Python 3.13

### Azure Services
- **Frontend Hosting**: Azure Static Web Apps (recommended) or Azure App Service
- **Backend Hosting**: Azure Container Apps (recommended) or Azure App Service
- **Secrets Management**: Azure Key Vault
- **Monitoring**: Azure Application Insights
- **CDN**: Azure Front Door (optional, for global distribution)
- **Database**: Neo4j Aura (cloud) or self-hosted on Azure VM

## Architecture Components

### 1. Frontend Application (Next.js)

**Structure:**
```
frontend/
├── app/
│   ├── layout.tsx          # Root layout
│   ├── page.tsx            # Chat interface
│   ├── api/                # API routes (if needed)
│   └── components/
│       ├── ChatInterface.tsx
│       ├── MessageList.tsx
│       ├── MessageInput.tsx
│       ├── CypherViewer.tsx
│       └── ResultsTable.tsx
├── lib/
│   ├── api.ts              # API client
│   └── websocket.ts        # WebSocket client
└── public/
```

**Key Features:**
- Chat interface with message history
- Streaming responses (typing indicators)
- Display Cypher queries (with syntax highlighting)
- Show results in tables/charts
- Error handling and retry logic
- Loading states

### 2. Backend API (FastAPI)

**Structure:**
```
backend/
├── app/
│   ├── main.py             # FastAPI app
│   ├── api/
│   │   ├── chat.py         # Chat endpoints
│   │   ├── health.py       # Health checks
│   │   └── websocket.py    # WebSocket handler
│   ├── services/
│   │   ├── graphrag.py     # Your existing text_to_cypher logic
│   │   └── streaming.py    # Streaming response handler
│   └── models/
│       └── schemas.py      # Pydantic models
├── Dockerfile
└── requirements.txt
```

**API Endpoints:**
- `POST /api/chat` - Send question, get response
- `WS /api/chat/stream` - WebSocket for streaming responses
- `GET /api/health` - Health check
- `GET /api/schema` - Get Neo4j schema (optional)

### 3. Integration with Existing Code

**Reuse Existing Modules:**
- `ai/text_to_cypher.py` - Core logic
- `ai/fewshots/vector_store.py` - Vector search
- `ai/llmops/langfuse_client.py` - Langfuse integration
- `utils_neo4j.py` - Neo4j connection

**API Service Layer:**
```python
# backend/app/services/graphrag.py
from ai.text_to_cypher import main as text_to_cypher_main
# Wrap existing functionality in async API handlers
```

## Deployment Options

### Option 1: Azure Container Apps (Recommended)

**Benefits:**
- Serverless containers (auto-scaling)
- Pay-per-use
- Easy CI/CD integration
- Built-in load balancing

**Setup:**
1. Containerize FastAPI app with Docker
2. Push to Azure Container Registry (ACR)
3. Deploy to Azure Container Apps
4. Configure environment variables from Azure Key Vault

### Option 2: Azure App Service

**Benefits:**
- Simple deployment
- Built-in CI/CD
- Good for smaller scale

**Setup:**
1. Deploy FastAPI as Azure App Service
2. Use Azure App Service for Linux
3. Configure environment variables

### Option 3: Azure Static Web Apps + Azure Functions

**Benefits:**
- Serverless (very cost-effective)
- Auto-scaling
- Good for high traffic

**Setup:**
1. Frontend: Azure Static Web Apps
2. Backend: Azure Functions (Python)
3. Use Function Apps for API endpoints

## Implementation Steps

### Phase 1: Backend API (FastAPI)

1. **Create FastAPI application**
   - Wrap existing `text_to_cypher.py` logic
   - Add async endpoints
   - Implement WebSocket for streaming

2. **Add request/response models**
   - Pydantic schemas for validation
   - Error handling

3. **Containerize**
   - Create Dockerfile
   - Test locally

### Phase 2: Frontend (Next.js)

1. **Setup Next.js project**
   - Initialize with TypeScript
   - Install UI libraries (shadcn/ui)

2. **Build chat interface**
   - Message components
   - Input handling
   - WebSocket integration

3. **Add features**
   - Cypher query display
   - Results visualization
   - Error handling

### Phase 3: Azure Deployment

1. **Setup Azure resources**
   - Create Resource Group
   - Setup Azure Container Registry
   - Create Azure Container Apps environment
   - Setup Azure Static Web Apps

2. **Configure secrets**
   - Store in Azure Key Vault
   - Reference in Container Apps

3. **CI/CD Pipeline**
   - GitHub Actions or Azure DevOps
   - Auto-deploy on push

## Security Considerations

1. **Authentication**
   - Azure AD B2C for user authentication
   - API keys for service-to-service
   - CORS configuration

2. **Secrets Management**
   - All secrets in Azure Key Vault
   - No secrets in code or environment files

3. **Network Security**
   - Private endpoints for Neo4j (if Aura)
   - VNet integration (if needed)
   - API rate limiting

4. **Data Protection**
   - HTTPS only
   - Input validation
   - SQL injection prevention (Cypher sanitization)

## Monitoring & Observability

1. **Azure Application Insights**
   - Track API performance
   - Monitor errors
   - User analytics

2. **Langfuse Integration**
   - Already integrated for LLM tracing
   - Track prompt performance
   - Cost monitoring

3. **Logging**
   - Structured logging
   - Log Analytics workspace

## Cost Optimization

1. **Azure Container Apps**: Pay-per-use, auto-scales to zero
2. **Azure Static Web Apps**: Free tier available
3. **Neo4j Aura**: Choose appropriate tier
4. **Azure OpenAI**: Use when available (cheaper than OpenAI API)

## Recommended Tech Stack Summary

| Component | Technology | Azure Service |
|-----------|-----------|---------------|
| Frontend | Next.js 14 + React | Azure Static Web Apps |
| Backend | FastAPI (Python) | Azure Container Apps |
| Real-time | WebSockets/SSE | Built into FastAPI |
| Database | Neo4j | Neo4j Aura |
| Secrets | - | Azure Key Vault |
| Monitoring | - | Azure Application Insights |
| CI/CD | GitHub Actions | Azure DevOps (optional) |

## Next Steps

1. Create FastAPI backend wrapper
2. Build Next.js frontend
3. Setup Azure infrastructure
4. Deploy and test

Would you like me to start implementing any of these components?

