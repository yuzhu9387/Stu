import pytest
from app.connectors.base import BaseConnector, SyncResult

def test_sync_result():
    r = SyncResult(connector="test", items_synced=5, items_created=3, items_updated=2)
    assert r.items_synced == 5

def test_abstract():
    with pytest.raises(TypeError):
        BaseConnector()
