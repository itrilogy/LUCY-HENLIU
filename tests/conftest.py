"""pytest 全局配置：项目根加入 sys.path，保证 from src.xxx 导入可用"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 测试不得依赖真实网络与真实数据文件
os.environ.setdefault("GT_ZNXG_KEY", "test-key")
os.environ.setdefault("GS_API_KEY", "test-key")
