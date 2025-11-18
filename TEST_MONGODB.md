# Testing MongoDB Knowledge Base Integration

## Step 1: Test MongoDB Connection

First, verify that you can connect to your MongoDB instance:

```bash
source venv/bin/activate
python -c "from backend.app.services.mongodb import get_database; db = get_database(); print('✓ Connected! Collections:', db.list_collection_names())"
```

Expected output:
```
✓ Connected! Collections: []
```
(Empty list is fine if collections don't exist yet)

## Step 2: Run Migration

Migrate data from JSON files to MongoDB:

```bash
source venv/bin/activate
python -m backend.app.services.migrate_to_mongodb
```

Expected output:
```
Starting migration from JSON to MongoDB...
--------------------------------------------------

1. Migrating categories...
Migrated category: Node summary & attribute distributions
Migrated category: Content exposure by theme and topic
...

2. Migrating query examples...
Migrated category 'Content exposure by theme and topic' with 8 examples
Migrated category 'Exposure-paths from influencers to youth' with 9 examples
...

--------------------------------------------------
Migration completed successfully!
```

## Step 3: Verify Data in MongoDB

Check that collections were created and have data:

```bash
source venv/bin/activate
python -c "
from backend.app.services.mongodb import get_database
db = get_database()
print('Collections:', db.list_collection_names())
print('\nCategories count:', db.ai_query_categories.count_documents({}))
print('Query examples categories:', db.ai_query_examples.count_documents({}))
"
```

## Step 4: Test Backend API

### Start Backend (if not running):

```bash
source venv/bin/activate
uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000
```

### Test Categories Endpoint:

```bash
curl http://localhost:8000/api/knowledge-base/categories | python -m json.tool | head -20
```

Expected: JSON array of categories

### Test Queries Endpoint:

```bash
curl "http://localhost:8000/api/knowledge-base/queries?category=Content%20exposure%20by%20theme%20and%20topic" | python -m json.tool | head -30
```

Expected: JSON array of query examples for that category

### Test Add Query:

```bash
curl -X POST http://localhost:8000/api/knowledge-base/queries \
  -H "Content-Type: application/json" \
  -d '{
    "category_name": "Content exposure by theme and topic",
    "question": "Test question?",
    "cypher": "MATCH (n) RETURN n LIMIT 1"
  }' | python -m json.tool
```

Expected: `{"message": "Query added successfully", "example": {...}}`

### Test Delete Query:

```bash
curl -X DELETE "http://localhost:8000/api/knowledge-base/queries?category=Content%20exposure%20by%20theme%20and%20topic&question=Test%20question?&cypher=MATCH%20(n)%20RETURN%20n%20LIMIT%201" | python -m json.tool
```

Expected: `{"message": "Query deleted successfully"}`

## Step 5: Test Frontend

1. **Start frontend** (if not running):
   ```bash
   cd frontend
   npm run dev
   ```

2. **Open browser**: http://localhost:3002

3. **Navigate to Knowledge Base**:
   - Click "Knowledge Base" in the left sidebar
   - You should see all categories displayed as boxes

4. **Test viewing queries**:
   - Click on any category
   - You should see all queries for that category

5. **Test adding a query**:
   - Click "Add Query" button
   - Fill in question and Cypher query
   - Submit
   - Query should appear in the list

6. **Test deleting a query**:
   - Click the trash icon on any query
   - Confirm deletion
   - Query should be removed

## Step 6: Verify in MongoDB

Check that data persists in MongoDB:

```bash
source venv/bin/activate
python -c "
from backend.app.services.mongodb import get_query_examples_collection, get_categories_collection

# Check categories
categories = get_categories_collection()
print('Total categories:', categories.count_documents({}))
print('Sample category:', categories.find_one({}, {'_id': 0}))

# Check query examples
queries = get_query_examples_collection()
print('\nTotal query example categories:', queries.count_documents({}))
sample = queries.find_one({}, {'_id': 0})
if sample:
    print('Sample category:', sample['category_name'])
    print('Number of examples:', len(sample.get('examples', [])))
"
```

## Troubleshooting

### Connection Error
```
ValueError: MONGODB_URI environment variable is not set
```
**Solution**: Check your `.env` file has `MONGODB_URI` set

### Authentication Error
```
pymongo.errors.OperationFailure: Authentication failed
```
**Solution**: Verify your MongoDB credentials in `MONGODB_URI`

### Collection Not Found
If collections don't exist, they'll be created automatically on first write operation.

### Data Not Showing
- Restart backend after migration
- Check browser console for errors
- Verify backend logs for MongoDB connection issues

