"""
Mock Tiled objects that match real data structures.

These mocks are based on actual Tiled catalog structures from NSLS-II,
but don't require authentication to use.
"""

from unittest.mock import MagicMock
from typing import Any, Dict, List
import json
from pathlib import Path


def load_fixture(name: str) -> Dict[str, Any]:
    """Load a test fixture by name."""
    fixture_path = Path(__file__).parent.parent / 'fixtures' / f'{name}.json'
    with open(fixture_path) as f:
        return json.load(f)


def create_mock_tiled_run(scan_id: int = 12345, uid: str = "test-uid-123") -> MagicMock:
    """
    Create a mock Tiled BlueskyRun with realistic structure.

    Based on real CMS beamline data structure.
    """
    fixture = load_fixture('sample_tiled_scan')

    mock_run = MagicMock()
    mock_run.metadata = {
        'start': {
            'uid': uid,
            'scan_id': scan_id,
            'plan_name': 'count',
            'detectors': ['saxs_detector'],
            'time': 1696723200.0,
            'beamline_id': 'CMS (11-BM)',
        }
    }

    # Mock data access
    mock_primary = MagicMock()
    mock_primary.read.return_value = {
        'saxs_detector': MagicMock(shape=(1, 1043, 981))
    }

    mock_run.__getitem__.return_value = mock_primary
    mock_run.keys.return_value = ['primary']

    return mock_run


def create_mock_tiled_catalog(profile_name: str = 'test') -> MagicMock:
    """
    Create a mock Tiled catalog with realistic structure.

    Includes sample runs with real-like metadata structure.
    """
    mock_catalog = MagicMock()

    # Create some sample runs
    runs = {
        'run-001': create_mock_tiled_run(scan_id=12345, uid='run-001'),
        'run-002': create_mock_tiled_run(scan_id=12346, uid='run-002'),
        'run-003': create_mock_tiled_run(scan_id=12347, uid='run-003'),
    }

    # Mock catalog behavior
    mock_catalog.__getitem__.side_effect = lambda key: runs.get(key)
    mock_catalog.keys.return_value = list(runs.keys())
    mock_catalog.items.return_value = list(runs.items())
    mock_catalog.values.return_value = list(runs.values())
    mock_catalog.__len__.return_value = len(runs)

    # Mock metadata
    mock_catalog.metadata = {
        'beamline': 'CMS',
        'facility': 'NSLS-II'
    }

    # Mock context for auth
    mock_context = MagicMock()
    mock_context.authenticated = True
    mock_catalog.context = mock_context

    return mock_catalog


def create_mock_stream_update(run_uid: str = 'test-run-123') -> MagicMock:
    """
    Create a mock Tiled stream update message.

    Based on real bluesky-tiled-plugins stream format.
    """
    mock_update = MagicMock()
    mock_update.run_uid = run_uid
    mock_update.stream_name = 'primary'
    mock_update.seq_num = 1

    return mock_update


class MockTiledContext:
    """
    Mock Tiled context that behaves like real one but without authentication.

    Usage:
        context = MockTiledContext()
        # No authentication needed!
        context.authenticated  # Returns True
    """

    def __init__(self):
        self.authenticated = True
        self._api_keys: List[Dict[str, str]] = []

    def create_api_key(self, expires_in: int = 60, note: str = "") -> Dict[str, str]:
        """Mock API key creation."""
        key_info = {
            'secret': f'mock-key-{len(self._api_keys)}',
            'first_eight': f'mockkey{len(self._api_keys):01d}',
            'expires_in': expires_in,
            'note': note
        }
        self._api_keys.append(key_info)
        return key_info

    def revoke_api_key(self, first_eight: str) -> None:
        """Mock API key revocation."""
        self._api_keys = [k for k in self._api_keys if k['first_eight'] != first_eight]

    def whoami(self) -> Dict[str, Any]:
        """Mock whoami response."""
        return {
            'uuid': 'test-user-uuid',
            'identities': [{'id': 'test-user'}],
            'api_keys': self._api_keys
        }


# Example usage in tests:
def example_test_with_real_structure():
    """
    Example: Test using mocks with real data structure.
    """
    # Get a catalog with real-like structure
    catalog = create_mock_tiled_catalog('cms_migration')

    # Access it like real Tiled
    run = catalog['run-001']
    assert run.metadata['start']['scan_id'] == 12345

    # Get data with real-like shape
    data = run['primary'].read()
    assert 'saxs_detector' in data

    # No authentication required!
