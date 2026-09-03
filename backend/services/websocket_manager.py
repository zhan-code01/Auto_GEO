# backend/services/websocket_manager.py
from typing import Dict, List
from fastapi import WebSocket
from loguru import logger


class ConnectionManager:
    def __init__(self):
        # 存储活跃的连接 {client_id: WebSocket}
        self.active_connections: Dict[str, WebSocket] = {}
        # user_id -> [client_id, ...] 映射（Agent V2 异步任务推送用）
        self.user_connections: Dict[int, List[str]] = {}

    async def connect(self, websocket: WebSocket, client_id: str, user_id: int | None = None):
        """接受连接。若提供 user_id，则建立 user → client 映射，便于按用户推送。"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        if user_id is not None:
            self.user_connections.setdefault(user_id, []).append(client_id)
        logger.info(f"WebSocket连接建立: client_id={client_id} user_id={user_id}")

    def disconnect(self, client_id: str):
        """断开连接"""
        if client_id in self.active_connections:
            del self.active_connections[client_id]
            logger.info(f"WebSocket连接断开: {client_id}")
        # 清理 user_connections 中的引用
        for user_id, clients in list(self.user_connections.items()):
            if client_id in clients:
                clients.remove(client_id)
                if not clients:
                    del self.user_connections[user_id]
                break

    async def send_personal(self, message: dict, client_id: str):
        """🌟 补全此方法：发送消息给指定客户端"""
        if client_id in self.active_connections:
            try:
                await self.active_connections[client_id].send_json(message)
            except Exception as e:
                logger.error(f"发送个人消息失败: {e}")

    async def notify_user(self, user_id: int, message: dict) -> bool:
        """推送给某用户的所有在线连接（Agent V2 异步任务通知用）。

        Returns:
            bool: True 表示至少有一个连接收到；False 表示用户离线
        """
        clients = self.user_connections.get(user_id, [])
        if not clients:
            return False  # 用户离线
        for client_id in list(clients):
            await self.send_personal(message, client_id)
        return True

    def get_user_connections(self, user_id: int) -> List[str]:
        """获取用户所有在线 client_id。"""
        return list(self.user_connections.get(user_id, []))

    async def broadcast(self, message: dict):
        """广播消息给所有客户端"""
        for connection in list(self.active_connections.values()):
            try:
                await connection.send_json(message)
            except Exception:
                # 忽略已经失效的连接
                pass


# 创建全局单例
ws_manager = ConnectionManager()
