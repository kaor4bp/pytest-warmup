from __future__ import annotations

import pytest

from tests.support.demo_domain import FacilityPlan, InventoryPlan, ProgramPlan
from pytest_warmup import warmup_param

facility = FacilityPlan("facility")
program = ProgramPlan("program")
inventory = InventoryPlan("inventory")

facility_de = facility.require(
    country="DE",
    id="facility_de",
)
program_main = program.require(
    program_profile="MAIN",
    facility=facility_de,
    id="program_main",
)
products_alpha = inventory.require(
    qty=10,
    upc="123",
    id="products_alpha",
    program=program_main,
)
products_beta = inventory.require(
    qty=20,
    upc="456",
    id="products_beta",
    program=program_main,
    is_per_test=True,
)

SEEN_SHARED_BATCH_IDS: list[str] = []
SEEN_PER_TEST_BATCH_IDS: list[str] = []


@pytest.fixture(scope="module")
def prepare_data(warmup_mgr):
    return warmup_mgr.use(facility, program, inventory).prepare()


@pytest.fixture
@warmup_param("products", products_alpha)
def alpha_products(prepare_data, products):
    del prepare_data
    return products


def test_fixture_injection_first(alpha_products):
    SEEN_SHARED_BATCH_IDS.append(alpha_products["batch_id"])
    assert alpha_products["program_id"].startswith("program-")
    assert alpha_products["qty"] == 10


def test_fixture_injection_second(alpha_products):
    SEEN_SHARED_BATCH_IDS.append(alpha_products["batch_id"])
    assert SEEN_SHARED_BATCH_IDS == [SEEN_SHARED_BATCH_IDS[0], SEEN_SHARED_BATCH_IDS[0]]


@warmup_param("products", products_beta)
@pytest.mark.parametrize("label", ["one", "two"])
def test_direct_test_injection(prepare_data, products, label):
    del prepare_data, label
    SEEN_PER_TEST_BATCH_IDS.append(products["batch_id"])
    assert products["qty"] == 20
    assert products["program_id"].startswith("program-")


def test_per_test_distribution_created_two_runtime_instances():
    assert len(SEEN_PER_TEST_BATCH_IDS) == 2
    assert len(set(SEEN_PER_TEST_BATCH_IDS)) == 2
    assert facility.api.create_facility_calls == 1
    assert program.api.create_program_calls == 1
    assert inventory.api.create_products_calls == 3
