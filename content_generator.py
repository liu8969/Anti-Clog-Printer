"""防堵头测试页生成模块

三种图案（config: content.pattern）：

- ``coverage``（默认）：**全喷嘴斜线覆盖页**。C/M/Y/K 各占一整列，列内用满页高的斜线幕
  铺满，再加一条满高实心竖条；黑墨默认加强（颜料黑最易堵）。斜线跨过的每个高度都对应
  喷头的不同行，因此每一行喷孔每趟走纸都会出墨 —— 这是"用上全部喷孔"的关键。
- ``classic``：经典彩色页（渐变色条 + 喷嘴网格），保留给需要看色彩表现的场景。
- ``link_test``：极简省墨细色带页，**只用于验证打印链路，不防堵**。

设计依据（EPSON L6370 实测，IPP Get-Printer-Attributes）：

- 四边不可打印边距 3mm（media-col-default）→ 内容画在 3.4mm 以内；
- URF/JPEG 光栅 300dpi（urf-supported=RS300）→ coverage 默认 300dpi A4（2480x3508）；
- A4 四色喷头竖向约 180~400 行（15~34mm），IPP 不暴露喷孔数
  → 斜线幕在竖直方向连续铺满整页，无论喷头多高都能覆盖全部喷孔；
- 爱普生官方喷嘴检查页同样是"每个色块一堆浅斜线，线中缺口=该位置喷孔堵塞"
  （参考 https://asm.epson.eu/en_IE/faq/KA-01531 ）。

旧的细色带只有 6px（200dpi → 0.76mm）高，300dpi 下约等于 9 行喷孔，不足喷头高度的
5% —— 这正是"过一段时间黑色堵了一点点"的原因。
"""

import os
import tempfile
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# 图案与档位
PATTERNS = ("coverage", "classic", "link_test")
DEFAULT_PATTERN = "coverage"
# 档位 → 每个喷孔每趟走纸连续吐出的点数（coverage 图案）
DUTY_RUN = {"eco": 4, "standard": 8, "strong": 16}
DEFAULT_DUTY = "standard"
DPI_CHOICES = (200, 300)
DEFAULT_DPI = 300

# 版面尺寸（毫米）
MARGIN_MM = 3.4       # 略大于打印机 3mm 不可打印边距
RULER_MM = 6.0        # 左侧毫米标尺带宽度（要放得下 3 位数字，不能压到 K 色块）
HEADER_H = 205        # 页眉高度（像素，与 dpi 无关：字号是固定像素）
FOOTER_H = 95         # 页脚高度（像素）
LABEL_H = 40          # 色块标签带高度（像素）
GUTTER = 6            # 色块之间的白缝（像素）
SLOPE_DIV = 4         # 斜线斜率：横跨一个色块上升 1/4 块宽
LINE_INK_ML_PER_PERCENT = 0.0056  # 5% 覆盖≈0.028ml（127ml 黑墨≈4500 页@5%）

# 色块顺序：黑在最左（黑墨最易堵，打出来最醒目）
COLOR_ZONES = (
    ("K", (0, 0, 0), "黑"),
    ("C", (0, 255, 255), "青"),
    ("M", (255, 0, 255), "洋红"),
    ("Y", (255, 255, 0), "黄"),
)


def _a4_px(dpi):
    """A4 竖向在指定 dpi 下的像素尺寸（200dpi → 1654x2339，与原图完全一致）"""
    return (round(210 / 25.4 * dpi), round(297 / 25.4 * dpi))


def _flag(value, default):
    """配置值 → 布尔：None 用默认；字符串支持 1/true/yes/on"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


class ContentGenerator:
    """生成防堵头测试页，输出 JPEG（打印机兼容性最好）"""

    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------ #
    #  配置解析（非法值一律回退默认，保证调度线程永不因配置崩掉）
    # ------------------------------------------------------------------ #

    def resolve_pattern(self):
        """显式 content.pattern 优先；否则兼容旧开关 content.test_mode。

        旧版只有 test_mode 一个开关（True=细色带）。升级后：
        配置里没写 pattern 时，test_mode=True 仍得到细色带页（行为不突变），
        否则得到新的全喷嘴覆盖页。
        """
        raw = self._config.get("content.pattern")
        pattern = raw.strip().lower() if isinstance(raw, str) else ""
        if pattern in PATTERNS:
            return pattern
        if _flag(self._config.get("content.test_mode"), False):
            return "link_test"
        return DEFAULT_PATTERN

    def resolve_duty(self):
        raw = self._config.get("content.duty")
        duty = raw.strip().lower() if isinstance(raw, str) else ""
        return duty if duty in DUTY_RUN else DEFAULT_DUTY

    def resolve_dpi(self):
        try:
            dpi = int(self._config.get("content.dpi", DEFAULT_DPI))
        except (TypeError, ValueError):
            return DEFAULT_DPI
        return dpi if dpi in DPI_CHOICES else DEFAULT_DPI

    # ------------------------------------------------------------------ #
    #  几何与墨量估算（绘图与 UI 提示共用同一套计算）
    # ------------------------------------------------------------------ #

    def _coverage_geometry(self, width, height, dpi, run, k_boost, bars, ruler):
        margin = max(8, round(MARGIN_MM / 25.4 * dpi))
        ruler_w = max(12, round(RULER_MM / 25.4 * dpi)) if ruler else 0
        x_left = margin + ruler_w
        x_right = width - margin
        zone_w = max(40, (x_right - x_left) // 4)
        label_top = margin + HEADER_H
        y_top = label_top + LABEL_H
        y_bot = max(y_top + 10, height - margin - FOOTER_H)
        rise = max(6, zone_w // SLOPE_DIV)
        thickness = max(1, round(run / 4))
        bar_w = max(2, run // 2)
        zone_h = y_bot - y_top
        n_lines = zone_h // rise + 2

        # 墨量估算：斜线幕像素数 + 竖条像素数（K 加强则各翻一倍）
        curtain_px = n_lines * zone_w * 1.03 * thickness
        bar_px = zone_h * bar_w if bars else 0
        page_px = width * height
        per_color = {}
        for label, _color, _cn in COLOR_ZONES:
            boost = 2 if (k_boost and label == "K") else 1
            per_color[label] = (curtain_px + bar_px) * boost / page_px * 100
        total = sum(per_color.values())

        return {
            "width": width, "height": height, "dpi": dpi, "run": run,
            "margin": margin, "ruler_w": ruler_w, "x_left": x_left,
            "zone_w": zone_w, "label_top": label_top, "y_top": y_top, "y_bot": y_bot,
            "rise": rise, "thickness": thickness, "bar_w": bar_w, "n_lines": n_lines,
            "bars": bars, "ruler": ruler, "k_boost": k_boost,
            "coverage_percent": per_color, "coverage_total_percent": total,
        }

    def describe(self, pattern=None, duty=None, dpi=None):
        """返回当前/指定设置的摘要（不生成图片），供 UI 提示与 CLI 打印"""
        pattern = pattern or self.resolve_pattern()
        duty = duty or self.resolve_duty()
        dpi = dpi or self.resolve_dpi()
        width, height = _a4_px(dpi)
        if pattern == "coverage":
            geo = self._coverage_geometry(
                width, height, dpi, DUTY_RUN[duty],
                _flag(self._config.get("content.k_boost"), True),
                _flag(self._config.get("content.bars"), True),
                _flag(self._config.get("content.ruler"), True),
            )
            return {
                "pattern": pattern, "duty": duty, "dpi": dpi,
                "width": width, "height": height,
                "run": geo["run"], "thickness": geo["thickness"],
                "rise": geo["rise"], "lines_per_zone": geo["n_lines"],
                "coverage_percent": geo["coverage_percent"],
                "coverage_total_percent": geo["coverage_total_percent"],
                "ink_ml_per_page": geo["coverage_total_percent"] * LINE_INK_ML_PER_PERCENT,
            }
        width, height = _a4_px(200)
        legacy_pct = 0.26 if pattern == "link_test" else 4.9  # 旧图案实测值
        return {
            "pattern": pattern, "duty": duty, "dpi": 200,
            "width": width, "height": height,
            "coverage_total_percent": legacy_pct,
            "ink_ml_per_page": legacy_pct * LINE_INK_ML_PER_PERCENT,
        }

    def summary_line(self, pattern=None, duty=None):
        """一行中文摘要（UI 标签用）"""
        info = self.describe(pattern=pattern, duty=duty)
        labels = {"coverage": "全喷嘴斜线覆盖", "classic": "经典彩色页",
                  "link_test": "细色带自检（不防堵）"}
        name = labels.get(info["pattern"], info["pattern"])
        if info["pattern"] == "coverage":
            per = " / ".join(f"{k} {v:.1f}%" for k, v in info["coverage_percent"].items())
            return (f"{name} · 强度 {info['duty']}：每孔每趟≈{info['run']}点，"
                    f"整页覆盖≈{info['coverage_total_percent']:.1f}%（{per}），"
                    f"约 {info['ink_ml_per_page']:.3f}ml/页")
        return f"{name}：整页覆盖≈{info['coverage_total_percent']:.1f}%，不保证覆盖全部喷孔"

    # ------------------------------------------------------------------ #
    #  字体
    # ------------------------------------------------------------------ #

    def _load_font(self, size):
        """按字号加载一个字体（找不到任何中文字体时回退 PIL 默认位图字体）"""
        font_paths = [
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            # Linux (Docker)
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    return ImageFont.truetype(fp, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    def _load_fonts(self):
        return (self._load_font(56), self._load_font(32), self._load_font(24))

    # ------------------------------------------------------------------ #
    #  图案一：全喷嘴斜线覆盖页（默认）
    # ------------------------------------------------------------------ #

    def _build_coverage_image(self, dpi=None, duty=None, k_boost=None,
                              bars=None, ruler=None):
        """全喷嘴斜线覆盖页：每个颜色一整列，满页高斜线幕 + 满高竖条。

        斜线：横跨一个色块上升 zone_w/4，线距=上升量 → 相邻两条首尾相接，
        竖直方向连续覆盖整页；每一行喷孔在自己的高度上都会经过至少一条斜线，
        因此每趟走纸都出墨。缺口（堵孔）在相邻斜线上呈斜向重复，便于定位。
        """
        dpi = dpi or self.resolve_dpi()
        duty = duty or self.resolve_duty()
        if duty not in DUTY_RUN:
            duty = DEFAULT_DUTY
        k_boost = _flag(k_boost if k_boost is not None
                        else self._config.get("content.k_boost"), True)
        bars = _flag(bars if bars is not None
                     else self._config.get("content.bars"), True)
        ruler = _flag(ruler if ruler is not None
                      else self._config.get("content.ruler"), True)
        run = DUTY_RUN[duty]

        width, height = _a4_px(dpi)
        geo = self._coverage_geometry(width, height, dpi, run, k_boost, bars, ruler)
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        title_font, normal_font, small_font = self._load_fonts()

        # ---- 页眉（黑字：顺带喂 K 喷孔）----
        y = geo["margin"]
        draw.text((geo["margin"], y), "打印机防堵头 · 全喷嘴斜线覆盖页",
                  fill=(0, 0, 0), font=title_font)
        y += 70
        draw.text((geo["margin"], y),
                  f"打印时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
                  fill=(0, 0, 0), font=normal_font)
        y += 44
        draw.text(
            (geo["margin"], y),
            f"图案=coverage 强度={duty} 每孔每趟≈{run}点 DPI={dpi} "
            f"预计覆盖≈{geo['coverage_total_percent']:.1f}%",
            fill=(60, 60, 60), font=small_font,
        )
        y += 40
        custom_text = self._config.get("content.custom_text", "")
        custom_text = custom_text.strip() if isinstance(custom_text, str) else ""
        if custom_text:
            draw.text((geo["margin"], y), f"备注: {custom_text}",
                      fill=(0, 0, 0), font=small_font)

        # ---- 左侧毫米标尺（缺口位置定位用，刻度线很细，几乎不费墨）----
        if ruler:
            ruler_font = self._load_font(max(11, round(dpi * 0.055)))
            self._draw_ruler(draw, geo, dpi, ruler_font)

        # ---- 4 个色块 ----
        for idx, (label, color, cn) in enumerate(COLOR_ZONES):
            zx0 = geo["x_left"] + idx * geo["zone_w"]
            zx1 = zx0 + geo["zone_w"] - GUTTER
            draw.text((zx0 + 4, geo["label_top"]), f"{label} {cn}",
                      fill=color, font=normal_font)

            boost = 2 if (k_boost and label == "K") else 1
            for s in range(boost):
                y_a = geo["y_top"] + s * (geo["rise"] // 2)
                while y_a < geo["y_bot"]:
                    y_b = min(y_a + geo["rise"], geo["y_bot"])
                    draw.line([(zx0, y_a), (zx1, y_b)],
                              fill=color, width=geo["thickness"])
                    y_a += geo["rise"]

            if bars:
                bar_w = geo["bar_w"] * boost
                draw.rectangle([zx0, geo["y_top"], zx0 + bar_w - 1, geo["y_bot"]],
                               fill=color)

        # ---- 页脚说明 ----
        fy = geo["y_bot"] + 24
        draw.text((geo["margin"], fy),
                  "每条斜线由不同喷孔打印：线中出现缺口＝该位置喷孔堵塞，"
                  "相邻线缺口呈斜向重复即可定位（对照爱普生官方喷嘴检查页）。",
                  fill=(90, 90, 90), font=small_font)
        draw.text((geo["margin"], fy + 34),
                  "--- 此页面由打印机自动防堵程序生成 ---",
                  fill=(160, 160, 160), font=small_font)
        return img

    @staticmethod
    def _draw_ruler(draw, geo, dpi, font):
        """左侧毫米标尺：每 10mm 短刻度，每 50mm 长刻度 + 数字（mm）

        数字放不下时整段跳过，避免压到 K 色块（标尺只是辅助定位用）。
        """
        x = geo["margin"]
        step = max(4, round(10 / 25.4 * dpi))
        tick_minor = max(3, round(dpi * 0.02))
        tick_major = max(6, round(dpi * 0.045))
        text_x = x + tick_major + max(2, round(dpi * 0.01))
        limit = geo["x_left"] - 2
        mm = 0
        y = geo["y_top"]
        while y <= geo["y_bot"]:
            if mm % 50 == 0:
                draw.line([(x, y), (x + tick_major, y)], fill=(0, 0, 0), width=2)
                label = str(mm)
                if text_x + draw.textlength(label, font=font) <= limit:
                    draw.text((text_x, y - max(6, round(dpi * 0.04))), label,
                              fill=(0, 0, 0), font=font)
            else:
                draw.line([(x, y), (x + tick_minor, y)], fill=(120, 120, 120), width=1)
            y += step
            mm += 10

    # ------------------------------------------------------------------ #
    #  图案二：经典彩色页（渐变 + 网格），保留兼容
    # ------------------------------------------------------------------ #

    def _build_image(self):
        """构建 A4 测试页 PIL Image（渐变色条 + 喷嘴网格）"""
        width, height = _a4_px(200)
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        title_font, normal_font, small_font = self._load_fonts()

        y = 60
        draw.text((60, y), "打印机防堵头自动测试页", fill="black", font=title_font)
        y += 80

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((60, y), f"打印时间: {now_str}", fill="black", font=normal_font)
        y += 50

        custom_text = self._config.get("content.custom_text", "")
        custom_text = custom_text.strip() if isinstance(custom_text, str) else ""
        if custom_text:
            draw.text((60, y), f"备注: {custom_text}", fill="black", font=normal_font)
            y += 50

        y += 40
        bar_w = width - 120

        # 渐变色条（细）
        draw.text((60, y), "渐变色测试", fill="black", font=normal_font)
        y += 48
        grad_h = 18
        for label, sc, ec in [
            ("C → K 渐变", (0, 255, 255), (0, 0, 0)),
            ("M → K 渐变", (255, 0, 255), (0, 0, 0)),
            ("Y → K 渐变", (255, 255, 0), (0, 0, 0)),
        ]:
            for x in range(bar_w):
                r = int(sc[0] + (ec[0] - sc[0]) * x / bar_w)
                g = int(sc[1] + (ec[1] - sc[1]) * x / bar_w)
                b = int(sc[2] + (ec[2] - sc[2]) * x / bar_w)
                draw.line([(60 + x, y), (60 + x, y + grad_h)], fill=(r, g, b), width=1)
            draw.text((60 + bar_w + 15, y + 4), label, fill="black", font=small_font)
            y += grad_h + 8

        y += 20

        # 喷嘴网格（细）
        draw.text((60, y), "喷嘴网格测试", fill="black", font=normal_font)
        y += 48
        for color in [
            (0, 255, 255), (255, 0, 255), (255, 255, 0),
            (0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255),
        ]:
            for i in range(0, bar_w, 3):
                draw.line([(60 + i, y), (60 + i, y + 10)], fill=color, width=1)
            y += 14

        y += 40
        draw.text((60, y), "--- 此页面由打印机自动防堵程序生成 ---",
                  fill=(160, 160, 160), font=small_font)

        return img

    # ------------------------------------------------------------------ #
    #  图案三：极简省墨细色带（仅验证打印链路）
    # ------------------------------------------------------------------ #

    def _build_test_image(self):
        """
        极简省墨测试页（A4 竖向，与完整模式同方向，确保打印机原样打印不缩放旋转）：
        标题/时间文字 + 一条横贯纸宽的 6px 四色细色带。

        ⚠️ 该色带只有 6px（200dpi → 0.76mm），300dpi 下≈9 行喷孔，不足喷头高度的 5%，
        不能用于日常防堵；只用来确认"能不能打出来"。
        """
        width, height = _a4_px(200)
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        _, normal_font, small_font = self._load_fonts()

        # 说明文字（灰色，省墨）
        draw.text((60, 120), "省墨测试页 - 打印机自动防堵（不防堵）",
                  fill=(80, 80, 80), font=normal_font)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((60, 180), f"打印时间: {now_str}", fill=(150, 150, 150), font=small_font)
        draw.text((60, 240), "TEST MODE", fill=(180, 180, 180), font=small_font)

        # 一条细带，等分为 C / M / Y / K 四段，横贯纸宽
        y = 320
        bar_h = 6
        seg_w = width // 4
        for i, color in enumerate([(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 0, 0)]):
            draw.rectangle([i * seg_w, y, (i + 1) * seg_w - 1, y + bar_h], fill=color)

        return img

    # ------------------------------------------------------------------ #
    #  对外接口
    # ------------------------------------------------------------------ #

    def generate(self, test_mode=None, pattern=None, duty=None, out_path=None):
        """生成测试页 JPEG，返回文件路径。

        pattern: coverage / classic / link_test，优先于一切；
        test_mode: 旧 API 兼容开关，True=细色带自检页（不防堵）；
                   False 时仍按配置里的 pattern 走（默认 coverage）。
        out_path: 指定输出路径（预览另存用），不传则写临时目录。
        """
        if pattern is None:
            pattern = "link_test" if test_mode else self.resolve_pattern()
        if pattern not in PATTERNS:
            pattern = DEFAULT_PATTERN

        if pattern == "link_test":
            img = self._build_test_image()
        elif pattern == "classic":
            img = self._build_image()
        else:
            img = self._build_coverage_image(duty=duty)

        # 旋转补偿（部分打印机连 A4 竖向图也旋转时开启）对所有图案一致生效
        if _flag(self._config.get("content.test_rotate"), False):
            img = img.rotate(90, expand=True)

        if not out_path:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = {"link_test": "_test", "coverage": "_coverage"}.get(pattern, "")
            out_path = os.path.join(
                tempfile.gettempdir(), f"printer_anti_clog{suffix}_{ts}.jpg")
            # 同秒多次打印时避免覆盖已有文件
            n = 1
            while os.path.exists(out_path):
                out_path = os.path.join(
                    tempfile.gettempdir(),
                    f"printer_anti_clog{suffix}_{ts}_{n}.jpg")
                n += 1
        else:
            out_path = os.path.abspath(out_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

        if pattern == "coverage":
            # 4:4:4 + 高质量：否则 1~2px 的彩色斜线会被 JPEG 抽色糊掉
            img.save(out_path, "JPEG", quality=95, subsampling=0)
        else:
            img.save(out_path, "JPEG", quality=92)

        if out_path.startswith(tempfile.gettempdir()):
            self._cleanup_old_files()
        return out_path

    @staticmethod
    def _cleanup_old_files(max_age_seconds=7 * 24 * 3600):
        """清理 7 天前的旧测试页临时文件，防止 /tmp 积累"""
        try:
            now = time.time()
            for fn in os.listdir(tempfile.gettempdir()):
                if not (fn.startswith("printer_anti_clog_") and fn.endswith(".jpg")):
                    continue
                fp = os.path.join(tempfile.gettempdir(), fn)
                try:
                    if now - os.path.getmtime(fp) > max_age_seconds:
                        os.remove(fp)
                except OSError:
                    pass
        except OSError:
            pass
