"""content_generator 回归测试。

关注三件事（这是"防堵头到底管不管用"的核心）：

1. **全喷嘴覆盖**：coverage 图案里，每个颜色在自己那一列中，竖直方向每一段都有墨
   （＝喷头的每一行喷孔都会被用到），且不是只靠那条竖条撑场面（斜线幕本身铺满）。
2. **墨量预算**：档位越高墨量越大，但 standard 仍然远低于一张普通彩色页。
3. **向后兼容**：老的 test_mode/test_rotate 配置、classic/link_test 图案行为不变。

跑法（无需 pytest、无需打印机、不联网）：

    python -m unittest discover -s tests -v
    # 或
    python tests/test_content_generator.py
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402

from content_generator import (  # noqa: E402
    COLOR_ZONES, DEFAULT_DUTY, DEFAULT_PATTERN, DUTY_RUN,
    ContentGenerator, _a4_px,
)

ZONE_INDEX = {label: i for i, (label, _c, _cn) in enumerate(COLOR_ZONES)}
COLOR_BY_LABEL = {label: color for label, color, _cn in COLOR_ZONES}
BANDS = 40          # 竖直方向分段数
MAX_COLORS = 4_000_000  # getcolors 上限（超了会返回 None，说明颜色异常多）


class StubConfig:
    """只实现点号路径 get()，与 ConfigManager 的读取接口一致"""

    def __init__(self, data=None):
        self._data = dict(data or {})

    def get(self, key, default=None):
        return self._data.get(key, default)


def make_gen(**content):
    return ContentGenerator(StubConfig({f"content.{k}": v for k, v in content.items()}))


def color_counts(img):
    """精确统计每种颜色的像素数（纯 Python，不依赖 numpy）"""
    colors = img.getcolors(maxcolors=MAX_COLORS)
    if colors is None:
        raise AssertionError("图像颜色数异常多，无法统计")
    return {tuple(rgb): cnt for cnt, rgb in colors}


def zone_x(geo, label):
    """某个色块的 x 范围（不含色块之间的白缝）"""
    idx = ZONE_INDEX[label]
    x0 = geo["x_left"] + idx * geo["zone_w"]
    return x0, x0 + geo["zone_w"] - 6  # GUTTER=6


class CoverageGeometryTest(unittest.TestCase):
    """全喷嘴覆盖：每个色块竖直方向无死角，且斜线幕本身铺满"""

    def setUp(self):
        self.gen = make_gen()
        self.width, self.height = _a4_px(300)
        self.geo = self.gen._coverage_geometry(
            self.width, self.height, 300, DUTY_RUN[DEFAULT_DUTY],
            True, True, True)

    def test_every_band_has_ink_for_every_color(self):
        img = self.gen._build_coverage_image()
        px = img.load()
        y_top, y_bot = self.geo["y_top"], self.geo["y_bot"]
        for label, color, _cn in COLOR_ZONES:
            x0, x1 = zone_x(self.geo, label)
            missing = []
            for i in range(BANDS):
                ya = y_top + (y_bot - y_top) * i // BANDS
                yb = max(ya + 1, y_top + (y_bot - y_top) * (i + 1) // BANDS)
                found = False
                for y in range(ya, yb):
                    for x in range(x0, x1, 2):
                        if px[x, y] == color:
                            found = True
                            break
                    if found:
                        break
                if not found:
                    missing.append(i)
            self.assertEqual(
                missing, [],
                f"{label} 色块在 {BANDS} 个竖直分段中有 {len(missing)} 段没有墨："
                f"{missing}（喷头对应位置的喷孔永远不会被用到）")

    def test_curtain_alone_covers_full_height(self):
        """排除竖条之后（只看斜线幕），每一段仍然有墨"""
        img = self.gen._build_coverage_image()
        px = img.load()
        y_top, y_bot = self.geo["y_top"], self.geo["y_bot"]
        for label, color, _cn in COLOR_ZONES:
            x0, _x1 = zone_x(self.geo, label)
            boost = 2 if label == "K" else 1
            x_start = x0 + self.geo["bar_w"] * boost + 12  # 跳过竖条与边界
            missing = []
            for i in range(BANDS):
                ya = y_top + (y_bot - y_top) * i // BANDS
                yb = max(ya + 1, y_top + (y_bot - y_top) * (i + 1) // BANDS)
                found = any(px[x, y] == color
                            for y in range(ya, yb)
                            for x in range(x_start, zone_x(self.geo, label)[1], 2))
                if not found:
                    missing.append(i)
            self.assertEqual(missing, [],
                             f"{label} 斜线幕在分段 {missing} 没有覆盖")

    def test_geometry_is_sane(self):
        self.assertGreater(self.geo["y_bot"] - self.geo["y_top"], 2500)
        self.assertGreaterEqual(self.geo["thickness"], 1)
        self.assertGreaterEqual(self.geo["bar_w"], 2)
        # 内容都在可打印范围（3mm≈35px）以内
        self.assertGreaterEqual(self.geo["margin"], 35)
        self.assertLessEqual(self.geo["x_left"] + 4 * self.geo["zone_w"],
                             self.width - self.geo["margin"] + 1)


class InkBudgetTest(unittest.TestCase):
    """墨量：档位单调、预算够低、K 加强只影响 K"""

    def _region_counts(self, img, geo):
        out = {}
        for label, color, _cn in COLOR_ZONES:
            x0, x1 = zone_x(geo, label)
            region = img.crop((x0, geo["y_top"], x1, geo["y_bot"]))
            counts = color_counts(region)
            out[label] = counts.get(color, 0)
            out[label + "_white"] = counts.get((255, 255, 255), 0)
        return out

    def test_duty_is_monotonic_and_within_budget(self):
        inked = {}
        for duty in ("eco", "standard", "strong"):
            img = make_gen(duty=duty)._build_coverage_image()
            counts = color_counts(img)
            white = counts.get((255, 255, 255), 0)
            inked[duty] = (img.size[0] * img.size[1] - white) / (img.size[0] * img.size[1])
        self.assertLess(inked["eco"], inked["standard"])
        self.assertLess(inked["standard"], inked["strong"])
        # standard 非白像素占比 < 6%（含文字/标尺/JPEG 前的纯像素统计，留足余量）
        self.assertLess(inked["standard"], 0.06)
        # 但也不能少到"只润湿几行喷孔"的程度：至少 0.5%
        self.assertGreater(inked["standard"], 0.005)

    def test_k_boost_only_touches_k(self):
        plain = make_gen(k_boost=False)._build_coverage_image()
        boosted = make_gen(k_boost=True)._build_coverage_image()
        geo = make_gen()._coverage_geometry(*_a4_px(300), 300,
                                            DUTY_RUN[DEFAULT_DUTY], True, True, True)
        a = self._region_counts(plain, geo)
        b = self._region_counts(boosted, geo)
        self.assertGreater(b["K"], a["K"])
        for label in ("C", "M", "Y"):
            self.assertEqual(b[label], a[label],
                             f"k_boost 不应改变 {label} 的墨量")

    def test_describe_reports_reasonable_estimate(self):
        info = make_gen().describe()
        self.assertEqual(info["pattern"], DEFAULT_PATTERN)
        self.assertLess(info["coverage_total_percent"], 4.0)
        self.assertGreater(info["coverage_total_percent"], 1.0)
        self.assertIn("K", info["coverage_percent"])
        self.assertIn("每孔每趟", make_gen().summary_line())


class PatternCompatTest(unittest.TestCase):
    """图案解析：显式 pattern 优先，旧 test_mode 行为不变，非法值回退"""

    def test_default_is_coverage(self):
        self.assertEqual(make_gen().resolve_pattern(), "coverage")

    def test_legacy_test_mode_maps_to_link_test(self):
        self.assertEqual(make_gen(test_mode=True).resolve_pattern(), "link_test")

    def test_explicit_pattern_wins(self):
        self.assertEqual(make_gen(test_mode=True, pattern="classic").resolve_pattern(),
                         "classic")
        self.assertEqual(make_gen(pattern="coverage").resolve_pattern(), "coverage")
        self.assertEqual(make_gen(pattern="LINK_TEST").resolve_pattern(), "link_test")

    def test_invalid_values_fall_back(self):
        gen = make_gen(pattern="???", duty="xxx", dpi=123)
        self.assertEqual(gen.resolve_pattern(), "coverage")
        self.assertEqual(gen.resolve_duty(), DEFAULT_DUTY)
        self.assertEqual(gen.resolve_dpi(), 300)

    def test_dpi_choices(self):
        self.assertEqual(_a4_px(300), (2480, 3508))
        self.assertEqual(_a4_px(200), (1654, 2339))
        self.assertEqual(make_gen(dpi=200).resolve_dpi(), 200)

    def test_generate_test_mode_override(self):
        gen = make_gen(pattern="coverage")
        path = gen.generate(test_mode=True, out_path=os.path.join(
            tempfile.gettempdir(), "anti_clog_test_override.jpg"))
        self.assertTrue(path.endswith(".jpg"))
        with Image.open(path) as img:
            self.assertEqual(img.size, (1654, 2339))

    def test_legacy_patterns_geometry_unchanged(self):
        gen = make_gen()
        classic = gen._build_image()
        self.assertEqual(classic.size, (1654, 2339))
        thin = gen._build_test_image()
        self.assertEqual(thin.size, (1654, 2339))
        px = thin.load()
        # 细色带：y=320 起、高 6px 的四色带（PIL rectangle 含端点 → 实际 7 行），K 占最后一列
        rows = [y for y in range(300, 360)
                if any(px[x, y] == (0, 0, 0) for x in range(1300, 1600))]
        self.assertEqual(rows, [320, 321, 322, 323, 324, 325, 326])


class GenerateOutputTest(unittest.TestCase):
    """generate()：路径、JPEG 可读、尺寸正确、旋转补偿仍生效"""

    def test_writes_readable_jpeg(self):
        tmpdir = tempfile.mkdtemp(prefix="anti_clog_test_")
        out = os.path.join(tmpdir, "sub", "coverage.jpg")
        path = make_gen().generate(out_path=out)
        self.assertEqual(path, os.path.abspath(out))
        with Image.open(path) as img:
            self.assertEqual(img.format, "JPEG")
            self.assertEqual(img.size, (2480, 3508))

    def test_dpi_200_output_size(self):
        tmpdir = tempfile.mkdtemp(prefix="anti_clog_test_")
        path = make_gen(dpi=200).generate(out_path=os.path.join(tmpdir, "c200.jpg"))
        with Image.open(path) as img:
            self.assertEqual(img.size, (1654, 2339))

    def test_test_rotate_applies_to_coverage_too(self):
        tmpdir = tempfile.mkdtemp(prefix="anti_clog_test_")
        path = make_gen(test_rotate=True).generate(
            out_path=os.path.join(tmpdir, "rot.jpg"))
        with Image.open(path) as img:
            self.assertEqual(img.size, (3508, 2480))  # 旋转 90° 后宽高互换


if __name__ == "__main__":
    unittest.main(verbosity=2)
