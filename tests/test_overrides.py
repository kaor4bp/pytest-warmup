from __future__ import annotations

from pathlib import Path

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
)
program_per_test = program.require(
    program_profile="SECONDARY",
    facility=facility_de,
    id="program_per_test",
    is_per_test=True,
)
products_gamma = inventory.require(
    qty=30,
    upc="789",
    id="products_gamma",
    program=program_per_test,
)


@pytest.fixture(scope="module")
def prepare_data(warmup_mgr):
    snapshot_file = Path(__file__).with_name("snapshots").joinpath("test_overrides.snapshot.json")
    return warmup_mgr.use(facility, program, inventory).prepare(snapshot_file=snapshot_file)


@pytest.fixture
@warmup_param("products", products_alpha)
def alpha_products(prepare_data, products):
    del prepare_data
    return products


@pytest.fixture
@warmup_param("products", products_beta)
def beta_products(prepare_data, products):
    del prepare_data
    return products


SEEN_GAMMA_BATCHES: dict[str, str] = {}


def test_alpha_override(alpha_products):
    assert alpha_products["batch_id"] == "debug-alpha"
    assert alpha_products["program_id"] == "debug-program-1"
    assert program.prepare_calls == 1
    assert program.api.create_program_calls == 2
    assert all(":SECONDARY:" in item for item in program.api.trace)


def test_shared_override_cuts_program_prepare_and_beta_uses_it(beta_products):
    assert beta_products["program_id"] == "debug-program-1"
    assert beta_products["batch_id"].startswith("products-")
    assert program.prepare_calls == 1
    assert inventory.prepare_calls == 1
    assert facility.api.create_facility_calls == 1
    assert program.api.create_program_calls == 2
    assert inventory.api.create_products_calls == 3


@warmup_param("products", products_gamma)
@pytest.mark.parametrize("label", ["one", "two"])
def test_inherited_per_test_override_stays_local(prepare_data, products, label):
    del prepare_data
    SEEN_GAMMA_BATCHES[label] = str(products["batch_id"])
    if label == "one":
        assert products["batch_id"] == "debug-gamma-one"
        assert products["program_id"] == "program-debug-one"
    else:
        assert products["batch_id"].startswith("products-")
        assert products["program_id"].startswith("program-")


def test_inherited_per_test_override_keeps_tests_addressing_only():
    assert SEEN_GAMMA_BATCHES["one"] == "debug-gamma-one"
    assert SEEN_GAMMA_BATCHES["two"].startswith("products-")
    assert program.api.create_program_calls == 2
    assert inventory.api.create_products_calls == 3
