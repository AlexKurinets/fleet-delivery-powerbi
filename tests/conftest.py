"""Fixtures. Database tests need a SQL Server (FLEETBI_TEST_SQL_HOST/PORT/PASSWORD); CI runs one as a
service container. Each loaded fixture uses its own pair of databases."""

import pytest

from fleetbi import synth
from helpers import Loaded, load


@pytest.fixture(scope="session")
def loaded(tmp_path_factory) -> Loaded:
    return load(tmp_path_factory.mktemp("base"), "t")


@pytest.fixture(scope="session")
def full_world() -> synth.World:
    return synth.World()
