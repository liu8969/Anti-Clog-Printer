# 打印机自动防堵程序

定时自动打印彩色测试页，防止喷墨打印机喷嘴堵塞。支持 macOS 桌面 GUI 和 Docker Web 管理两种运行方式。

## 功能

- **定时打印**：可配置每天/每 N 天自动打印 CMYK 全色测试页
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
| `CUSTOM_TEXT` | （空） | 测试页备注文字 |
| `TZ` | `Asia/Shanghai` | 时区 |

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
