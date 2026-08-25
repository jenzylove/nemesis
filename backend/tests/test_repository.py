import pytest

from app.repository import FirestoreCaseRepository


class _Document:
    async def get(self):
        return None


class _Collection:
    def document(self, _name):
        return _Document()


class _Client:
    def collection(self, _name):
        return _Collection()



@pytest.mark.asyncio
async def test_default_firestore_database_uses_client_default(monkeypatch):
    captured = {}

    def client_factory(**kwargs):
        captured.update(kwargs)
        return _Client()

    from google.cloud import firestore

    monkeypatch.setattr(firestore, "AsyncClient", client_factory)
    repository = FirestoreCaseRepository("nemesis-test", "(default)")
    await repository.initialize()

    assert captured == {"project": "nemesis-test"}


@pytest.mark.asyncio
async def test_url_encoded_default_firestore_database_uses_client_default(monkeypatch):
    captured = {}

    def client_factory(**kwargs):
        captured.update(kwargs)
        return _Client()

    from google.cloud import firestore

    monkeypatch.setattr(firestore, "AsyncClient", client_factory)
    repository = FirestoreCaseRepository("nemesis-test", "%28default%29")
    await repository.initialize()

    assert captured == {"project": "nemesis-test"}


@pytest.mark.asyncio
async def test_named_firestore_database_is_forwarded(monkeypatch):
    captured = {}

    def client_factory(**kwargs):
        captured.update(kwargs)
        return _Client()

    from google.cloud import firestore

    monkeypatch.setattr(firestore, "AsyncClient", client_factory)
    repository = FirestoreCaseRepository("nemesis-test", "investigations")
    await repository.initialize()

    assert captured == {"project": "nemesis-test", "database": "investigations"}
