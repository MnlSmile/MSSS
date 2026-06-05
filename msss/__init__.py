import asyncio as aio
import json
import time
import machineid
import logging
import uuid

from async_timer import Timer
from pydantic import BaseModel, Field, ConfigDict
from typing import Callable, Optional, TypeVar, Awaitable, Iterable
from enum import Enum

class SKindEnum(str, Enum):
    host = 'HOST'
    HOST = 'HOST'
    guest = 'GUEST'
    GUEST = 'GUEST'

async def void_func(*args, **kwargs) -> None:
    return

class SStrList(list): ...

class SProfile(BaseModel):
    name:str
    machine_id:str
    vendor:str
    kind:SKindEnum = SKindEnum.guest
    easytier_id:str = None

T = TypeVar('T')

_Type = type

class SRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    ip:str
    port:int
    addr:tuple[str, int]
    type:str
    body:bytes
    reader:aio.StreamReader
    writer:aio.StreamWriter
    time:float = Field(default_factory = time.time)    
    
    def as_scaffolding_str_list(self) -> list[str]:
        """
        将请求体按 Scaffolding 字符串列表解析。

        Scaffolding 字符串列表是使用 '\0' 作为分隔符的 utf-8 字节串。
        """
        return self.body.decode('utf-8').split('\0')
    def as_json(self) -> dict:
        """
        将请求体按 json 解析。
        """
        return json.loads(self.body.decode('utf-8'))
    def as_pydantic(self, _t:_Type[T]) -> T:
        """
        将请求体按 pydantic 模型解析。  

        Args:
            _t (type): 要解析为的 pydantic 模型类型。
        """
        return _t.model_validate_json(self.body)

class SException(Exception):
    def __init__(self, code:int, message:str = '', *args):
        """
        Args:
            code (int): 返回给客户端的状态码。取值范围 [0, 255]
            message (str): 返回给客户端的信息。
        """
        self.code = code
        self.message = message
        super().__init__(*args)

class SServer:
    def __init__(self, host:str, port:int, mc_port:int, logger:Optional[logging.Logger] = None):
        """
        Args:
            host (str): 要绑定的地址。
            port (int): 要监听的端口。
            mc_port (int): 《我的世界》服务器运行的端口。
            logger (Logger): 要使用的日志记录器实例。其应提供和标准库 logging.Logger 类似的 API 接口。
        """
        self.host = host
        self.port = port
        self.mc_port = mc_port
        self.logger = logger if logger else logging.getLogger(f"<SServer python_id='{id(self)} host='{self.host}' port='{self.port}' mc_port='{self.mc_port}'>")

        self.protocol_handlers:dict[str, Callable[[SRequest], Awaitable[bytearray|bytes|BaseModel|dict|list]]] = {}
        self.connected_callback:Callable[[tuple[str, int], Awaitable[None]]] = void_func
        self.disconnected_callback:Callable[[tuple[str, int], Awaitable[None]]] = void_func
    
    def protocol(self, protocol:str):
        """
        将函数声明为协议处理器。   
        原函数不会被装饰器替换。

        Args:
            protocol (str): 要处理的协议，用半角冒号分隔，其中冒号前为命名空间，冒号后为协议名。传入的协议若为 any，则会注册为针对未实现协议的后备处理程序。
        """
        def _d(func):
            self.protocol_handlers[protocol] = func
            return func
        return _d
    
    async def request_handler(self, _t:str, addr:tuple[str, int], body:bytes, reader:aio.StreamReader, writer:aio.StreamWriter) -> tuple[int, bytes|bytearray]:
        """
        解析来自客户端的原始请求。   

        返回值为空时，自动转换为空字节串。   
        返回值类型为 str 时，自动转换为 utf-8 编码字节串。   
        返回值类型为 bytes 或 bytearray 时，不作转换。   
        返回值类型为 SStrList 时，自动转换为 Scaffolding 字符串列表。   
        返回值类型为 list 或 dict 时，自动转换为 json。
        """
        req = SRequest(ip = addr[0], port = addr[1], addr = addr, type = _t, body = body, reader = reader, writer = writer)
        try:
            if _t in self.protocol_handlers:
                r = await self.protocol_handlers[_t](req)
            else:
                if 'any' in self.protocol_handlers:
                    r = await self.protocol_handlers['any'](req)
                else:
                    return 255, f"Protocol not supported: {_t}".encode('utf-8')
        except SException as se:
            return se.code, se.message.encode('utf-8')
        
        if r is None:
            return 0, bytearray()
        elif isinstance(r, str):
            return 0, r.encode('utf-8')
        elif isinstance(r, (bytes, bytearray)):
            return 0, r
        elif isinstance(r, BaseModel):
            return 0, r.model_dump_json().encode('utf-8')
        elif isinstance(r, SStrList):
            return 0, '\0'.join(r).encode('utf-8')
        elif isinstance(r,(dict, list)):
            return 0, json.dumps(r).encode('utf-8')
        
    def connected(self, func):
        """
        将函数声明为连接建立时自动调用的 connected 回调函数。   
        原函数不会被装饰器替换。
        """
        self.connected_callback = func
        return func

    def disconnected(self, func):
        """
        将函数声明为连断开时自动调用的 disconnected 回调函数。   
        原函数不会被装饰器替换。
        """
        self.disconnected_callback = func
        return func

    async def connection_handler(self, reader:aio.StreamReader, writer:aio.StreamWriter):
        """
        处理来自客户端的原始连接。
        """
        addr = writer.get_extra_info('peername')
        self.logger.info(f"接收到来自 {addr} 的连接。")
        try:
            await self.connected_callback(addr)
        except Exception as e:
            self.logger.error(f"在 connected 回调函数中发生错误: {e}")
        try:
            while True:
                type_len_data = await reader.readexactly(1)
                if not type_len_data:
                    break
                type_len = type_len_data[0]

                req_type_bytes = await reader.readexactly(type_len)
                req_type = req_type_bytes.decode('ascii')

                body_len_data = await reader.readexactly(4)
                body_len = int.from_bytes(body_len_data, byteorder='big', signed=False)

                body = await reader.readexactly(body_len) if body_len > 0 else b''

                try:
                    status, response_body = await self.request_handler(req_type, addr, body, reader, writer)
                except Exception as e:
                    status, response_body = 255,str(e).encode('utf-8')
                    self.logger.error(f"在请求处理器中发生错误: {e}")

                writer.write(status.to_bytes(1, byteorder='big', signed=False))
                writer.write(len(response_body).to_bytes(4, byteorder='big'))
                if response_body:
                    writer.write(response_body)
                await writer.drain()
        except (aio.IncompleteReadError, ConnectionResetError):
            self.logger.info(f"来自 {addr} 的连接已断开。")
            return
        except Exception as e:
            self.logger.error(f"处理来自 {addr} 的请求时发生一般错误: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                pass

            try:
                await self.disconnected_callback(addr)
            except Exception as e:
                self.logger.error(f"在 disconnect 回调函数中发生错误: {e}")

    async def run(self):
        """
        运行服务器。
        """
        server = await aio.start_server(
            self.connection_handler, host = self.host, port = self.port
        )
        async with server:
            await server.serve_forever()

class ScaffoldingGetPlayersContextManager:
    def __init__(self, parent:'Scaffolding'):
        self.parent = parent

    async def __aenter__(self) -> 'ScaffoldingGetPlayersContextManager':
        await self.parent.lock.acquire()
        return self
    
    async def __aexit__(self, *args):
        self.parent.lock.release()
    
    def __iter__(self) -> Iterable:
        return iter(self.parent.players.values())

class Scaffolding:
    def __init__(self, host:str = '0.0.0.0', port:int = 13659, mc_port:int = 25565, server:Optional[SServer] = None, host_player:Optional[SProfile] = None, setup_default_handlers:bool = True, llt:float = 15.0, checking_freq:float = 1.0, logger:Optional[logging.Logger] = None):
        """
        Args:
            host (str): 要绑定的地址。仅在不传入 server 时才有效。
            port (int): 要监听的端口。仅在不传入 server 时才有效。
            mc_port (int): 《我的世界》服务器运行的端口。仅在不传入 server 时才有效。
            server (SServer): 要使用的 SServer 实例。
            host_player (SProfile): 房主（即本机）的玩家身份。该身份会展示给所有玩家。
            setup_default_handlers (bool): 是否启用 MSSS 默认的标准协议处理函数和一般事件回调函数。默认的心跳管理器采用批处理模式。风险提示：默认行为一切从简，可能包含意外和漏洞。
            llt (float): 使用默认心跳管理器时，允许客户端无心跳的最长时间。超过该时间未心跳的客户端会被清除。
            checking_freq (float): 使用默认心跳管理器时，批处理程序的处理间隔。每隔该时间间隔都会检查一次客户端的心跳情况。
            logger (Logger): 要使用的日志记录器实例。其应提供和标准库 logging.Logger 类似的 API 接口。
        """
        try:
            mid = machineid.id()
        except Exception:
            mid = str(uuid.uuid4())
        self.host_player = host_player if host_player else SProfile(
            name = 'MnlSmile Scaffolding Server',
            machine_id = mid,
            vendor = 'MSSS',
            kind = SKindEnum.host
        )
        self.logger = logger if logger else logging.getLogger(f"<Scaffolding id='{id(self)} host='{host}' port='{port}' mc_port='{mc_port}' host_player='SProfile({host_player})'>")
        s = self.server = server if server else SServer(host, port, mc_port, logger = self.logger)
        self.players = { self.host_player.machine_id: self.host_player }
        self.players_lt:dict[str, float] = {}
        self.conns:dict[str, aio.StreamWriter] = {}
        self.lock = aio.Lock()
        self._clean_worker:Optional[Callable[[], Awaitable[None]]] = None
        self._clean_worker_task:Optional[aio.Task] = None

        if setup_default_handlers:
            @s.protocol('c:ping')
            async def ping(req:SRequest) -> bytes:
                return req.body

            @s.protocol('c:protocols')
            async def protocols(req:SRequest) -> list:
                return [k for k in s.protocol_handlers]

            @s.protocol('c:server_port')
            async def server_port(req:SRequest) -> bytes:
                return s.mc_port.to_bytes(2, byteorder='big', signed=False)
            
            @s.protocol('c:player_ping')
            async def player_ping(req:SRequest) -> None:
                p = req.as_pydantic(SProfile)
                async with self.lock:
                    if not self.players.get(p.machine_id):
                        self.logger.info(f"新玩家加入: <SProfile {p}>")
                    if req.writer is not (w := self.conns[p.machine_id]):
                        self.logger.info(f"玩家 <SProfile {p}> 使用一个新连接加入了房间，正在关闭旧连接。")
                        try:
                            w.close()
                            await w.wait_closed()
                        except Exception:
                            pass

                    self.players[p.machine_id] = p
                    self.conns[p.machine_id] = req.writer
                    self.players_lt[p.machine_id] = time.time()

            @s.protocol('c:player_easytier_id')
            async def player_easytier_id(req:SRequest) -> None:
                pass

            @s.protocol('c:player_profiles_list')
            async def player_profiles_list(req:SRequest) -> list[dict]:
                async with self.lock:
                    return [p.model_dump(mode='json') for p in self.players.values()]
            
            @s.disconnected
            async def disconnected(addr:tuple[str, int]) -> None:
                async with self.lock:
                    for mid, w in list(self.conns.items()):
                        if w.get_extra_info('peername') == addr:
                            try:
                                del self.players[mid]
                                del self.players_lt[mid]
                                del self.conns[mid]
                            except Exception as e:
                                pass
                            finally:
                                break

            async def clean_worker(llt:float = llt, checking_freq:float = 1.0):
                async with Timer(checking_freq, target = time.time) as timer:
                    async for t in timer:
                        async with self.lock:
                            for mid, ct in [i for i in self.players_lt.items()]:
                                if t - ct > llt and not mid == self.host_player.machine_id:
                                    try:
                                        self.logger.info(f"Cleaning player {mid}")
                                        w = self.conns[mid]
                                        w.close()
                                        await w.wait_closed()
                                        del self.players[mid]
                                        del self.players_lt[mid]
                                        del self.conns[mid]
                                    except Exception:
                                        pass
            self._clean_worker = clean_worker

    async def get_players_async(self) -> ScaffoldingGetPlayersContextManager:
        """
        通过自动加锁的异步上下文管理器安全地获取玩家列表。 

        示例:
        >>> app = Scaffolding(...)
        >>> async with app.get_players_async() as players:
        >>>     for p in players:
        >>>         print(f"<SProfile {p}>")
        """
        return ScaffoldingGetPlayersContextManager(self)

    async def kick(self, mid:str) -> bool:
        """
        踢出玩家。   
        方法不保证成功踢出。   
        风险提示：由于 Scaffolding 协议运行在 EasyTier 网络上，且《我的世界》端口号公开透明，玩家有办法完全绕开 Scaffolding 协议，直接通过 EasyTier 网络加入《我的世界》服务器。

        Args:
            mid (str): 目标玩家的机器标识符。
        """
        try:
            async with self.lock:
                w = self.conns[mid]
                w.close()
                await w.wait_closed()
                return True
        except Exception:
            return False

    def protocol(self, protocol:str):
        """
        将函数声明为协议处理器。   
        原函数不会被装饰器替换。

        Args:
            protocol (str): 要处理的协议，用半角冒号分隔，其中冒号前为命名空间，冒号后为协议名。传入的协议若为 any，则会注册为针对未实现协议的后备处理程序。
        """
        return self.server.protocol(protocol)
    
    def connected(self):
        """
        将函数声明为连接建立时自动调用的 connected 回调函数。   
        原函数不会被装饰器替换。
        """
        return self.server.connected
    
    def disconnected(self):
        """
        将函数声明为连断开时自动调用的 disconnected 回调函数。   
        原函数不会被装饰器替换。
        """
        return self.server.disconnected
    
    def easytier(self, code:str, path:str = './easytier-core', dhcp:bool = True, extras:list[str] = []) -> str:
        """
        按照传入的房间码，生成一种适用于 Windows 平台的 EasyTier 启动命令。

        Args:
            code (str): Scaffolding 房间码。
            path (str): EasyTier 的路径。
            dhcp (bool): 是否开启 DHCP。如果不开启，须要在 extras 参数中传入要使用的私网地址。
            extras (list[str]): 传递给 EasyTier 额外参数。
        """
        return ' '.join([
            path,
            f"--network-name scaffolding-mc-{code[2:11]}",
            f"--network-secret {code[12:]}",
            f"--hostname scaffolding-mc-server-{self.server.port}",
            f"-p \"https://etnode.zkitefly.eu.org/node1\"",
            f"-p \"https://etnode.zkitefly.eu.org/node2\""
        ] + ([f"-d"] if dhcp else []) + extras[:])

    async def run(self) -> None: 
        """
        运行 Scaffolding 服务器。   
        """
        if self._clean_worker:
            self._clean_worker_task = aio.create_task(self._clean_worker())
        await self.server.run()
        if self._clean_worker_task:
            self._clean_worker_task.cancel()

if __name__ == '__main__':
    app = Scaffolding()
    logger = logging.getLogger(__name__)
    logging.basicConfig(level=logging.INFO)
    logger.info('Use command:')
    logger.info(app.easytier('U/AAAA-AAAA-AAAA-AAAA'))
    logger.info('to launch EasyTier')
    aio.run(app.run())