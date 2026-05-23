from __future__ import annotations
import socket
import threading
from typing import Dict
from common import send_message, recv_message, ConnectionClosed
from chess_logic import ChessGame

class ChessServer:
    # Server Initialization
    def __init__(self, host: str = '0.0.0.0', port: int = 5000) -> None:
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: Dict[str, socket.socket] = {}
        self.lock = threading.Lock()
        self.game = ChessGame() # Initialize the actual chess game
        self.running = True
        self.game_started = False
        self.reconnect_timers: Dict[str, threading.Timer] = {}

    # Main loop that accepts clients and manages the game state
    def start(self) -> None:
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(2)
        print(f'Server listening on {self.host}:{self.port}')
        
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
            except OSError:
                break
            
            with self.lock:
                color = None
                if 'white' not in self.clients:
                    color = 'white'
                elif 'black' not in self.clients:
                    color = 'black'

                if not color:
                    try:
                        send_message(client_sock, {'type': 'error', 'message': 'Mecz jest już pełen.'})
                        client_sock.close()
                    except OSError:
                        pass
                    continue
                
                self.clients[color] = client_sock

                is_reconnect = color in self.reconnect_timers
                if is_reconnect:
                    self.reconnect_timers[color].cancel()
                    del self.reconnect_timers[color]
                
                threading.Thread(target=self.handle_client, args=(client_sock, color), daemon=True).start()
                print(f'{addr} Connected as {color} (Reconnect: {is_reconnect})')
                send_message(client_sock, {'type': 'welcome', 'color': color, 'state': self.game.serialize()})
                
                if is_reconnect:
                    self.broadcast({'type': 'info', 'message': f'Player {color.capitalize()} reconnected! Game resumed.'})
                else:
                    if len(self.clients) == 2 and not self.game_started:
                        self.game_started = True
                        self.broadcast({'type': 'info', 'message': 'Both players connected. Game started.'})

    # Method to send a message to all connected clients, it also handles disconnections
    def broadcast(self, message: dict) -> None:
        dead = []
        for color, sock in self.clients.items():
            try:
                send_message(sock, message)
            except OSError:
                dead.append(color)
                
        for color in dead:
            self.disconnect_player(color)

    # Method to safely disconnect a player and handle game state if a player disconnects
    def disconnect_player(self, color: str) -> None:
        with self.lock:
            sock = self.clients.pop(color, None)
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
                    
            if self.running and not self.game.winner:
                if self.game_started:
                    if color not in self.reconnect_timers:
                        print(f'Player {color} disconnected. Waiting 30s for reconnection...')
                        self.broadcast({
                            'type': 'info', 
                            'message': f'Player {color.capitalize()} disconnected. Waiting for reconnection (30 seconds)...'
                        })
                        timer = threading.Timer(30.0, self.handle_walkover, args=(color,))
                        self.reconnect_timers[color] = timer
                        timer.start()
                else:
                    print(f'Player {color} disconnected before the game started.')

    def handle_walkover(self, color: str) -> None:
        with self.lock:
            if color in self.reconnect_timers:
                del self.reconnect_timers[color]
            
            # Jeżeli gracz wciąż nie wrócił do słownika clients, ogłaszamy walkower
            if color not in self.clients and self.running and not self.game.winner:
                winner = 'black' if color == 'white' else 'white'
                self.game.winner = winner
                self.game.status = f'{color.capitalize()} did not reconnect. {winner.capitalize()} wins by walkover.'
                self.broadcast({'type': 'game_over', 'reason': 'disconnect', 'state': self.game.serialize()})
                self.running = False

    # Method to handle incoming messages from a client, it processes moves and handles disconnections
    def handle_client(self, sock: socket.socket, color: str) -> None:
        try:
            while self.running:
                message = recv_message(sock)
                if message.get('type') == 'move':
                    with self.lock:
                        if self.game.turn != color:
                            send_message(sock, {'type': 'error', 'message': 'Wait for your turn.', 'state': self.game.serialize()})
                            continue
                            
                        ok, status = self.game.make_move(message['from_pos'], message['to_pos'], message.get('promotion'))
                        if not ok:
                            send_message(sock, {'type': 'error', 'message': status, 'state': self.game.serialize()})
                        else:
                            self.broadcast({'type': 'state', 'message': status, 'state': self.game.serialize()})
                            if self.game.winner:
                                self.running = False
                                self.broadcast({'type': 'game_over', 'reason': 'finished', 'state': self.game.serialize()})
                                
                elif message.get('type') == 'quit':
                    raise ConnectionClosed('Client quit')
        except (ConnectionClosed, OSError):
            self.disconnect_player(color)


if __name__ == '__main__':
    ChessServer().start()