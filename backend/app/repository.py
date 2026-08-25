from copy import deepcopy

from .models import InvestigationCase


class CaseRepository:
    async def initialize(self) -> None: ...
    async def save(self, case: InvestigationCase) -> InvestigationCase:
        raise NotImplementedError
    async def get(self, case_id: str) -> InvestigationCase | None:
        raise NotImplementedError
    async def list_by_owner(self, owner_user_id: str) -> list[InvestigationCase]:
        raise NotImplementedError


class InMemoryCaseRepository(CaseRepository):
    def __init__(self):
        self._cases = {}

    async def initialize(self) -> None:
        return None

    async def save(self, case):
        self._cases[case.id] = deepcopy(case.model_dump(mode="json"))
        return case

    async def get(self, case_id):
        value = self._cases.get(case_id)
        return InvestigationCase.model_validate(deepcopy(value)) if value else None

    async def list_by_owner(self, owner_user_id: str):
        cases = [
            InvestigationCase.model_validate(deepcopy(value))
            for value in self._cases.values()
            if value.get("owner_user_id") == owner_user_id
        ]
        return sorted(cases, key=lambda case: case.updated_at, reverse=True)


class FirestoreCaseRepository(CaseRepository):
    def __init__(self, project_id: str, database: str = "(default)", collection: str = "cases"):
        self.project_id, self.database, self.collection, self.client = project_id, database, collection, None

    async def initialize(self):
        from google.cloud import firestore

        client_options = {"project": self.project_id}
        if self.database not in {"(default)", "%28default%29"}:
            client_options["database"] = self.database
        self.client = firestore.AsyncClient(**client_options)
        await self.client.collection("_nemesis_health").document("runtime").get()

    async def save(self, case):
        if self.client is None:
            raise RuntimeError("Firestore repository is not initialized")
        await self.client.collection(self.collection).document(case.id).set(case.model_dump(mode="python"))
        return case

    async def get(self, case_id):
        if self.client is None:
            raise RuntimeError("Firestore repository is not initialized")
        snap = await self.client.collection(self.collection).document(case_id).get()
        return InvestigationCase.model_validate(snap.to_dict()) if snap.exists else None

    async def list_by_owner(self, owner_user_id: str):
        if self.client is None:
            raise RuntimeError("Firestore repository is not initialized")
        query = self.client.collection(self.collection).where("owner_user_id", "==", owner_user_id)
        cases = [InvestigationCase.model_validate(snap.to_dict()) async for snap in query.stream()]
        return sorted(cases, key=lambda case: case.updated_at, reverse=True)

    async def close(self):
        if self.client is not None:
            self.client.close()


def repository_from_settings(settings):
    return (
        FirestoreCaseRepository(
            settings.firestore_project_id,
            settings.firestore_database,
            settings.firestore_cases_collection,
        )
        if settings.firestore_project_id
        else InMemoryCaseRepository()
    )
