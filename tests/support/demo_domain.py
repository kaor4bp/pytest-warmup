from __future__ import annotations

from pytest_warmup import WarmupNode, WarmupPlan, WarmupRequirement

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

    def before_prepare(self, nodes: list[WarmupNode]) -> None:
        self.prepare_calls += 1

    def prepare_node(self, node: WarmupNode) -> object:
        country = str(node.payload["country"])
        return self.api.create_facility(country=country)


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

    def before_prepare(self, nodes: list[WarmupNode]) -> None:
        self.prepare_calls += 1

    def prepare_node(self, node: WarmupNode) -> object:
        facility = node.deps["facility"]
        program_profile = str(node.payload["program_profile"])
        return self.api.create_program(
            facility=facility,
            program_profile=program_profile,
        )


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

    def before_prepare(self, nodes: list[WarmupNode]) -> None:
        self.prepare_calls += 1

    def prepare_node(self, node: WarmupNode) -> object:
        program = node.deps["program"]
        return self.api.create_products(
            program=program,
            qty=int(node.payload["qty"]),
            upc=str(node.payload["upc"]),
        )
