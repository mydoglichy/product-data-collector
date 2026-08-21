from coupang_API.checkpoint import Checkpoint


def test_checkpoint_persists_completed_keywords(tmp_path):
    path = tmp_path / "checkpoint.json"

    checkpoint = Checkpoint.load(path)
    checkpoint.mark_completed("선글라스 케이스")

    loaded = Checkpoint.load(path)
    assert loaded.is_completed("선글라스 케이스")
    assert not loaded.is_completed("휴대용 안경집")


def test_checkpoint_clear_removes_file(tmp_path):
    path = tmp_path / "checkpoint.json"
    checkpoint = Checkpoint.load(path)
    checkpoint.mark_completed("선글라스 케이스")

    checkpoint.clear()

    assert not path.exists()

