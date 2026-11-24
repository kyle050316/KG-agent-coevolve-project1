import pytest

from kgcoevo.kb.executor import Executor
from kgcoevo.kb.store import KBStore
from tests.fixtures.mini import make_kb


@pytest.fixture(scope="session")
def store() -> KBStore:
    return KBStore(make_kb(mirrors=True))


@pytest.fixture(scope="session")
def executor(store) -> Executor:
    return Executor.from_store(store)
