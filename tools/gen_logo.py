#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""G-POT Loc 应用图标生成器（Pillow 单真源）

设计意图（老板 2026-10-09 口述 + 参考实拍渲染图二次修订）：
    一个正在熬煮的大锅，散发粉色的蒸汽，蒸汽中有个 8bit 风格的 3D 爱心，
    45° 角斜对着屏幕。

v2（参考图修订）：锅更大更圆、俯视开口能看到粉色沸腾液面与气泡、
    锁钉金属锅沿、爱心改热粉并加斜向光泽渐变、蒸汽收轻收雾。

实现要点：
  1. 单真源：所有图形都由本脚本生成，改这里再跑一次即可重建全部产物。
  2. 平滑层（背景 / 锅体 / 蒸汽）按 SS 倍超采样绘制再降采样，边缘干净。
  3. 爱心在最上层**硬边绘制**，不参与降采样糊化，保住 8bit 的锐利块面。
     立体感用「斜二测挤出（oblique extrusion）」：心形正面用正方形网格保持正立，
     厚度沿右上 45° 挤出，只在暴露边画顶面 / 右侧面 —— 即 45° 斜视的 3D 像素块；
     正面按「离左上角的距离」做光泽渐变，复刻参考图的釉面高光。

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
POT_LIT   = (0x3C, 0x31, 0x4B)   # 锅体受光面（铸铁）
POT_DARK  = (0x18, 0x11, 0x24)   # 锅体暗面
RIM_METAL = (0x5C, 0x4C, 0x74)   # 锅沿金属带
POT_INNER = (0x1E, 0x15, 0x2C)   # 锅内壁
BRASS     = (0xDD, 0xA0, 0xBC)   # 黄铜/玫瑰金描边
ROSE      = (0xE8, 0x62, 0x9A)   # 玫瑰粉（主光源）
ROSE_HI   = (0xF5, 0x8B, 0xC0)   # 粉高光
VIOLET    = (0x9B, 0x6B, 0xF0)   # 紫（副光源）
LIQ_BASE  = (0xD8, 0x45, 0x86)   # 液面基色
LIQ_HI    = (0xF2, 0x77, 0xAC)   # 液面亮部
BUBBLE    = (0xFB, 0xA7, 0xCF)   # 气泡
HEART_FACE= (0xF0, 0x50, 0x9B)   # 爱心正面（热粉）
HEART_TOP = (0xFF, 0xA0, 0xD4)   # 爱心顶面（亮）
HEART_SIDE= (0xC2, 0x2E, 0x72)   # 爱心右侧面（暗）
HEART_OUT = (0x54, 0x17, 0x38)   # 爱心外描边
GLOSS     = (0xFF, 0xD6, 0xEB)   # 釉面高光（混入正面）
SPARK     = (0xFF, 0xF3, 0xF9)   # 高光点


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
    """锅体轮廓：上接锅沿，中下部鼓腹，底部收圆。"""
    pts: list[tuple[float, float]] = []
    step = (bot_y - rim_y) / 90.0
    for i in range(91):
        yy = rim_y + step * i
        t = (yy - bulge_cy) / bulge_ry
        if abs(t) <= 1.0:
            half = bulge_rx * math.sqrt(max(0.0, 1 - t * t))
            pts.append((cx - half, yy))
    cut_half = bulge_rx * math.sqrt(max(0.0, 1 - ((bot_y - bulge_cy) / bulge_ry) ** 2))
    for i in range(1, 40):
        a = math.pi * (1 - i / 39.0)
        pts.append((cx - cut_half * math.cos(a), bot_y - cap_ry * math.sin(a)))
    for i in range(1, 40):
        a = math.pi * (i / 39.0)
        pts.append((cx + cut_half * math.cos(a), bot_y - cap_ry * math.sin(a)))
    for i in range(90, -1, -1):
        yy = rim_y + step * i
        t = (yy - bulge_cy) / bulge_ry
        if abs(t) <= 1.0:
            half = bulge_rx * math.sqrt(max(0.0, 1 - t * t))
            pts.append((cx + half, yy))
    pts.append((cx - bulge_rx * math.sqrt(max(0.0, 1 - ((rim_y - bulge_cy) / bulge_ry) ** 2)), rim_y))
    return pts


# 锅体几何参数（母版坐标）——v2：更宽的鼓腹 + 俯视大开口
POT = dict(cx=512.0, rim_y=606.0, rim_rx=302.0, rim_ry=104.0,
           bot_y=830.0, bulge_rx=338.0, bulge_cy=710.0, bulge_ry=226.0, cap_ry=52.0)


def build_cauldron() -> Image.Image:
    """把手（先画，被锅体遮住内侧）+ 三条腿 + 锅体 + 左上受光弧。"""
    big = W * SS
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    cx, rim_rx = POT["cx"], POT["rim_rx"]

    # --- 把手：两个侧环（挂在锅沿带上） ---
    handles = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    hd = ScaledDraw(handles, SS)
    for sx in (-1, 1):
        bx = cx + sx * (rim_rx - 2)
        hd.ellipse([bx - 58, 604, bx + 58, 706], outline=BRASS + (165,), width=int(17 * SS))
    paste(out, downscale(handles))

    # --- 三条腿（中间一条是前腿，略低） ---
    legs = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ld = ScaledDraw(legs, SS)
    for lx, y1 in ((cx - 176, 878), (cx, 896), (cx + 176, 878)):
        w_top, w_bot = 46, 30
        y0 = 792
        ld.polygon([(lx - w_top / 2, y0), (lx + w_top / 2, y0),
                    (lx + w_bot / 2, y1), (lx - w_bot / 2, y1)], fill=POT_DARK + (255,))
    paste(out, downscale(legs))

    # --- 锅体（渐变填充） ---
    outline_pts = _body_outline(cx, POT["rim_y"], POT["bot_y"],
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
        if p[1] > POT["rim_y"] + 132:
            break
        hi_pts.append(p)
    ad.line(hi_pts, fill=BRASS + (135,), width=int(10 * SS), joint="curve")
    arc = downscale(arc).filter(ImageFilter.GaussianBlur(3))
    arc.putalpha(arc.getchannel("A").point(lambda v: int(v * 0.75)))
    paste(out, arc)
    return out


def build_rim_and_brew() -> Image.Image:
    """铆钉金属锅沿 + 锅内壁 + 粉色沸腾液面（气泡/泡沫）。"""
    big = W * SS
    out = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ScaledDraw(layer, SS)
    cx, rim_y = POT["cx"], POT["rim_y"]
    rim_rx, rim_ry = POT["rim_rx"], POT["rim_ry"]

    # 锅沿金属带（外圈）→ 锅内壁（中圈）→ 液面（内圈）
    d.ellipse([cx - rim_rx, rim_y - rim_ry, cx + rim_rx, rim_y + rim_ry],
              fill=RIM_METAL + (255,))
    d.ellipse([cx - rim_rx + 26, rim_y - rim_ry + 20, cx + rim_rx - 26, rim_y + rim_ry - 20],
              fill=POT_INNER + (255,))
    layer = downscale(layer)
    paste(out, layer)

    # 铆钉：沿锅沿带的中线，只钉在朝向观众的下半弧
    rivets = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    rd = ScaledDraw(rivets, SS)
    rx_mid, ry_mid = (rim_rx + (rim_rx - 26)) / 2, (rim_ry + (rim_ry - 20)) / 2
    for i in range(11):
        th = math.pi * (0.10 + 0.80 * i / 10)
        bx = cx + rx_mid * math.cos(th)
        by = rim_y + ry_mid * math.sin(th)
        r = 9.5
        rd.ellipse([bx - r, by - r * 0.72, bx + r, by + r * 0.72],
                   fill=mix(BRASS, (255, 255, 255), 0.22, 235),
                   outline=POT_INNER + (200,), width=max(1, int(2.2 * SS)))
    paste(out, downscale(rivets))

    # 液面：热粉基底 + 后缘反光（光从后上方来，前缘深后缘亮）
    liquid = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ld2 = ImageDraw.Draw(liquid)
    lx, ly, lrx, lry = cx, rim_y - 2, rim_rx - 44, rim_ry - 30
    ld2.ellipse([lx - lrx, ly - lry, lx + lrx, ly + lry], fill=LIQ_BASE + (255,))
    ld2.ellipse([lx - lrx + 64, ly - lry + 10, lx + lrx - 64, ly + 6],
                fill=mix(LIQ_BASE, LIQ_HI, 0.65, 210))
    # 液面在内壁上映出的一圈粉边
    ld2.ellipse([lx - lrx - 12, ly - lry - 9, lx + lrx + 12, ly + lry + 9],
                outline=mix(LIQ_HI, ROSE, 0.5, 150), width=6)
    paste(out, liquid.filter(ImageFilter.GaussianBlur(1)))

    # 气泡 + 泡沫
    bub = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bub)
    for bx, by, r in ((-158, -8, 15), (-74, 10, 10), (6, -16, 19), (92, 2, 13),
                      (164, -4, 9), (-16, 22, 8), (58, 24, 7), (-112, 18, 8),
                      (126, 20, 6), (-206, 6, 7), (210, 10, 6)):
        x, y = cx + bx, rim_y + by
        bd.ellipse([x - r, y - r * 0.66, x + r, y + r * 0.66], fill=BUBBLE + (240,))
        bd.ellipse([x - r * 0.42, y - r * 0.52, x - r * 0.05, y - r * 0.16],
                   fill=mix(BUBBLE, SPARK, 0.6, 235))
    for fx, fy in ((-38, -30), (12, -34), (52, -26), (-2, -24), (86, -30), (-84, -26)):
        x, y = cx + fx, rim_y + fy
        bd.ellipse([x - 4, y - 2.6, x + 4, y + 2.6], fill=mix(BUBBLE, SPARK, 0.45, 210))
    paste(out, bub.filter(ImageFilter.GaussianBlur(1)))
    return out


# ---------------------------------------------------------------- 蒸汽
def _plume(d: ScaledDraw, x0: float, y0: float, height: float, amp: float,
           freq: float, phase: float, color, w0: float, w1: float,
           fade: tuple[int, int] = (225, 55), steps: int = 56):
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
        a = int(lerp(fade[0], fade[1], t ** 1.1))
        d.line([pts[i], pts[i + 1]], fill=color + (a,),
               width=max(1, int(round(w))), joint="curve")


def build_steam(top_wisp: bool = False) -> Image.Image:
    """top_wisp=False：锅口两侧的主蒸汽（画在爱心后面）；
    top_wisp=True：爱心上方冒头的一小缕（画在爱心前面）。v2：更轻更雾。"""
    big = W * SS
    layer = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ScaledDraw(layer, SS)
    cx = POT["cx"]
    mist = mix(ROSE_HI, (255, 255, 255), 0.35)[:3]
    if top_wisp:
        specs = [(cx - 6, 168, 112, 38, 1.6, 0.8, mist, 56, 10, (190, 60))]
    else:
        specs = [
            # x0, 起始y, 高度, 摆幅, 频率, 相位, 颜色, 底宽, 顶宽, 渐隐
            (cx - 244, 570, 340, 62, 1.8, 0.5, mist, 84, 14, (185, 45)),
            (cx + 240, 578, 322, 56, 2.1, 1.5, mist, 76, 12, (175, 42)),
            (cx - 300, 520, 260, 44, 2.4, 2.9, mix(ROSE, (255, 255, 255), 0.5)[:3], 48, 8, (120, 30)),
            (cx + 298, 528, 246, 42, 2.7, 4.0, mix(ROSE_HI, (255, 255, 255), 0.5)[:3], 44, 8, (115, 28)),
        ]
    base = 570.0
    for x0, _, h, amp, freq, ph, col, w0, w1, fd in specs:
        y0 = 168.0 if top_wisp else base
        _plume(d, x0, y0, h, amp, freq, ph, col, w0, w1, fade=fd)
    layer = downscale(layer).filter(ImageFilter.GaussianBlur(10))
    return layer


def build_mist() -> Image.Image:
    """爱心底部与液面交界处的一团白粉雾（参考图里心尖没入蒸汽的效果）。"""
    layer = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([512 - 152, 494, 512 + 152, 584], fill=(255, 219, 236, 105))
    d.ellipse([512 - 86, 512, 512 + 86, 566], fill=(255, 231, 243, 90))
    return layer.filter(ImageFilter.GaussianBlur(26))


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


def build_heart(center=(512.0, 350.0), target_w: float = 428.0,
                depth: int = 3, depth_ratio: float = 0.45) -> Image.Image:
    """斜二测挤出的 8bit 立体爱心（釉面高光版）。

    正面：正方形网格（心形正立），并按「离左上角的距离」混入 GLOSS 高光，
    复刻参考图的釉面反光；厚度沿右上 45° 挤出，只在暴露边画顶面 / 右侧面。
    """
    cells = set(heart_cells())
    N = max(c[0] for c in cells) + 1
    M = max(c[1] for c in cells) + 1
    u = target_w / N                       # 单元边长
    du = u * depth_ratio                   # 每层深度偏移（右上 45°）
    dv = -u * depth_ratio

    def cell_xy(i: int, k: int) -> tuple[float, float]:
        return (i * u, (M - 1 - k) * u)

    xs = [cell_xy(i, k)[0] for i, k in cells]
    ys = [cell_xy(i, k)[1] for i, k in cells]
    min_x, max_x = min(xs), max(xs) + u + depth * du
    min_y, max_y = min(ys) + depth * dv, max(ys) + u
    off_x = center[0] - (min_x + max_x) / 2
    off_y = center[1] - (min_y + max_y) / 2

    def layer_origin(d: int) -> tuple[float, float]:
        return (off_x + d * du, off_y + d * dv)

    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def quad(x, y, w, h):
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]

    def face_shade(i: int, k: int) -> float:
        """正面釉面：越靠左上越亮（复刻参考图的斜向反光）。"""
        t = (i / (N - 1)) * 0.55 + ((M - 1 - k) / (M - 1)) * 0.45
        return 0.30 * (1 - t)

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
            # 正面（带釉面渐变）
            d.polygon([(ox + x, oy + y), (ox + x + u, oy + y),
                       (ox + x + u, oy + y + u), (ox + x, oy + y + u)],
                      fill=mix(HEART_FACE, GLOSS, face_shade(i, k)))
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
                  fill=SPARK + (240,))
    return img


# ---------------------------------------------------------------- 组装
def build_master() -> Image.Image:
    canvas = build_background()
    # 锅身后的玫瑰光：把近黑的铸铁从深紫底里衬出来
    canvas.alpha_composite(build_glow(512, 664, 500, 330, ROSE, 0.36))
    canvas.alpha_composite(build_glow(512, 240, 430, 320, VIOLET, 0.18))

    canvas.alpha_composite(build_steam())          # 两侧主蒸汽（在爱心后面）
    canvas.alpha_composite(build_cauldron())
    canvas.alpha_composite(build_rim_and_brew())
    canvas.alpha_composite(build_mist())           # 心尖没入的白粉雾

    # 爱心背后的粉色光环，让它从蒸汽里浮出来
    canvas.alpha_composite(build_glow(512, 380, 330, 300, ROSE_HI, 0.30))
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
