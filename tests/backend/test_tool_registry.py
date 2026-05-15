from app.tools.registry import registry


def test_registry_has_required_tools():
    names = registry.list_tools()
    assert "calculator" in names
    assert "file_read" in names
    assert "document_search" in names
