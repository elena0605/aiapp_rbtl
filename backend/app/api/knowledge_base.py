"""Knowledge Base endpoints for managing query examples."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

from backend.app.services.mongodb import (
    get_query_examples_collection,
    get_categories_collection
)
from backend.app.services.neo4j_sync import (
    add_example_to_neo4j,
    delete_example_from_neo4j,
    ensure_vector_index
)
from backend.app.services.update_category_in_neo4j import update_category_in_neo4j
import sys
from pathlib import Path
import os
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from utils_neo4j import get_session  # type: ignore
VECTOR_NODE_LABEL = os.getenv("VECTOR_NODE_LABEL", "QueryExample")

router = APIRouter()


def _normalize_created_by(value: Optional[str]) -> str:
    """Ensure created_by is always a non-empty string."""
    creator = (value or "ai").strip()
    return creator or "ai"


class AddQueryRequest(BaseModel):
    category_name: str
    question: str
    cypher: str
    created_by: Optional[str] = "ai"


class UpdateQueryRequest(BaseModel):
    old_question: str
    old_cypher: str
    new_question: str
    new_cypher: str
    new_created_by: Optional[str] = None


class CreateCategoryRequest(BaseModel):
    category_name: str
    category_description: str


class UpdateCategoryRequest(BaseModel):
    category_name: Optional[str] = None
    category_description: Optional[str] = None


@router.get("/knowledge-base/categories")
async def get_categories():
    """Get all categories with descriptions."""
    try:
        categories_collection = get_categories_collection()
        categories = list(categories_collection.find({}, {"_id": 0}))
        
        # If no categories in MongoDB, return empty list
        if not categories:
            return {"categories": []}
        
        return {"categories": categories}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch categories: {str(e)}")


@router.post("/knowledge-base/categories")
async def create_category(request: CreateCategoryRequest):
    """Create a new category."""
    try:
        categories_collection = get_categories_collection()
        
        # Check if category already exists
        existing = categories_collection.find_one({"category_name": request.category_name})
        if existing:
            raise HTTPException(status_code=409, detail="Category already exists")
        
        # Create new category
        category = {
            "category_name": request.category_name,
            "category_description": request.category_description
        }
        categories_collection.insert_one(category)
        
        return {"message": "Category created successfully", "category": category}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create category: {str(e)}")


@router.put("/knowledge-base/categories/{category_name}")
async def update_category(category_name: str, request: UpdateCategoryRequest):
    """Update a category."""
    try:
        categories_collection = get_categories_collection()
        query_collection = get_query_examples_collection()
        
        # Check if category exists
        existing = categories_collection.find_one({"category_name": category_name})
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Prepare update data
        update_data = {}
        new_category_name = None
        if request.category_name and request.category_name != category_name:
            # Category name is being changed - need to update in query_examples too
            update_data["category_name"] = request.category_name
            new_category_name = request.category_name
            # Update category_name in all query examples
            query_collection.update_many(
                {"category_name": category_name},
                {"$set": {"category_name": request.category_name}}
            )
        
        if request.category_description is not None:
            update_data["category_description"] = request.category_description
        
        # Update category information in Neo4j nodes
        if new_category_name or request.category_description is not None:
            try:
                update_category_in_neo4j(
                    category_name=category_name,
                    new_category_name=new_category_name,
                    category_description=request.category_description
                )
            except Exception as e:
                print(f"Warning: Failed to update category in Neo4j: {e}")
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        # Update category
        categories_collection.update_one(
            {"category_name": category_name},
            {"$set": update_data}
        )
        
        # Get updated category
        updated_category = categories_collection.find_one(
            {"category_name": update_data.get("category_name", category_name)},
            {"_id": 0}
        )
        
        return {"message": "Category updated successfully", "category": updated_category}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update category: {str(e)}")


@router.delete("/knowledge-base/categories/{category_name}")
async def delete_category(category_name: str, delete_queries: bool = False):
    """Delete a category.
    
    Args:
        category_name: Name of the category to delete
        delete_queries: If True, also delete all queries in this category. If False, deletion fails if category has queries.
    """
    try:
        categories_collection = get_categories_collection()
        query_collection = get_query_examples_collection()
        
        # Check if category exists
        existing = categories_collection.find_one({"category_name": category_name})
        if not existing:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Check if category has queries
        category_doc = query_collection.find_one({"category_name": category_name})
        has_queries = category_doc and len(category_doc.get("examples", [])) > 0
        
        if has_queries and not delete_queries:
            raise HTTPException(
                status_code=400,
                detail=f"Category has {len(category_doc.get('examples', []))} queries. Set delete_queries=true to delete category and all its queries."
            )
        
        # Delete all queries in this category if requested
        if has_queries and delete_queries:
            examples = category_doc.get("examples", [])
            # Delete from Neo4j
            try:
                for example in examples:
                    delete_example_from_neo4j(question=example.get("question"))
            except Exception as e:
                print(f"Warning: Failed to delete queries from Neo4j: {e}")
            
            # Delete from MongoDB
            query_collection.delete_one({"category_name": category_name})
        
        # Delete category
        categories_collection.delete_one({"category_name": category_name})
        
        return {"message": "Category deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete category: {str(e)}")


@router.get("/knowledge-base/queries")
async def get_queries(category: str):
    """Get all queries for a specific category."""
    try:
        query_collection = get_query_examples_collection()
        
        # Find the category document
        category_doc = query_collection.find_one({"category_name": category})
        
        if not category_doc:
            return {"queries": []}
        
        # Return the examples array
        examples = category_doc.get("examples", [])
        updates = {}
        # Remove _id from each example if present
        for idx, example in enumerate(examples):
            example.pop("_id", None)
            if not example.get("created_by"):
                example["created_by"] = "ai"
                updates[f"examples.{idx}.created_by"] = "ai"
        
        if updates:
            query_collection.update_one(
                {"category_name": category},
                {"$set": updates}
            )
        
        return {"queries": examples}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch queries: {str(e)}")


@router.post("/knowledge-base/queries")
async def add_query(request: AddQueryRequest):
    """Add a new query example to a category."""
    try:
        query_collection = get_query_examples_collection()
        created_by = _normalize_created_by(request.created_by)
        
        # Create new query example
        added_at = datetime.now().isoformat()
        new_example = {
            "question": request.question,
            "cypher": request.cypher,
            "added_at": added_at,
            "created_by": created_by,
        }
        
        # Find or create the category document
        category_doc = query_collection.find_one({"category_name": request.category_name})
        
        if not category_doc:
            # Create new category document
            category_doc = {
                "category_name": request.category_name,
                "examples": [new_example]
            }
            query_collection.insert_one(category_doc)
        else:
            # Add to existing category
            query_collection.update_one(
                {"category_name": request.category_name},
                {"$push": {"examples": new_example}}
            )
        
        # Sync to Neo4j vector store
        try:
            ensure_vector_index()  # Ensure index exists
            # Get category description for Neo4j
            categories_collection = get_categories_collection()
            category_doc = categories_collection.find_one({"category_name": request.category_name})
            category_description = category_doc.get("category_description", "") if category_doc else ""
            
            add_example_to_neo4j(
                question=request.question,
                cypher=request.cypher,
                category_name=request.category_name,
                added_at=added_at,
                category_description=category_description,
                created_by=created_by,
            )
        except Exception as neo4j_error:
            # Log error but don't fail the request - MongoDB update succeeded
            print(f"Warning: Failed to sync to Neo4j: {neo4j_error}")
            # Optionally, you could raise an error here if you want strict consistency
        
        return {"message": "Query added successfully", "example": new_example}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add query: {str(e)}")


@router.put("/knowledge-base/queries")
async def update_query(category: str, request: UpdateQueryRequest):
    """Update an existing query example in a category."""
    try:
        query_collection = get_query_examples_collection()
        
        # Find the category document
        category_doc = query_collection.find_one({"category_name": category})
        
        if not category_doc:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Find the query in the examples array
        examples = category_doc.get("examples", [])
        query_index = None
        for i, example in enumerate(examples):
            if example.get("question") == request.old_question and example.get("cypher") == request.old_cypher:
                query_index = i
                break
        
        if query_index is None:
            raise HTTPException(status_code=404, detail="Query not found")
        
        # Update the query in MongoDB
        # Use arrayFilters to update the specific element in the array
        update_fields = {
            "examples.$.question": request.new_question,
            "examples.$.cypher": request.new_cypher,
        }
        new_creator = None
        if request.new_created_by is not None:
            new_creator = _normalize_created_by(request.new_created_by)
            update_fields["examples.$.created_by"] = new_creator
        
        result = query_collection.update_one(
            {
                "category_name": category,
                "examples.question": request.old_question,
                "examples.cypher": request.old_cypher
            },
            {"$set": update_fields}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Query not found or no changes made")
        
        # Sync update to Neo4j vector store
        try:
            ensure_vector_index()
            # Delete old query from Neo4j
            delete_example_from_neo4j(question=request.old_question)
            # Add updated query to Neo4j
            categories_collection = get_categories_collection()
            category_info = categories_collection.find_one({"category_name": category})
            category_description = category_info.get("category_description", "") if category_info else ""
            
            creator_value = new_creator or _normalize_created_by(examples[query_index].get("created_by"))
            add_example_to_neo4j(
                question=request.new_question,
                cypher=request.new_cypher,
                category_name=category,
                added_at=examples[query_index].get("added_at", datetime.now().isoformat()),
                category_description=category_description,
                created_by=creator_value,
            )
        except Exception as neo4j_error:
            # Log error but don't fail the request - MongoDB update succeeded
            print(f"Warning: Failed to sync update to Neo4j: {neo4j_error}")
        
        return {"message": "Query updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update query: {str(e)}")


@router.delete("/knowledge-base/queries")
async def delete_query(category: str, question: str, cypher: str):
    """Delete a query example from a category."""
    try:
        query_collection = get_query_examples_collection()
        
        # Find the category document
        category_doc = query_collection.find_one({"category_name": category})
        
        if not category_doc:
            raise HTTPException(status_code=404, detail="Category not found")
        
        # Remove the query from examples array
        result = query_collection.update_one(
            {"category_name": category},
            {"$pull": {"examples": {"question": question, "cypher": cypher}}}
        )
        
        if result.modified_count == 0:
            raise HTTPException(status_code=404, detail="Query not found")
        
        # Sync deletion to Neo4j vector store
        try:
            deleted = delete_example_from_neo4j(question=question)
            if not deleted:
                print(f"Warning: Query '{question}' not found in Neo4j (may have been already deleted)")
        except Exception as neo4j_error:
            # Log error but don't fail the request - MongoDB deletion succeeded
            print(f"Warning: Failed to delete from Neo4j: {neo4j_error}")
            # Optionally, you could raise an error here if you want strict consistency
        
        return {"message": "Query deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete query: {str(e)}")
