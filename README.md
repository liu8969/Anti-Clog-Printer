# 打印机自动防堵程序

定时自动打印彩色测试页，防止喷墨打印机喷嘴堵塞。支持 macOS 桌面 GUI 和 Docker Web 管理两种运行方式。

## 功能

- **定时打印**：可配置每天/每 N 天自动打印防堵测试页
- **全喷嘴斜线覆盖页（默认）**：C/M/Y/K 各占一整列，列内用满页高的斜线幕铺满，
  保证每个颜色的**每一行喷孔每趟走纸都会出墨**（爱普生官方喷嘴检查页同样是斜线）；
  黑墨默认加强；整页墨量仅约 2.3%，一页约 0.013ml
- **三档覆盖强度**：省墨 ≈1.2% / 标准 ≈2.3%（默认）/ 加强 ≈4.6%（已轻微堵塞时连打几张）
- **图案预览**：Web 端与桌面端都能"生成预览并下载/另存"，**不打印、不费纸**先看效果
- **精细自检页（旧）**：只打印一条 6px 细色带，**仅用于验证打印链路，不能防堵**
- **IPP/IPPS 直连**：纯 Python IPP 客户端，无需 CUPS，跨平台
- **Web 管理**（Docker）：NiceGUI 4 页签界面，浏览器管理打印计划、查看日志、手动触发
- **日志记录**：每次打印结果持久化，可查看历史

## 项目结构

```
├── main.py                 # macOS 桌面 GUI（tkinter + CUPS）
├── print_manager.py        # macOS 打印管理（ipptool + CUPS 兜底）
├── web_main.py             # Docker Web 管理端（NiceGUI）
├── ipp_client.py           # 纯 Python IPP/IPPS 客户端
├── config_manager.py       # JSON 配置管理
├── log_manager.py          # 打印日志管理
├── content_generator.py    # 测试页生成（Pillow）：全喷嘴斜线覆盖 / 经典页 / 细色带
├── scheduler_manager.py    # 后台定时调度
├── docker_main.py          # Docker 无界面入口（含 preview 预览子命令）
├── healthcheck.py          # Docker 健康检查
├── tests/
│   └── test_content_generator.py   # 全喷嘴覆盖 / 墨量预算 / 向后兼容 回归测试
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .gitignore
```

## Docker 部署（推荐）

适用于 Windows Server / Linux / NAS 等 24x7 运行环境。

### 1. 修改打印机 IP

编辑 `docker-compose.yml`，将 `PRINTER_IP` 改为你的打印机 IP：

```yaml
environment:
  - PRINTER_IP=192.168.0.228   # 改成你的打印机 IP
```

### 2. 启动

```bash
docker compose -p printer up -d
```

> 首次部署时只要配置了 `PRINTER_IP`，计划会自动启用（无需先打开网页），
> 保证 24x7 防堵开箱即用。配置与打印日志通过 `./data` 卷持久化，容器重建不丢失。

### 3. 打开管理页面

浏览器访问 `http://<服务器IP>:18080`

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PRINTER_IP` | （必填） | 打印机 IP 地址 |
| `PRINTER_PORT` | `631` | IPP 端口 |
| `PRINTER_IPP_PATH` | `/ipp/print` | IPP 路径 |
| `SCHEDULE_FREQUENCY` | `every_2` | 打印频率：daily / every_2 / every_3 / every_5 / every_7 |
| `SCHEDULE_HOUR` | `9` | 打印时间（时） |
| `SCHEDULE_MINUTE` | `0` | 打印时间（分） |
| `SCHEDULE_ENABLED` | 自动 | 显式开关调度：`1` 启动 / `0` 停止（覆盖本地状态） |
| `CUSTOM_TEXT` | （空） | 测试页备注文字 |
| `PATTERN` | `coverage` | 打印图案：`coverage`=全喷嘴斜线覆盖页（防堵主力）/ `classic`=经典彩色页 / `link_test`=细色带自检（不防堵） |
| `DUTY` | `standard` | 覆盖强度：`eco`≈1.2% / `standard`≈2.3% / `strong`≈4.6%（已轻微堵塞时用） |
| `K_BOOST` | `1` | 黑墨加强：`1` 时 K 列的斜线幕与竖条都加倍（颜料黑最易干堵） |
| `BARS` | `1` | 每个色块是否加一条满高实心竖条 |
| `RULER` | `1` | 左侧毫米标尺（用于读出缺口在纸上的位置） |
| `PRINT_DPI` | `300` | 覆盖页分辨率：`300`（与打印机 URF RS300 一致，线条最锐利）/ `200`（兼容回退） |
| `TEST_MODE` | `0` | ⚠️ 仅为兼容旧配置：`1` 时只打印一条 6px 细色带，**只润湿极少数喷孔，不能防堵**（仅排查"能不能打出来"时临时开） |
| `TEST_ROTATE` | `0` | 测试页旋转补偿：`1` 时预先旋转 90°（若打印出来是竖线则设为 `1`） |
| `CONFIG_PATH` | `/app/config.json` | 配置文件路径（建议放到挂载卷） |
| `LOG_PATH` | `/app/print_log.json` | 日志文件路径（建议放到挂载卷） |
| `WEB_USER` | `admin` | Web 管理界面用户名（配合 `WEB_PASSWORD`） |
| `WEB_PASSWORD` | （空，不鉴权） | 设置后 Web 界面需 Basic Auth 登录 |
| `IPP_VERIFY_SSL` | 关闭 | 设为 `1` 开启 IPPS 证书校验（默认跳过自签名证书） |
| `TZ` | `Asia/Shanghai` | 时区 |

> ⚠️ 安全提示：Web 管理界面默认**无鉴权**，局域网内任何人均可访问。
> 公网/不可信网络部署时务必设置 `WEB_PASSWORD`。
> 注意：Basic Auth 仅拦截 HTTP 页面请求，NiceGUI 的 WebSocket 更新通道不受
> 其保护，因此**不可信网络**下即便设置了密码也不建议直接暴露，建议配合
> 反向代理 + 内网穿透/VPN 使用。

### 已知问题：测试页细线方向不对（竖着）

部分打印机（本项目实测的打印机即如此）对**非 A4 比例的小图片**按"长边适配"缩放打印，
导致测试页色带总是沿纸张**长边**（竖着），而不是沿短边（横着）。

- **原因**：打印机对图片的长边适配缩放（小图片无论横竖都被转成长边沿纸长边）。
- **解决（已内置）**：所有图案都用 **A4 竖向页面**——`link_test`/`classic` 为 1654×2339
  （200dpi），`coverage` 为 2480×3508（300dpi，与打印机 URF `RS300` 一致），
  比例与原完整模式相同，打印机按标准 A4 原样打印，斜线/色带横贯纸宽。
- 仅当个别打印机连 A4 竖向图也旋转时，才需要 `TEST_ROTATE=1` 补偿。

## 为什么"一条细色带"不能防堵（实测根因）

实测机型 **EPSON L6370 Series**（`printer-device-id`：`MFG:EPSON; MDL:L6370 Series;`，
Mopria 2.1），IPP 只读查询结果：

| 项 | 实测值 |
|---|---|
| 打印分辨率 | 默认 `600x300`，支持到 `4800x1200`；URF 光栅 `RS300`（300dpi） |
| 纸张 | `iso_a4_210x297mm`，四边不可打印边距 **3mm** |
| 墨量上报 | 只有 `Black`（`marker-names`） |
| 清洗操作 | `operations-supported` 里**没有**清洗/大墨量冲洗（只能从 Epson 网页高级设置或 App 触发） |

**问题**：旧的省墨测试模式只画一条 **6px 高**的色带（200dpi → 0.76mm），300dpi 下约等于
**9 行喷孔**；而 A4 四色喷头竖向有 **180~400 行喷孔**（300dpi 下 15~34mm）。
也就是说旧图案每次只润湿了 **约 2%~10% 的喷孔**，其余喷孔长期不出墨 →
就是"过一段时间某几个黑孔堵了一点点"的机理（IPP 不暴露喷孔数，但无论喷头多高，
竖直方向只覆盖 0.76mm 都远远不够）。

**对策**：新的 `coverage` 图案在竖直方向**连续铺满整页可打印高度**，4 个颜色各占一整列：

```
K 列          C 列          M 列          Y 列
满高斜线幕 + 满高竖条，黑墨加倍（k_boost）
左边 0/50/100…mm 标尺，用于读出缺口位置
```

- **斜线**：横跨一个色块上升 1/4 块宽，线距 = 上升量 → 上下首尾相接，整页高度无缝隙。
  喷头随小车横扫全幅，斜线在经过的每个高度都要求对应那行喷孔出墨 —— 于是**每行喷孔
  每趟走纸都出墨**。爱普生官方喷嘴检查页同样是每个色块一堆浅斜线，
  线中缺口＝该位置喷孔堵塞（[Epson KA-01531](https://asm.epson.eu/en_IE/faq/KA-01531)、
  [爱普生中国 L63XX 常见问题](https://www.epson.com.cn/faq/df07cdab3660481982c95d39a81e2eb3.html)）。
- **竖条**：每个色块一条满高实心竖条，保证每趟都有连续吐墨量（不只是点一个点）。
- **黑墨加强**：K 列的斜线幕与竖条都加倍 —— 颜料黑（本项目机型黑墨为颜料墨水）最容易干堵。

### 墨量对比

| 图案 | 竖直覆盖 | 用到的喷孔 | 整页覆盖 | 每页墨量 |
|---|---|---|---|---|
| `link_test` 细色带（旧默认） | 0.76mm | 约 2%~10% | 0.26% | ≈0.001ml |
| `classic` 经典彩色页 | 1~1.5mm | 约 4%~10% | 4.9% | ≈0.027ml |
| **`coverage` 标准（新默认）** | **整页 262mm** | **全部** | **2.3%** | ≈0.013ml |
| `coverage` 加强（连打几张冲堵） | 整页 | 全部（吐墨量×2） | 4.6% | ≈0.026ml |

每 2 天一张标准页 ≈ **每年 2.5ml 墨**（一瓶 127ml 黑墨够用几十年），换来的是全部喷孔
每两天活动一次。

### 打印出来后怎么看

1. 每列斜线应当从可打印区顶部一直连到底部（贯通整页）；
2. 线中的**缺口**就是该位置喷孔堵塞 —— 相邻斜线上的缺口呈斜向重复，
   配合左侧毫米标尺即可读出位置（例如"K 列在 120mm 附近缺 2 根线"）；
3. 偶发一两处缺口且下次打印消失＝轻微干堵，已被本页冲开；反复缺失同一位置＝已堵实，
   建议用 Epson 网页"高级设置 → 打印头清洗/大墨量冲洗"（或 Epson Smart Panel App）处理。

### 升级部署（已部署 Docker 的机器）

```bash
git pull                      # 或同步最新代码
docker compose -p printer up -d --build
```

- `docker-compose.yml` 里原来的 `TEST_MODE=1` 已改为 `TEST_MODE=0` 并新增
  `PATTERN=coverage`、`DUTY=standard`；**环境变量在每次启动时覆盖 `./data/config.json`**，
  所以旧配置不用删。
- 升级后建议先在网页"打印内容"页点 **"生成预览并下载（不打印）"** 看一眼图案，
  再点"立即打印"打一张实物确认。也可以直接在容器里生成到挂载卷：

  ```bash
  docker compose -p printer exec anti-clog \
      python docker_main.py preview --out /app/data/preview.jpg   # 宿主机 ./data/preview.jpg
  ```
- 若打印出来方向不对（历史上个别打印机会把图片旋转/按长边缩放），
  设 `TEST_ROTATE=1` 或 `PRINT_DPI=200` 后重启容器。

## macOS 桌面版

```bash
pip install -r requirements.txt
python main.py
```

macOS 版本依赖 CUPS 和 `ipptool`，适合桌面交互使用。
"打印内容"页可分别选择打印图案与覆盖强度，并可"生成预览并另存为…"（不打印）。

### 开发与自测

```bash
# 生成三种图案的预览图 + 打印墨量统计（不联网、不打印）
python docker_main.py preview --all --out /tmp/preview.jpg
python docker_main.py preview --pattern coverage --duty strong

# 回归测试：全喷嘴覆盖 / 墨量预算 / 版本兼容
python -m unittest discover -s tests -v
```

### 后台运行与单实例

- **单实例保护**：程序通过 PID 文件保证同一时间只有一个实例。若已有一个在
  后台运行，再次执行 `python main.py` 会**唤醒已有窗口**（发 `SIGUSR1`）后
  退出，避免两个调度器在计划时间到重复打印。
- **关闭窗口**：若定时打印正在运行，点关闭会询问——
  - **是**：退出程序（停止定时打印）；
  - **否**：最小化到 Dock（`iconify`），调度器继续在后台运行。
- **恢复窗口**：最小化后点击 Dock 中的程序图标即可恢复；或再次运行
  `python main.py`（会自动唤醒后台实例）。

> 连接测试 / 打印会**同时尝试 IPPS（`ipps://`）与 IPP（`ipp://`）** 多个路径，
> 先短超时探测可达的 URI 再发送打印，兼容仅支持 IPPS 的打印机。

## 技术要点

- **IPP over HTTPS**：打印机通常使用自签名证书，客户端跳过 SSL 证书验证
- **JPEG 格式**：大多数打印机支持 JPEG 直接打印，PDF 兼容性较差
- **纯 Python IPP**：`ipp_client.py` 使用 `struct` 手动构造 IPP 二进制协议，零系统依赖
- **准确的成败判定**：打印成功需 HTTP 层正常 **且** IPP 状态码为 0x0000/0x0001；
  打印机常用 HTTP 200 + IPP 错误码拒绝作业，只看 HTTP 层会把失败误报为成功
- **防丢配置**：`config.json` / `print_log.json` 均"临时文件 + 原子替换"落盘并加锁，
  断电/并发不会写坏；文件损坏时自动备份并告警，而不是静默回退默认值
- **全喷嘴覆盖的几何依据**：竖直线覆盖多少喷孔只取决于图案的**竖直高度**，与线宽无关；
  斜线幕的墨量只取决于"每行喷孔每趟吐几个点"（本页 standard = 8 点），
  所以"整页高度 + 细斜线"能用极少的墨换到 100% 的喷孔参与度
- **旧配置兼容**：`content.pattern` 显式值优先；未显式设置时仍按旧的
  `content.test_mode` 决定是否为细色带页，老 `config.json`/环境变量不会行为突变
- **Web UI**：基于 NiceGUI 框架，全 Python 实现，单文件 `web_main.py`
