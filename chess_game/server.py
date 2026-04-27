from __future__ import annotations
import socket
import threading
from typing import Dict
from .common import send_message, recv_message, ConnectionClosed

# Mock of the chess game logic - just to keep server running without game logic yet
class MockGame:
    def __init__(self):
        self.turn = 'white'
        self.winner = None
        self.status = 'Game in progress'
        
    def make_move(self, from_pos, to_pos, promotion=None):
        self.turn = 'black' if self.turn == 'white' else 'white'
        self.status = f'Moved {from_pos} to {to_pos}'
        return True, self.status
        
    def serialize(self):
        return {'board': [[None]*8 for _ in range(8)], 'turn': self.turn, 'winner': self.winner, 'status': self.status}


class ChessServer:
    # Server Initialization
    def __init__(self, host: str = '0.0.0.0', port: int = 5000) -> None:
        self.host = host
        self.port = port
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.clients: Dict[str, socket.socket] = {}
        self.lock = threading.Lock()
        self.game = MockGame() # Mock until we implement actual game logic
        self.running = True

    # Main loop that accepts clients and manages the game state
    def start(self) -> None:
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(2)
        print(f'Server listening on {self.host}:{self.port}')
        
        colors = ['white', 'black']
        while len(self.clients) < 2:
            client_sock, addr = self.server_socket.accept()
            color = colors[len(self.clients)]
            self.clients[color] = client_sock           
            threading.Thread(target=self.handle_client, args=(client_sock, color), daemon=True).start()
            print(f'{addr} connected as {color}')
            send_message(client_sock, {'type': 'welcome', 'color': color})
            
        self.broadcast({'type': 'info', 'message': 'Both players connected. Game started.'})

        while self.running:
            threading.Event().wait(1)

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
                winner = 'black' if color == 'white' else 'white'
                self.game.winner = winner
                self.game.status = f'{color.capitalize()} disconnected. {winner.capitalize()} wins by walkover.'
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