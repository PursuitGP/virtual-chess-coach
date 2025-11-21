# motifs.py
import chess
import math

# -------------------------
# Config
# -------------------------
MAX_OPENING_MOVE = 10  # only perform opening-book deviance checks in the opening (MVP)

def compute_eval_delta(prev_eval, current_eval):
    if prev_eval is None:
        return 0
    return current_eval - prev_eval

# -------------------------
# Utility helpers
# -------------------------
def piece_value(piece_type):
    if piece_type == chess.PAWN:
        return 1
    if piece_type == chess.KNIGHT:
        return 3
    if piece_type == chess.BISHOP:
        return 3
    if piece_type == chess.ROOK:
        return 5
    if piece_type == chess.QUEEN:
        return 9
    return 0

# -------------------------
# Motif detectors (each returns dict or list or None)
# Each motif includes exactly the explanation text you provided.
# -------------------------

def development_lead(board, move_number, eval, prev_eval=None):
    """
    Development Lead — one side has more minor pieces developed than the other. You can’t attack the opponent's king or consequently have more space and defenders for your own king if you do not develop pieces. 
    Detect: count minor pieces (Nb/B) off original squares vs opponent; dev_diff >= 1.
    """
    dev_white = 0
    dev_black = 0
    original_white = {chess.B1, chess.G1, chess.C1, chess.F1}
    original_black = {chess.B8, chess.G8, chess.C8, chess.F8}
    for sq in original_white:
        p = board.piece_at(sq)
        if p is None or p.color != chess.WHITE:
            dev_white += 1
    for sq in original_black:
        p = board.piece_at(sq)
        if p is None or p.color != chess.BLACK:
            dev_black += 1
    dev_diff = abs(dev_white - dev_black)
    eval_delta = compute_eval_delta(prev_eval, eval)
    if dev_diff >= 1:
        return {
            "motif": "Development Lead",
            "explanation": development_lead.__doc__.strip(),
            "eval_delta": eval_delta
        }

def king_safety_lag(board, move_number, eval, prev_eval=None):
    """
    King Safety Lag — king not castled and center opening or files opening toward king. In the opening, often one wants to castle as soon as possible to avoid direct attacks at the king in the center of the board. 
    Detect: king hasn't castled and there are open/semi-open files or advanced enemy pieces pointing at king.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        # proxy for "not castled": king still on starting square E1/E8
        original_king = chess.E1 if color == chess.WHITE else chess.E8
        if king_sq == original_king:
            king_file = chess.square_file(king_sq)
            files_to_check = [king_file - 1, king_file, king_file + 1]
            threat_found = False
            for f in files_to_check:
                if 0 <= f <= 7:
                    file_squares = [chess.square(f, r) for r in range(8)]
                    pawns = [sq for sq in file_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN]
                    # open or semi-open file if <= 1 pawn on that file
                    if len(pawns) <= 1:
                        opp = not color
                        # opponent sliding pieces on that file or advanced minor pieces pointing at that file
                        attackers_on_file = any(
                            (board.piece_at(sq) and board.piece_at(sq).color == opp and board.piece_at(sq).piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP))
                            for sq in file_squares
                        )
                        if attackers_on_file:
                            threat_found = True
                            break
            if threat_found:
                motifs.append({
                    "motif": "King Safety Lag",
                    "explanation": king_safety_lag.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def open_file_control(board, move_number, eval, prev_eval=None):
    """
    Open File Control — a file is open and occupied/controlled by rooks/queens. Rooks particularly like open files as they see more space/squares and have more room to attack. 
    Detect: file open with no pawns on either side or if semi-open than there is one; check rook/queen on file or control squares along file.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for f in range(8):
        file_squares = [chess.square(f, r) for r in range(8)]
        pawns = [sq for sq in file_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN]
        if len(pawns) == 0:
            for sq in file_squares:
                p = board.piece_at(sq)
                if p and p.piece_type in (chess.ROOK, chess.QUEEN):
                    motifs.append({
                        "motif": "Open File Control",
                        "explanation": open_file_control.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def semi_open_file(board, move_number, eval, prev_eval=None):
    """
    Semi-Open File — file with only one side’s pawn missing (one pawn present). Rooks also enjoy semi-open files as they anticipate the opening of the file to gain more space or stop the pawn from advancing to a promotion square. 
    Detect: one pawn missing on file and opponent has rook/queen aiming along it.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for f in range(8):
        file_squares = [chess.square(f, r) for r in range(8)]
        pawns = [sq for sq in file_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN]
        if len(pawns) == 1:
            for sq in file_squares:
                p = board.piece_at(sq)
                if p and p.piece_type in (chess.ROOK, chess.QUEEN):
                    motifs.append({
                        "motif": "Semi-Open File",
                        "explanation": semi_open_file.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def bishop_pair(board, move_number, eval, prev_eval=None):
    """
    Bishop Pair — having both bishops vs not. Generally, while not a huge impact on lower rated players, bishops are considered to be preferable to knights as they have more scope or vision of the board. It is recommended to not trade off a bishop for a knight although seen as an equal trade unless there is a concrete reason. 
    Detect: count bishops for each side.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    white_bishops = len(board.pieces(chess.BISHOP, chess.WHITE))
    black_bishops = len(board.pieces(chess.BISHOP, chess.BLACK))
    if white_bishops == 2 or black_bishops == 2:
        return {
            "motif": "Bishop Pair",
            "explanation": bishop_pair.__doc__.strip(),
            "eval_delta": eval_delta
        }

def bad_bishop_good_bishop(board, move_number, eval, prev_eval=None):
    """
    Bad Bishop / Good Bishop — bishop is blocked by own pawns or has long diagonals. Bishops (or any piece for that matter) is only as powerful as its ability to see squares and subsequent pieces. If it is blocked in, its value is generally diminished. 
    Detect: number of pawns on bishop’s color squares + mobility (legal moves).
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for bishop_sq in board.pieces(chess.BISHOP, color):
            mobility = len(board.attacks(bishop_sq))
            bishop_color = chess.square_color(bishop_sq)
            blocked_pawns = 0
            for p_sq in board.pieces(chess.PAWN, color):
                if chess.square_color(p_sq) == bishop_color:
                    blocked_pawns += 1
            if blocked_pawns >= 2 or mobility <= 4:
                motifs.append({
                    "motif": "Bad Bishop / Good Bishop",
                    "explanation": bad_bishop_good_bishop.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def outpost(board, move_number, eval, prev_eval=None):
    """
    Outpost — a square protected by pawns and occupiable by a knight where an opponent piece cannot easily dislodge and there are absolutely no pawns that can dislodge it. Essentially, there must be a piece (rook, bishop, knight) trade to dislodge it. The knight on an outpost dominates squares often making it a significantly more valuable piece relative to others as indicated by an evaluation.
    Detect: a central/advanced square controlled by pawns, occupied by a knight, and enemy pawns cannot attack it.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for knight_sq in board.pieces(chess.KNIGHT, color):
            file_idx = chess.square_file(knight_sq)
            rank_idx = chess.square_rank(knight_sq)
            if 2 <= file_idx <= 5 and 2 <= rank_idx <= 5:  # central-ish
                friendly_support = False
                enemy_can_attack_with_pawn = False
                for pawn_sq in board.pieces(chess.PAWN, color):
                    if chess.square_file(pawn_sq) in (file_idx - 1, file_idx + 1):
                        if (color == chess.WHITE and chess.square_rank(pawn_sq) < rank_idx) or (color == chess.BLACK and chess.square_rank(pawn_sq) > rank_idx):
                            friendly_support = True
                enemy = not color
                for ep in board.pieces(chess.PAWN, enemy):
                    if chess.square_file(ep) in (file_idx - 1, file_idx + 1):
                        if (enemy == chess.WHITE and chess.square_rank(ep) < rank_idx) or (enemy == chess.BLACK and chess.square_rank(ep) > rank_idx):
                            enemy_can_attack_with_pawn = True
                if friendly_support and not enemy_can_attack_with_pawn:
                    motifs.append({
                        "motif": "Outpost",
                        "explanation": outpost.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
    return motifs if motifs else None

def weak_square(board, move_number, eval, prev_eval=None):
    """
    Weak Square — square in enemy camp that cannot be protected by pawns easily (e.g., d5 in some structures). Control of a square can often dictate the flow of a game, particularly, central squares and squares surrounding a king.
    Detect: candidate squares in enemy territory without pawn control; attacked by knights/bishops.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        for sq in chess.SQUARES:
            rank = chess.square_rank(sq)
            if (color == chess.WHITE and rank >= 4) or (color == chess.BLACK and rank <= 3):
                adj_files = [chess.square_file(sq) - 1, chess.square_file(sq) + 1]
                pawn_defended = False
                for af in adj_files:
                    if 0 <= af <= 7:
                        for pr in range(8):
                            psq = chess.square(af, pr)
                            p = board.piece_at(psq)
                            if p and p.piece_type == chess.PAWN and p.color == color:
                                pawn_defended = True
                                break
                        if pawn_defended:
                            break
                attackers = board.attackers(enemy, sq)
                if not pawn_defended and len(attackers) > 0:
                    motifs.append({
                        "motif": "Weak Square",
                        "explanation": weak_square.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
    return motifs if motifs else None

def isolated_pawn(board, move_number, eval, prev_eval=None):
    """
    Isolated Pawn — pawn with no adjacent file pawn neighbors. Pawns are strongest when in a chain as pawns behind other pawns in a diagonal manner can defend and reinforce a pawn structure creating barriers for both defense and advancement. If there are no pawn neighbors on side files, there is no possibility for
    Detect: pawn file has no friendly pawns on adjacent files.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        pawns = board.pieces(chess.PAWN, color)
        for sq in pawns:
            f = chess.square_file(sq)
            adj_files = [f - 1, f + 1]
            has_neighbor = False
            for af in adj_files:
                if 0 <= af <= 7:
                    if any(chess.square(af, r) in pawns for r in range(8)):
                        has_neighbor = True
                        break
            if not has_neighbor:
                motifs.append({
                    "motif": "Isolated Pawn",
                    "explanation": isolated_pawn.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def doubled_pawns(board, move_number, eval, prev_eval=None):
    """
    Doubled Pawns — two (or more) same-file pawns for one side. When pawns are stacked, they can’t defend each other…additionally, the pawn “behind” the more advanced one is limited in movement as it is essentially blocked making it a weakness and liability rather than an asset.
    Detect: more than one pawn on a file for color.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for f in range(8):
            pawns_in_file = [sq for sq in board.pieces(chess.PAWN, color) if chess.square_file(sq) == f]
            if len(pawns_in_file) > 1:
                motifs.append({
                    "motif": "Doubled Pawns",
                    "explanation": doubled_pawns.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def backward_pawn(board, move_number, eval, prev_eval=None):
    """
    Backward Pawn — pawn behind an adjacent pawn and cannot advance without being captured. It essentially is a pawn that cannot and is not defended by another pawn but rather is stuck defending a pawn (often it is the base of a chain making it the weakest aspect).
    Detect: pawn on a file where adjacent friendly pawns advanced past it and square ahead controlled by enemies.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        pawns = board.pieces(chess.PAWN, color)
        for sq in pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            adj_files = [f - 1, f + 1]
            advanced_adjacent = False
            for af in adj_files:
                if 0 <= af <= 7:
                    for rr in range(8):
                        if (color == chess.WHITE and rr > r) or (color == chess.BLACK and rr < r):
                            if chess.square(af, rr) in pawns:
                                advanced_adjacent = True
                                break
                    if advanced_adjacent:
                        break
            ahead_rank = r + 1 if color == chess.WHITE else r - 1
            if 0 <= ahead_rank <= 7 and advanced_adjacent:
                ahead_sq = chess.square(f, ahead_rank)
                if board.is_attacked_by(not color, ahead_sq):
                    motifs.append({
                        "motif": "Backward Pawn",
                        "explanation": backward_pawn.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
    return motifs if motifs else None

def passed_pawn(board, move_number, eval, prev_eval=None):
    """
    Passed Pawn — no opposing pawns on same or adjacent files ahead of it giving it a one way path down the board and to promotion. 
    Detect: check pawn’s forward files for opposing pawns.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        pawns = board.pieces(chess.PAWN, color)
        for sq in pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            blocked = False
            if color == chess.WHITE:
                ranks_ahead = range(r + 1, 8)
            else:
                ranks_ahead = range(r - 1, -1, -1)
            for af in [f - 1, f, f + 1]:
                if 0 <= af <= 7:
                    for rr in ranks_ahead:
                        fsq = chess.square(af, rr)
                        p = board.piece_at(fsq)
                        if p and p.piece_type == chess.PAWN and p.color != color:
                            blocked = True
                            break
                    if blocked:
                        break
            if not blocked:
                motifs.append({
                    "motif": "Passed Pawn",
                    "explanation": passed_pawn.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def minor_piece_vs_pawn_structure_attack(board, move_number, eval, prev_eval=None):
    """
    Minor Piece vs Pawn Structure Attack (Minor Piece Targeting Pawn) — knight/bishop targeting weak pawn.
    Detect: attack map shows minor piece attacking isolated/doubled/backward pawn.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        opp = not color
        opp_pawns = board.pieces(chess.PAWN, opp)
        for pawn_sq in opp_pawns:
            attackers = board.attackers(color, pawn_sq)
            if any(board.piece_at(a).piece_type in (chess.KNIGHT, chess.BISHOP) for a in attackers):
                f = chess.square_file(pawn_sq)
                adj_files = [f - 1, f + 1]
                isolated = all(not any(chess.square(af, r) in opp_pawns for r in range(8)) for af in adj_files if 0 <= af <= 7)
                doubled = len([sq for sq in opp_pawns if chess.square_file(sq) == f]) > 1
                if isolated or doubled:
                    motifs.append({
                        "motif": "Minor Piece vs Pawn Structure Attack",
                        "explanation": minor_piece_vs_pawn_structure_attack.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def absolute_pin(board, move_number, eval, prev_eval=None):
    """
    Absolute Pin — piece is pinned to the king as an opponent's piece has the king in the line of sight behind the pinned piece literally making it immovable. Moving a piece pinned to the king is not a legal move as it would hang the king. 
    Detect: move the pinned piece hypothetically off the line and test legality or use board.is_pinned() helper patterns.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for sq in board.pieces(chess.PAWN, color) | board.pieces(chess.KNIGHT, color) | board.pieces(chess.BISHOP, color) | board.pieces(chess.ROOK, color) | board.pieces(chess.QUEEN, color):
            if board.is_pinned(color, sq):
                # check if pinned specifically to king by testing moving hypothetical
                # python-chess board.is_pinned returns True for pins to king specifically
                motifs.append({
                    "motif": "Absolute Pin",
                    "explanation": absolute_pin.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def relative_pin(board, move_number, eval, prev_eval=None):
    """
    Relative Pin – A piece is pinned to another piece of higher value other than the king as an opponent’s piece has a higher value piece in the line of sight behind the pinned piece making the possibility of it moving unlikely. The pinned piece in a relative pin can literally move it just would result in a plummet in evaluation as material would be lost. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    # python-chess's is_pinned only checks to king, so we approximate relative pin:
    for color in [chess.WHITE, chess.BLACK]:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color:
                # check if moving this piece would expose a higher-value friendly piece behind to an enemy sliding piece
                for df, dr in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                    nf = chess.square_file(sq) + df
                    nr = chess.square_rank(sq) + dr
                    blockers = []
                    while 0 <= nf <= 7 and 0 <= nr <= 7:
                        nsq = chess.square(nf, nr)
                        np = board.piece_at(nsq)
                        if np:
                            blockers.append((nsq, np))
                            break
                        nf += df
                        nr += dr
                    if blockers:
                        target_sq, target_piece = blockers[0]
                        if target_piece and target_piece.color == color and target_piece.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP):
                            motifs.append({
                                "motif": "Relative Pin",
                                "explanation": relative_pin.__doc__.strip(),
                                "eval_delta": eval_delta
                            })
                            break
    return motifs if motifs else None

def skewer(board, move_number, eval, prev_eval=None):
    """
    Skewer — a line attack where moving the front piece exposes a more valuable piece. What separates this from a pin is that often the piece in the front line being attacked HAS to move in order to maintain the best evaluation. Or consequently the piece in front is undefended and when it moves there is another undefended piece. Often the King is in the front line of attack meaning it literally has to move (given nothing can block or take the piece placing the king in check) and thus revealing another piece that is undefended… the piece undefended was skewered by the attacking piece. 
    Detect: line attack by rook, bishop, or queen onto a queen, king, or minor piece that doesn’t reflect the view (rook sees bishop and behind bishop is another bishop that is undefended). with front piece between attacker and more valuable piece.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for opp in [chess.WHITE, chess.BLACK]:
        us = not opp
        for attacker_sq in board.pieces(chess.ROOK, opp) | board.pieces(chess.BISHOP, opp) | board.pieces(chess.QUEEN, opp):
            for ray_sq in board.attacks(attacker_sq):
                if board.piece_at(ray_sq) and board.piece_at(ray_sq).color == us:
                    df = chess.square_file(ray_sq) - chess.square_file(attacker_sq)
                    dr = chess.square_rank(ray_sq) - chess.square_rank(attacker_sq)
                    df = 0 if df == 0 else (1 if df > 0 else -1)
                    dr = 0 if dr == 0 else (1 if dr > 0 else -1)
                    nf = chess.square_file(ray_sq) + df
                    nr = chess.square_rank(ray_sq) + dr
                    if 0 <= nf <= 7 and 0 <= nr <= 7:
                        behind_sq = chess.square(nf, nr)
                        if board.piece_at(behind_sq) and board.piece_at(behind_sq).color == us:
                            front_val = piece_value(board.piece_at(ray_sq).piece_type)
                            behind_val = piece_value(board.piece_at(behind_sq).piece_type)
                            if behind_val > front_val:
                                motifs.append({
                                    "motif": "Skewer",
                                    "explanation": skewer.__doc__.strip(),
                                    "eval_delta": eval_delta
                                })
                                break
    return motifs if motifs else None

def fork(board, move_number, eval, prev_eval=None):
    """
    Fork — single piece attacks two or more valuable targets simultaneously (e.g., knight forks king & queen) and the opponent cannot save both ensuring taking one is a guaranteed option in the subsequent move. The knight fork on a king and another subsequent undefended piece/material is an extremely common example of a fork…
    Detect: compute attacked squares for piece, count how many high-value targets in that set.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    targets = {chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT}
    for color in [chess.WHITE, chess.BLACK]:
        pieces_to_check = list(board.pieces(chess.KNIGHT, color)) + list(board.pieces(chess.QUEEN, color)) + list(board.pieces(chess.BISHOP, color))
        for sq in pieces_to_check:
            attacked = board.attacks(sq)
            valuable = 0
            for a in attacked:
                p = board.piece_at(a)
                if p and p.color != color and p.piece_type in targets:
                    valuable += 1
            if valuable >= 2:
                motifs.append({
                    "motif": "Fork",
                    "explanation": fork.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def battery(board, move_number, eval, prev_eval=None):
    """
    Battery — rook/queen/bishop aligned with another heavy piece aiming at the same line (e.g., Q behind B). The front piece will be supported by the back piece ensuring the opponent must have at least 2 defenders of a piece in the line of sight to maintain material equality in the event of a capture by the battery. 
    Detect: same file/diagonal alignment and no intervening pieces or the front piece can move to open line.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        heavy = set(board.pieces(chess.QUEEN, color) | board.pieces(chess.ROOK, color) | board.pieces(chess.BISHOP, color))
        for p1 in heavy:
            for p2 in heavy:
                if p1 == p2:
                    continue
                df = chess.square_file(p2) - chess.square_file(p1)
                dr = chess.square_rank(p2) - chess.square_rank(p1)
                if df == 0 or dr == 0 or abs(df) == abs(dr):
                    steps = max(abs(df), abs(dr))
                    step_f = 0 if df == 0 else (1 if df > 0 else -1)
                    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
                    blocked = False
                    nf = chess.square_file(p1) + step_f
                    nr = chess.square_rank(p1) + step_r
                    for _ in range(steps - 1):
                        if board.piece_at(chess.square(nf, nr)):
                            blocked = True
                            break
                        nf += step_f
                        nr += step_r
                    if not blocked:
                        motifs.append({
                            "motif": "Battery",
                            "explanation": battery.__doc__.strip(),
                            "eval_delta": eval_delta
                        })
                        break
    return motifs if motifs else None

def discovery_attack(board, move_number, eval, prev_eval=None):
    """
    Discovery Attack – when a piece moves unveiling the line of sight of another piece onto a move valuable or undefended piece. This usually means the front piece that moved is free to go anywhere as the opponent has to address the discovered attack. The most effective discovered attack is a discovered check as the opponent literally has to respond to the unveiled piece allowing the front piece that moved to essentially have 2 guaranteed moves. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for slider_sq in board.pieces(chess.ROOK, color) | board.pieces(chess.BISHOP, color) | board.pieces(chess.QUEEN, color):
            for df, dr in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                f = chess.square_file(slider_sq) + df
                r = chess.square_rank(slider_sq) + dr
                while 0 <= f <= 7 and 0 <= r <= 7:
                    sq = chess.square(f, r)
                    p = board.piece_at(sq)
                    if p:
                        if p.color == color:
                            nf = f + df
                            nr = r + dr
                            while 0 <= nf <= 7 and 0 <= nr <= 7:
                                bsq = chess.square(nf, nr)
                                bp = board.piece_at(bsq)
                                if bp and bp.color != color and bp.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                                    motifs.append({
                                        "motif": "Discovery Attack",
                                        "explanation": discovery_attack.__doc__.strip(),
                                        "eval_delta": eval_delta
                                    })
                                    break
                                if bp:
                                    break
                                nf += df
                                nr += dr
                        break
                    f += df
                    r += dr
    return motifs if motifs else None

def double_check(board, move_number, eval, prev_eval=None):
    """
    Double Check – When two pieces place the opponent’s king into check forcing the king itself to move rather than having an additional option of blocking (as two pieces are checking) and the option of taking the piece doing the checking (as there are two and you can’t take both).
    Detect: When two pieces place the opponent's king into check (>=2 attackers to king).
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        attackers = board.attackers(not color, king_sq)
        if len(attackers) >= 2:
            motifs.append({
                "motif": "Double Check",
                "explanation": double_check.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def pawn_majority(board, move_number, eval, prev_eval=None):
    """
    Pawn Majority (Queenside / Kingside) — more pawns on one wing than the opponent. A majority structure indicates the potential for a passed pawn creation. 
    Detect: count pawns on files a–c (queenside) and f–h (kingside) and compare.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        qside = sum(1 for sq in board.pieces(chess.PAWN, color) if chess.square_file(sq) in (0,1,2))
        kside = sum(1 for sq in board.pieces(chess.PAWN, color) if chess.square_file(sq) in (5,6,7))
        opp_qside = sum(1 for sq in board.pieces(chess.PAWN, not color) if chess.square_file(sq) in (0,1,2))
        opp_kside = sum(1 for sq in board.pieces(chess.PAWN, not color) if chess.square_file(sq) in (5,6,7))
        if qside > opp_qside:
            motifs.append({
                "motif": "Pawn Majority (Queenside)",
                "explanation": pawn_majority.__doc__.strip(),
                "eval_delta": eval_delta
            })
        if kside > opp_kside:
            motifs.append({
                "motif": "Pawn Majority (Kingside)",
                "explanation": pawn_majority.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def minor_piece_trapped(board, move_number, eval, prev_eval=None):
    """
    Minor Piece Trapped — piece with few legal moves and under attack. A piece trap indicates there is no move for said trapped piece that wouldn’t result in loss of material. 
    Detect: piece has len(list(board.legal_moves_from(square))) <= threshold and square is attacked.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    threshold = 2
    # python-chess doesn't have legal_moves_from, so we count legal moves where from_square==sq
    for color in [chess.WHITE, chess.BLACK]:
        for sq in board.pieces(chess.KNIGHT, color) | board.pieces(chess.BISHOP, color):
            legal_moves_count = sum(1 for m in board.legal_moves if m.from_square == sq)
            if legal_moves_count <= threshold and board.is_attacked_by(not color, sq):
                motifs.append({
                    "motif": "Minor Piece Trapped",
                    "explanation": minor_piece_trapped.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None

def early_queen_exposure(board, move_number, eval, prev_eval=None):
    """
    Early Queen Exposure — queen moved out early leading to tempo loss. The queen moving up early is often not a good decision as it can be chased early causing it to move again (loss of tempo). Additionally, the queen moving out early can potentially block the typical development of other minor pieces. 
    Detect: queen moved before N moves (configurable, e.g., before move 10) and has been chased (attacked multiple times).
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    QUEEN_MOVE_THRESHOLD = 10
    for color in [chess.WHITE, chess.BLACK]:
        original_sq = chess.D1 if color == chess.WHITE else chess.D8
        queens = set(board.pieces(chess.QUEEN, color))
        if queens and original_sq not in queens:
            if move_number <= QUEEN_MOVE_THRESHOLD:
                for qsq in queens:
                    if board.is_attacked_by(not color, qsq):
                        motifs.append({
                            "motif": "Early Queen Exposure",
                            "explanation": early_queen_exposure.__doc__.strip(),
                            "eval_delta": eval_delta
                        })
                        break
    return motifs if motifs else None

def minority_attack_setup(board, move_number, eval, prev_eval=None):
    """
    Minority Attack Setup — pawn structure aiming for minority attack (e.g., a-b-c vs a-b pawns).
    Detect: pawn majority/opponent structure matches minority attack patterns (a common template).
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    w_q = sum(1 for sq in board.pieces(chess.PAWN, chess.WHITE) if chess.square_file(sq) in (0,1,2))
    b_q = sum(1 for sq in board.pieces(chess.PAWN, chess.BLACK) if chess.square_file(sq) in (0,1,2))
    if w_q >= 3 and b_q <= 2:
        motifs.append({
            "motif": "Minority Attack Setup",
            "explanation": minority_attack_setup.__doc__.strip(),
            "eval_delta": eval_delta
        })
    w_k = sum(1 for sq in board.pieces(chess.PAWN, chess.WHITE) if chess.square_file(sq) in (5,6,7))
    b_k = sum(1 for sq in board.pieces(chess.PAWN, chess.BLACK) if chess.square_file(sq) in (5,6,7))
    if b_k >= 3 and w_k <= 2:
        motifs.append({
            "motif": "Minority Attack Setup",
            "explanation": minority_attack_setup.__doc__.strip(),
            "eval_delta": eval_delta
        })
    return motifs if motifs else None

def threatened_mate_net(board, move_number, eval, prev_eval=None):
    """
    Threatened Mate Net — direct mating threats (e.g., two+ attackers on mating square).
    Detect: search for forced mate in 1 or 2 with stockfish engine or check heavy attack patterns near the king.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    # heuristic: many attackers near king or open file to king
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        surrounding = []
        kf = chess.square_file(king_sq)
        kr = chess.square_rank(king_sq)
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df == 0 and dr == 0: continue
                nf = kf + df
                nr = kr + dr
                if 0 <= nf <= 7 and 0 <= nr <= 7:
                    surrounding.append(chess.square(nf, nr))
        attackers_count = sum(len(board.attackers(not color, s)) for s in surrounding)
        file_open = not any(board.piece_at(chess.square(kf, r)) and board.piece_at(chess.square(kf, r)).piece_type == chess.PAWN for r in range(8))
        if attackers_count >= 4 or file_open:
            motifs.append({
                "motif": "Threatened Mate Net",
                "explanation": threatened_mate_net.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def opening_theory_deviance(board, move_number, eval, prev_eval=None):
    """
    Opening Theory Deviance — move deviates from top N/book opening moves from master/lichess DB. This indicates novelties or likely non accurate moves/mistakes given the delta of an eval. 
    Detect: query Lichess opening replies for FEN; check if current move is in top 2–3 book moves; if not, flag deviance.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    # Only run in opening (MVP)
    if move_number > MAX_OPENING_MOVE:
        return None
    # If the caller injected an opening book on board, use it.
    # board.opening_book_moves should be: { fen_str: [ { "uci": "e2e4", "white": X, "black": Y, "draws": Z }, ... ] }
    # board.last_move_uci should be set to the UCI of the move that produced this FEN.
    if hasattr(board, "opening_book_moves"):
        fen = board.fen()
        book_entries = board.opening_book_moves.get(fen, [])
        last_move = getattr(board, "last_move_uci", None)
        if last_move is not None:
            # find if last_move is in top book moves (by order)
            top_moves = [entry["uci"] for entry in book_entries[:3]]
            if last_move not in top_moves:
                motifs.append({
                    "motif": "Opening Theory Deviance",
                    "explanation": opening_theory_deviance.__doc__.strip(),
                    "eval_delta": eval_delta,
                    "book_top": book_entries[:3]  # include top book data for UI
                })
    # if no book injected, return None (caller can optionally fetch via Lichess — see backend snippet)
    return motifs if motifs else None

def take_the_center(board, move_number, eval, prev_eval=None):
    """
    Take The Center – If your opponent allows you to take the center with both e4 and d4 (White) or d5 and e5 (black) then take it! Taking the center opens up more space for your pieces to advance and controls more advanced central squares putting more pressure on your opponents position. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    centers = [chess.D4, chess.E4, chess.D5, chess.E5]
    for color in [chess.WHITE, chess.BLACK]:
        control_count = 0
        for c in centers:
            if board.piece_at(c) and board.piece_at(c).color == color:
                control_count += 1
            elif board.is_attacked_by(color, c):
                control_count += 0.5
        if control_count >= 2:
            motifs.append({
                "motif": "Take The Center",
                "explanation": take_the_center.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def f2_f7_weakness(board, move_number, eval, prev_eval=None):
    """
    F2/F7 Weakness - f7 (for Black) and f2 (for White) are the weakest pawns on the board as they start with only one defender - the king, f7 or f2  is susceptible to forks from the knight onto the queen and rook, or early bishop/queen attacks either ending in mate or the loss of castling rights. 
    Detect: Knight and queen or bishop aiming at f7 or f2 and eval delta indicates there is an imminent threat or book move indicates a main line to attack the pawn.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    sq_f2 = chess.square(5,1)
    sq_f7 = chess.square(5,6)
    if board.piece_at(sq_f2) and board.piece_at(sq_f2).color == chess.WHITE:
        attackers = board.attackers(chess.BLACK, sq_f2)
        if attackers:
            motifs.append({
                "motif": "F2 Weakness",
                "explanation": f2_f7_weakness.__doc__.strip(),
                "eval_delta": eval_delta
            })
    if board.piece_at(sq_f7) and board.piece_at(sq_f7).color == chess.BLACK:
        attackers = board.attackers(chess.WHITE, sq_f7)
        if attackers:
            motifs.append({
                "motif": "F7 Weakness",
                "explanation": f2_f7_weakness.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def c2_c7_weakness(board, move_number, eval, prev_eval=None):
    """
    C2/C7 Weakness - Similar to f7 and f2, c2 and c7 have only one defender starting out… the queen. This potentially makes it susceptible to bishop and knight or queen and knight attacks threatening a knight fork onto the king and the rook especially if a knight is not available to go to a3 or e4(white)/a6 or e5 (black) to defend by adding another defender. 
    Detect: Knight and queen or bishop aiming at c7 or c2 and eval delta indicates there is an imminent threat or book move indicates a main line to attack the pawn.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    sq_c2 = chess.square(2,1)
    sq_c7 = chess.square(2,6)
    if board.piece_at(sq_c2) and board.piece_at(sq_c2).color == chess.WHITE:
        attackers = board.attackers(chess.BLACK, sq_c2)
        if attackers:
            motifs.append({
                "motif": "C2 Weakness",
                "explanation": c2_c7_weakness.__doc__.strip(),
                "eval_delta": eval_delta
            })
    if board.piece_at(sq_c7) and board.piece_at(sq_c7).color == chess.BLACK:
        attackers = board.attackers(chess.WHITE, sq_c7)
        if attackers:
            motifs.append({
                "motif": "C7 Weakness",
                "explanation": c2_c7_weakness.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def hanging_piece(board, move_number, eval, prev_eval=None):
    """
    Hanging Piece/material – In chess there must be an equal or more number of defender(s) than attacker(s) to ensure material equality at the end of a capture sequence. The most obvious example of loss of material is of course one attacker vs zero defenders meaning the defending side is losing material given it is the attackers move to make. In this case there is a hanging piece.
    Detect: A piece of material is under attack by one more attacker than defender, thus a threat of gain/loss of material. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color:
                attackers = len(board.attackers(not color, sq))
                defenders = len(board.attackers(color, sq))
                if attackers > defenders:
                    motifs.append({
                        "motif": "Hanging Piece",
                        "explanation": hanging_piece.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
    return motifs if motifs else None

def equal_trade(board, move_number, eval, prev_eval=None):
    """
    Equal Trade – Evaluation doesn’t change much as two equal material values were exchanged. There is a caveat… the position of pieces can affect the relative value of pieces meaning that despite material being the literal same, it may not have been an equal trade of course this would be reflected in an evaluation shift.
    Detect: A capture of material in which the outcome is equal value material  
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    if prev_eval is not None and abs(eval_delta) < 20:
        try:
            if board.move_stack:
                last = board.move_stack[-1]
                if last and board.is_capture(last):
                    return {
                        "motif": "Equal Trade",
                        "explanation": equal_trade.__doc__.strip(),
                        "eval_delta": eval_delta
                    }
        except Exception:
            pass
    return None

def opposite_side_castling(board, move_number, eval, prev_eval=None):
    """
    Opposite Side Castling – When both sides castle on the opposite corners of the board (one kingside castled and the other queenside castled) then the game will be decided by offense…who mates the other first.
    Detect: if the players castle on opposite sides.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    white_castle_side = None
    black_castle_side = None
    if wk and chess.square_file(wk) == 6:
        white_castle_side = "kingside"
    elif wk and chess.square_file(wk) == 2:
        white_castle_side = "queenside"
    if bk and chess.square_file(bk) == 6:
        black_castle_side = "kingside"
    elif bk and chess.square_file(bk) == 2:
        black_castle_side = "queenside"
    if white_castle_side and black_castle_side and white_castle_side != black_castle_side:
        motifs.append({
            "motif": "Opposite Side Castling",
            "explanation": opposite_side_castling.__doc__.strip(),
            "eval_delta": eval_delta
        })
    return motifs if motifs else None

def knight_on_the_rim_is_dim(board, move_number, eval, prev_eval=None):
    """
    Knight on the rim is dim – A knight enjoys being closer to the center of the board because it sees and controls more squares in the center. When a knight is placed or developed to the edge of the board without justification, it has less functionality as it literally sees less squares.
    Detect: If a knight is developed to a3 or h3 (white), a6 or h6(black) and the eval drops. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    rim_squares_white = {chess.A3, chess.H3}
    rim_squares_black = {chess.A6, chess.H6}
    for color in [chess.WHITE, chess.BLACK]:
        if color == chess.WHITE and any(sq in board.pieces(chess.KNIGHT, color) for sq in rim_squares_white):
            motifs.append({
                "motif": "Knight on the rim is dim",
                "explanation": knight_on_the_rim_is_dim.__doc__.strip(),
                "eval_delta": eval_delta
            })
        if color == chess.BLACK and any(sq in board.pieces(chess.KNIGHT, color) for sq in rim_squares_black):
            motifs.append({
                "motif": "Knight on the rim is dim",
                "explanation": knight_on_the_rim_is_dim.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

def piece_sacrifice(board, move_number, eval, prev_eval=None):
    """
    Piece Sacrifice – When an attacking player either captures a lower value piece purposefully losing material or leaves a minor piece or higher for a winning or advantageous position. These are often classified by engines or analysis tools as “Brilliant” moves as they ignore general principles of maintaining material equality or responding to your opponent’s threats. 
    Detect: A piece is left hanging but it is a top engine move or taking a lower value piece with a higher one in an exchange but top engine move. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    try:
        if board.move_stack:
            last = board.move_stack[-1]
            if board.is_capture(last):
                if prev_eval is not None and abs(eval_delta) > 30:
                    motifs.append({
                        "motif": "Piece Sacrifice",
                        "explanation": piece_sacrifice.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
    except Exception:
        pass
    return motifs if motifs else None

def intermezzo_counter_threat(board, move_number, eval, prev_eval=None):
    """
    Intermezzo/counter threat – When there is a threat from the opponent but the defending player makes an in-between move or a forcing move before the opponent can capitalize on the threat often leading to a more favorable position in which the defending player can then respond or even ignore.
    Detect: An inbetween forcing move like a check before having to respond to an opponent's threat.  
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    if board.is_check():
        motifs.append({
            "motif": "Intermezzo / Counter Threat",
            "explanation": intermezzo_counter_threat.__doc__.strip(),
            "eval_delta": eval_delta
        })
    return motifs if motifs else None

def attraction(board, move_number, eval, prev_eval=None):
    """
    Attraction – When a player lures an opponent’s piece to a more favorable square to set up a tactical idea. This often occurs from a sacrifice where the opponent's king is brought to a more open attackable square. 
    Detect: when a valuable piece of the opponent is lured into a more valuable square setting up a tactical idea that wins material, the game, or gains an advantageous position. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color and board.is_attacked_by(not color, sq):
                for df, dr in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                    nf = chess.square_file(sq) + df
                    nr = chess.square_rank(sq) + dr
                    while 0 <= nf <= 7 and 0 <= nr <= 7:
                        nsq = chess.square(nf, nr)
                        np = board.piece_at(nsq)
                        if np:
                            if np.color != color and np.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP):
                                motifs.append({
                                    "motif": "Attraction",
                                    "explanation": attraction.__doc__.strip(),
                                    "eval_delta": eval_delta
                                })
                                break
                            else:
                                break
                        nf += df
                        nr += dr
    return motifs if motifs else None

def deflection(board, move_number, eval, prev_eval=None):
    """
    Deflection – When a player disrupts an opponent’s piece from the continuity of defending another piece or material via a sacrifice or forcing threat. This is also known as removing the guard or undermining the defense of a piece.
    Detect: A forced move/threat that removes the defend of another piece that should be taken.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        opp = not color
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color and board.is_attacked_by(opp, sq):
                # heuristic: if this square defends another piece and is attacked -> deflection possibility
                defenders = board.attackers(color, sq)
                if defenders:
                    motifs.append({
                        "motif": "Deflection",
                        "explanation": deflection.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def clearance_sacrifice(board, move_number, eval, prev_eval=None):
    """
    Clearance Sacrifice – When a player sacrifices a piece to clear a square or open up a line for a more powerful piece to attack or support a general attack on the king.
    Detect: A sacrifice that is a top move in which another more powerful piece is revealed and aids in the general attack not necessarily immediately.  
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    try:
        if board.move_stack:
            last = board.move_stack[-1]
            if board.is_capture(last):
                motifs.append({
                    "motif": "Clearance Sacrifice",
                    "explanation": clearance_sacrifice.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    except Exception:
        pass
    return motifs if motifs else None

def xray_potential_energy(board, move_number, eval, prev_eval=None):
    """
    XRAY/ Potential Energy – When a piece placement allows it to have a future vision of a more valuable piece or square setting up future tactical ideas. 
    Detect: If a piece not in its original position sees a valuable piece of an opponent through any other piece.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        opp = not color
        sliders = set(board.pieces(chess.QUEEN, color) | board.pieces(chess.ROOK, color) | board.pieces(chess.BISHOP, color))
        for sq in sliders:
            for df, dr in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
                nf = chess.square_file(sq) + df
                nr = chess.square_rank(sq) + dr
                blocked_once = False
                while 0 <= nf <= 7 and 0 <= nr <= 7:
                    nsq = chess.square(nf, nr)
                    p = board.piece_at(nsq)
                    if p:
                        if not blocked_once:
                            blocked_once = True
                        else:
                            if p.color == opp and p.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                                motifs.append({
                                    "motif": "XRAY/ Potential Energy",
                                    "explanation": xray_potential_energy.__doc__.strip(),
                                    "eval_delta": eval_delta
                                })
                                break
                            else:
                                break
                    nf += df
                    nr += dr
    return motifs if motifs else None

def never_push_f3_f6(board, move_number, eval, prev_eval=None):
    """
    “Never Push f3/f6” – it is a well known concept that pushing either of pawns before the king is castled is a poor move as it exposes the king early often leading to thematic checks by either queen on the h file. 
    Detect: If the f pawns are pushed prior to castling leading to a meaningful loss in the evaluation. 
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        original_king_sq = chess.E1 if color == chess.WHITE else chess.E8
        if king_sq == original_king_sq:
            fs = [sq for sq in board.pieces(chess.PAWN, color) if chess.square_file(sq) == 5]
            for p in fs:
                if (color == chess.WHITE and chess.square_rank(p) != 1) or (color == chess.BLACK and chess.square_rank(p) != 6):
                    motifs.append({
                        "motif": "Never Push f3/f6",
                        "explanation": never_push_f3_f6.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def connect_the_rooks(board, move_number, eval, prev_eval=None):
    """
    Connect the rooks – After every minor piece is developed, there is center control, and the king is castled, the queen  wants to move off the back rank to develop and to connect the rooks and allow for more space grabbing and advancement of pieces. 
    Detect: If a all minor piece are developed and the king is castled and the best move WAS to move/develop the queen thus connecting the rooks
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        minors_original = {chess.B1, chess.G1, chess.C1, chess.F1} if color == chess.WHITE else {chess.B8, chess.G8, chess.C8, chess.F8}
        minors_developed = any(sq not in minors_original for sq in set(board.pieces(chess.KNIGHT, color)) | set(board.pieces(chess.BISHOP, color)))
        king_sq = board.king(color)
        king_original = chess.E1 if color == chess.WHITE else chess.E8
        queen_sq = next(iter(board.pieces(chess.QUEEN, color)), None)
        queen_off_back = False
        if queen_sq is not None:
            if (color == chess.WHITE and chess.square_rank(queen_sq) != 0) or (color == chess.BLACK and chess.square_rank(queen_sq) != 7):
                queen_off_back = True
        if minors_developed and king_sq != king_original and queen_off_back:
            motifs.append({
                "motif": "Connect the rooks",
                "explanation": connect_the_rooks.__doc__.strip(),
                "eval_delta": eval_delta
            })
    return motifs if motifs else None

# -------------------------
# Master detect function
# -------------------------
def detect_motifs(board, move_number, eval, prev_eval=None):
    """
    Run all motif detection functions for a given board and return a list of detected motifs.
    """
    results = []
    funcs = [
        development_lead,
        king_safety_lag,
        open_file_control,
        semi_open_file,
        bishop_pair,
        bad_bishop_good_bishop,
        outpost,
        weak_square,
        isolated_pawn,
        doubled_pawns,
        backward_pawn,
        passed_pawn,
        minor_piece_vs_pawn_structure_attack,
        absolute_pin,
        relative_pin,
        skewer,
        fork,
        battery,
        discovery_attack,
        double_check,
        pawn_majority,
        minor_piece_trapped,
        early_queen_exposure,
        minority_attack_setup,
        threatened_mate_net,
        opening_theory_deviance,
        take_the_center,
        f2_f7_weakness,
        c2_c7_weakness,
        hanging_piece,
        equal_trade,
        opposite_side_castling,
        knight_on_the_rim_is_dim,
        piece_sacrifice,
        intermezzo_counter_threat,
        attraction,
        deflection,
        clearance_sacrifice,
        xray_potential_energy,
        never_push_f3_f6,
        connect_the_rooks,
    ]
    for func in funcs:
        try:
            res = func(board, move_number, eval, prev_eval)
            if res:
                if isinstance(res, list):
                    results.extend(res)
                else:
                    results.append(res)
        except Exception:
            # keep pipeline robust; skip failing detectors
            pass
    return results
