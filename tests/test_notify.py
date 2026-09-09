"""通知与调度测试（mock 外部端点，不真发消息）"""
import json
import logging
import sys
from unittest.mock import patch

from src.service.notify import notify, _weixin
from src.scheduler import is_trading_day


def test_notify_log_channel_writes_log(tmp_path, monkeypatch):
    import src.service.notify as nt
    logger = logging.getLogger("notify.test.write")
    logger.handlers.clear()
    log_path = tmp_path / "n.log"
    fh = logging.FileHandler(log_path, encoding="utf-8")
    logger.addHandler(fh)
    logger.setLevel(logging.INFO)
    monkeypatch.setattr(nt, "logger", logger)

    with patch("src.service.notify._weixin") as mock_wx:
        notify("标题", "内容", channels=("log",))
    mock_wx.assert_not_called()
    fh.flush()
    text = log_path.read_text(encoding="utf-8")
    assert "标题" in text and "内容" in text


def test_weixin_skips_without_token(monkeypatch):
    import src.service.notify as nt
    monkeypatch.setattr(nt, "logger", logging.getLogger("notify.test"))
    monkeypatch.delenv("WEIXIN_BOT_TOKEN", raising=False)
    # 无 token 时不发请求
    with patch("urllib.request.urlopen") as mock_req:
        _weixin("t", "m")
    mock_req.assert_not_called()


def test_weixin_posts_json_with_token(monkeypatch):
    import src.service.notify as nt
    monkeypatch.setattr(nt, "logger", logging.getLogger("notify.test"))
    monkeypatch.setenv("WEIXIN_BOT_TOKEN", "test-token")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    with patch("urllib.request.urlopen", return_value=FakeResp()) as mock_req:
        _weixin("标题", "内容")
    mock_req.assert_called_once()
    # 请求包含 token 与内容（JSON 体解析校验）
    call = mock_req.call_args[0][0]
    payload = json.loads(call.data.decode("utf-8"))
    assert payload["token"] == "test-token"
    assert payload["title"] == "标题"
    assert "内容" in payload["content"]


def test_is_trading_day():
    import datetime
    # 2026-08-08 是周六 → 非交易日
    assert not is_trading_day(datetime.date(2026, 8, 8))
    # 2026-08-10 是周一 → 交易日
    assert is_trading_day(datetime.date(2026, 8, 10))
