from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple

FILES = 'abcdefgh'
RANKS = '12345678'


def in_bounds(r: int, c: int) -> bool:
    return 0 <= r < 8 and 0 <= c < 8


def pos_to_idx(pos: str) -> Tuple[int, int]:
    c = FILES.index(pos[0])
    r = 8 - int(pos[1])
    return r, c


def idx_to_pos(r: int, c: int) -> str:
    return f'{FILES[c]}{8-r}'


@dataclass
class Piece:
    color: str
    kind: str

    def symbol(self) -> str:
        symbols = {
            ('white', 'K'): '♔', ('white', 'Q'): '♕   ', ('white', 'R'): '♖', ('white', 'B'): '♗', ('white', 'N'): '♘', ('white', 'P'): '♙',
            ('black', 'K'): '♚', ('black', 'Q'): '♛', ('black', 'R'): '♜', ('black', 'B'): '♝', ('black', 'N'): '♞', ('black', 'P'): '♟',
        }
        return symbols[(self.color, self.kind)]


class ChessGame:
    def __init__(self) -> None:
        self.board: List[List[Optional[Piece]]] = [[None for _ in range(8)] for _ in range(8)]
        self.turn = 'white'
        self.winner: Optional[str] = None
        self.status = 'White to move.'
        self.en_passant_target: Optional[Tuple[int, int]] = None
        self.castling = {
            'white': {'K': True, 'Q': True},
            'black': {'K': True, 'Q': True},
        }
        self._setup()

    def _setup(self) -> None:
        order = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
        for c, kind in enumerate(order):
            self.board[0][c] = Piece('black', kind)
            self.board[7][c] = Piece('white', kind)
        for c in range(8):
            self.board[1][c] = Piece('black', 'P')
            self.board[6][c] = Piece('white', 'P')

    def serialize(self):
        rows = []
        for row in self.board:
            rows.append([
                None if p is None else {'color': p.color, 'kind': p.kind, 'symbol': p.symbol()}
                for p in row
            ])
        return {
            'board': rows,
            'turn': self.turn,
            'winner': self.winner,
            'status': self.status,
        }

    def clone(self) -> 'ChessGame':
        import copy
        return copy.deepcopy(self)

    def find_king(self, color: str) -> Tuple[int, int]:
        for r in range(8):
            for c in range(8):
                p = self.board[r][c]
                if p and p.color == color and p.kind == 'K':
                    return (r, c)
        raise ValueError('King not found')
     # function to check for checks and attacks on the king
    def is_square_attacked(self, r: int, c: int, by_color: str) -> bool:
        for rr in range(8):
            for cc in range(8):
                p = self.board[rr][cc]
                if p and p.color == by_color:
                    if (r, c) in self.pseudo_moves(rr, cc, attacks_only=True):
                        return True
        return False
     # we check if our king is in check
    def in_check(self, color: str) -> bool:
        kr, kc = self.find_king(color)
        enemy = 'black' if color == 'white' else 'white'
        return self.is_square_attacked(kr, kc, enemy)
     # we simualate all the moves possible of every chess piece to validate them against the rules of the game
    def pseudo_moves(self, r: int, c: int, attacks_only: bool = False):
        p = self.board[r][c]
        if not p:
            return []
        moves = []
        direction = -1 if p.color == 'white' else 1
        enemy = 'black' if p.color == 'white' else 'white'
        if p.kind == 'P':
            nr = r + direction
            if not attacks_only and in_bounds(nr, c) and self.board[nr][c] is None:
                moves.append((nr, c))
                start_row = 6 if p.color == 'white' else 1
                nr2 = r + 2 * direction
                if r == start_row and self.board[nr2][c] is None:
                    moves.append((nr2, c))
            for dc in (-1, 1):
                nc = c + dc
                if in_bounds(nr, nc):
                    target = self.board[nr][nc]
                    if attacks_only:
                        moves.append((nr, nc))
                    elif target and target.color == enemy:
                        moves.append((nr, nc))
                    elif self.en_passant_target == (nr, nc):
                        moves.append((nr, nc))
        elif p.kind == 'N':
            for dr, dc in [(-2,-1),(-2,1),(-1,-2),(-1,2),(1,-2),(1,2),(2,-1),(2,1)]:
                nr, nc = r + dr, c + dc
                if in_bounds(nr, nc):
                    target = self.board[nr][nc]
                    if target is None or target.color != p.color:
                        moves.append((nr, nc))
        elif p.kind in ('B', 'R', 'Q'):
            directions = []
            if p.kind in ('B', 'Q'):
                directions += [(-1,-1),(-1,1),(1,-1),(1,1)]
            if p.kind in ('R', 'Q'):
                directions += [(-1,0),(1,0),(0,-1),(0,1)]
            for dr, dc in directions:
                nr, nc = r + dr, c + dc
                while in_bounds(nr, nc):
                    target = self.board[nr][nc]
                    if target is None:
                        moves.append((nr, nc))
                    else:
                        if target.color != p.color:
                            moves.append((nr, nc))
                        break
                    nr += dr
                    nc += dc
        elif p.kind == 'K':
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = r + dr, c + dc
                    if in_bounds(nr, nc):
                        target = self.board[nr][nc]
                        if target is None or target.color != p.color:
                            moves.append((nr, nc))
            if not attacks_only:
                row = 7 if p.color == 'white' else 0
                if r == row and c == 4 and not self.in_check(p.color):
                    if self.castling[p.color]['K'] and self.board[row][5] is None and self.board[row][6] is None:
                        if not self.is_square_attacked(row, 5, enemy) and not self.is_square_attacked(row, 6, enemy):
                            rook = self.board[row][7]
                            if rook and rook.kind == 'R' and rook.color == p.color:
                                moves.append((row, 6))
                    if self.castling[p.color]['Q'] and self.board[row][1] is None and self.board[row][2] is None and self.board[row][3] is None:
                        if not self.is_square_attacked(row, 3, enemy) and not self.is_square_attacked(row, 2, enemy):
                            rook = self.board[row][0]
                            if rook and rook.kind == 'R' and rook.color == p.color:
                                moves.append((row, 2))
        return moves
    # we have to check for all the legal moves like if we move a piece then we will be in check or if we can move our king so that he isnt in check or we have to move a piece cause otherwise we lose the game
    def legal_moves(self, r: int, c: int):
        p = self.board[r][c]
        if not p:
            return []
        legal = []
        for nr, nc in self.pseudo_moves(r, c):
            test = self.clone()
            test._apply_unchecked((r, c), (nr, nc), promotion='Q')
            if not test.in_check(p.color):
                legal.append((nr, nc))
        return legal
def make_move(self, from_pos: str, to_pos: str, promotion: Optional[str] = None):
        if self.winner:
            return False, 'Game already finished.'
        try:
            r1, c1 = pos_to_idx(from_pos)
            r2, c2 = pos_to_idx(to_pos)
        except Exception:
            return False, 'Use coordinates like e2 and e4.'
        piece = self.board[r1][c1]
        if piece is None:
            return False, 'No piece on the selected square.'
        if piece.color != self.turn:
            return False, f'It is {self.turn}\'s turn.'
        legal = self.legal_moves(r1, c1)
        if (r2, c2) not in legal:
            return False, 'Illegal move. The move would break chess rules or leave king in check.'