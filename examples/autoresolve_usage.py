from __future__ import annotations

from pathlib import Path

import pytest

from pytest_warmup import WarmupPlan, WarmupRequirement, warmup_param


class WorkspacePlan(WarmupPlan):
    def require(
        self,
        *,
        region: str,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"region": region},
            dependencies={},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(self, nodes, runtime) -> None:
        for node in nodes:
            runtime.set(
                node,
                {
                    "workspace_id": f"workspace-{node.payload['region']}",
                    "region": node.payload["region"],
                },
            )


class ProfilePlan(WarmupPlan):
    def require(
        self,
        *,
        profile_name: str,
        workspace: WarmupRequirement,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"profile_name": profile_name},
            dependencies={"workspace": workspace},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(self, nodes, runtime) -> None:
        for node in nodes:
            workspace = node.deps["workspace"]
            runtime.set(
                node,
                {
                    "profile_id": f"profile-{node.payload['profile_name']}",
                    "workspace_id": workspace["workspace_id"],
                    "profile_name": node.payload["profile_name"],
                },
            )


class ItemsPlan(WarmupPlan):
    def require(
        self,
        *,
        count: int,
        reference: str,
        profile: WarmupRequirement,
        id: str | None = None,
        is_per_test: bool | None = None,
    ) -> WarmupRequirement:
        return super().require(
            payload={"count": count, "reference": reference},
            dependencies={"profile": profile},
            id=id,
            is_per_test=is_per_test,
        )

    def prepare(self, nodes, runtime) -> None:
        for node in nodes:
            profile = node.deps["profile"]
            runtime.set(
                node,
                {
                    "items_id": f"items-{node.payload['reference']}",
                    "profile_id": profile["profile_id"],
                    "count": node.payload["count"],
                    "reference": node.payload["reference"],
                },
            )


workspace = WorkspacePlan("workspace")
profile = ProfilePlan("profile")
items = ItemsPlan("items")

workspace_eu = workspace.require(region="eu", id="workspace_eu")
profile_main = profile.require(
    profile_name="main",
    workspace=workspace_eu,
    id="profile_main",
)
items_alpha = items.require(
    count=10,
    reference="alpha",
    profile=profile_main,
    id="items_alpha",
)


@pytest.fixture(scope="module")
def prepare_data(warmup_mgr):
    snapshot_file = Path(__file__).with_name("warmup.snapshot.json")
    return warmup_mgr.use(workspace, profile, items).prepare(snapshot_file=snapshot_file)


@pytest.fixture
def warmup_autoresolve_producer(prepare_data):
    return prepare_data


@pytest.fixture
@warmup_param("prepared_items", items_alpha)
def prepared_items_fixture(prepared_items):
    return prepared_items


def test_items_are_available(prepared_items_fixture):
    assert prepared_items_fixture["profile_id"] == "debug-profile"
    assert prepared_items_fixture["count"] == 10
