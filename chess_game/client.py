from __future__ import annotations
import socket
import threading
from typing import Callable, Any, Dict, Optional
from .common import send_message, recv_message, ConnectionClosed

class ChessNetworkClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 5000) -> None:
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.is_running = False
        self.color: Optional[str] = None
        self.state: Optional[Dict[str, Any]] = None

        # Callbacks for UI or other components to react to game events
        self.on_state_update: Optional[Callable[[Dict[str, Any]], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_info: Optional[Callable[[str], None]] = None
        self.on_game_over: Optional[Callable[[str], None]] = None
        self.on_connection_lost: Optional[Callable[[str], None]] = None

    # Method to connect to the server, it also starts the listener thread to receive messages from the server
    def connect(self) -> None:
        self.sock.connect((self.host, self.port))
        welcome = recv_message(self.sock)
        self.color = welcome['color']
        self.state = welcome['state']
        self.is_running = True
        self.listener = threading.Thread(target=self.listen_server, daemon=True)
        self.listener.start()

    # Method to send a move to the server, it also handles disconnections while sending
    def send_move(self, from_pos: str, to_pos: str, promotion: Optional[str] = None) -> None:
        if not self.is_running:
            return
        try:
            send_message(self.sock, {
                'type': 'move', 
                'from_pos': from_pos, 
                'to_pos': to_pos, 
                'promotion': promotion
            })
        except OSError:
            if self.on_connection_lost:
                self.on_connection_lost('Connection lost while sending move.')

    # Method to disconnect from the server
    def disconnect(self) -> None:
        self.is_running = False
        try:
            send_message(self.sock, {'type': 'quit'})
        except (OSError, ConnectionClosed):
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    # Method that runs in a background thread to listen for messages from the server, it also handles disconnections while receiving
    def listen_server(self) -> None:
        try:
            while self.is_running:
                msg = recv_message(self.sock)
                self.handle_message(msg)
        except (ConnectionClosed, OSError):
            if self.is_running and self.on_connection_lost:
                self.on_connection_lost('Connection to server was lost.')

    # Method to handle incoming messages from the server, it updates the game state
    def handle_message(self, msg: Dict[str, Any]) -> None:
        if 'state' in msg:
            self.state = msg['state']
            if self.on_state_update:
                self.on_state_update(self.state)

        if msg['type'] == 'error':
            if self.on_error:
                self.on_error(msg['message'])

        elif msg['type'] in ('state', 'info', 'game_over'):
            info_text = msg.get('message') or (self.state.get('status', '') if self.state else '')
            
            if self.on_info and info_text:
                self.on_info(info_text)
                
            if msg['type'] == 'game_over':
                if self.on_game_over:
                    self.on_game_over(info_text)