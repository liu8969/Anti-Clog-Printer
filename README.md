# 打印机自动防堵程序

定时自动打印彩色测试页，防止喷墨打印机喷嘴堵塞。支持 macOS 桌面 GUI 和 Docker Web 管理两种运行方式。

## 功能

- **定时打印**：可配置每天/每 N 天自动打印 CMYK 全色测试页
- **省墨测试模式**：只打印一条细色带（墨量约为完整页的几十分之一），适合验证软件/打印链路时使用
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
├── content_generator.py    # 彩色测试页生成（Pillow）
├── scheduler_manager.py    # 后台定时调度
├── docker_main.py          # Docker 无界面入口（备用）
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
| `TEST_MODE` | `0` | 省墨测试模式：`1` 时只打印一条细色带（验证打印链路用，几乎不耗墨） |
| `TEST_ROTATE` | `0` | 测试页旋转补偿：`1` 时预先旋转 90°（若打印出来是竖线则设为 `1`） |
| `CONFIG_PATH` | `/app/config.json` | 配置文件路径（建议放到挂载卷） |
| `LOG_PATH` | `/app/print_log.json` | 日志文件路径（建议放到挂载卷） |
| `WEB_USER` | `admin` | Web 管理界面用户名（配合 `WEB_PASSWORD`） |
| `WEB_PASSWORD` | （空，不鉴权） | 设置后 Web 界面需 Basic Auth 登录 |
| `IPP_VERIFY_SSL` | 关闭 | 设为 `1` 开启 IPPS 证书校验（默认跳过自签名证书） |
| `TZ` | `Asia/Shanghai` | 时区 |

> ⚠️ 安全提示：Web 管理界面默认**无鉴权**，局域网内任何人均可访问。
> 公网/不可信网络部署时务必设置 `WEB_PASSWORD`。

### 已知问题：测试页细线方向不对（竖着）

部分打印机（本项目实测的打印机即如此）对**非 A4 比例的小图片**按"长边适配"缩放打印，
导致测试页色带总是沿纸张**长边**（竖着），而不是沿短边（横着）。

- **原因**：打印机对图片的长边适配缩放（小图片无论横竖都被转成长边沿纸长边）。
- **解决（已内置）**：测试页改为 **A4 竖向页面**（1654×2339，与完整模式同方向），
  打印机按标准 A4 原样打印，色带横贯纸宽 → 与短边平行。整页几乎全白，墨量依旧极小。
- 仅当个别打印机连 A4 竖向图也旋转时，才需要 `TEST_ROTATE=1` 补偿。

## macOS 桌面版

```bash
pip install -r requirements.txt
python main.py
```

macOS 版本依赖 CUPS 和 `ipptool`，适合桌面交互使用。

## 技术要点

- **IPP over HTTPS**：打印机通常使用自签名证书，客户端跳过 SSL 证书验证
- **JPEG 格式**：大多数打印机支持 JPEG 直接打印，PDF 兼容性较差
- **纯 Python IPP**：`ipp_client.py` 使用 `struct` 手动构造 IPP 二进制协议，零系统依赖
- **Web UI**：基于 NiceGUI 框架，全 Python 实现，单文件 `web_main.py`
