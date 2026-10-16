"""
Pytest configuration and fixtures.

Supports both:
1. Mocked Tiled for unit tests (no auth needed)
2. Real Tiled with cached tokens for integration tests
"""

import pytest
import os
from unittest.mock import MagicMock
from pathlib import Path


def pytest_addoption(parser):
    """Add custom pytest command-line options."""
    parser.addoption(
        "--use-real-tiled",
        action="store_true",
        default=False,
        help="Use real Tiled server with cached credentials (integration tests)"
    )
    parser.addoption(
        "--tiled-profile",
        action="store",
        default="cms_migration",
        help="Tiled profile to use for integration tests"
    )


@pytest.fixture
def use_real_tiled(request):
    """Flag indicating whether to use real Tiled."""
    return request.config.getoption("--use-real-tiled")


@pytest.fixture
def tiled_profile(request):
    """Tiled profile name for integration tests."""
    return request.config.getoption("--tiled-profile")


@pytest.fixture
def tiled_client(use_real_tiled, tiled_profile):
    """
    Get a Tiled client - mocked by default, real if requested.

    Usage in tests:
        def test_something(tiled_client):
            catalog = tiled_client.get_catalog()
            # Works with both mock and real!

    To run with real Tiled (requires prior login):
        pytest --use-real-tiled
        pytest --use-real-tiled --tiled-profile=cms_migration
    """
    if use_real_tiled:
        # Use real Tiled with cached tokens
        from sciview.sources.tiled_client import tiled_manager

        # Attempt to use cached tokens
        client = tiled_manager.get_or_create_client(
            tiled_profile,
            interactive_fallback=False  # Don't prompt for login in tests!
        )

        if client is None:
            pytest.skip(
                f"Real Tiled requested but authentication failed. "
                f"Run 'pixi run python main.py' and login to '{tiled_profile}' first, "
                f"then retry tests."
            )

        return tiled_manager

    else:
        # Use mock (default)
        from tests.mocks.tiled_mocks import create_mock_tiled_catalog, MockTiledContext

        mock_manager = MagicMock()
        mock_manager.get_or_load_catalog.return_value = create_mock_tiled_catalog()

        mock_context = MockTiledContext()
        mock_manager.get_or_create_client.return_value = MagicMock(context=mock_context)

        return mock_manager


@pytest.fixture
def tiled_catalog(tiled_client, tiled_profile):
    """
    Get a Tiled catalog - mocked by default, real if requested.

    This is the most common fixture you'll use in tests.
    """
    return tiled_client.get_or_load_catalog(tiled_profile)


# Mark for integration tests
def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires real Tiled with cached auth)"
    )
    config.addinivalue_line(
        "markers",
        "requires_auth: mark test as requiring authenticated Tiled connection"
    )
