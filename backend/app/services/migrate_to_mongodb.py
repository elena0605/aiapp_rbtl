"""Migration script to move query examples from JSON to MongoDB and sync to Neo4j."""

import json
from pathlib import Path
from typing import List, Dict, Any
from backend.app.services.mongodb import (
    get_query_examples_collection,
    get_categories_collection
)
from backend.app.services.neo4j_sync import (
    add_example_to_neo4j,
    ensure_vector_index
)

# Paths to JSON files
ROOT = Path(__file__).resolve().parents[3]
QUERY_EXAMPLES_PATH = ROOT / "ai" / "fewshots" / "query_examples.json"
GRAPH_CATEGORIES_PATH = ROOT / "ai" / "fewshots" / "graph_categories.json"


def load_json_file(file_path: Path) -> Any:
    """Load JSON file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: {file_path} not found")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing {file_path}: {e}")
        return None


def migrate_categories():
    """Migrate categories from JSON to MongoDB."""
    categories_data = load_json_file(GRAPH_CATEGORIES_PATH)
    if not categories_data:
        print("No categories data to migrate")
        return
    
    categories = categories_data.get('categories', [])
    if not categories:
        print("No categories found in JSON file")
        return
    
    categories_collection = get_categories_collection()
    
    # Clear existing categories (optional - comment out if you want to keep existing)
    # Note: This will clear the ai_query_categories collection
    # categories_collection.delete_many({})
    
    # Insert categories
    for category in categories:
        # Check if category already exists
        existing = categories_collection.find_one({"category_name": category["category_name"]})
        if not existing:
            categories_collection.insert_one(category)
            print(f"Migrated category: {category['category_name']}")
        else:
            print(f"Category already exists: {category['category_name']}")


def migrate_query_examples():
    """Migrate query examples from JSON to MongoDB."""
    query_examples_data = load_json_file(QUERY_EXAMPLES_PATH)
    if not query_examples_data:
        print("No query examples data to migrate")
        return
    
    if not isinstance(query_examples_data, list):
        print("Invalid format: query_examples.json should be a list")
        return
    
    query_collection = get_query_examples_collection()
    
    # Clear existing query examples (optional - comment out if you want to keep existing)
    # Note: This will clear the ai_query_examples collection
    # query_collection.delete_many({})
    
    # Insert query examples
    for category_data in query_examples_data:
        category_name = category_data.get('category_name')
        examples = category_data.get('examples', [])
        
        if not category_name:
            print("Skipping entry without category_name")
            continue
        
        # Check if category already exists
        existing = query_collection.find_one({"category_name": category_name})
        
        if existing:
            # Update existing category - merge examples
            existing_examples = existing.get('examples', [])
            # Only add examples that don't already exist (by question + cypher)
            existing_pairs = {(ex.get('question'), ex.get('cypher')) for ex in existing_examples}
            
            new_examples = [
                ex for ex in examples
                if (ex.get('question'), ex.get('cypher')) not in existing_pairs
            ]
            
            if new_examples:
                query_collection.update_one(
                    {"category_name": category_name},
                    {"$push": {"examples": {"$each": new_examples}}}
                )
                print(f"Updated category '{category_name}' with {len(new_examples)} new examples")
            else:
                print(f"Category '{category_name}' already has all examples")
        else:
            # Create new category document
            query_collection.insert_one({
                "category_name": category_name,
                "examples": examples
            })
            print(f"Migrated category '{category_name}' with {len(examples)} examples")


def sync_to_neo4j():
    """Sync all query examples from MongoDB to Neo4j."""
    print("\n3. Syncing query examples to Neo4j vector store...")
    try:
        ensure_vector_index()
        
        query_collection = get_query_examples_collection()
        categories_collection = get_categories_collection()
        all_categories = query_collection.find({})
        
        # Build category descriptions map
        category_descriptions = {}
        for cat in categories_collection.find({}):
            category_descriptions[cat.get("category_name")] = cat.get("category_description", "")
        
        total_synced = 0
        for category_doc in all_categories:
            category_name = category_doc.get("category_name")
            examples = category_doc.get("examples", [])
            category_description = category_descriptions.get(category_name, "")
            
            for example in examples:
                try:
                    add_example_to_neo4j(
                        question=example.get("question"),
                        cypher=example.get("cypher"),
                        category_name=category_name,
                        added_at=example.get("added_at"),
                        category_description=category_description,
                        created_by=example.get("created_by")
                    )
                    total_synced += 1
                except Exception as e:
                    print(f"  ⚠️  Failed to sync example '{example.get('question', '')[:50]}...': {e}")
        
        print(f"  ✓ Synced {total_synced} examples to Neo4j")
    except Exception as e:
        print(f"  ⚠️  Warning: Failed to sync to Neo4j: {e}")
        print("  Note: MongoDB migration succeeded, but Neo4j sync failed.")


def main():
    """Run migration."""
    print("Starting migration from JSON to MongoDB...")
    print("-" * 50)
    
    try:
        print("\n1. Migrating categories...")
        migrate_categories()
        
        print("\n2. Migrating query examples...")
        migrate_query_examples()
        
        print("\n3. Syncing to Neo4j vector store...")
        sync_to_neo4j()
        
        print("\n" + "-" * 50)
        print("Migration completed successfully!")
        print("✓ Data migrated to MongoDB")
        print("✓ Data synced to Neo4j vector store")
        
    except Exception as e:
        print(f"\nError during migration: {e}")
        raise


if __name__ == "__main__":
    main()

