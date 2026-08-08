"""
跨进程单实例锁（fcntl 文件锁）。

防止 cron 定时任务与手动执行并发运行同步脚本写坏 SQLite。
被占用时立即退出（不排队等待），避免堆积。
"""
import fcntl
import sys
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "sync.lock"


@contextmanager
def single_instance(name: str = "同步"):
    """同一时间只允许一个实例；已被占用时以非零码退出（供调度器识别跳过）。"""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOCK_FILE, "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"⚠️ 已有其他{name}进程在运行（{LOCK_FILE} 被占用），本次跳过",
              file=sys.stderr)
        sys.exit(1)  # 非零退出码：scheduler 可据此识别"被跳过"而非同步失败
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
