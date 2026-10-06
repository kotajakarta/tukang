from app.core.config import adopt_legacy_db


def test_fresh_install_uses_new_db_name(tmp_path):
    assert adopt_legacy_db(tmp_path) == tmp_path / "tukang.db"
    assert list(tmp_path.iterdir()) == []


def test_pre_rebrand_db_and_sqlite_side_files_are_adopted(tmp_path):
    (tmp_path / "cockpit.db").write_text("main")
    (tmp_path / "cockpit.db-wal").write_text("wal")
    (tmp_path / "cockpit.db-shm").write_text("shm")

    assert adopt_legacy_db(tmp_path) == tmp_path / "tukang.db"

    assert (tmp_path / "tukang.db").read_text() == "main"
    assert (tmp_path / "tukang.db-wal").read_text() == "wal"  # uncheckpointed writes must follow the DB
    assert (tmp_path / "tukang.db-shm").read_text() == "shm"
    assert not list(tmp_path.glob("cockpit.db*"))


def test_existing_new_db_wins_over_legacy(tmp_path):
    (tmp_path / "tukang.db").write_text("current")
    (tmp_path / "cockpit.db").write_text("old")

    adopt_legacy_db(tmp_path)

    assert (tmp_path / "tukang.db").read_text() == "current"
    assert (tmp_path / "cockpit.db").read_text() == "old"  # left alone, never overwritten
