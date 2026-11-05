# AX3000T 高通版 SSH 工具

适用：Windows 10/11 x64，高通 IPQ5018 的小米 AX3000T **RD03v2、原厂固件 2.0.28**。

本目录只提供代码、启动脚本和 Markdown 文档，**不附带 Python、虚拟环境、第三方库或解释器安装包**。请自行安装环境，准备完成后可断开互联网操作路由器。

## 自行安装环境

1. 从 [Python 官网](https://www.python.org/downloads/windows/) 安装 **Python 3.13 x64**，并安装 Python Launcher。
2. 在本文件夹打开 PowerShell，执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
.\.venv\Scripts\python.exe .\app\offline_ssh.py
```

看到 `Offline dependencies and source hashes OK` 后再操作路由器。上述命令由你执行；启动器不会自动下载或安装 Python/依赖。`.venv` 是你在本机创建的环境，复制代码给其他电脑时不要附带它，接收电脑应重新安装。

外部依赖仅为 `ssh2-python`，版本见 `requirements.txt`。推荐 Python 3.13 x64；若使用其他版本遇到没有 Windows wheel 的错误，请换用 3.13 x64。首次安装需要互联网，完成安装后的路由器操作只需要局域网。

## 使用顺序

先阅读 [完整操作指南](docs/操作指南.md)，保存恢复上网所需的信息。每次只连接一台待处理路由器并核对屏幕显示的 SN。

| 顺序 | 入口 | 作用 |
|---|---|---|
| 1 | `00-本地检查.cmd` | 查找你安装的 Python 并检查依赖，不访问路由器 |
| 2 | `01-查看路由器.cmd` | 读取设备身份与端口状态 |
| 3 | `05-允许临时通信.cmd` | 右键以管理员运行，为实际使用的 Python 添加临时防火墙规则 |
| 4 | 手动恢复出厂 | 先备份；重置后不要完成小米设置向导 |
| 5 | `02-最小初始化.cmd` | 核对设备，输入 `INIT` 后初始化并重启 |
| 6 | `03-开启SSH.cmd` | 设置密码，输入 `ENABLE` 后开启 SSH |
| 7 | `04-验证SSH和后台.cmd` | 验证 root 登录、后台密码和持久化补丁文件 |
| 8 | `06-删除临时规则.cmd` | 右键以管理员运行，删除本次临时规则 |

第一个密码用于 **SSH root 和小米后台**，第二个用于临时 Wi-Fi，可设为相同值。长度为 **10–63 个字符**，使用不含空格的可打印 ASCII 字符。

默认目标为 `192.168.31.1`，可用 `--host`、`--port`、`--local-ip` 指定其他局域网地址。工具没有绑定某一台设备的 SN、MAC 或密码。

## 启动器选择哪个 Python

依次选择：`AX3000T_PYTHON` 显式指定的解释器、本目录 `.venv`、已激活的虚拟环境、Python Launcher 列出的已安装解释器（优先 3.13），最后才使用 PATH 中的 `python.exe`。环境必须是 Python 3.10+、64 位。不会自动安装缺失的解释器。

推荐按上面的步骤创建本目录 `.venv`，保证普通启动器和管理员防火墙脚本选择同一个解释器。环境缺失时，工具在修改路由器之前停止。

## 重启保持

补丁位于持久目录 `/etc/crontabs/patches`，由 cron 每分钟修复内存中的 SSH 启动限制。**重启后等待 90 秒，再运行验证入口。** 每台设备都需要实际重启后验证；补丁文件存在不等于已经完成重启验证，OTA 或恢复出厂可能覆盖它。

## 目录

- `README.md`：环境安装和使用入口。
- `requirements.txt`：pip 读取的依赖清单。
- `app/`：主程序、来源模块、SSH 补丁与来源校验信息。
- `scripts/`：系统 Python 选择、启动和临时防火墙脚本。
- `docs/`：[操作指南](docs/操作指南.md)、[验证报告](docs/验证报告.md)、[第三方来源](docs/第三方来源.md)。
- `tests/`：本地行为测试及开发用隔离模拟。
- `licenses/`：随附来源代码的许可证与说明。

本工具不自动恢复出厂，不刷 bootloader，不安装 OpenWrt。型号、固件和 NETMODE 检查保持启用。
