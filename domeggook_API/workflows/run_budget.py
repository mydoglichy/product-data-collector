from __future__ import annotations


class RunBudget:
    def __init__(self, max_api_calls: int | None) -> None:
        self.max_api_calls = max_api_calls if max_api_calls is not None else None
        self.used_api_calls = 0

    def can_call(self) -> bool:
        return self.max_api_calls is None or self.used_api_calls < self.max_api_calls

    def record_call(self) -> None:
        self.used_api_calls += 1

    def exhausted(self) -> bool:
        return self.max_api_calls is not None and self.used_api_calls >= self.max_api_calls
