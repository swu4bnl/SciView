# Test Fixtures

This directory contains captured data structures from real Tiled sources for testing purposes.

## Capturing Fixtures

To create new fixtures:

```python
# Run once when authenticated to real Tiled
from sciview.sources.tiled_client import tiled_manager
import json

# Get real catalog
catalog = tiled_manager.get_or_load_catalog('cms_migration')

# Capture structure (no credentials, just data shape)
fixture = {
    'metadata': dict(catalog.metadata),
    'structure': {
        'keys': list(catalog.keys())[:5],  # Sample keys
        'specs': catalog.specs,
    }
}

# Save as fixture
with open('tests/fixtures/tiled_catalog_structure.json', 'w') as f:
    json.dump(fixture, f, indent=2, default=str)
```

## Using Fixtures

```python
# In tests
import json

with open('tests/fixtures/tiled_catalog_structure.json') as f:
    fixture = json.load(f)
```

## What to Capture

- ✅ Data structure (keys, metadata schema, specs)
- ✅ Sample run metadata
- ✅ Example stream updates
- ❌ API keys or credentials
- ❌ Personal/sensitive data
