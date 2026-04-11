from __future__ import annotations

from dataclasses import dataclass, field
import itertools


@dataclass
class FakeExternalApi:
    create_facility_calls: int = 0
    create_program_calls: int = 0
    create_products_calls: int = 0
    trace: list[str] = field(default_factory=list)
    _facility_counter: itertools.count = field(
        default_factory=lambda: itertools.count(1),
        init=False,
        repr=False,
    )
    _program_counter: itertools.count = field(
        default_factory=lambda: itertools.count(1),
        init=False,
        repr=False,
    )
    _products_counter: itertools.count = field(
        default_factory=lambda: itertools.count(1),
        init=False,
        repr=False,
    )

    def create_facility(self, *, country: str) -> dict[str, object]:
        self.create_facility_calls += 1
        facility_id = f"facility-{next(self._facility_counter)}"
        self.trace.append(f"create_facility:{country}:{facility_id}")
        return {
            "facility_id": facility_id,
            "country": country,
        }

    def create_program(
        self,
        *,
        facility: dict[str, object],
        program_profile: str,
    ) -> dict[str, object]:
        self.create_program_calls += 1
        program_id = f"program-{next(self._program_counter)}"
        self.trace.append(
            f"create_program:{facility['facility_id']}:{program_profile}:{program_id}"
        )
        return {
            "program_id": program_id,
            "facility_id": facility["facility_id"],
            "program_profile": program_profile,
        }

    def create_products(
        self,
        *,
        program: dict[str, object],
        qty: int,
        upc: str,
    ) -> dict[str, object]:
        self.create_products_calls += 1
        batch_id = f"products-{next(self._products_counter)}"
        self.trace.append(
            f"create_products:{program['program_id']}:{qty}:{upc}:{batch_id}"
        )
        return {
            "batch_id": batch_id,
            "program_id": program["program_id"],
            "qty": qty,
            "upc": upc,
        }
