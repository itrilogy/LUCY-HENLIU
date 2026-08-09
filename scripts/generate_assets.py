"""
QuantLab 品牌位图资产生成器（Pillow，几何与 src/assets/logo.svg 同源）。

生成：
    src/assets/favicon.ico            (16/32/48 多尺寸)
    src/assets/favicon-16x16.png
    src/assets/favicon-32x32.png
    src/assets/apple-touch-icon.png   (180×180)

用法：python3 scripts/generate_assets.py
依赖：Pillow（pip install Pillow）
"""
from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "src" / "assets"

# 品牌配色（与 logo.svg 一致）
C_BG_TOP = (20, 41, 63)        # #14293F
C_BG_BOTTOM = (10, 26, 46)     # #0A1A2E
C_CANDLE_UP = (0, 229, 160)    # #00E5A0
C_CANDLE_FLAT = (245, 247, 250)  # #F5F7FA
C_SIGNAL = (0, 210, 255)       # #00D2FF


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def vertical_gradient(size: int, radius: int) -> Image.Image:
    """圆角瓦片 + 垂直渐变底"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(size):
        d.line([(0, y), (size, y)], fill=lerp(C_BG_TOP, C_BG_BOTTOM, y / size))
    # 圆角掩码
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.putalpha(mask)
    return img


def draw_logo(size: int) -> Image.Image:
    """在 32×32 坐标系上绘制 QuantLab 图标，缩放至 size"""
    S = size / 32.0
    img = vertical_gradient(size, radius=int(8 * S))
    d = ImageDraw.Draw(img)

    def rect(x, y, w, h, fill, opacity=1.0):
        color = (*fill, int(255 * opacity))
        d.rounded_rectangle(
            [x * S, y * S, (x + w) * S, (y + h) * S], radius=0.5 * S, fill=color)

    def line(x1, y1, x2, y2, fill, width, opacity=1.0):
        d.line([x1 * S, y1 * S, x2 * S, y2 * S],
               fill=(*fill, int(255 * opacity)), width=max(1, int(width * S)))

    # candle 1: 横盘（白 半透明）
    rect(8, 15, 2.2, 6, C_CANDLE_FLAT, 0.4)
    line(9.1, 12.5, 9.1, 21.5, C_CANDLE_FLAT, 0.8, 0.4)
    # candle 2: 上涨（青绿）
    rect(12.6, 12, 2.2, 6, C_CANDLE_UP, 0.75)
    line(13.7, 10.5, 13.7, 18.5, C_CANDLE_UP, 0.8, 0.75)
    # candle 3: 放量突破（信号青高亮）
    rect(17.2, 9.5, 2.2, 6.5, C_CANDLE_UP)
    line(18.3, 7.8, 18.3, 16.5, C_CANDLE_UP, 0.8)
    # rising arrow: 量化发现趋势
    d.line([22.2 * S, 21.8 * S, 26 * S, 18 * S], fill=C_SIGNAL, width=max(1, int(1.3 * S)))
    d.line([26 * S, 18 * S, 23.4 * S, 17.8 * S], fill=C_SIGNAL, width=max(1, int(1.1 * S)))
    d.line([26 * S, 18 * S, 25.8 * S, 20.6 * S], fill=C_SIGNAL, width=max(1, int(1.1 * S)))
    # scan line: 算法逐点分析（折线近似）
    pts = [(5.5, 25.5), (9.5, 24.5), (13, 26.2), (16.5, 25.2), (20, 24.6), (22.5, 25.4), (26.5, 24.8)]
    d.line([(x * S, y * S) for x, y in pts], fill=(0, 210, 255, 230), width=max(1, int(1.3 * S)))
    # star: 策略灵感（菱形 + 圆点）
    cx, cy, r = 25.2, 6.8, 2.0
    d.polygon([(cx * S, (cy - r) * S), ((cx + r * 0.55) * S, cy * S),
               (cx * S, (cy + r) * S), ((cx - r * 0.55) * S, cy * S)], fill=C_SIGNAL)
    d.ellipse([(cx - 0.55) * S, (cy - 0.55) * S, (cx + 0.55) * S, (cy + 0.55) * S],
              fill=C_CANDLE_FLAT)
    return img


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)

    # 单尺寸 PNG
    draw_logo(16).save(ASSETS / "favicon-16x16.png")
    draw_logo(32).save(ASSETS / "favicon-32x32.png")
    draw_logo(180).save(ASSETS / "apple-touch-icon.png")

    # 多尺寸 ICO
    draw_logo(32).save(
        ASSETS / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)])

    for f in ("favicon.ico", "favicon-16x16.png",
              "favicon-32x32.png", "apple-touch-icon.png"):
        p = ASSETS / f
        print(f"✓ {p.relative_to(ASSETS.parent.parent)} ({p.stat().st_size} B)")


if __name__ == "__main__":
    main()
