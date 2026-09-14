import pytest

from ml_platform import tasks


def test_wait_returns_requested_seconds_without_sleeping_for_real(
    monkeypatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(tasks.time, "sleep", slept.append)

    result = tasks.wait.run(2.5)

    assert result == 2.5
    assert slept == [2.5]


@pytest.mark.parametrize("seconds", [-0.1, 30.1])
def test_wait_rejects_seconds_outside_allowed_range(seconds: float) -> None:
    with pytest.raises(ValueError, match="seconds must be between 0 and 30"):
        tasks.wait.run(seconds)
