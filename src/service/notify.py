"""
多通道通知：日志 + 微信机器人（best-effort）。

微信通道使用现有资源：环境变量 WEIXIN_BOT_TOKEN，端点 https://ilinkai.weixin.qq.com。
API 格式未公开文档，采用最常见 POST JSON 格式；失败仅记录日志，不影响主流程。
"""
import json
import logging
import os
import urllib.request

logger = logging.getLogger("src.service.notify")

WEIXIN_ENDPOINT = os.environ.get("WEIXIN_ENDPOINT", "https://ilinkai.weixin.qq.com")


def notify(title: str, message: str, channels=("log", "weixin")) -> None:
    """多通道发送通知。单通道失败不影响其他通道。"""
    for ch in channels:
        try:
            if ch == "log":
                _log(title, message)
            elif ch == "weixin":
                _weixin(title, message)
            else:
                logger.warning("未知通知通道: %s", ch)
        except Exception as e:
            logger.error("通知通道 %s 失败: %s", ch, e)


def _log(title: str, message: str) -> None:
    logger.info("%s\n%s", title, message)


def _weixin(title: str, message: str) -> None:
    token = os.environ.get("WEIXIN_BOT_TOKEN", "")
    if not token:
        logger.warning("未配置 WEIXIN_BOT_TOKEN，跳过微信通知（可设 WEIXIN_ENDPOINT 指定 webhook）")
        return
    payload = json.dumps({
        "token": token,
        "title": title,
        "content": f"{title}\n{message}",
    }).encode("utf-8")
    req = urllib.request.Request(
        WEIXIN_ENDPOINT, data=payload,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        logger.info("微信通知响应: %s", body[:200])
