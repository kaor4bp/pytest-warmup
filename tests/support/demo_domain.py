from __future__ import annotations

from pytest_warmup import WarmupPlan, WarmupRequirement
from pytest_warmup.core import PlanNode, RuntimeContext

from .fake_external_api import FakeExternalApi


class FacilityPlan(WarmupPlan):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.api = FakeExternalApi()
        self.prepare_calls = 0

    def require(
        self,
        *,
        country: str,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"country": country},
            dependencies={},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(
        self,
        nodes: list[PlanNode],
        runtime: RuntimeContext,
    ) -> None:
        self.prepare_calls += 1
        for node in nodes:
            country = str(node.payload["country"])
            runtime.set(node, self.api.create_facility(country=country))
            runtime.trace.append(f"facility_ready:{node.runtime_key}")


class ProgramPlan(WarmupPlan):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.api = FakeExternalApi()
        self.prepare_calls = 0

    def require(
        self,
        *,
        program_profile: str,
        facility: WarmupRequirement,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"program_profile": program_profile},
            dependencies={"facility": facility},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(
        self,
        nodes: list[PlanNode],
        runtime: RuntimeContext,
    ) -> None:
        self.prepare_calls += 1
        for node in nodes:
            facility = node.deps["facility"]
            program_profile = str(node.payload["program_profile"])
            runtime.set(
                node,
                self.api.create_program(
                facility=facility,
                program_profile=program_profile,
                ),
            )
            runtime.trace.append(f"program_ready:{node.runtime_key}")


class InventoryPlan(WarmupPlan):
    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.api = FakeExternalApi()
        self.prepare_calls = 0

    def require(
        self,
        *,
        qty: int,
        upc: str,
        program: WarmupRequirement,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"qty": qty, "upc": upc},
            dependencies={"program": program},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(
        self,
        nodes: list[PlanNode],
        runtime: RuntimeContext,
    ) -> None:
        self.prepare_calls += 1
        for node in nodes:
            program = node.deps["program"]
            runtime.set(
                node,
                self.api.create_products(
                    program=program,
                    qty=int(node.payload["qty"]),
                    upc=str(node.payload["upc"]),
                ),
            )
            runtime.trace.append(f"products_ready:{node.runtime_key}")
