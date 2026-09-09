from src.db.connection import open_db


def test_open_db_pragmas(tmp_path):
    db = open_db(tmp_path / "x.db")
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    mode = db.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    ver = db.execute("PRAGMA user_version").fetchone()[0]
    assert ver >= 2
    db.close()
