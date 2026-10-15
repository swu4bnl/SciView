"""
Tests for Tiled integration.

These tests work with:
1. Mock Tiled (default) - no authentication needed
2. Real Tiled (--use-real-tiled) - uses cached tokens from prior login

Usage:
    # Run experimental tests with mocks
    pixi run test-experimental tests/test_tiled_integration.py

    # Run experimental tests with real Tiled (requires prior login)
    pixi run test-experimental tests/test_tiled_integration.py --use-real-tiled

    # Run only experimental integration tests
    pixi run test-experimental -m "experimental and integration" --use-real-tiled
"""

import pytest
from sciview.sources.tiled_source import TiledScanSummary

pytestmark = pytest.mark.experimental


class TestTiledCatalogAccess:
    """Test accessing Tiled catalog (works with mock or real)."""

    def test_get_catalog(self, tiled_catalog):
        """Test getting a catalog."""
        assert tiled_catalog is not None

    def test_catalog_has_keys(self, tiled_catalog):
        """Test that catalog contains runs."""
        keys = list(tiled_catalog.keys())
        assert len(keys) > 0

    def test_access_run_metadata(self, tiled_catalog):
        """Test accessing run metadata."""
        # Get first run
        first_key = list(tiled_catalog.keys())[0]
        run = tiled_catalog[first_key]

        # Check structure
        assert hasattr(run, 'metadata')
        assert 'start' in run.metadata

    @pytest.mark.integration
    @pytest.mark.requires_auth
    def test_real_cms_data_structure(self, tiled_catalog):
        """
        Integration test: Verify real CMS data structure.

        Only runs with --use-real-tiled flag.
        """
        # This test uses REAL data from cached auth
        # No mock - actual Tiled connection!

        keys = list(tiled_catalog.keys())
        assert len(keys) > 0, "CMS catalog should have runs"

        # Get a real run
        run = tiled_catalog[keys[0]]

        # Verify real CMS structure
        assert 'start' in run.metadata
        start_doc = run.metadata['start']

        # These fields should exist in real CMS data
        assert 'scan_id' in start_doc
        assert 'uid' in start_doc


class TestTiledLiveMonitor:
    """Test Tiled live monitoring (works with mock or real)."""

    def test_create_monitor(self, tiled_profile):
        """Test creating a TiledLiveMonitor."""
        from sciview.sources.tiled_stream import TiledLiveMonitor

        monitor = TiledLiveMonitor(tiled_profile)
        assert monitor is not None
        assert not monitor.is_running

    @pytest.mark.integration
    def test_monitor_with_real_catalog(self, tiled_catalog, tiled_profile):
        """
        Integration test: Monitor with real catalog.

        Uses cached tokens - no manual login required!
        """
        from sciview.sources.tiled_stream import TiledLiveMonitor

        monitor = TiledLiveMonitor(tiled_profile, catalog=tiled_catalog)

        # Start monitoring
        events_received = []

        def callback(event):
            events_received.append(event)

        # This would use real Tiled with cached auth!
        # (Skipped in CI where no auth is available)
        try:
            monitor.start(callback)
            assert monitor.is_running

            # Stop
            monitor.stop()
            assert not monitor.is_running
        except RuntimeError as e:
            if "authentication" in str(e).lower():
                pytest.skip("No cached authentication available")
            raise


class TestTiledAPIKeyManagement:
    """Test API key lifecycle."""

    def test_api_key_creation_mock(self, tiled_client):
        """Test API key creation with mock."""
        client = tiled_client.get_or_create_client('test')

        if hasattr(client, 'context'):
            context = client.context

            # With mock, this doesn't hit real Tiled
            key_info = context.create_api_key(expires_in=60, note="test")

            assert 'secret' in key_info
            assert 'first_eight' in key_info

            # Clean up (mock)
            context.revoke_api_key(key_info['first_eight'])

    @pytest.mark.integration
    @pytest.mark.requires_auth
    def test_api_key_lifecycle_real(self, tiled_client, use_real_tiled):
        """
        Integration test: Real API key lifecycle.

        Uses cached tokens from prior login.
        """
        if not use_real_tiled:
            pytest.skip("Real Tiled not requested")

        client = tiled_client.get_or_create_client('cms_migration')
        context = client.context

        # Create real API key using cached auth
        key_info = context.create_api_key(expires_in=60, note="pytest-test")

        try:
            assert 'secret' in key_info
            assert 'first_eight' in key_info

            # Verify it was created
            response = context.http_client.get(
                "https://tiled.nsls2.bnl.gov/api/v1/auth/whoami"
            )
            if response.status_code == 200:
                keys = response.json().get('api_keys', [])
                key_ids = [k['first_eight'] for k in keys]
                assert key_info['first_eight'] in key_ids

        finally:
            # Always clean up the test key
            context.revoke_api_key(key_info['first_eight'])
