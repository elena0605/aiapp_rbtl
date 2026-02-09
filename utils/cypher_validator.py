"""Cypher query validation using CyVer library.

This module provides validation for Cypher queries before execution on Neo4j.
It uses CyVer to validate syntax, schema, and properties.
Also enforces read-only queries to prevent write operations.
"""

import os
import re
import logging
from typing import Dict, Any, Optional, Tuple, List
from functools import lru_cache

from utils.neo4j import get_driver, get_default_database

logger = logging.getLogger(__name__)

# Try to import CyVer, but handle gracefully if not installed
try:
    from CyVer import SyntaxValidator, SchemaValidator, PropertiesValidator
    CYVER_AVAILABLE = True
except ImportError:
    CYVER_AVAILABLE = False
    SyntaxValidator = None
    SchemaValidator = None
    PropertiesValidator = None
    logger.warning(
        "CyVer library not available. Cypher validation will be skipped. "
        "Install with: pip install CyVer"
    )


class CypherValidationError(Exception):
    """Raised when a Cypher query fails validation."""
    
    def __init__(self, message: str, validation_details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.validation_details = validation_details or {}


class ReadOnlyViolationError(CypherValidationError):
    """Raised when a Cypher query attempts to perform write operations."""
    pass


def check_read_only(query: str) -> Tuple[bool, Optional[str], List[str]]:
    """Check if a Cypher query is read-only.
    
    Args:
        query: The Cypher query to check
    
    Returns:
        Tuple of (is_read_only, violation_type, detected_operations)
        - is_read_only: True if query is read-only, False otherwise
        - violation_type: Type of violation if not read-only (e.g., "CREATE", "DELETE")
        - detected_operations: List of write operations detected
    
    This function checks for common write operations in Cypher:
    - CREATE (node/relationship creation)
    - SET (property updates)
    - DELETE (node/relationship deletion)
    - REMOVE (property/label removal)
    - DETACH DELETE
    - MERGE (can create nodes/relationships)
    - FOREACH with write operations
    - CALL procedures that write (apoc.create, apoc.merge, etc.)
    """
    # Normalize query: remove comments and normalize whitespace
    # Remove single-line comments (// ...)
    query_normalized = re.sub(r'//.*?$', '', query, flags=re.MULTILINE)
    # Remove multi-line comments (/* ... */)
    query_normalized = re.sub(r'/\*.*?\*/', '', query_normalized, flags=re.DOTALL)
    # Normalize whitespace
    query_normalized = ' '.join(query_normalized.split())
    
    # Convert to uppercase for case-insensitive matching
    query_upper = query_normalized.upper()
    
    # List of write operations to detect
    # Using word boundaries to avoid false positives (e.g., "RETURN" contains "RETURN")
    write_patterns = [
        (r'\bCREATE\b', 'CREATE'),
        (r'\bSET\b', 'SET'),
        (r'\bDELETE\b', 'DELETE'),
        (r'\bDETACH\s+DELETE\b', 'DETACH DELETE'),
        (r'\bREMOVE\b', 'REMOVE'),
        (r'\bMERGE\b', 'MERGE'),
    ]
    
    # Check for write operations
    detected_operations = []
    violation_type = None
    
    for pattern, operation_name in write_patterns:
        matches = re.findall(pattern, query_upper, re.IGNORECASE)
        if matches:
            detected_operations.append(operation_name)
            if violation_type is None:
                violation_type = operation_name
    
    # Check for write procedures (APOC, GDS, etc.)
    # Pattern: CALL procedure.name(...) where procedure might write
    write_procedures = [
        r'CALL\s+(?:db|apoc|gds)\.(?:create|merge|delete|remove|set|update)',
        r'CALL\s+(?:db|apoc|gds)\.(?:write|mutate)',
    ]
    
    for pattern in write_procedures:
        if re.search(pattern, query_upper, re.IGNORECASE):
            detected_operations.append('CALL_WRITE_PROCEDURE')
            if violation_type is None:
                violation_type = 'CALL_WRITE_PROCEDURE'
    
    # Check for FOREACH with write operations inside
    # This is more complex - look for FOREACH followed by write operations
    foreach_pattern = r'FOREACH\s*\([^)]+\)\s*'
    foreach_matches = list(re.finditer(foreach_pattern, query_upper, re.IGNORECASE))
    if foreach_matches:
        for match in foreach_matches:
            # Check if the FOREACH block contains write operations
            foreach_block = query_upper[match.end():match.end()+200]  # Check next 200 chars
            for pattern, op_name in write_patterns[:4]:  # Check CREATE, SET, DELETE, REMOVE
                if re.search(pattern, foreach_block, re.IGNORECASE):
                    detected_operations.append(f'FOREACH_{op_name}')
                    if violation_type is None:
                        violation_type = f'FOREACH_{op_name}'
    
    is_read_only = len(detected_operations) == 0
    
    return is_read_only, violation_type, detected_operations


class CypherValidator:
    """Validates Cypher queries using CyVer library.
    
    Performs three levels of validation:
    1. Syntax validation - checks for correct Cypher syntax
    2. Schema validation - checks query alignment with KG schema
    3. Properties validation - ensures property accesses are correct
    """
    
    def __init__(self, driver=None, database_name: Optional[str] = None):
        """Initialize the validator.
        
        Args:
            driver: Neo4j driver instance. If None, uses get_driver()
            database_name: Database name. If None, uses get_default_database()
        """
        if not CYVER_AVAILABLE:
            raise RuntimeError(
                "CyVer library is not installed. Install with: pip install CyVer"
            )
        
        self.driver = driver or get_driver()
        self.database_name = database_name or get_default_database()
        
        # Initialize validators
        # check_multilabeled_nodes=False to match example usage
        self.syntax_validator = SyntaxValidator(
            self.driver,
            check_multilabeled_nodes=False
        )
        self.schema_validator = SchemaValidator(self.driver)
        self.props_validator = PropertiesValidator(self.driver)
    
    def validate(
        self,
        query: str,
        strict: bool = True,
        database_name: Optional[str] = None,
        enforce_read_only: bool = True
    ) -> Tuple[bool, Dict[str, Any]]:
        """Validate a Cypher query.
        
        Args:
            query: The Cypher query to validate
            strict: If True, raises exception on validation failure. If False, returns (False, details)
            database_name: Override database name for this validation
            enforce_read_only: If True, ensures query is read-only (default: True)
        
        Returns:
            Tuple of (is_valid, validation_details)
            validation_details contains:
                - read_only_valid: bool
                - read_only_violations: list of detected write operations
                - syntax_valid: bool
                - syntax_metadata: dict
                - schema_score: float (0.0 to 1.0)
                - schema_metadata: dict
                - props_score: float or None (0.0 to 1.0)
                - props_metadata: dict
                - is_valid: bool (overall validation result)
        
        Raises:
            ReadOnlyViolationError: If query contains write operations and enforce_read_only=True
            CypherValidationError: If validation fails and strict=True
        """
        db_name = database_name or self.database_name
        
        validation_details = {
            "read_only_valid": True,
            "read_only_violations": [],
            "syntax_valid": False,
            "syntax_metadata": {},
            "schema_score": 0.0,
            "schema_metadata": {},
            "props_score": None,
            "props_metadata": {},
            "is_valid": False,
        }
        
        # 0. Read-only check (first, before any other validation)
        if enforce_read_only:
            is_read_only, violation_type, detected_ops = check_read_only(query)
            validation_details["read_only_valid"] = is_read_only
            validation_details["read_only_violations"] = detected_ops
            
            if not is_read_only:
                error_msg = (
                    f"Query contains write operations and is not read-only. "
                    f"Detected operations: {', '.join(detected_ops)}. "
                    f"Only SELECT/READ queries are allowed."
                )
                logger.error(f"Read-only violation: {error_msg}")
                if strict:
                    raise ReadOnlyViolationError(
                        error_msg,
                        validation_details
                    )
                validation_details["is_valid"] = False
                return False, validation_details
        
        # 1. Syntax Validation (must pass first)
        try:
            is_syntax_valid, syntax_metadata = self.syntax_validator.validate(
                query,
                database_name=db_name
            )
            validation_details["syntax_valid"] = is_syntax_valid
            validation_details["syntax_metadata"] = syntax_metadata
            
            if not is_syntax_valid:
                logger.warning(
                    f"Cypher syntax validation failed: {syntax_metadata}"
                )
                if strict:
                    raise CypherValidationError(
                        f"Cypher query syntax validation failed: {syntax_metadata}",
                        validation_details
                    )
                validation_details["is_valid"] = False
                return False, validation_details
        except Exception as e:
            logger.error(f"Syntax validation error: {e}", exc_info=True)
            if strict:
                raise CypherValidationError(
                    f"Syntax validation error: {e}",
                    validation_details
                ) from e
            validation_details["is_valid"] = False
            return False, validation_details
        
        # 2. Schema Validation
        try:
            schema_score, schema_metadata = self.schema_validator.validate(
                query,
                database_name=db_name
            )
            validation_details["schema_score"] = schema_score
            validation_details["schema_metadata"] = schema_metadata
            
            if schema_score != 1.0:
                logger.warning(
                    f"Cypher schema validation score: {schema_score} (expected 1.0): {schema_metadata}"
                )
                if strict:
                    raise CypherValidationError(
                        f"Cypher query schema validation failed (score: {schema_score}): {schema_metadata}",
                        validation_details
                    )
                validation_details["is_valid"] = False
                return False, validation_details
        except Exception as e:
            logger.error(f"Schema validation error: {e}", exc_info=True)
            if strict:
                raise CypherValidationError(
                    f"Schema validation error: {e}",
                    validation_details
                ) from e
            validation_details["is_valid"] = False
            return False, validation_details
        
        # 3. Properties Validation
        try:
            props_score, props_metadata = self.props_validator.validate(
                query,
                strict=False,  # Use strict=False as in example
                database_name=db_name
            )
            validation_details["props_score"] = props_score
            validation_details["props_metadata"] = props_metadata
            
            # According to CyVer docs: score should be 1 or None for valid queries
            if props_score is not None and props_score != 1.0:
                logger.warning(
                    f"Cypher properties validation score: {props_score} (expected 1.0 or None): {props_metadata}"
                )
                if strict:
                    raise CypherValidationError(
                        f"Cypher query properties validation failed (score: {props_score}): {props_metadata}",
                        validation_details
                    )
                validation_details["is_valid"] = False
                return False, validation_details
        except Exception as e:
            logger.error(f"Properties validation error: {e}", exc_info=True)
            if strict:
                raise CypherValidationError(
                    f"Properties validation error: {e}",
                    validation_details
                ) from e
            validation_details["is_valid"] = False
            return False, validation_details
        
        # All validations passed
        validation_details["is_valid"] = True
        logger.debug("Cypher query validation passed")
        return True, validation_details


@lru_cache(maxsize=1)
def get_validator(driver=None, database_name: Optional[str] = None) -> Optional[CypherValidator]:
    """Get a cached Cypher validator instance.
    
    Returns None if CyVer is not available.
    """
    if not CYVER_AVAILABLE:
        return None
    
    try:
        return CypherValidator(driver=driver, database_name=database_name)
    except Exception as e:
        logger.warning(f"Failed to initialize Cypher validator: {e}")
        return None


def validate_cypher(
    query: str,
    strict: bool = True,
    driver=None,
    database_name: Optional[str] = None,
    enforce_read_only: bool = True
) -> Tuple[bool, Dict[str, Any]]:
    """Convenience function to validate a Cypher query.
    
    Args:
        query: The Cypher query to validate
        strict: If True, raises exception on validation failure
        driver: Neo4j driver (optional, uses get_driver() if None)
        database_name: Database name (optional, uses get_default_database() if None)
        enforce_read_only: If True, ensures query is read-only (default: True)
    
    Returns:
        Tuple of (is_valid, validation_details)
    
    Raises:
        ReadOnlyViolationError: If query contains write operations and enforce_read_only=True
        CypherValidationError: If validation fails and strict=True
        RuntimeError: If CyVer is not available and strict=True
    """
    # Always check read-only first, even if CyVer is not available
    if enforce_read_only:
        is_read_only, violation_type, detected_ops = check_read_only(query)
        if not is_read_only:
            error_msg = (
                f"Query contains write operations and is not read-only. "
                f"Detected operations: {', '.join(detected_ops)}. "
                f"Only SELECT/READ queries are allowed."
            )
            logger.error(f"Read-only violation: {error_msg}")
            if strict:
                raise ReadOnlyViolationError(
                    error_msg,
                    {
                        "read_only_valid": False,
                        "read_only_violations": detected_ops,
                        "violation_type": violation_type,
                    }
                )
            return False, {
                "read_only_valid": False,
                "read_only_violations": detected_ops,
                "violation_type": violation_type,
                "is_valid": False,
            }
    
    if not CYVER_AVAILABLE:
        if strict:
            raise RuntimeError(
                "CyVer library is not installed. Install with: pip install CyVer"
            )
        logger.warning("CyVer not available, skipping validation")
        return True, {"skipped": True, "reason": "CyVer not available"}
    
    validator = get_validator(driver=driver, database_name=database_name)
    if validator is None:
        if strict:
            raise RuntimeError("Failed to initialize Cypher validator")
        logger.warning("Validator initialization failed, skipping validation")
        return True, {"skipped": True, "reason": "Validator initialization failed"}
    
    return validator.validate(
        query,
        strict=strict,
        database_name=database_name,
        enforce_read_only=enforce_read_only
    )
