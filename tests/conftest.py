import pytest


@pytest.fixture(autouse=True)
def no_locally_installed_event_model(monkeypatch, tmp_path):
    """Keep tests independent of an optional checkpoint in the weights folder."""
    from badminton import event_model

    monkeypatch.setattr(
        event_model,
        "checkpoint_path",
        lambda mode="singles": tmp_path / "absent-events.pt",
    )
