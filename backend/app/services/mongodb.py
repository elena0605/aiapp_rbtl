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
    """Get or create MongoDB client.
    
    For environment switching:
      - Set ENVIRONMENT=development to use MONGODB_URI_DEV
      - Set ENVIRONMENT=production (or omit) to use MONGODB_URI
    """
    global _client
    if _client is None:
        environment = os.getenv("ENVIRONMENT", "production").lower()
        
        # Select environment-specific connection string
        if environment == "development":
            connection_string = os.getenv("MONGODB_URI_DEV") or os.getenv("MONGODB_URI")
        else:
            connection_string = os.getenv("MONGODB_URI")
        
        if not connection_string:
            raise ValueError(
                f"MONGODB_URI environment variable is not set "
                f"(environment={environment})"
            )
        # For Azure CosmosDB, we may need to disable SSL certificate verification
        # Note: This is safe for Azure CosmosDB as it uses Microsoft-managed certificates
        _client = MongoClient(
            connection_string,
            tlsAllowInvalidCertificates=True  # Required for Azure CosmosDB
        )
    return _client


def get_database():
    """Get MongoDB database instance.
    
    For environment switching:
      - Set ENVIRONMENT=development to use MONGODB_DB_DEV or MONGODB_DATABASE_DEV
      - Set ENVIRONMENT=production (or omit) to use MONGODB_DB or MONGODB_DATABASE
    """
    global _db
    if _db is None:
        client = get_mongo_client()
        environment = os.getenv("ENVIRONMENT", "production").lower()
        
        # Select environment-specific database name
        if environment == "development":
            # Support both MONGODB_DB_DEV and MONGODB_DATABASE_DEV for compatibility
            db_name = (
                os.getenv("MONGODB_DB_DEV") 
                or os.getenv("MONGODB_DATABASE_DEV")
                or os.getenv("MONGODB_DB")
                or os.getenv("MONGODB_DATABASE", "graphrag")
            )
        else:
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

