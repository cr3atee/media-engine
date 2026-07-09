from __future__ import annotations

from typing import Generic, Protocol, TypeVar

T = TypeVar("T")


class Stage(Protocol[T]):
    async def process(self, data: T) -> T: ...


class Pipeline(Generic[T]):
    def __init__(self) -> None:
        self._stages: list[Stage[T]] = []

    def add_stage(self, stage: Stage[T]) -> None:
        self._stages.append(stage)

    async def run(self, data: T) -> T:
        result = data
        for stage in self._stages:
            result = await stage.process(result)
        return result
