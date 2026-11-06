"""UPD-06 worker gate: a queued scheduled batch must not start after its switch is off."""

from __future__ import annotations

from types import SimpleNamespace

from xingtu.domain import CreatorScene, PlatformId, TaskKind, TaskStatus
from xingtu.worker import Activities


class FakeRepo:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.edited: list[str] = []
        self.lookups: list[tuple[str, str]] = []
        self.state: TaskStatus | None = None
        self.failure_reason: str | None = None
        self._holder: SimpleNamespace | None = None

    def scheduled_update_enabled(self, platform: str, scene: str) -> bool:
        self.lookups.append((platform, scene))
        return self.enabled

    def edit(self, root: str):
        repo = self
        repo.edited.append(root)
        repo._holder = SimpleNamespace(state=None, failure_reason=None)

        class Edit:
            def __enter__(self):
                assert repo._holder is not None
                return (repo._holder, None)

            def __exit__(self, exc_type, exc, tb):
                del exc_type, exc, tb
                assert repo._holder is not None
                repo.state = repo._holder.state
                repo.failure_reason = repo._holder.failure_reason
                return False

        return Edit()


def task(kind: TaskKind = TaskKind.SCHEDULED_UPDATE):
    return SimpleNamespace(
        task_kind=kind,
        platform=PlatformId.DOUYIN_XINGTU,
        creator_scene=CreatorScene.LIVE_SQUARE,
        root_task_id="root-1",
    )


def test_disabled_scheduled_update_is_cancelled_before_execution() -> None:
    repo = FakeRepo(enabled=False)
    activities = SimpleNamespace(repo=repo)
    result = Activities.cancel_disabled_scheduled_update(activities, task())
    assert result == TaskStatus.CANCELLED
    assert repo.lookups == [("douyin_xingtu", "live_square")]
    assert repo.edited == ["root-1"]
    assert repo.state == TaskStatus.CANCELLED
    assert repo.failure_reason == "UPDATE_SERVICE_DISABLED"


def test_enabled_scheduled_update_and_other_task_kinds_are_not_cancelled() -> None:
    enabled = FakeRepo(enabled=True)
    assert (
        Activities.cancel_disabled_scheduled_update(SimpleNamespace(repo=enabled), task()) is None
    )
    assert enabled.edited == []

    manual = FakeRepo(enabled=False)
    assert (
        Activities.cancel_disabled_scheduled_update(
            SimpleNamespace(repo=manual), task(TaskKind.MANUAL_UPDATE)
        )
        is None
    )
    assert manual.lookups == [] and manual.edited == []

    collection = FakeRepo(enabled=False)
    assert (
        Activities.cancel_disabled_scheduled_update(
            SimpleNamespace(repo=collection), task(TaskKind.COLLECTION)
        )
        is None
    )
    assert collection.lookups == [] and collection.edited == []
