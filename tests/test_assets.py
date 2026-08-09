"""品牌资产与版权声明测试"""
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "src" / "assets"

EXPECTED_ASSETS = [
    "logo.svg",
    "favicon.ico",
    "favicon-16x16.png",
    "favicon-32x32.png",
    "apple-touch-icon.png",
]


@pytest.mark.parametrize("name", EXPECTED_ASSETS)
def test_asset_exists(name):
    assert (ASSETS / name).exists(), f"缺少资产 {name}"


def test_logo_svg_valid():
    svg = (ASSETS / "logo.svg").read_text(encoding="utf-8")
    assert "<svg" in svg and "viewBox" in svg
    # 品牌元素齐备：K线蜡烛 / 上升箭头 / 扫描线 / 星点
    for mark in ("candle", "arrow", "scan", "star"):
        assert mark in svg, f"SVG 缺少设计元素注释 {mark}"


def test_png_sizes():
    assert Image.open(ASSETS / "favicon-16x16.png").size == (16, 16)
    assert Image.open(ASSETS / "favicon-32x32.png").size == (32, 32)
    assert Image.open(ASSETS / "apple-touch-icon.png").size == (180, 180)


def test_ico_multi_size():
    img = Image.open(ASSETS / "favicon.ico")
    sizes = {s for s in img.info.get("sizes", [])}
    assert (16, 16) in sizes and (32, 32) in sizes


def test_license_exists():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert "鹿溪联合创新实验室" in license_text


def test_readme_declaration():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for section in ("版权与数据声明", "不构成投资建议", "鹿溪联合创新实验室"):
        assert section in readme, f"README 缺少声明内容 {section}"
