from __future__ import annotations
import copy
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog
from common import send_message, recv_message, ConnectionClosed

LIGHT = '#f0d9b5'
DARK = '#b58863'
SELECTED = '#f6f669'
LEGAL = '#7ec850'

SQUARE_SIZE = 72
ANIM_STEPS = 14
ANIM_DELAY_MS = 28


class ChessClient:
    def __init__(self, host: str = '127.0.0.1', port: int = 5000) -> None:
        self.legal_moves = []
        self.host = host
        self.port = port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((host, port))

        welcome = recv_message(self.sock)
        self.color = welcome['color']
        self.state = welcome['state']

        self.selected = None
        self._display_board = copy.deepcopy(self.state['board'])
        self._animating = False
        self._pending_state = None

        self.root = tk.Tk()
        self.root.title(f'Network Chess - {self.color}')
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

        self.status_var = tk.StringVar(value='Connecting...')
        self.info_var = tk.StringVar(value='')
        self.piece_font = ('Arial', int(SQUARE_SIZE * 0.55))

        self._build_ui()
        self.apply_state(self.state, animate=False)

        self.update_clocks_loop()

        self.listener = threading.Thread(target=self.listen_server, daemon=True)
        self.listener.start()

    def _build_ui(self):
        board_frame = tk.Frame(self.root)
        board_frame.pack(padx=10, pady=10)

        size = SQUARE_SIZE * 8
        self.canvas = tk.Canvas(
            board_frame,
            width=size,
            height=size,
            highlightthickness=0,
            bg=LIGHT,
        )
        self.canvas.pack()
        self.canvas.bind('<Button-1>', self.on_canvas_click)

        tk.Label(self.root, textvariable=self.status_var, font=('Arial', 12, 'bold')).pack(pady=(0, 4))
        tk.Label(self.root, textvariable=self.info_var, wraplength=520, justify='center').pack(padx=10, pady=(0, 10))

        self.root.bind('<space>', self.hit_clock)

    def _board_to_display(self, r: int, c: int) -> tuple[int, int]:
        if self.color == 'black':
            return 7 - r, 7 - c
        return r, c

    def _display_to_board(self, dr: int, dc: int) -> tuple[int, int]:
        if self.color == 'black':
            return 7 - dr, 7 - dc
        return dr, dc

    def _square_center(self, dr: int, dc: int) -> tuple[float, float]:
        x = dc * SQUARE_SIZE + SQUARE_SIZE / 2
        y = dr * SQUARE_SIZE + SQUARE_SIZE / 2
        return x, y

    def on_canvas_click(self, event):
        dc = event.x // SQUARE_SIZE
        dr = event.y // SQUARE_SIZE
        if not (0 <= dr < 8 and 0 <= dc < 8):
            return
        r, c = self._display_to_board(dr, dc)
        self.on_square(r, c)

    def on_square(self, r, c):
        if self._animating:
            return

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

            send_message(self.sock, {
                'type': 'get_moves',
                'r': r,
                'c': c
            })

            self.redraw()
            self.info_var.set('Now select a destination square.')
            return

        if self.selected == (r, c):
            self.selected = None
            self.legal_moves = []
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

            is_valid = False

            if sel_piece['color'] == 'white' and from_r == 1 and r == 0:
                if from_c == c and target_piece is None:
                    is_valid = True
                elif abs(from_c - c) == 1 and target_piece is not None:
                    is_valid = True

            elif sel_piece['color'] == 'black' and from_r == 6 and r == 7:
                if from_c == c and target_piece is None:
                    is_valid = True
                elif abs(from_c - c) == 1 and target_piece is not None:
                    is_valid = True

            if is_valid:
                promotion = simpledialog.askstring(
                    'Promotion', 'Promote to (Q/R/B/N):', initialvalue='Q'
                ) or 'Q'
                promotion = promotion.upper()

        try:
            send_message(self.sock, {
                'type': 'move',
                'from_pos': from_pos,
                'to_pos': to_pos,
                'promotion': promotion
            })
        except OSError:
            self.info_var.set('Connection lost while sending move.')

        self.selected = None
        self.legal_moves = []
        self.redraw()

    def handle_message(self, msg):
        if 'state' in msg:
            self.apply_state(msg['state'])

        if msg['type'] == 'error':
            self.info_var.set(msg['message'])

        elif msg['type'] in ('state', 'info', 'game_over'):
            self.info_var.set(msg.get('message') or self.state.get('status', ''))
            if msg['type'] == 'game_over':
                messagebox.showinfo('Game over', self.state['status'])

        elif msg['type'] == 'moves':
            self.legal_moves = [tuple(m) for m in msg['moves']]
            self.redraw()

    @staticmethod
    def _same_piece(a, b) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return a['color'] == b['color'] and a['kind'] == b['kind']

    @staticmethod
    def _boards_differ(old_board, new_board) -> bool:
        for r in range(8):
            for c in range(8):
                if not ChessClient._same_piece(old_board[r][c], new_board[r][c]):
                    return True
        return False

    def _detect_movements(self, old_board, new_board, next_turn: str) -> list[dict]:
        mover = 'white' if next_turn == 'black' else 'black'
        emptied = []
        filled = []

        for r in range(8):
            for c in range(8):
                op = old_board[r][c]
                np = new_board[r][c]
                if self._same_piece(op, np):
                    continue
                if op is not None:
                    emptied.append((r, c, op))
                if np is not None:
                    filled.append((r, c, np))

        movements = []
        remaining_filled = list(filled)

        for fr, fc, piece in emptied:
            if piece['color'] != mover:
                continue
            match_idx = None
            for i, (tr, tc, dest) in enumerate(remaining_filled):
                if dest['color'] != piece['color']:
                    continue
                if (tr, tc) == (fr, fc):
                    continue
                same_kind = dest['kind'] == piece['kind']
                promotion = piece['kind'] == 'P' and dest['kind'] in 'QRBN'
                if same_kind or promotion:
                    match_idx = i
                    break
            if match_idx is None:
                continue
            tr, tc, dest = remaining_filled.pop(match_idx)
            movements.append({
                'fr': fr, 'fc': fc, 'tr': tr, 'tc': tc,
                'symbol': dest['symbol'],
            })

        return movements

    def _start_animation(self, movements: list[dict], final_state: dict, old_board: list) -> None:
        self._animating = True
        self._anim_step = 0
        self._anim_movements = movements
        self._anim_final_state = final_state

        interim = copy.deepcopy(old_board)
        for m in movements:
            interim[m['fr']][m['fc']] = None
        self._display_board = interim
        self.redraw()

        self._anim_items = []
        for m in movements:
            dr, dc = self._board_to_display(m['fr'], m['fc'])
            x, y = self._square_center(dr, dc)
            item = self.canvas.create_text(
                x, y,
                text=m['symbol'],
                font=self.piece_font,
                tags='anim',
            )
            self._anim_items.append(item)

        self._anim_tick()

    def _anim_tick(self) -> None:
        self._anim_step += 1
        t = min(1.0, self._anim_step / ANIM_STEPS)

        for item, m in zip(self._anim_items, self._anim_movements):
            dr1, dc1 = self._board_to_display(m['fr'], m['fc'])
            dr2, dc2 = self._board_to_display(m['tr'], m['tc'])
            x1, y1 = self._square_center(dr1, dc1)
            x2, y2 = self._square_center(dr2, dc2)
            x = x1 + (x2 - x1) * t
            y = y1 + (y2 - y1) * t
            self.canvas.coords(item, x, y)

        if self._anim_step < ANIM_STEPS:
            self.root.after(ANIM_DELAY_MS, self._anim_tick)
        else:
            self.canvas.delete('anim')
            self._animating = False
            self._display_board = copy.deepcopy(self._anim_final_state['board'])
            self._update_status_text(self._anim_final_state)
            self.redraw()

            if self._pending_state is not None:
                pending = self._pending_state
                self._pending_state = None
                self.apply_state(pending)

    def redraw(self):
        board = self._display_board
        self.canvas.delete('all')

        for dr in range(8):
            for dc in range(8):
                br, bc = self._display_to_board(dr, dc)
                base = LIGHT if (br + bc) % 2 == 0 else DARK

                if self.selected == (br, bc):
                    base = SELECTED
                if (br, bc) in self.legal_moves:
                    base = LEGAL

                x0 = dc * SQUARE_SIZE
                y0 = dr * SQUARE_SIZE
                x1 = x0 + SQUARE_SIZE
                y1 = y0 + SQUARE_SIZE
                self.canvas.create_rectangle(x0, y0, x1, y1, fill=base, outline=base)

                piece = board[br][bc]
                if piece is not None:
                    cx, cy = self._square_center(dr, dc)
                    self.canvas.create_text(cx, cy, text=piece['symbol'], font=self.piece_font)

    def idx_to_pos(self, r, c):
        return f"{'abcdefgh'[c]}{8-r}"

    def hit_clock(self, event=None):
        send_message(self.sock, {'type': 'clock_hit'})

    def update_clocks_loop(self):
        if self.state and self.state.get('game_started') and not self.state.get('winner'):
            if 'clocks' in self.state:
                ticking = self.state.get('clock_waiting_for') or self.state.get('turn')
                if ticking in self.state['clocks'] and self.state['clocks'][ticking] > 0:
                    self.state['clocks'][ticking] -= 1
                    self.apply_state(self.state, animate=False)

        self.root.after(1000, self.update_clocks_loop)

    def listen_server(self):
        try:
            while True:
                msg = recv_message(self.sock)
                self.root.after(0, self.handle_message, msg)
        except (ConnectionClosed, OSError):
            self.root.after(0, lambda: self.connection_lost('Connection lost'))

    def _update_status_text(self, state: dict) -> None:
        clocks = state.get('clocks', {'white': 60, 'black': 60})
        w_min, w_sec = divmod(clocks.get('white', 60), 60)
        b_min, b_sec = divmod(clocks.get('black', 60), 60)
        time_text = f"[White: {int(w_min):02d}:{int(w_sec):02d}] [Black: {int(b_min):02d}:{int(b_sec):02d}]"

        turn_text = f"You are {self.color} | Turn: {state['turn']} | {time_text}"
        if state.get('winner'):
            turn_text += f" | Result: {state['status']}"
        self.status_var.set(turn_text)

    def apply_state(self, state, animate: bool = True):
        old_board = copy.deepcopy(self.state['board']) if self.state else None

        if self._animating:
            self.state = state
            self._pending_state = state
            self._update_status_text(state)
            return

        self.state = state
        self._update_status_text(state)

        new_board = state['board']
        should_animate = (
            animate
            and old_board is not None
            and self._boards_differ(old_board, new_board)
        )

        if should_animate:
            movements = self._detect_movements(old_board, new_board, state['turn'])
            if movements:
                self._start_animation(movements, state, old_board)
                return

        self._display_board = copy.deepcopy(new_board)
        self.root.after(0, self.redraw)

    def connection_lost(self, text):
        self.info_var.set(text)
        messagebox.showwarning('Disconnected', text)

    def on_close(self):
        try:
            send_message(self.sock, {'type': 'quit'})
        except OSError:
            pass
        self.sock.close()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    host = input('Server IP [127.0.0.1]: ').strip() or '127.0.0.1'
    ChessClient(host=host).run()
