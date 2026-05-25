from __future__ import annotations
import socket
import threading
import time
from typing import Dict, Optional
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
        self.lock = threading.RLock() # RLock protects shared resources from race conditions
        self.game = ChessGame() # Initialize the actual chess game
        self.running = True
        self.game_started = False
        self.reconnect_timers: Dict[str, threading.Timer] = {}
        self.clock_waiting_for: Optional[str] = None
        self.clocks = {'white': 60.0, 'black': 60.0} # Set the time here (in seconds)
        self.turn_start_time: Optional[float] = None
        self.timeout_timer: Optional[threading.Timer] = None
        self.clock_waiting_for: Optional[str] = None

    def get_full_state(self) -> dict:
        state = self.game.serialize()
        current_clocks = self.clocks.copy()
        
        if self.game_started and self.turn_start_time and not self.game.winner and not self.reconnect_timers:
            ticking_color = self.clock_waiting_for if self.clock_waiting_for else self.game.turn
            elapsed = time.time() - self.turn_start_time
            current_clocks[ticking_color] = max(0.0, current_clocks[ticking_color] - elapsed)
            
        state['clocks'] = {k: round(v) for k, v in current_clocks.items()}
        state['clock_waiting_for'] = self.clock_waiting_for
        state['game_started'] = self.game_started
        return state

    # Manages asynchronous countdown for a player's chess clock
    def start_timeout_timer(self, color: str, remaining_time: float) -> None:
        if self.timeout_timer:
            self.timeout_timer.cancel()
        if remaining_time > 0:
            self.timeout_timer = threading.Timer(remaining_time, self.handle_timeout, args=(color,))
            self.timeout_timer.start()

    # Triggered when a player's clock reaches 0
    def handle_timeout(self, color: str) -> None:
        with self.lock:
            if self.running and not self.game.winner:
                winner = 'black' if color == 'white' else 'white'
                self.game.winner = winner
                self.game.status = f'Game over! Player {color.capitalize()} ran out of time. {winner.capitalize()} wins.'
                self.broadcast({'type': 'game_over', 'reason': 'timeout', 'state': self.get_full_state()})
                self.running = False

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
                    if self.turn_start_time is not None:
                        self.turn_start_time = time.time()
                        ticking_color = self.clock_waiting_for if self.clock_waiting_for else self.game.turn
                        self.start_timeout_timer(ticking_color, self.clocks[ticking_color])
                
                # Start a dedicated thread for the connected client
                threading.Thread(target=self.handle_client, args=(client_sock, color), daemon=True).start()
                print(f'{addr} Connected as {color} (Reconnect: {is_reconnect})')
                send_message(client_sock, {'type': 'welcome', 'color': color, 'state': self.get_full_state()})
                
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
                        if self.timeout_timer:
                            self.timeout_timer.cancel()
                        if self.turn_start_time:
                            ticking_color = self.clock_waiting_for if self.clock_waiting_for else self.game.turn
                            elapsed = time.time() - self.turn_start_time
                            self.clocks[ticking_color] = max(0.0, self.clocks[ticking_color] - elapsed)
                        self.broadcast({
                            'type': 'info', 
                            'message': f'Player {color.capitalize()} disconnected. Waiting for reconnection (30 seconds)...'
                        })
                        timer = threading.Timer(30.0, self.handle_walkover, args=(color,))
                        self.reconnect_timers[color] = timer
                        timer.start()
                else:
                    print(f'Player {color} disconnected before the game started.')

    # Ends the game if a disconnected player fails to return in time
    def handle_walkover(self, color: str) -> None:
        with self.lock:
            if color in self.reconnect_timers:
                del self.reconnect_timers[color]

            if color not in self.clients and self.running and not self.game.winner:
                winner = 'black' if color == 'white' else 'white'
                self.game.winner = winner
                self.game.status = f'{color.capitalize()} did not reconnect. {winner.capitalize()} wins by walkover.'
                self.broadcast({'type': 'game_over', 'reason': 'disconnect', 'state': self.get_full_state()})
                self.running = False

    # Method to handle incoming messages from a client, it processes moves and handles disconnections
    def handle_client(self, sock: socket.socket, color: str) -> None:
        try:
            while self.running:
                message = recv_message(sock)
                with self.lock:
                    if message.get('type') == 'move':
                        if not self.game_started:
                            send_message(sock, {'type': 'error', 'message': 'Wait for the game to start.', 'state': self.get_full_state()})
                            continue
                        if self.clock_waiting_for:
                            send_message(sock, {'type': 'error', 'message': f'Wait! Player {self.clock_waiting_for} must click the clock.', 'state': self.get_full_state()})
                            continue
                        if self.game.turn != color:
                            send_message(sock, {'type': 'error', 'message': 'Wait for your turn.', 'state': self.get_full_state()})
                            continue
                            
                        ok, status = self.game.make_move(message['from_pos'], message['to_pos'], message.get('promotion'))
                        if not ok:
                            send_message(sock, {'type': 'error', 'message': status, 'state': self.get_full_state()})
                        else:
                            if not self.game.winner:
                                if self.turn_start_time is None:
                                    self.turn_start_time = time.time()
                                    self.start_timeout_timer(color, self.clocks[color])
                                
                                self.clock_waiting_for = color
                                status = f'Move made. {color.capitalize()} must click the clock (press SPACE)!'
                            self.broadcast({'type': 'state', 'message': status, 'state': self.get_full_state()})
                            if self.game.winner:
                                self.running = False
                                self.broadcast({'type': 'game_over', 'reason': 'finished', 'state': self.get_full_state()})
                    
                    elif message.get('type') == 'get_moves':
                        r = message.get('r')
                        c = message.get('c')

                        if r is None or c is None:
                            send_message(sock, {
                                'type': 'error',
                                'message': 'Invalid coordinates.',
                                'state': self.get_full_state()
                            })
                            continue

                        piece = self.game.board[r][c]

                        if piece is None:
                            send_message(sock, {
                                'type': 'moves',
                                'from': (r, c),
                                'moves': [],
                                'state': self.get_full_state()
                            })
                            continue

                        if piece.color != color:
                            send_message(sock, {
                                'type': 'moves',
                                'from': (r, c),
                                'moves': [],
                                'state': self.get_full_state()
                            })
                            continue

                        moves = self.game.legal_moves(r, c)

                        send_message(sock, {
                            'type': 'moves',
                            'from': (r, c),
                            'moves': moves,
                            'state': self.get_full_state()
                        })

                    elif message.get('type') == 'clock_hit':
                        if self.clock_waiting_for == color:
                            elapsed = time.time() - self.turn_start_time
                            self.clocks[color] = max(0.0, self.clocks[color] - elapsed)

                            if self.timeout_timer:
                                self.timeout_timer.cancel()
                                
                            self.clock_waiting_for = None
                            next_player = self.game.turn
                            
                            self.turn_start_time = time.time()
                            self.start_timeout_timer(next_player, self.clocks[next_player])
                            
                            status = f'Clock clicked. Now it\'s {self.game.turn}\'s turn.'
                            self.broadcast({'type': 'state', 'message': status, 'state': self.get_full_state()})
                        else:
                            send_message(sock, {'type': 'error', 'message': 'Other player must click the clock.', 'state': self.get_full_state()})
                    elif message.get('type') == 'quit':
                        raise ConnectionClosed('Client quit')
        except (ConnectionClosed, OSError):
            self.disconnect_player(color)


if __name__ == '__main__':
    ChessServer().start()