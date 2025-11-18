# MongoDB Migration Guide

This guide explains how to migrate the Knowledge Base from JSON files to MongoDB.

## Prerequisites

1. **MongoDB Cloud Instance**: You need a MongoDB Atlas account or self-hosted MongoDB instance
2. **Connection String**: Get your MongoDB connection string from your MongoDB provider

## Step 1: Install Dependencies

```bash
source venv/bin/activate
pip install -r backend/requirements.txt
```

This will install `pymongo>=4.6.0` which is required for MongoDB operations.

## Step 2: Configure MongoDB Connection

Ensure your `.env` file has the following variables (you likely already have these):

```bash
# MongoDB Configuration (Azure CosmosDB)
MONGODB_URI=mongodb://rbl:password@rbl.mongo.cosmos.azure.com:10255/rbl?ssl=true&retrywrites=false&replicaSet=globaldb&maxIdleTimeMS=120000&appName=@rbl@
MONGODB_DB=rbl  # Database name
```

**Note:** The code supports both `MONGODB_DB` and `MONGODB_DATABASE` environment variables. If neither is set, it defaults to `graphrag`.

## Step 3: Run Migration

Run the migration script to move data from JSON files to MongoDB:

```bash
source venv/bin/activate
python -m backend.app.services.migrate_to_mongodb
```

This will:
- Create a `categories` collection with all category definitions
- Create a `query_examples` collection with all query examples organized by category
- Preserve existing data (won't duplicate if already exists)

## Step 4: Verify Migration

After migration, restart your backend server:

```bash
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

Then test the Knowledge Base API:
- Open http://localhost:8000/docs
- Test the `/api/knowledge-base/categories` endpoint
- Test the `/api/knowledge-base/queries?category=<category_name>` endpoint

## MongoDB Collections Structure

### `ai_query_categories` Collection
```json
{
  "category_name": "Content exposure by theme and topic",
  "category_description": "Queries linking videos to topics/tags..."
}
```

### `ai_query_examples` Collection
```json
{
  "category_name": "Content exposure by theme and topic",
  "examples": [
    {
      "question": "How many YouTube videos are associated with gaming topics?",
      "cypher": "MATCH (v:YouTubeVideo)...",
      "added_at": "2025-11-17T17:34:35.142676"
    }
  ]
}
```

## Notes

- The migration script is **idempotent** - you can run it multiple times safely
- Existing data in MongoDB won't be overwritten (only new items are added)
- The JSON files remain unchanged - they serve as backup
- All CRUD operations now use MongoDB instead of JSON files

## Troubleshooting

### Connection Error
- Verify `MONGODB_URI` is correct in `.env`
- Check that your IP is whitelisted in MongoDB Atlas (if using Atlas)
- Ensure your MongoDB user has read/write permissions

### Migration Fails
- Check that JSON files exist at `ai/fewshots/query_examples.json` and `ai/fewshots/graph_categories.json`
- Verify the JSON files are valid JSON
- Check MongoDB connection is working: `python -c "from backend.app.services.mongodb import get_database; print(get_database().list_collection_names())"`

