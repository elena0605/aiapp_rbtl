import os
import atexit
from contextlib import contextmanager
from typing import Iterator, Optional

from neo4j import GraphDatabase, Driver, Session
from dotenv import load_dotenv


_driver: Optional[Driver] = None


def get_driver() -> Driver:
    """Return a singleton Neo4j Driver initialized from env/.env.

    Requires env variables:
      - NEO4J_URI (e.g., neo4j+s://<db-id>.databases.neo4j.io)
      - NEO4J_USER
      - NEO4J_PASSWORD
    
    For environment switching:
      - Set ENVIRONMENT=development to use NEO4J_URI_DEV, NEO4J_USER_DEV, NEO4J_PASSWORD_DEV
      - Set ENVIRONMENT=production (or omit) to use NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
    """
    global _driver
    if _driver is None:
        load_dotenv()
        environment = os.environ.get("ENVIRONMENT", "production").lower()
        
        # Select environment-specific variables
        if environment == "development":
            uri = os.environ.get("NEO4J_URI_DEV") or os.environ.get("NEO4J_URI")
            user = os.environ.get("NEO4J_USER_DEV") or os.environ.get("NEO4J_USER")
            password = os.environ.get("NEO4J_PASSWORD_DEV") or os.environ.get("NEO4J_PASSWORD")
        else:
            uri = os.environ.get("NEO4J_URI")
            user = os.environ.get("NEO4J_USER")
            password = os.environ.get("NEO4J_PASSWORD")
        
        if not uri or not user or not password:
            raise RuntimeError(
                f"NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD must be set in environment or .env "
                f"(environment={environment})"
            )
        # Configure timeouts from environment or use defaults
        connection_timeout = float(os.environ.get("NEO4J_CONNECTION_TIMEOUT", "30.0"))
        max_connection_lifetime = float(os.environ.get("NEO4J_MAX_CONNECTION_LIFETIME", "3600.0"))
        max_connection_pool_size = int(os.environ.get("NEO4J_MAX_CONNECTION_POOL_SIZE", "50"))
        
        
        
        driver_kwargs = {
            "uri": uri,
            "auth": (user, password),
            "connection_timeout": connection_timeout,
            "max_connection_lifetime": max_connection_lifetime,
            "max_connection_pool_size": max_connection_pool_size,
        }
        
        
        
        _driver = GraphDatabase.driver(**driver_kwargs)
        # Skip verify_connectivity() during initialization to avoid hanging
        # Connection will be tested on first actual query/operation
        # Set NEO4J_VERIFY_ON_INIT=true in environment to enable verification
        verify_on_init = os.environ.get("NEO4J_VERIFY_ON_INIT", "").lower() in {"1", "true", "yes"}
        if verify_on_init:
            try:
                _driver.verify_connectivity()
            except Exception as e:
                # If connectivity check fails, close the driver and re-raise
                try:
                    _driver.close()
                except Exception:
                    pass
                _driver = None
                raise RuntimeError(
                    f"Failed to connect to Neo4j at {uri}. "
                    f"Please check your NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD. "
                    f"Original error: {e}"
                ) from e
        atexit.register(close_driver)
    return _driver


def get_default_database() -> Optional[str]:
    """Get the default Neo4j database name based on the current environment.
    
    Returns:
        Database name from NEO4J_DATABASE_DEV (development) or NEO4J_DATABASE (production),
        or None if not set (uses Neo4j default).
    """
    load_dotenv()
    environment = os.environ.get("ENVIRONMENT", "production").lower()
    
    if environment == "development":
        database = os.environ.get("NEO4J_DATABASE_DEV") or os.environ.get("NEO4J_DATABASE")
    else:
        database = os.environ.get("NEO4J_DATABASE")
    
    return database if database else None


@contextmanager
def get_session(database: Optional[str] = None) -> Iterator[Session]:
    """Yield a Neo4j session bound to the optional database and close it on exit.
    
    If database is not provided, uses the default database from environment variables:
    - NEO4J_DATABASE_DEV (when ENVIRONMENT=development)
    - NEO4J_DATABASE (when ENVIRONMENT=production)
    - None (uses Neo4j default database) if neither is set
    """
    driver = get_driver()
    # Use provided database, or fall back to environment-based default
    if database is None:
        database = get_default_database()
    kwargs = {"database": database} if database else {}
    session = driver.session(**kwargs)
    try:
        yield session
    finally:
        try:
            session.close()
        except Exception:
            pass


def close_driver() -> None:
    """Close the global driver (registered with atexit)."""
    global _driver
    if _driver is not None:
        try:
            _driver.close()
        finally:
            _driver = None

