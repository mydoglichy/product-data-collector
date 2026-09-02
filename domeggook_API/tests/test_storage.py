import os
import time

import pytest

from domeggook_API.persistence.storage import (
    FileLock,
    atomic_write_json,
    chunked,
    load_state,
)


def test_chunked_splits_detail_batches_by_100():
    product_ids = [str(value) for value in range(205)]

    chunks = chunked(product_ids, 100)

    assert [len(chunk) for chunk in chunks] == [100, 100, 5]
    assert chunks[0][0] == "0"
    assert chunks[-1][-1] == "204"


def test_atomic_write_json_replaces_valid_file(tmp_path):
    path = tmp_path / "state.json"

    atomic_write_json(path, {"1": {"productId": "1"}})
    atomic_write_json(path, {"2": {"productId": "2"}})

    assert load_state(path) == {"2": {"productId": "2"}}
    assert not list(tmp_path.glob("*.tmp"))


def test_file_lock_rejects_recent_existing_lock(tmp_path):
    path = tmp_path / "collector.lock"
    path.write_text("12345", encoding="ascii")

    with pytest.raises(RuntimeError, match="another domeggook_API collection"):
        with FileLock(path, stale_after_seconds=60):
            pass

    assert path.exists()


def test_file_lock_removes_stale_existing_lock(tmp_path):
    path = tmp_path / "collector.lock"
    path.write_text("12345", encoding="ascii")
    old_time = time.time() - 120
    os.utime(path, (old_time, old_time))

    with FileLock(path, stale_after_seconds=60):
        assert path.exists()

    assert not path.exists()
