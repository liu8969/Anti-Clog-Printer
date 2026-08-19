"""防堵头彩色测试页生成模块"""

import os
import tempfile
import time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont


class ContentGenerator:
    """生成包含 CMYK 全色喷嘴测试图案，输出 JPEG（打印机兼容性最好）和 PDF"""

    def __init__(self, config):
        self._config = config

    def _load_fonts(self):
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
                    return (
                        ImageFont.truetype(fp, 56),
                        ImageFont.truetype(fp, 32),
                        ImageFont.truetype(fp, 24),
                    )
                except OSError:
                    continue
        d = ImageFont.load_default()
        return d, d, d

    def _build_image(self):
        """构建 A4 测试页 PIL Image（渐变色条 + 喷嘴网格，线条细，更省墨）"""
        width, height = 1654, 2339
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        title_font, normal_font, small_font = self._load_fonts()

        y = 60
        draw.text((60, y), "打印机防堵头自动测试页", fill="black", font=title_font)
        y += 80

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((60, y), f"打印时间: {now_str}", fill="black", font=normal_font)
        y += 50

        custom_text = self._config.get("content.custom_text", "").strip()
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

    def _build_test_image(self):
        """
        极简省墨测试页（A4 竖向，与完整模式同方向，确保打印机原样打印不缩放旋转）：
        标题/时间文字 + 一条横贯纸宽的 6px 四色细色带。
        整页几乎全白，墨量远小于完整测试页，用于验证打印链路。
        """
        width, height = 1654, 2339
        img = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(img)
        _, normal_font, small_font = self._load_fonts()

        # 说明文字（灰色，省墨）
        draw.text((60, 120), "省墨测试页 - 打印机自动防堵", fill=(80, 80, 80), font=normal_font)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        draw.text((60, 180), f"打印时间: {now_str}", fill=(150, 150, 150), font=small_font)
        draw.text((60, 240), "TEST MODE", fill=(180, 180, 180), font=small_font)

        # 一条细带，等分为 C / M / Y / K 四段，横贯纸宽
        y = 320
        bar_h = 6
        seg_w = width // 4
        for i, color in enumerate([(0, 255, 255), (255, 0, 255), (255, 255, 0), (0, 0, 0)]):
            draw.rectangle([i * seg_w, y, (i + 1) * seg_w - 1, y + bar_h], fill=color)

        if self._config.get("content.test_rotate", False):
            # 备用：万一打印机连 A4 竖向图也旋转，可开此补偿
            img = img.rotate(90, expand=True)

        return img

    def generate(self, test_mode=None):
        """
        生成防堵头测试页 JPEG 文件，返回路径。
        test_mode=True 时生成极简省墨细色带页（验证打印链路用）；
        不传或为 None 时读取配置 content.test_mode。
        """
        if test_mode is None:
            test_mode = bool(self._config.get("content.test_mode", False))
        img = self._build_test_image() if test_mode else self._build_image()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "_test" if test_mode else ""
        path = os.path.join(tempfile.gettempdir(), f"printer_anti_clog{suffix}_{ts}.jpg")
        # 同秒多次打印时避免覆盖已有文件
        n = 1
        while os.path.exists(path):
            path = os.path.join(tempfile.gettempdir(), f"printer_anti_clog{suffix}_{ts}_{n}.jpg")
            n += 1
        img.save(path, "JPEG", quality=92)
        self._cleanup_old_files()
        return path

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
