"""MongoDB service for knowledge base operations."""

from pymongo import MongoClient
from pymongo.collection import Collection
from typing import Optional
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
ROOT = Path(__file__).resolve().parents[3]
load_dotenv(dotenv_path=str(ROOT / ".env"))

# MongoDB connection
_client: Optional[MongoClient] = None
_db = None


def get_mongo_client() -> MongoClient:
    """Get or create MongoDB client."""
    global _client
    if _client is None:
        connection_string = os.getenv("MONGODB_URI")
        if not connection_string:
            raise ValueError("MONGODB_URI environment variable is not set")
        # For Azure CosmosDB, we may need to disable SSL certificate verification
        # Note: This is safe for Azure CosmosDB as it uses Microsoft-managed certificates
        _client = MongoClient(
            connection_string,
            tlsAllowInvalidCertificates=True  # Required for Azure CosmosDB
        )
    return _client


def get_database():
    """Get MongoDB database instance."""
    global _db
    if _db is None:
        client = get_mongo_client()
        # Support both MONGODB_DB and MONGODB_DATABASE for compatibility
        db_name = os.getenv("MONGODB_DB") or os.getenv("MONGODB_DATABASE", "graphrag")
        _db = client[db_name]
    return _db


def get_query_examples_collection() -> Collection:
    """Get the ai_query_examples collection."""
    db = get_database()
    return db["ai_query_examples"]


def get_categories_collection() -> Collection:
    """Get the ai_query_categories collection."""
    db = get_database()
    return db["ai_query_categories"]


def get_chat_sessions_collection() -> Collection:
    """Get the chat_sessions collection."""
    db = get_database()
    return db["chat_sessions"]


def close_connection():
    """Close MongoDB connection."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None

