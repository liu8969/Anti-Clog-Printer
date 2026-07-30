"""防堵头彩色测试页生成模块"""

import os
import tempfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont


class ContentGenerator:
    """生成包含 CMYK 全色喷嘴测试图案，输出 JPEG（打印机兼容性最好）和 PDF"""

    def __init__(self, config):
        self._config = config

    def _load_fonts(self):
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
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
        """构建 A4 测试页 PIL Image"""
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
        bar_h = 46
        gap = 18

        # CMYK 四色条
        draw.text((60, y), "CMYK 四色测试", fill="black", font=normal_font)
        y += 48
        for label, color in [
            ("青色 Cyan           ", (0, 255, 255)),
            ("品红 Magenta      ", (255, 0, 255)),
            ("黄色 Yellow         ", (255, 255, 0)),
            ("黑色 Black           ", (0, 0, 0)),
        ]:
            draw.rectangle([60, y, 60 + bar_w, y + bar_h], fill=color)
            tc = (255, 255, 255) if color == (0, 0, 0) else (0, 0, 0)
            draw.text((60 + bar_w + 15, y + 8), label, fill=tc, font=small_font)
            y += bar_h + gap

        y += 20

        # 混合色条
        draw.text((60, y), "混合色测试 (CMY 叠加)", fill="black", font=normal_font)
        y += 48
        for label, color in [
            ("红色 Red   (M+Y)", (255, 0, 0)),
            ("绿色 Green (C+Y)", (0, 255, 0)),
            ("蓝色 Blue  (C+M)", (0, 0, 255)),
        ]:
            draw.rectangle([60, y, 60 + bar_w, y + bar_h], fill=color)
            draw.text((60 + bar_w + 15, y + 8), label, fill="black", font=small_font)
            y += bar_h + gap

        y += 20

        # 渐变色条
        draw.text((60, y), "渐变色测试", fill="black", font=normal_font)
        y += 48
        grad_h = 30
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
            y += grad_h + 10

        y += 20

        # 喷嘴网格
        draw.text((60, y), "喷嘴网格测试", fill="black", font=normal_font)
        y += 48
        for color in [
            (0, 255, 255), (255, 0, 255), (255, 255, 0),
            (0, 0, 0), (255, 0, 0), (0, 255, 0), (0, 0, 255),
        ]:
            for i in range(0, bar_w, 3):
                draw.line([(60 + i, y), (60 + i, y + 18)], fill=color, width=1)
            y += 22

        y += 40
        draw.text((60, y), "--- 此页面由打印机自动防堵程序生成 ---",
                  fill=(160, 160, 160), font=small_font)

        return img

    def generate(self, fmt="jpeg"):
        """
        生成测试页文件。
        fmt: "jpeg" | "pdf" | "both"
        返回: 单路径 (jpeg/pdf) 或 (jpeg_path, pdf_path) (both)
        """
        img = self._build_image()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tmp = tempfile.gettempdir()

        if fmt == "jpeg":
            path = os.path.join(tmp, f"printer_anti_clog_{ts}.jpg")
            img.save(path, "JPEG", quality=92)
            return path

        elif fmt == "pdf":
            path = os.path.join(tmp, f"printer_anti_clog_{ts}.pdf")
            img.save(path, "PDF", resolution=200.0)
            return path

        elif fmt == "both":
            jpg = os.path.join(tmp, f"printer_anti_clog_{ts}.jpg")
            pdf = os.path.join(tmp, f"printer_anti_clog_{ts}.pdf")
            img.save(jpg, "JPEG", quality=92)
            img.save(pdf, "PDF", resolution=200.0)
            return jpg, pdf

        else:
            return self.generate("jpeg")
