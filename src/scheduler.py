"""
交易日定时调度器：工作日 15:30 自动执行全量同步，完成后微信/日志告警。

启动方式（常驻）：
    python3 src/scheduler.py

说明：
- 交易日判断：周一~周五（不含 A 股法定节假日；后续可用 trade_calendar 表扩展精确日历）
- 同步后自动备份（sync_daily.py 内已集成）
- 通知复用现有资源：WEIXIN_BOT_TOKEN → 微信机器人（best-effort）
"""
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import schedule

from src.service.calendar import is_trading_day as _cal_trading_day
from src.service.logging_setup import setup_logging
from src.service.notify import notify

ROOT = Path(__file__).resolve().parent.parent
logger = setup_logging("scheduler")

# 交易日 15:30 触发（A股收盘后）
SYNC_TIME = "15:30"
SYNC_TIMEOUT = 1800  # 秒


def is_trading_day(d=None) -> bool:
    """周末 + 法定休市（CLOSED_DATES）。有库时也可传入 db 读 trade_calendar。"""
    return _cal_trading_day(d, db=None)


def run_sync_and_notify() -> None:
    if not is_trading_day():
        logger.info("非交易日，跳过本次同步")
        return
    logger.info("⏰ 触发每日全量同步")
    t0 = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "src" / "sync_daily.py"), "--full"],
            capture_output=True, text=True, timeout=SYNC_TIMEOUT)
        dur = time.time() - t0
        tail = [ln for ln in r.stdout.strip().splitlines() if ln.strip()][-8:]
        summary = "\n".join(tail) if tail else "(无输出)"
        if r.returncode == 0:
            notify("✅ 衡流每日同步完成",
                   f"耗时 {dur:.0f}s\n{summary}")
        elif r.returncode == 2:
            notify("⚠️ 衡流同步部分失败",
                   f"退出码 2，耗时 {dur:.0f}s\n{summary}")
        else:
            err = r.stderr.strip()[-500:] if r.stderr else ""
            if "跳过" in (r.stderr or ""):
                logger.info("同步被跳过（已有实例在运行），不告警")
            else:
                notify("⚠️ 衡流同步异常",
                       f"退出码 {r.returncode}，耗时 {dur:.0f}s\n{summary}\n{err}")
    except subprocess.TimeoutExpired:
        notify("❌ 衡流同步超时", f"超过 {SYNC_TIMEOUT}s 未完成")
    except Exception as e:
        notify("❌ 衡流同步失败", str(e))


def main() -> None:
    setup_logging("src")
    schedule.every().day.at(SYNC_TIME).do(run_sync_and_notify)
    logger.info("🕒 调度器启动：工作日 %s 自动全量同步（Ctrl+C 退出）", SYNC_TIME)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
