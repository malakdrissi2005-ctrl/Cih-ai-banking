import pytest


@pytest.fixture
def chroma_persist_dir(tmp_path):
    return str(tmp_path / "chroma_test")


@pytest.fixture
def faq_json_path(tmp_path):
    return tmp_path / "faq_docs" / "faq.json"
