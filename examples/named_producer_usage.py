from __future__ import annotations

import pytest

from pytest_warmup import WarmupNode, WarmupPlan, WarmupRequirement, warmup_param


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

    def prepare_node(self, node: WarmupNode) -> dict[str, object]:
        return {
            "workspace_id": f"workspace-{node.payload['region']}",
            "region": node.payload["region"],
        }


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

    def prepare_node(self, node: WarmupNode) -> dict[str, object]:
        workspace = node.deps["workspace"]
        return {
            "profile_id": f"profile-{node.payload['profile_name']}",
            "workspace_id": workspace["workspace_id"],
            "profile_name": node.payload["profile_name"],
        }


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

    def prepare_node(self, node: WarmupNode) -> dict[str, object]:
        profile = node.deps["profile"]
        return {
            "items_id": f"items-{node.payload['reference']}",
            "profile_id": profile["profile_id"],
            "count": node.payload["count"],
            "reference": node.payload["reference"],
        }


workspace = WorkspacePlan("workspace")
profile = ProfilePlan("profile")
items = ItemsPlan("items")

workspace_primary = workspace.require(region="eu", id="workspace_primary")
profile_primary = profile.require(
    profile_name="main",
    workspace=workspace_primary,
    id="profile_primary",
)
items_alpha = items.require(
    count=10,
    reference="alpha",
    profile=profile_primary,
    id="items_alpha",
)


@pytest.fixture(scope="module")
def prepare_data_a(warmup_mgr):
    return warmup_mgr.use(workspace, profile, items).prepare()


@pytest.fixture(scope="module")
def prepare_data_b(warmup_mgr):
    return warmup_mgr.use(workspace, profile, items).prepare()


@pytest.fixture
def helper_a(prepare_data_a):
    return prepare_data_a


@pytest.fixture
def helper_b(prepare_data_b):
    return prepare_data_b


@warmup_param("prepared_items", items_alpha, producer_fixture="prepare_data_a")
def test_items_are_available(helper_a, helper_b, prepared_items):
    assert prepared_items["profile_id"].startswith("profile-")
    assert prepared_items["count"] == 10
