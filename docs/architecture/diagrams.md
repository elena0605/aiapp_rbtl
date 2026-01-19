# Architecture Diagrams

This document provides three complementary Mermaid diagrams that illustrate the GraphRAG system from different perspectives:

1. **User Journey Diagram** - Shows the user experience flow and interactions
2. **Cloud Infrastructure Diagram** - Shows deployment architecture and service relationships
3. **AI Implementation Diagram** - Shows the AI/LLM processing pipeline and decision flows

## 1. User Journey Diagram

This diagram illustrates the user's perspective: how they interact with the system, what they see, and the flow of their experience.

```mermaid
flowchart TD
    Start([User Opens Application]) --> Login[Login/Select Username]
    Login --> Dashboard[Main Dashboard]
    
    Dashboard --> AskQuestion[Ask Natural Language Question]
    Dashboard --> ViewKB[Browse Knowledge Base]
    Dashboard --> ViewFavorites[View Favorites]
    Dashboard --> ViewHistory[View Chat History]
    
    AskQuestion --> Processing[System Processing]
    Processing --> RouteDecision{Route Decision}
    
    RouteDecision -->|Analytics Question| AnalyticsRoute[Analytics Agent]
    RouteDecision -->|Standard Query| CypherRoute[Text-to-Cypher]
    
    AnalyticsRoute --> AnalyticsResult[Graph Algorithm Results]
    CypherRoute --> CypherGen[Generate Cypher Query]
    CypherGen --> ExecuteQuery[Execute on Neo4j]
    ExecuteQuery --> QueryResults[Raw Query Results]
    
    AnalyticsResult --> Summarize[Generate Summary]
    QueryResults --> Summarize
    
    Summarize --> DisplayResults[Display Results]
    DisplayResults --> ShowCypher[Show Generated Cypher]
    DisplayResults --> ShowTable[Show Results Table]
    DisplayResults --> ShowSummary[Show Natural Language Summary]
    DisplayResults --> ShowRoute[Show Route Type Badge]
    
    ShowCypher --> UserActions{User Actions}
    ShowTable --> UserActions
    ShowSummary --> UserActions
    ShowRoute --> UserActions
    
    UserActions -->|Save| SaveFavorite[Save to Favorites]
    UserActions -->|Ask Follow-up| AskQuestion
    UserActions -->|Browse KB| ViewKB
    UserActions -->|Delete| DeleteMessage[Delete Message]
    
    SaveFavorite --> Dashboard
    DeleteMessage --> Dashboard
    ViewKB --> KBDetail[View Category Details]
    KBDetail --> Dashboard
    ViewFavorites --> Dashboard
    ViewHistory --> Dashboard
    
    style Start fill:#e1f5ff
    style Dashboard fill:#fff4e1
    style Processing fill:#ffe1f5
    style RouteDecision fill:#e1ffe1
    style DisplayResults fill:#f0e1ff
```

## 2. Cloud Infrastructure Diagram

This diagram shows the deployment architecture, cloud services, and how components communicate in a production environment.

```mermaid
graph TB
    subgraph "User Layer"
        Browser[Web Browser]
        Mobile[Mobile App]
    end
    
    subgraph "Azure Static Web Apps / CDN"
        Frontend[Next.js Frontend<br/>Port 3003]
    end
    
    subgraph "Azure Container Apps"
        Backend[FastAPI Backend<br/>Port 8001]
    end
    
    subgraph "Managed Services"
        Neo4j[(Neo4j Aura<br/>Graph Database)]
        MongoDB[(MongoDB Atlas<br/>Knowledge Base)]
    end
    
    subgraph "AI Services"
        OpenAI[OpenAI API<br/>GPT-4o]
    end
    
    subgraph "Observability Stack"
        Langfuse[Langfuse UI<br/>Port 3001]
        Postgres[(PostgreSQL<br/>Port 5433)]
        ClickHouse[(ClickHouse<br/>Port 8123)]
    end
    
    subgraph "Optional Services"
        GDSAgent[Neo4j GDS Agent<br/>via MCP stdio]
    end
    
    Browser -->|HTTPS| Frontend
    Mobile -->|HTTPS| Frontend
    
    Frontend -->|REST API<br/>WebSocket| Backend
    
    Backend -->|Cypher Queries<br/>Bolt Protocol| Neo4j
    Backend -->|MongoDB Driver| MongoDB
    Backend -->|Langfuse SDK| Langfuse
    Backend -->|OpenAI SDK| OpenAI
    Backend -->|MCP stdio<br/>JSON-RPC| GDSAgent
    
    Langfuse --> Postgres
    Langfuse --> ClickHouse
    
    GDSAgent -.->|Queries| Neo4j
    
    Backend -.->|Traces| Langfuse
    
    style Browser fill:#e1f5ff
    style Frontend fill:#fff4e1
    style Backend fill:#ffe1f5
    style Neo4j fill:#e1ffe1
    style MongoDB fill:#e1ffe1
    style OpenAI fill:#f0e1ff
    style Langfuse fill:#ffe1f5
    style GDSAgent fill:#e1f5ff,stroke-dasharray: 5 5
```

## 3. AI Implementation Diagram

This diagram details the AI processing pipeline, showing how natural language questions are transformed into Cypher queries or routed to analytics tools, including all the AI components and decision points.

```mermaid
flowchart TD
    Start([User Question]) --> LoadContext[Load Context]
    
    LoadContext --> LoadSchema[Load Neo4j Schema<br/>ai/schema/]
    LoadContext --> LoadTerminology[Load Terminology<br/>ai/terminology/]
    LoadContext --> LoadPrompt[Load Prompt Template<br/>ai/prompts/]
    
    LoadSchema --> CheckAnalytics{Analytics<br/>Enabled?}
    LoadTerminology --> CheckAnalytics
    LoadPrompt --> CheckAnalytics
    
    CheckAnalytics -->|Yes| TryAnalytics[Analytics Agent Route]
    CheckAnalytics -->|No| TextToCypher[Text-to-Cypher Route]
    
    subgraph "Analytics Agent Path"
        TryAnalytics --> LLMSelect[LLM Tool Selector<br/>GraphAnalyticsAgent]
        LLMSelect --> ToolDecision{Tool<br/>Appropriate?}
        ToolDecision -->|Yes| CallMCP[Call MCP Tool<br/>leiden/article_rank/bridges]
        ToolDecision -->|No| FallbackCypher[Fallback to Cypher]
        CallMCP --> MCPResult[MCP Tool Result]
        MCPResult --> AnalyticsSummary[Generate Summary<br/>LLM]
        AnalyticsSummary --> AnalyticsOutput[Return Analytics Result]
    end
    
    subgraph "Text-to-Cypher Path"
        TextToCypher --> VectorSearch{Vector Search<br/>Enabled?}
        FallbackCypher --> VectorSearch
        
        VectorSearch -->|Yes| SearchExamples[Search Similar Examples<br/>ai/fewshots/vector_store]
        VectorSearch -->|No| LoadStatic[Load Static Examples<br/>ai/fewshots/loader]
        
        SearchExamples --> RenderPrompt[Render Prompt Template]
        LoadStatic --> RenderPrompt
        
        RenderPrompt --> InjectSchema[Inject Schema Context]
        RenderPrompt --> InjectTerminology[Inject Terminology]
        RenderPrompt --> InjectExamples[Inject Few-Shot Examples]
        RenderPrompt --> InjectQuestion[Inject User Question]
        
        InjectSchema --> CompilePrompt[Compile Full Prompt]
        InjectTerminology --> CompilePrompt
        InjectExamples --> CompilePrompt
        InjectQuestion --> CompilePrompt
        
        CompilePrompt --> CallLLM[Call OpenAI LLM<br/>GPT-4o]
        CallLLM --> TraceLangfuse[Trace to Langfuse]
        TraceLangfuse --> ExtractCypher[Extract Cypher Query]
        
        ExtractCypher --> ValidateCypher{Valid<br/>Cypher?}
        ValidateCypher -->|No| Error[Return Error]
        ValidateCypher -->|Yes| ExecuteCypher[Execute on Neo4j]
        
        ExecuteCypher --> QueryResults[Raw Query Results]
        QueryResults --> LoadSummaryPrompt[Load Summary Prompt<br/>graph-result-summarizer]
        LoadSummaryPrompt --> RenderSummary[Render Summary Prompt]
        RenderSummary --> CallSummaryLLM[Call OpenAI LLM<br/>for Summary]
        CallSummaryLLM --> TraceSummary[Trace Summary to Langfuse]
        TraceSummary --> CypherOutput[Return Cypher Result]
    end
    
    AnalyticsOutput --> End([Return to User])
    CypherOutput --> End
    Error --> End
    
    style Start fill:#e1f5ff
    style CheckAnalytics fill:#fff4e1
    style TryAnalytics fill:#ffe1f5
    style TextToCypher fill:#ffe1f5
    style CallLLM fill:#f0e1ff
    style CallSummaryLLM fill:#f0e1ff
    style LLMSelect fill:#f0e1ff
    style End fill:#e1ffe1
```

## Diagram Usage Recommendations

### When to Use Each Diagram

1. **User Journey Diagram**: 
   - Best for onboarding new users
   - Demonstrating the user experience to stakeholders
   - UX/UI design discussions
   - User documentation

2. **Cloud Infrastructure Diagram**:
   - DevOps and deployment planning
   - Infrastructure reviews
   - Cost estimation discussions
   - Security and compliance audits
   - System architecture documentation

3. **AI Implementation Diagram**:
   - Developer onboarding
   - AI/ML team discussions
   - Debugging AI pipeline issues
   - Prompt engineering sessions
   - Performance optimization

### Integration with Documentation

These diagrams complement the existing architecture documentation:

- **User Journey** → See `frontend.md` for component details
- **Cloud Infrastructure** → See `azure-deployment.md` for deployment specifics
- **AI Implementation** → See `ai-stack.md` and `mcp.md` for technical details

### Maintenance

- Update diagrams when adding new user features (User Journey)
- Update diagrams when changing deployment architecture (Cloud Infrastructure)
- Update diagrams when modifying AI pipeline or adding new LLM routes (AI Implementation)

### Exporting Diagrams

To export these diagrams as images:

1. Use Mermaid Live Editor: https://mermaid.live/
2. Copy each diagram code block
3. Export as PNG/SVG
4. Add to documentation or presentations

Alternatively, if using MkDocs with mermaid plugin, these will render automatically in the documentation site.
