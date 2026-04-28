from __future__ import annotations
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from common import send_message, recv_message, ConnectionClosed

LIGHT = '#f0d9b5'
DARK = '#b58863'
SELECTED = '#f6f669'
LEGAL = '#7ec850'


class ChessClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 5000) -> None:
        self.host = host
        self.port = port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))
        welcome = recv_message(self.sock)
        self.color = welcome['color']
        self.state = welcome['state']
        self.selected = None
        self.root = tk.Tk()
        self.root.title(f'Network Chess - {self.color}')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)
        self.status_var = tk.StringVar(value='Connecting...')
        self.info_var = tk.StringVar(value='')
        self.buttons = []
        self._build_ui()
        self.apply_state(self.state)
        self.listener = threading.Thread(target=self.listen_server, daemon=True)
        self.listener.start()

    def _build_ui(self):
        board_frame = tk.Frame(self.root)
        board_frame.pack(padx=10, pady=10)
        for r in range(8):
            row = []
            for c in range(8):
                btn = tk.Button(board_frame, width=4, height=2, font=('Arial', 20), command=lambda rr=r, cc=c: self.on_square(rr, cc))
                btn.grid(row=r, column=c)
                row.append(btn)
            self.buttons.append(row)
        tk.Label(self.root, textvariable=self.status_var, font=('Arial', 12, 'bold')).pack(pady=(0, 4))
        tk.Label(self.root, textvariable=self.info_var, wraplength=520, justify='center').pack(padx=10, pady=(0, 10))

    def on_square(self, r, c):
        board = self.state['board']
        piece = board[r][c]
        my_turn = self.state['turn'] == self.color and not self.state.get('winner')
        if not my_turn:
            self.info_var.set('It is not your turn.')
            return
        if self.selected is None:
            if piece is None:
                self.info_var.set('Select one of your own pieces first.')
                return
            if piece['color'] != self.color:
                self.info_var.set('You can only move your own pieces.')
                return
            self.selected = (r, c)
            self.redraw()
            self.info_var.set('Now select a destination square.')
            return
        if self.selected == (r, c):
            self.selected = None
            self.redraw()
            self.info_var.set('Selection cleared.')
            return
        from_pos = self.idx_to_pos(*self.selected)
        to_pos = self.idx_to_pos(r, c)
        promotion = None
        sel_piece = board[self.selected[0]][self.selected[1]]
        if sel_piece and sel_piece['kind'] == 'P':
            from_r, from_c = self.selected
            target_piece = board[r][c]
            is_valid_promotion_attempt = False
            if sel_piece['color'] == 'white' and from_r == 1 and r == 0:
                if from_c == c and target_piece is None:
                    is_valid_promotion_attempt = True
                elif abs(from_c - c) == 1 and target_piece is not None:
                    is_valid_promotion_attempt = True
                    
            elif sel_piece['color'] == 'black' and from_r == 6 and r == 7:
                if from_c == c and target_piece is None:
                    is_valid_promotion_attempt = True
                elif abs(from_c - c) == 1 and target_piece is not None:
                    is_valid_promotion_attempt = True

            if is_valid_promotion_attempt:
                promotion = simpledialog.askstring('Promotion', 'Promote to (Q/R/B/N):', initialvalue='Q') or 'Q'
                promotion = promotion.upper()
                if promotion not in {'Q', 'R', 'B', 'N'}:
                    self.info_var.set('Invalid promotion choice.')
                    self.selected = None
                    self.redraw()
                    return
        try:
            send_message(self.sock, {'type': 'move', 'from_pos': from_pos, 'to_pos': to_pos, 'promotion': promotion})
        except OSError:
            self.info_var.set('Connection lost while sending move.')
        self.selected = None
        self.redraw()

    def idx_to_pos(self, r, c):
        return f"{'abcdefgh'[c]}{8-r}"

    def listen_server(self):
        try:
            while True:
                msg = recv_message(self.sock)
                self.root.after(0, self.handle_message, msg)
        except (ConnectionClosed, OSError):
            self.root.after(0, lambda: self.connection_lost('Connection to server was lost.'))

    def handle_message(self, msg):
        if 'state' in msg:
            self.apply_state(msg['state'])
        if msg['type'] == 'error':
            self.info_var.set(msg['message'])
        elif msg['type'] in ('state', 'info', 'game_over'):
            self.info_var.set(msg.get('message') or self.state.get('status', ''))
            if msg['type'] == 'game_over':
                messagebox.showinfo('Game over', self.state['status'])

    def apply_state(self, state):
        self.state = state
        turn_text = f"You are {self.color}. Turn: {state['turn']}"
        if state.get('winner'):
            turn_text += f" | Result: {state['status']}"
        self.status_var.set(turn_text)
        self.redraw()

    def redraw(self):
        board = self.state['board']
        for r in range(8):
            for c in range(8):
                base = LIGHT if (r + c) % 2 == 0 else DARK
                if self.selected == (r, c):
                    base = SELECTED
                btn = self.buttons[r][c]
                piece = board[r][c]
                btn.configure(text='' if piece is None else piece['symbol'], bg=base, activebackground=base)

    def connection_lost(self, text):
        self.info_var.set(text)
        messagebox.showwarning('Disconnected', text)

    def on_close(self):
        try:
            send_message(self.sock, {'type': 'quit'})
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    host = input('Server IP [127.0.0.1]: ').strip() or '127.0.0.1'
    ChessClient(host=host).run()
