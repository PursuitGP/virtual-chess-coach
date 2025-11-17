# motifs.py
import chess

def compute_eval_delta(prev_eval, current_eval):
    if prev_eval is None:
        return 0
    return current_eval - prev_eval

def development_lead(board, move_number, eval, prev_eval=None):
    """
    Development Lead — one side has more minor pieces developed than the other. 
    You can’t attack the opponent's king or consequently have more space and defenders for your own king if you do not develop pieces.
    Detect: count minor pieces (Nb/B) off original squares vs opponent; dev_diff >= 1.
    """
    dev_white = sum(1 for sq in [chess.B1, chess.G1, chess.C1, chess.F1] if board.piece_at(sq) and board.piece_at(sq).color == chess.WHITE)
    dev_black = sum(1 for sq in [chess.B8, chess.G8, chess.C8, chess.F8] if board.piece_at(sq) and board.piece_at(sq).color == chess.BLACK)
    dev_diff = abs(dev_white - dev_black)
    if dev_diff >= 1:
        return {
            "motif": "Development Lead",
            "explanation": development_lead.__doc__.strip(),
            "eval_delta": compute_eval_delta(prev_eval, eval)
        }

def king_safety_lag(board, move_number, eval, prev_eval=None):
    """
    King Safety Lag — king not castled and center opening or files opening toward king. 
    In the opening, often one wants to castle as soon as possible to avoid direct attacks at the king in the center of the board.
    Detect: king hasn't castled and there are open/semi-open files or advanced enemy pieces pointing at king.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_square = board.king(color)
        castled = board.has_castling_rights(color) is False
        if not castled:
            # Check if center files are open or semi-open
            files_to_check = [3, 4, 5]  # d, e, f files
            for f in files_to_check:
                file_squares = [chess.square(f, r) for r in range(8)]
                if all(board.piece_at(sq) is None or board.piece_at(sq).color != color for sq in file_squares):
                    motifs.append({
                        "motif": "King Safety Lag",
                        "explanation": king_safety_lag.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def open_file_control(board, move_number, eval, prev_eval=None):
    """
    Open File Control — a file is open and occupied/controlled by rooks/queens. 
    Rooks particularly like open files as they see more space/squares and have more room to attack.
    Detect: file open with no pawns on either side or if semi-open than there is one; check rook/queen on file or control squares along file.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for f in range(8):
        file_squares = [chess.square(f, r) for r in range(8)]
        pawns = [board.piece_at(sq) for sq in file_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN]
        if len(pawns) == 0:
            # Check rook/queen presence
            for sq in file_squares:
                p = board.piece_at(sq)
                if p and p.piece_type in [chess.ROOK, chess.QUEEN]:
                    motifs.append({
                        "motif": "Open File Control",
                        "explanation": open_file_control.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

def semi_open_file(board, move_number, eval, prev_eval=None):
    """
    Semi-Open File — file with only one side’s pawn missing (one pawn present). 
    Rooks also enjoy semi-open files as they anticipate the opening of the file to gain more space or stop the pawn from advancing to a promotion square.
    Detect: one pawn missing on file and opponent has rook/queen aiming along it.
    """
    eval_delta = compute_eval_delta(prev_eval, eval)
    motifs = []
    for f in range(8):
        file_squares = [chess.square(f, r) for r in range(8)]
        pawns = [board.piece_at(sq) for sq in file_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN]
        if len(pawns) == 1:
            # Check if opponent rook/queen attacks along file
            for sq in file_squares:
                p = board.piece_at(sq)
                if p and p.piece_type in [chess.ROOK, chess.QUEEN]:
                    motifs.append({
                        "motif": "Semi-Open File",
                        "explanation": semi_open_file.__doc__.strip(),
                        "eval_delta": eval_delta
                    })
                    break
    return motifs if motifs else None

# Additional motif functions would follow the same template:
# bishop_pair, bad_bishop, outpost, weak_square, isolated_pawn, doubled_pawns, backward_pawn, passed_pawn, 
# minor_piece_vs_pawn_structure_attack, absolute_pin, relative_pin, skewer, fork, battery, discovery_attack, double_check,
# pawn_majority, minor_piece_trapped, early_queen_exposure, minority_attack_setup, threatened_mate_net, opening_theory_deviance,
# take_the_center, f2_f7_weakness, c2_c7_weakness, hanging_piece, equal_trade, opposite_side_castling,
# knight_on_the_rim_is_dim, piece_sacrifice, intermezzo_counter_threat, attraction, deflection, clearance_sacrifice,
# xray_potential_energy, never_push_f3_f6, connect_the_rooks

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
        # Add remaining motif functions here...
    ]
    for func in funcs:
        res = func(board, move_number, eval, prev_eval)
        if res:
            if isinstance(res, list):
                results.extend(res)
            else:
                results.append(res)
    return results
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
            mobility = len(list(board.attacks(bishop_sq)))
            color_squares = [sq for sq in chess.SQUARES if (board.color_at(sq) == color if board.piece_at(sq) else False)]
            blocked_pawns = sum(1 for sq in color_squares if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.PAWN)
            if blocked_pawns > 1 or mobility < 3:
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
            if chess.square_rank(knight_sq) in [2,3,4,5] and chess.square_file(knight_sq) in [2,3,4,5]:
                if all(not board.piece_at(sq) or board.piece_at(sq).color != color for sq in board.attacks(knight_sq)):
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
        enemy_pawn_squares = board.pieces(chess.PAWN, not color)
        for sq in enemy_pawn_squares:
            # check if no friendly pawns control it
            if not any(board.is_attacked_by(color, sq) for sq in enemy_pawn_squares):
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
            file_index = chess.square_file(sq)
            adj_files = [file_index-1, file_index+1]
            if all(f < 0 or f > 7 or not any(chess.square(f, r) in pawns for r in range(8)) for f in adj_files):
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
            adj_files = [f-1, f+1]
            if any(
                0 <= af <= 7 and any(chess.square(af, rr) in pawns and rr > r if color == chess.WHITE else rr < r for rr in range(8))
                for af in adj_files
            ):
                if board.is_attacked_by(not color, chess.square(f, r+1 if color==chess.WHITE else r-1)):
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
            for af in [f-1, f, f+1]:
                if 0 <= af <= 7:
                    squares_ahead = range(r+1, 8) if color==chess.WHITE else range(r-1, -1, -1)
                    if any(board.piece_at(chess.square(af, rr)) and board.piece_at(chess.square(af, rr)).color != color for rr in squares_ahead):
                        blocked = True
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
        pawns_weak = [sq for sq in board.pieces(chess.PAWN, not color)]
        for sq in pawns_weak:
            attackers = board.attackers(color, sq)
            if any(board.piece_at(a).piece_type in [chess.KNIGHT, chess.BISHOP] for a in attackers):
                motifs.append({
                    "motif": "Minor Piece vs Pawn Structure Attack",
                    "explanation": minor_piece_vs_pawn_structure_attack.__doc__.strip(),
                    "eval_delta": eval_delta
                })
    return motifs if motifs else None
