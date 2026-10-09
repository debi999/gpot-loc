#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G-POT Loc 应用图标生成器（Pillow 单真源）

设计意图（老板 2026-10-09 口述）：
    一个正在熬煮的大锅，散发粉色的蒸汽，蒸汽中有个 8bit 风格的 3D 爱心，
    45° 角斜对着屏幕。

实现要点：
  1. 单真源：所有图形都由本脚本生成，改这里再跑一次即可重建全部产物。
  2. 平滑层（背景 / 锅体 / 蒸汽）按 SS 倍超采样绘制再降采样，边缘干净。
  3. 爱心在最上层**硬边绘制**，不参与降采样糊化，保住 8bit 的锐利块面。
     立体感用「斜二测挤出（oblique extrusion）」：心形正面用正方形网格保持正立，
     厚度沿右上 45° 挤出，只在暴露边画顶面 / 右侧面 —— 即 45° 斜视的 3D 像素块。

用法：
    python tools/gen_logo.py            # 生成到 src/gpot/ui/assets/
"""
from __future__ import annotations

import math
import os
import sys
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- 可调参数
W = 1024                    # 母版边长
SS = 3                      # 平滑层超采样倍数
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "src", "gpot", "ui", "assets")
ICO_SIZES = [(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48),
             (64, 64), (96, 96), (128, 128), (256, 256)]

# 配色沿用《UI规格说明书》§1.2 令牌（炼香工坊 · 暧昧粉紫）
BG_TOP    = (0x27, 0x1B, 0x36)   # 机身顶：暖调深紫
BG_BOT    = (0x13, 0x0D, 0x1C)   # 机身底：更深
POT_LIT   = (0x4A, 0x38, 0x63)   # 锅体受光面
POT_DARK  = (0x25, 0x1B, 0x35)   # 锅体暗面
RIM_METAL = (0x5E, 0x4A, 0x7C)   # 锅沿金属
POT_INNER = (0x18, 0x11, 0x22)   # 锅内深色
BRASS     = (0xDD, 0xA0, 0xBC)   # 黄铜/玫瑰金描边
ROSE      = (0xE8, 0x62, 0x9A)   # 玫瑰粉（主光源）
ROSE_HI   = (0xF5, 0x8B, 0xC0)   # 粉高光
VIOLET    = (0x9B, 0x6B, 0xF0)   # 紫（副光源）
HEART_FACE= (0xEE, 0x74, 0xA6)   # 爱心正面
HEART_TOP = (0xFC, 0xAF, 0xD6)   # 爱心顶面（亮）
HEART_SIDE= (0xB2, 0x3A, 0x70)   # 爱心右侧面（暗）
HEART_OUT = (0x47, 0x19, 0x33)   # 爱心外描边
SPARK     = (0xFF, 0xEE, 0xF6)   # 高光点


# ---------------------------------------------------------------- 基础工具
def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def mix(c1: Sequence[int], c2: Sequence[int], t: float, alpha: int = 255) -> tuple[int, int, int, int]:
    return (int(round(lerp(c1[0], c2[0], t))),
            int(round(lerp(c1[1], c2[1], t))),
            int(round(lerp(c1[2], c2[2], t))),
            alpha)


def vertical_gradient(size: int, c_top, c_bot) -> Image.Image:
    img = Image.new("RGBA", (size, size))
    d = ImageDraw.Draw(img)
    for y in range(size):
        d.line([(0, y), (size, y)], fill=mix(c_top, c_bot, y / (size - 1)))
    return img


def rounded(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def shape_from_mask(mask: Image.Image, fill: Image.Image) -> Image.Image:
    out = fill.copy()
    out.putalpha(mask)
    return out


def paste(dst: Image.Image, src: Image.Image) -> None:
    dst.alpha_composite(src)


def downscale(img: Image.Image) -> Image.Image:
    return img.resize((W, W), Image.LANCZOS)


class ScaledDraw:
    """把母版坐标按倍率放大后绘制（超采样用）。"""

    def __init__(self, img: Image.Image, s: int):
        self.d = ImageDraw.Draw(img)
        self.s = s

    def _pts(self, pts: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
        return [(x * self.s, y * self.s) for x, y in pts]

    def polygon(self, pts, **kw):
        self.d.polygon(self._pts(pts), **kw)

    def ellipse(self, box, **kw):
        x0, y0, x1, y1 = box
        self.d.ellipse([x0 * self.s, y0 * self.s, x1 * self.s, y1 * self.s], **kw)

    def line(self, pts, **kw):
        self.d.line(self._pts(pts), **kw)


def build_glow(cx: float, cy: float, rx: float, ry: float,
               color, strength: float = 0.55) -> Image.Image:
    """柔和辐射光晕：实心椭圆 + 高斯模糊。"""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=color + (255,))
    layer.putalpha(layer.getchannel("A").point(lambda v: int(v * strength)))
    return layer.filter(ImageFilter.GaussianBlur(int(W * 0.055)))


# ---------------------------------------------------------------- 背景
def build_background() -> Image.Image:
    base = vertical_gradient(W, BG_TOP, BG_BOT)
    base.putalpha(rounded(W, int(W * 0.20)))
    return base


# ---------------------------------------------------------------- 锅体
def _body_outline(cx: float, rim_y: float, bot_y: float,
                  bulge_rx: float, bulge_cy: float, bulge_ry: float,
                  cap_ry: float) -> list[tuple[float, float]]:
    """锅体轮廓：上接锅沿，中部微鼓，底部收圆。"""
    pts: list[tuple[float, float]] = []
    step = (bot_y - rim_y) / 90.0
    # 左支：沿鼓腹椭圆从锅沿高度下行
    for i in range(91):
        yy = rim_y + step * i
        t = (yy - bulge_cy) / bulge_ry
        if abs(t) <= 1.0:
            half = bulge_rx * math.sqrt(max(0.0, 1 - t * t))
            pts.append((cx - half, yy))
    # 底部圆化收尾（下半椭圆帽）
    cut_half = bulge_rx * math.sqrt(max(0.0, 1 - ((bot_y - bulge_cy) / bulge_ry) ** 2))
    for i in range(1, 40):
        a = math.pi * (1 - i / 39.0)
        pts.append((cx - cut_half * math.cos(a), bot_y - cap_ry * math.sin(a)))
    for i in range(1, 40):
        a = math.pi * (i / 39.0)
        pts.append((cx + cut_half * math.cos(a), bot_y - cap_ry * math.sin(a)))
    # 右支：从底部上行回锅沿
    for i in range(90, -1, -1):
        yy = rim_y + step * i
        t = (yy - bulge_cy) / bulge_ry
        if abs(t) <= 1.0:
            half = bulge_rx * math.sqrt(max(0.0, 1 - t * t))
            pts.append((cx + half, yy))
    pts.append((cx - bulge_rx * math.sqrt(max(0.0, 1 - ((rim_y - bulge_cy) / bulge_ry) ** 2)), rim_y))
    return pts


# 锅体几何参数（母版坐标）
POT = dict(cx=512.0, rim_y=598.0, rim_rx=252.0, rim_ry=62.0,
           bot_y=806.0, bulge_rx=266.0, bulge_cy=648.0, bulge_ry=214.0, cap_ry=46.0)


def build_cauldron() -> Image.Image:
    """把手（先画，被锅体遮住内侧）+ 三条腿 + 锅体 + 左上受光弧。"""
    big = W * SS
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))

    # --- 把手：两个侧环 ---
    handles = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    hd = ScaledDraw(handles, SS)
    cx, rim_rx = POT["cx"], POT["rim_rx"]
    for sx in (-1, 1):
        bx = cx + sx * (rim_rx - 6)
        hd.ellipse([bx - 54, 612, bx + 54, 706], outline=BRASS + (170,), width=int(16 * SS))
    paste(out, downscale(handles))

    # --- 三条腿 ---
    legs = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ld = ScaledDraw(legs, SS)
    for lx in (POT["cx"] - 170, POT["cx"], POT["cx"] + 170):
        w_top, w_bot = 42, 28
        y0, y1 = 766, 876
        ld.polygon([(lx - w_top / 2, y0), (lx + w_top / 2, y0),
                    (lx + w_bot / 2, y1), (lx - w_bot / 2, y1)], fill=POT_DARK + (255,))
    paste(out, downscale(legs))

    # --- 锅体（渐变填充） ---
    outline_pts = _body_outline(POT["cx"], POT["rim_y"], POT["bot_y"],
                                POT["bulge_rx"], POT["bulge_cy"], POT["bulge_ry"], POT["cap_ry"])
    body_mask_big = Image.new("L", (big, big), 0)
    ImageDraw.Draw(body_mask_big).polygon([(x * SS, y * SS) for x, y in outline_pts], fill=255)
    body_mask = body_mask_big.resize((W, W), Image.LANCZOS)
    body = shape_from_mask(body_mask, vertical_gradient(W, POT_LIT, POT_DARK))
    paste(out, body)

    # --- 左上受光弧：沿轮廓左支的连续段（截断处 break，避免左右支被直连） ---
    arc = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ad = ScaledDraw(arc, SS)
    hi_pts: list[tuple[float, float]] = []
    for p in outline_pts:
        if p[1] > POT["rim_y"] + 116:
            break
        hi_pts.append(p)
    ad.line(hi_pts, fill=BRASS + (150,), width=int(9 * SS), joint="curve")
    arc = downscale(arc).filter(ImageFilter.GaussianBlur(3))
    arc.putalpha(arc.getchannel("A").point(lambda v: int(v * 0.8)))
    paste(out, arc)
    return out


def build_rim_and_brew() -> Image.Image:
    """锅沿金属环 + 锅内玫瑰色熬煮液面 + 气泡。"""
    big = W * SS
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ScaledDraw(layer, SS)
    cx, rim_y, rim_rx, rim_ry = POT["cx"], POT["rim_y"], POT["rim_rx"], POT["rim_ry"]

    d.ellipse([cx - rim_rx, rim_y - rim_ry, cx + rim_rx, rim_y + rim_ry], fill=RIM_METAL + (255,))
    d.ellipse([cx - rim_rx + 20, rim_y - rim_ry + 15, cx + rim_rx - 20, rim_y + rim_ry - 15],
              fill=POT_INNER + (255,))
    layer = downscale(layer)
    paste(out, layer)

    # 锅内玫瑰色液面辉光（沸腾感）
    brew = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(brew)
    bd.ellipse([cx - rim_rx + 18, rim_y - 8, cx + rim_rx - 18, rim_y + rim_ry - 12],
               fill=ROSE + (255,))
    brew = brew.filter(ImageFilter.GaussianBlur(22))
    brew.putalpha(brew.getchannel("A").point(lambda v: int(v * 0.95)))
    paste(out, brew)

    # 液面高光弧 + 几个气泡
    bubble = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bubble)
    bd.arc([cx - rim_rx + 40, rim_y - 20, cx + rim_rx - 40, rim_y + 34],
           start=200, end=340, fill=ROSE_HI + (230,), width=7)
    for bx, by, r in ((cx - 96, rim_y + 12, 9), (cx - 24, rim_y - 2, 12),
                      (cx + 58, rim_y + 16, 8), (cx + 132, rim_y + 6, 6)):
        bd.ellipse([bx - r, by - r * 0.62, bx + r, by + r * 0.62],
                   fill=mix(ROSE_HI, SPARK, 0.55, 235))
    paste(out, bubble.filter(ImageFilter.GaussianBlur(1)))
    return out


# ---------------------------------------------------------------- 蒸汽
def _plume(d: ScaledDraw, x0: float, y0: float, height: float, amp: float,
           freq: float, phase: float, color, w0: float, w1: float, steps: int = 56):
    """自下而上的蛇形蒸汽带：宽度自下而上收窄、透明度渐隐。"""
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + amp * math.sin(freq * math.pi * t + phase) * (0.35 + t * 0.9)
        y = y0 - height * t
        pts.append((x, y))
    for i in range(len(pts) - 1):
        t = i / (len(pts) - 1)
        w = lerp(w0, w1, t)
        a = int(lerp(225, 55, t ** 1.1))
        d.line([pts[i], pts[i + 1]], fill=color + (a,),
               width=max(1, int(round(w))), joint="curve")


def build_steam(top_wisp: bool = False) -> Image.Image:
    """top_wisp=False：锅口两侧的主蒸汽（画在爱心后面）；
    top_wisp=True：爱心上方冒头的一小缕（画在爱心前面）。"""
    big = W * SS
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ScaledDraw(layer, SS)
    cx = POT["cx"]
    if top_wisp:
        specs = [(cx - 6, 168, 116, 40, 1.6, 0.8, ROSE_HI, 60, 10)]
    else:
        specs = [
            # x0, 起始y, 高度, 摆幅, 频率, 相位, 颜色, 底宽, 顶宽
            (cx - 228, 566, 386, 66, 1.8, 0.5, ROSE_HI, 104, 16),
            (cx + 224, 574, 368, 60, 2.1, 1.5, ROSE, 96, 14),
            (cx - 178, 570, 336, 52, 2.4, 2.9, VIOLET, 66, 9),
            (cx + 176, 578, 322, 50, 2.7, 4.0, ROSE_HI, 62, 9),
        ]
    base = 570.0
    for x0, _, h, amp, freq, ph, col, w0, w1 in specs:
        y0 = 168.0 if top_wisp else base
        _plume(d, x0, y0, h, amp, freq, ph, col, w0, w1)
    layer = downscale(layer).filter(ImageFilter.GaussianBlur(9))
    return layer


# ---------------------------------------------------------------- 8bit 立体爱心
def heart_cells(N: int = 16, M: int = 15) -> list[tuple[int, int]]:
    """隐函数 (x²+y²-1)³ - x²y³ ≤ 0 采样出爱心像素网格，k 越大越靠上。

    采样后清掉四邻皆空的孤立块，避免轮廓出现「耳朵」。
    """
    nx0, nx1 = -1.26, 1.26
    ny0, ny1 = -1.40, 1.10
    raw: set[tuple[int, int]] = set()
    for k in range(M):
        ny = ny0 + (ny1 - ny0) * (k / (M - 1))
        for i in range(N):
            nx = nx0 + (nx1 - nx0) * (i / (N - 1))
            v = (nx * nx + ny * ny - 1) ** 3 - (nx * nx) * (ny ** 3)
            if v <= 0:
                raw.add((i, k))
    cells = {(i, k) for (i, k) in raw
             if any(n in raw for n in ((i - 1, k), (i + 1, k), (i, k - 1), (i, k + 1)))}
    return sorted(cells)


def build_heart(center=(512.0, 356.0), target_w: float = 404.0,
                depth: int = 3, depth_ratio: float = 0.45) -> Image.Image:
    """斜二测挤出的 8bit 立体爱心。

    正面：正方形网格（心形正立）；厚度沿右上 45° 挤出，
    只在暴露边画顶面 / 右侧面 —— 45° 斜视的 3D 像素块。
    """
    cells = set(heart_cells())
    N = max(c[0] for c in cells) + 1
    M = max(c[1] for c in cells) + 1
    u = target_w / N                       # 单元边长
    du = u * depth_ratio                   # 每层深度偏移（右上 45°）
    dv = -u * depth_ratio

    def cell_xy(i: int, k: int) -> tuple[float, float]:
        """该 cell 正面左上角在「未偏移层」的屏幕坐标（y 向下为正）。"""
        return (i * u, (M - 1 - k) * u)

    # 包围盒（含挤出厚度）→ 居中
    xs = [cell_xy(i, k)[0] for i, k in cells]
    ys = [cell_xy(i, k)[1] for i, k in cells]
    min_x, max_x = min(xs), max(xs) + u + depth * du
    min_y, max_y = min(ys) + depth * dv, max(ys) + u
    cx0 = (min_x + max_x) / 2
    cy0 = (min_y + max_y) / 2
    off_x = center[0] - cx0
    off_y = center[1] - cy0

    def layer_origin(d: int) -> tuple[float, float]:
        return (off_x + d * du, off_y + d * dv)

    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def quad(x, y, w, h):
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    def top_face(x, y):
        return [(x, y), (x + u, y), (x + u + du, y + dv), (x + du, y + dv)]

    def side_face(x, y):
        return [(x + u, y), (x + u, y + u), (x + u + du, y + u + dv), (x + u + du, y + dv)]

    # --- 外描边底板：正面 mask 每块向外扩 pad，整体形成均匀描边 ---
    pad = max(2.0, u * 0.10)
    ox0, oy0 = layer_origin(0)
    for i, k in cells:
        x, y = cell_xy(i, k)
        d.polygon(quad(ox0 + x - pad, oy0 + y - pad, u + 2 * pad, u + 2 * pad),
                  fill=HEART_OUT + (255,))

    # --- 画家算法：由后（右上）往前（左下）逐层画 ---
    for depth_i in range(depth - 1, -1, -1):
        ox, oy = layer_origin(depth_i)
        for i, k in sorted(cells):
            x, y = cell_xy(i, k)
            exposed_top = (i, k + 1) not in cells
            exposed_right = (i + 1, k) not in cells
            # 正面
            d.polygon([(ox + x, oy + y), (ox + x + u, oy + y),
                       (ox + x + u, oy + y + u), (ox + x, oy + y + u)],
                      fill=HEART_FACE + (255,))
            if exposed_top:
                d.polygon([(ox + x, oy + y), (ox + x + u, oy + y),
                           (ox + x + u + du, oy + y + dv), (ox + x + du, oy + y + dv)],
                          fill=HEART_TOP + (255,))
            if exposed_right:
                d.polygon([(ox + x + u, oy + y), (ox + x + u, oy + y + u),
                           (ox + x + u + du, oy + y + u + dv), (ox + x + u + du, oy + y + dv)],
                          fill=HEART_SIDE + (255,))

    # --- 左上高光块（经典 8bit 心：两块相邻的白块） ---
    top_cells = sorted(cells, key=lambda c: (-c[1], c[0]))
    for i, k in top_cells[:2]:
        x, y = cell_xy(i, k)
        d.polygon([(ox0 + x + u * 0.14, oy0 + y + u * 0.14),
                   (ox0 + x + u * 0.60, oy0 + y + u * 0.14),
                   (ox0 + x + u * 0.60, oy0 + y + u * 0.60),
                   (ox0 + x + u * 0.14, oy0 + y + u * 0.60)],
                  fill=SPARK + (235,))
    return img


# ---------------------------------------------------------------- 组装
def build_master() -> Image.Image:
    canvas = build_background()
    canvas.alpha_composite(build_glow(512, 706, 470, 300, ROSE, 0.32))
    canvas.alpha_composite(build_glow(512, 236, 430, 330, VIOLET, 0.20))

    canvas.alpha_composite(build_steam())          # 两侧主蒸汽（在爱心后面）
    canvas.alpha_composite(build_cauldron())
    canvas.alpha_composite(build_rim_and_brew())

    # 爱心背后的粉色光环，让它从蒸汽里浮出来
    canvas.alpha_composite(build_glow(512, 386, 330, 310, ROSE_HI, 0.36))
    canvas.alpha_composite(build_heart())
    canvas.alpha_composite(build_steam(top_wisp=True))  # 爱心上方冒头的一小缕

    # 细边框
    edge = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        [3, 3, W - 4, W - 4], radius=int(W * 0.20), outline=BRASS + (110,), width=6)
    canvas.alpha_composite(edge.filter(ImageFilter.GaussianBlur(1)))
    return canvas


# ---------------------------------------------------------------- 小尺寸变体
def build_small_icon() -> Image.Image:
    """≤48px 用：只保留大爱心（锅和蒸汽在小尺寸下会糊成一团）。

    与全场景版共用背景与爱心绘制，保证视觉语言一致。
    """
    canvas = build_background()
    canvas.alpha_composite(build_glow(512, 520, 470, 420, ROSE, 0.30))
    canvas.alpha_composite(build_glow(512, 300, 430, 330, VIOLET, 0.16))
    canvas.alpha_composite(build_heart(center=(512.0, 486.0), target_w=620.0))

    edge = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle(
        [3, 3, W - 4, W - 4], radius=int(W * 0.20), outline=BRASS + (110,), width=6)
    canvas.alpha_composite(edge.filter(ImageFilter.GaussianBlur(1)))
    return canvas


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.makedirs(OUT_DIR, exist_ok=True)
    master = build_master()
    small = build_small_icon()

    master_path = os.path.join(OUT_DIR, "logo-master.png")
    master.save(master_path)

    # .ico：64px 以上用全场景，≤48px 注入「只保留大爱心」的简化变体。
    # ⚠️ 全部 10 个尺寸都必须显式提供：Pillow ICO 保存的回退分支会拿
    #    append_images 的最后一个图去 thumbnail（只缩不放），64+ 帧会错成 48px 内容。
    ico_path = os.path.join(OUT_DIR, "icon.ico")
    append = [(small if sz[0] <= 48 else master).resize(sz, Image.LANCZOS)
              for sz in ICO_SIZES]
    master.save(ico_path, sizes=ICO_SIZES, append_images=append)

    # PNG：小尺寸也用简化变体
    for size in (16, 32, 48):
        small.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT_DIR, f"logo-{size}.png"))
    for size in (64, 128, 256):
        master.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT_DIR, f"logo-{size}.png"))

    print(f"母版  -> {master_path}")
    print(f"图标  -> {ico_path}  (64+ 全场景 / <=48 大爱心简化形)")
    print(f"PNG   -> logo-16/32(简化) 64/128/256(全场景) @ {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
