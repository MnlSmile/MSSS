# MSSS – MnlSmile Scaffolding Server

**MSSS** 是一个用于快速架设 [Scaffolding](https://github.com/Scaffolding-MC/Scaffolding-MC) 中心服务器的 Python 异步框架。  
  
# MSSS 由一个没有工程经验的初学者开发，能基本应付日常游玩，但请谨慎用于生产环境。

---

## 特性

- **开箱即用** – 几行代码即可启动一个完整的 Scaffolding 中心服务器。
- **自动化** - 能将创建房间的过程自动化，可轻松把本地《我的世界》服务器接入众多启动器联机生态。
- **协议可扩展** – 通过 `@app.protocol('namespace:protocol')` 装饰器即可注册自定义协议处理器。

---

## 安装

```bash
pip install msss
```

或者从源码安装：

```bash
git clone https://github.com/MnlSmile/MSSS.git
cd MSSS
pip install .
```

---

## 快速开始

以下示例启动一个监听 `0.0.0.0:13659` 的 Scaffolding 服务器，并假定《我的世界》服务器运行在 `25565` 端口。

```python
import asyncio
import logging
import subprocess
from msss import Scaffolding

logging.basicConfig(level=logging.INFO)

app = Scaffolding(host='0.0.0.0', port=13659, mc_port=25565, checking_freq=0.1)
et_proc = subprocess.Popen(app.easytier('U/0000-0000-0000-0000', path='"./et/easytier-core"', extras=['--no-listener']), shell=True, stdout=open('./etlog', 'w', encoding='utf-8'))
asyncio.run(app.run())
et_proc.terminate()
et_proc.wait()

```

启动后，您的朋友们可以在启动器通过房间码 **U/0000-0000-0000-0000** 加入房间，然后在《我的世界》多人游戏中直接连接。

> **提示**：`app.easytier(房间码)` 可以生成对应的 EasyTier 启动命令，详见下文。

---

## 自定义协议处理器

使用 `@app.protocol('命名空间:协议名')` 装饰器即可注册自己的协议。  
协议处理函数接收一个 `SRequest` 对象，可以返回多种类型的值（会自动编码为正确的响应格式）。如果编码不符合预期，也可以读取 `req.body` 获取原始字节数据。

```python
@app.protocol('my:hello')
async def handle_hello(req):
    # 解析客户端发送的 JSON 数据
    data = req.as_json()
    name = data.get('name', 'Guest')
    return {'message': f'Hello, {name}!'}
```

**支持的返回类型**：
- `None` → 空响应
- `str` → UTF-8 编码
- `bytes` / `bytearray` → 按原样发送
- `BaseModel` (Pydantic) → JSON 编码
- `SStrList` → Scaffolding 字符串列表（按 `\0` 分隔）
- `dict` / `list` → JSON 编码

如果协议未注册，且您注册了 `any` 后备处理器，则会调用它；否则自动返回错误码 `255`。

## 与 EasyTier 集成

`<Scaffolding>.easytier(code, path='./easytier-core', dhcp=True, extras=[])` 方法会根据房间码生成一个适用于 Windows 平台的命令。

- **`code`**：Scaffolding 房间码，格式例如 `U/AAAA-AAAA-AAAA-AAAA`。
- **`path`**：`easytier-core` 可执行文件的路径。
- **`dhcp`**：是否让 EasyTier 自动分配虚拟 IP（强烈建议开启）。
- **`extras`**：额外的命令行参数列表。

示例输出：

```bash
./easytier-core --network-name scaffolding-mc-AAAA-AAAA --network-secret AAAA-AAAA --hostname scaffolding-mc-server-13659 -p "https://etnode.zkitefly.eu.org/node1" -p "https://etnode.zkitefly.eu.org/node2" -d
```

---

## 默认行为

默认启用的心跳管理器会：
- 监听 `c:player_ping` 协议，更新每位玩家的最后活跃时间。
- 每隔 `checking_freq` 秒检查一次，将超过 `llt` 秒未发送心跳的客户端连接关闭并从玩家列表中移除。
- 房主（`host`）不会被自动清理。

您可以在创建 `Scaffolding` 实例时调整这两个参数：

```python
app = Scaffolding(..., llt=30.0, checking_freq=5.0)
```

---

## 协议实现参考

[Scaffolding 官方协议](https://github.com/Scaffolding-MC/Scaffolding-MC)

---

## 依赖项

- [py-machineid](https://github.com/ab77/py-machineid)
- [async-timer](https://github.com/MnlSmile/async-timer)
- [pydantic](https://github.com/pydantic/pydantic)

---

## 许可证

本项目使用 **MIT 许可证** 发布。

---

## 相关链接

- [Scaffolding 协议](https://github.com/Scaffolding-MC/Scaffolding-MC)
- [EasyTier](https://github.com/EasyTier/EasyTier)
- [MSSS](https://github.com/MnlSmile/MSSS)