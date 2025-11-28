# RBTL GraphRAG Documentation

RBTL (Reading Between the Lines) leverages a custom GraphRAG implementation to deliver a natural-language interface to Neo4j, combining Retrieval-Augmented Generation with graph analytics tooling. Use this site as the authoritative source for onboarding, architecture decisions, operational playbooks, and contribution guidelines.

## Highlights

- **LLM-powered graph querying** that transforms questions into Cypher using `ai/text_to_cypher.py`.
- **Schema-aware prompts** backed by `ai/schema/` helpers and Langfuse prompt management.
- **Observability-first approach** using Langfuse, structured logging, and automated tests.

## How to Use These Docs

- Start with [Getting Started](getting-started.md) to run the dockerized application locally.
- Explore the [Architecture](architecture/system-overview.md) section for diagrams and service breakdowns.
- Review [Docker Deployment](../DOCKER_DEPLOYMENT.md) for local and cloud container deployment.
- Consult [Operations](operations/deployment.md) for environment-specific deployment guides.
- See [Azure Production Deployment](operations/azure-deployment.md) for cloud deployment with Docker containers.

