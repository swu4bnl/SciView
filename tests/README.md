# SciView Tests

## Running Tests

### Required Test Suite

```bash
pixi run test

# Run specific test file
pixi run python -m pytest tests/test_image_viewer.py

# Run with verbose output
pixi run python -m pytest -v
```

The required suite does not need authentication or network access. Tests marked
`experimental` are excluded until their product behavior is defined.

### Experimental Tiled Tests

```bash
# Run experimental tests with mocks
pixi run test-experimental

# Run experimental integration tests after authentication
pixi run test-experimental -m "experimental and integration" --use-real-tiled
```

---

## Testing with Real Tiled Data

### One-Time Setup: Login to Tiled

```bash
# Login once to cache your credentials
pixi run python main.py
# → Open SciView
# → Go to Tiled Browser tab
# → Click "Login" and authenticate
# → Close SciView
```

Your tokens are now cached at `~/.config/tiled/tokens`

### Run Tests with Real Tiled

```bash
# Use cached tokens - no manual login during tests!
pytest --use-real-tiled

# Use specific profile
pytest --use-real-tiled --tiled-profile=cms_migration

# Run only integration tests
pytest -m integration --use-real-tiled
```

**No re-authentication needed!** Tests reuse your cached tokens.

---

## Test Types

### Required Tests
- Test established product behavior.
- Do not use network access or live services.
- Run in CI.
```bash
pixi run test
```

### Experimental Tests
- Test behavior that is still being defined.
- Do not run in the required test suite.
- Use `@pytest.mark.experimental`.
```bash
pixi run test-experimental
```

---

## Common Scenarios

### Scenario 1: Quick Development
```bash
# Run required tests
pixi run test
```

### Scenario 2: Verify Against Real Data
```bash
# Login once (if not already)
pixi run python main.py  # Login via GUI

# Run experimental integration tests with real data
pixi run test-experimental -m "experimental and integration" --use-real-tiled
```

### Scenario 3: CI/CD

```bash
# CI runs mocked tests only (no auth available)
pixi run test
```

The `Installation` GitHub Actions workflow starts without Pixi on Windows, Linux, and macOS. It runs the platform launcher, verifies the installed environment, and then runs the mocked test suite.

Developers who already have Pixi can run the installation simulation locally:

```bash
pixi run test-installation
```

---

## Test Fixtures

### Available Fixtures

```python
def test_example(tiled_catalog):
    """Use tiled_catalog fixture - works with mock or real."""
    # Gets mock catalog by default
    # Gets real catalog with --use-real-tiled
    assert tiled_catalog is not None
```

**Main fixtures:**
- `tiled_client` - TiledClientManager (mock or real)
- `tiled_catalog` - Catalog object (mock or real)
- `tiled_profile` - Profile name for tests
- `use_real_tiled` - Boolean flag

### Fixture Behavior

| Fixture | Default (No Flags) | With --use-real-tiled |
|---------|-------------------|----------------------|
| `tiled_catalog` | Mock (fake data) | Real (uses cached tokens) |
| `tiled_client` | Mock manager | Real tiled_manager |

---

## Token Management

### Where Tokens Are Stored
```
~/.config/tiled/tokens  # Tiled's cache (cross-platform)
```

### Token Lifecycle
1. **Login once** via SciView GUI or `tiled_authenticate()`
2. **Tokens cached** automatically by Tiled
3. **Tests reuse** cached tokens (no re-auth)
4. **Tokens expire** after ~7 days (refresh tokens)
5. **Re-login** when tokens expire (SciView will prompt)

### Troubleshooting

**Error: "Authentication required"**
```bash
# Solution: Login once to cache tokens
pixi run python main.py
# → Login via Tiled Browser tab
```

**Error: "No cached authentication available"**
```bash
# Your tokens expired - login again
pixi run python main.py
```

**Want fresh start:**
```bash
# Clear cached tokens
rm ~/.config/tiled/tokens
# Login again
pixi run python main.py
```

---

## Writing New Tests

### Pattern 1: Works with Mock or Real
```python
def test_catalog_access(tiled_catalog):
    """This test works with both mock and real Tiled."""
    keys = list(tiled_catalog.keys())
    assert len(keys) > 0
    # ✓ Runs fast with mocks by default
    # ✓ Can verify with real data using --use-real-tiled
```

### Pattern 2: Integration Test Only
```python
@pytest.mark.integration
@pytest.mark.requires_auth
def test_real_cms_structure(tiled_catalog):
    """This test only runs with real Tiled."""
    # Access real CMS data
    run = tiled_catalog[list(tiled_catalog.keys())[0]]
    # Verify actual data structure
    assert 'beamline_id' in run.metadata['start']
```

### Pattern 3: Skip if No Auth
```python
def test_optional_real_tiled(tiled_client, use_real_tiled):
    """Test that adapts based on what's available."""
    if not use_real_tiled:
        pytest.skip("Skipping - real Tiled not requested")

    # Test with real Tiled
    client = tiled_client.get_or_create_client('cms_migration')
    # ...
```

---

## Best Practices

### ✅ DO:
- Write tests that work with mocks by default
- Use `--use-real-tiled` for integration testing
- Mark integration tests with `@pytest.mark.integration`
- Reuse cached tokens (no hardcoded credentials)
- Clean up any test API keys you create

### ❌ DON'T:
- Hardcode NSLS-II URLs in tests
- Commit credentials or API keys
- Require manual login during test run
- Skip cleanup of test resources
- Assume tests always have real Tiled access

---

## Summary

```bash
# Development and CI: Required tests
pixi run test

# Experimental tests with mocks
pixi run test-experimental

# Integration: Login once, test many times
pixi run python main.py
pixi run test-experimental -m "experimental and integration" --use-real-tiled
```
