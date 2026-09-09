"""服务层测试：备份 / 日志 / 单实例锁"""
import logging
import sqlite3

from src.service.backup import backup_db
from src.service.logging_setup import setup_logging
from src.service.lock import single_instance


def test_backup_db_creates_snapshot(tmp_path):
    db_path = str(tmp_path / "stock.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()

    backup = backup_db(db_path, keep_days=2)
    assert backup.exists()
    # 备份内容一致
    c = sqlite3.connect(str(backup))
    assert c.execute("SELECT x FROM t").fetchone()[0] == 42
    c.close()


def test_backup_db_idempotent_same_day(tmp_path):
    db_path = str(tmp_path / "stock.db")
    sqlite3.connect(db_path).close()
    b1 = backup_db(db_path)
    b2 = backup_db(db_path)
    assert b1 == b2  # 当日不重复备份


def test_setup_logging_returns_same_logger(tmp_path, monkeypatch):
    import src.service.logging_setup as ls
    monkeypatch.setattr(ls, "LOG_DIR", tmp_path)
    logger = setup_logging("testmod")
    assert logger is setup_logging("testmod")  # 幂等
    logger.info("hello")
    log_file = tmp_path / "testmod.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_single_instance_lock_works(tmp_path, monkeypatch):
    import src.service.lock as lk
    monkeypatch.setattr(lk, "LOCK_FILE", tmp_path / "lock")
    with single_instance("测试"):
        assert lk.LOCK_FILE.exists()


def test_try_single_instance_yields_true(tmp_path, monkeypatch):
    import src.service.lock as lk
    monkeypatch.setattr(lk, "LOCK_FILE", tmp_path / "lock")
    with lk.try_single_instance("测试") as ok:
        assert ok is True
