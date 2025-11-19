# motifs.py
import chess
import math

# -------------------------
# Config / helpers
# -------------------------

MAX_OPENING_MOVE = 10  # used for early-queen, theory-ish ideas

def compute_eval_delta(prev_eval, current_eval):
    """Eval values are in centipawns."""
    if prev_eval is None or current_eval is None:
        return 0
    return current_eval - prev_eval

def side_name(color: bool) -> str:
    return "white" if color == chess.WHITE else "black"

def make_motif(motif_id, name, explanation, side=None, severity="info", eval_cp=None, eval_delta_cp=None, extra=None):
    d = {
        "id": motif_id,
        "name": name,
        "explanation": explanation,
        "side": side,
        "severity": severity,
    }
    if eval_cp is not None:
        d["eval_cp"] = eval_cp
    if eval_delta_cp is not None:
        d["eval_delta_cp"] = eval_delta_cp
    if extra:
        d["extra"] = extra
    return d

# -------------------------
# Explanations (YOUR text, unchanged)
# -------------------------

EX_DEV_LEAD = (
    "Development Lead — one side has more minor pieces developed than the other. "
    "You can’t attack the opponent's king or consequently have more space and defenders for your own king if you do not develop pieces."
)

EX_KING_SAFETY_LAG = (
    "King Safety Lag — king not castled and center opening or files opening toward king. "
    "In the opening, often one wants to castle as soon as possible to avoid direct attacks at the king in the center of the board."
)

EX_OPEN_FILE_CONTROL = (
    "Open File Control — a file is open and occupied/controlled by rooks/queens. "
    "Rooks particularly like open files as they see more space/squares and have more room to attack."
)

EX_SEMI_OPEN_FILE = (
    "Semi-Open File — file with only one side’s pawn missing (one pawn present). "
    "Rooks also enjoy semi-open files as they anticipate the opening of the file to gain more space or stop the pawn from advancing to a promotion square."
)

EX_BISHOP_PAIR = (
    "Bishop Pair — having both bishops vs not. Generally, while not a huge impact on lower rated players, "
    "bishops are considered to be preferable to knights as they have more scope or vision of the board. "
    "It is recommended to not trade off a bishop for a knight although seen as an equal trade unless there is a concrete reason."
)

EX_BAD_GOOD_BISHOP = (
    "Bad Bishop / Good Bishop — bishop is blocked by own pawns or has long diagonals. "
    "Bishops (or any piece for that matter) is only as powerful as its ability to see squares and subsequent pieces. "
    "If it is blocked in, its value is generally diminished."
)

EX_OUTPOST = (
    "Outpost — a square protected by pawns and occupiable by a knight where an opponent piece cannot easily dislodge and there are absolutely "
    "no pawns that can dislodge it. Essentially, there must be a piece (rook, bishop, knight) trade to dislodge it. "
    "The knight on an outpost dominates squares often making it a significantly more valuable piece relative to others as indicated by an evaluation."
)

EX_WEAK_SQUARE = (
    "Weak Square — square in enemy camp that cannot be protected by pawns easily (e.g., d5 in some structures). "
    "Control of a square can often dictate the flow of a game, particularly, central squares and squares surrounding a king."
)

EX_ISOLATED_PAWN = (
    "Isolated Pawn — pawn with no adjacent file pawn neighbors. "
    "Pawns are strongest when in a chain as pawns behind other pawns in a diagonal manner can defend and reinforce a pawn structure "
    "creating barriers for both defense and advancement. If there are no pawn neighbors on side files, there is no possibility for"
)

EX_DOUBLED_PAWNS = (
    "Doubled Pawns — two (or more) same-file pawns for one side. When pawns are stacked, they can’t defend each other…additionally, "
    "the pawn “behind” the more advanced one is limited in movement as it is essentially blocked making it a weakness and liability rather than an asset."
)

EX_BACKWARD_PAWN = (
    "Backward Pawn — pawn behind an adjacent pawn and cannot advance without being captured. "
    "It essentially is a pawn that cannot and is not defended by another pawn but rather is stuck defending a pawn "
    "(often it is the base of a chain making it the weakest aspect)."
)

EX_PASSED_PAWN = (
    "Passed Pawn — no opposing pawns on same or adjacent files ahead of it giving it a one way path down the board and to promotion."
)

EX_MINOR_VS_PAWN_STRUCT = (
    "Minor Piece vs Pawn Structure Attack (Minor Piece Targeting Pawn) — knight/bishop targeting weak pawn."
)

EX_ABSOLUTE_PIN = (
    "Absolute Pin — piece is pinned to the king as an opponent's piece has the king in the line of sight behind the pinned piece literally making it immovable. "
    "Moving a piece pinned to the king is not a legal move as it would hang the king."
)

EX_RELATIVE_PIN = (
    "Relative Pin – A piece is pinned to another piece of higher value other than the king as an opponent’s piece has a higher value piece in the line of sight "
    "behind the pinned piece making the possibility of it moving unlikely. The pinned piece in a relative pin can literally move it just would result in a plummet "
    "in evaluation as material would be lost."
)

EX_SKEWER = (
    "Skewer — a line attack where moving the front piece exposes a more valuable piece. "
    "What separates this from a pin is that often the piece in the front line of attack being attacked HAS to move in order to maintain the best evaluation. "
    "Or consequently the piece in front is undefended and when it moves there is another undefended piece. "
    "Often the King is in the front line of attack meaning it literally has to move (given nothing can block or take the piece placing the king in check) "
    "and thus revealing another piece that is undefended… the piece undefended was skewered by the attacking piece."
)

EX_FORK = (
    "Fork — single piece attacks two or more valuable targets simultaneously (e.g., knight forks king & queen) and the opponent cannot save both ensuring taking one "
    "is a guaranteed option in the subsequent move. The knight fork on a king and another subsequent undefended piece/material is an extremely common example of a fork…"
)

EX_BATTERY = (
    "Battery — rook/queen/bishop aligned with another heavy piece aiming at the same line (e.g., Q behind B). "
    "The front piece will be supported by the back piece ensuring the opponent must have at least 2 defenders of a piece in the line of sight to maintain material equality "
    "in the event of a capture by the battery."
)

EX_PAWN_MAJORITY = (
    "Pawn Majority (Queenside / Kingside) — more pawns on one wing than the opponent. "
    "A majority structure indicates the potential for a passed pawn creation."
)

EX_MINOR_TRAPPED = (
    "Minor Piece Trapped — piece with few legal moves and under attack. "
    "A piece trap indicates there is no move for said trapped piece that wouldn’t result in loss of material."
)

EX_EARLY_QUEEN = (
    "Early Queen Exposure — queen moved out early leading to tempo loss. "
    "The queen moving up early is often not a good decision as it can be chased early causing it to move again (loss of tempo). "
    "Additionally, the queen moving out early can potentially block the typical development of other minor pieces."
)

EX_F2_F7 = (
    "F2/F7 Weakness - f7 (for Black) and f2 (for White) are the weakest pawns on the board as they start with only one defender - the king, "
    "f7 or f2 is susceptible to forks from the knight onto the queen and rook, or early bishop/queen attacks either ending in mate or the loss of castling rights."
)

EX_C2_C7 = (
    "C2/C7 Weakness - Similar to f7 and f2, c2 and c7 have only one defender starting out… the queen. "
    "This potentially makes it susceptible to bishop and knight or queen and knight attacks threatening a knight fork onto the king and the rook "
    "especially if a knight is not available to go to a3 or e4(white)/a6 or e5 (black) to defend by adding another defender."
)

EX_HANGING = (
    "Hanging Piece/material – In chess there must be an equal or more number of defender(s) than attacker(s) to ensure material equality at the end of a capture sequence. "
    "The most obvious example of loss of material is of course one attacker vs zero defenders meaning the defending side is losing material given it is the attackers move "
    "to make. In this case there is a hanging piece."
)

EX_EQUAL_TRADE = (
    "Equal Trade – Evaluation doesn’t change much as two equal material values were exchanged. "
    "There is a caveat… the position of pieces can affect the relative value of pieces "
    "meaning that despite material being the literal same, it may not have been an equal trade of course this would be reflected in an evaluation shift."
)

EX_OPP_SIDE_CASTLE = (
    "Opposite Side Castling – When both sides castle on the opposite corners of the board (one kingside castled and the other queenside castled) "
    "then the game will be decided by offense…who mates the other first."
)

EX_KNIGHT_RIM = (
    "Knight on the rim is dim – A knight enjoys being closer to the center of the board because it sees and controls more squares in the center. "
    "When a knight is placed or developed to the edge of the board without justification, it has less functionality as it literally sees less squares."
)

EX_TAKE_CENTER = (
    "Take The Center – If your opponent allows you to take the center with both e4 and d4 (White) or d5 and e5 (black) then take it! "
    "Taking the center opens up more space for your pieces to advance and controls more advanced central squares putting more pressure on your opponents position."
)

EX_NEVER_PUSH_F = (
    "“Never Push f3/f6” – it is a well known concept that pushing either of pawns before the king is castled is a poor move as it exposes the king early "
    "often leading to thematic checks by either queen on the h file."
)

EX_CONNECT_ROOKS = (
    "Connect the rooks – After every minor piece is developed, there is center control, and the king is castled, the queen wants to move off the back rank to "
    "develop and to connect the rooks and allow for more space grabbing and advancement of pieces."
)

# (Some of the more exotic tactical motifs – attraction, deflection, clearance sac, etc. –
# are trickier without engine lines. We’ll start with this core set that reliably works
# with just FEN + eval/prev_eval. You can extend following the same pattern later.)

# -------------------------
# Low-level utilities
# -------------------------

def file_pawns(board, file_index, color=None):
    """Return squares of pawns on a given file. If color is None, any side."""
    result = []
    for rank in range(8):
        sq = chess.square(file_index, rank)
        p = board.piece_at(sq)
        if p and p.piece_type == chess.PAWN and (color is None or p.color == color):
            result.append(sq)
    return result

def open_or_semi_open_files(board):
    """Return (open_files, semi_open_for_white, semi_open_for_black)."""
    open_files = []
    semi_white = []
    semi_black = []
    for f in range(8):
        white_pawns = file_pawns(board, f, chess.WHITE)
        black_pawns = file_pawns(board, f, chess.BLACK)
        if not white_pawns and not black_pawns:
            open_files.append(f)
        elif not white_pawns and black_pawns:
            semi_white.append(f)
        elif white_pawns and not black_pawns:
            semi_black.append(f)
    return open_files, semi_white, semi_black

def piece_value(piece_type):
    return {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
        chess.KING: 1000
    }.get(piece_type, 0)

def legal_moves_from(board, sq):
    return [m for m in board.legal_moves if m.from_square == sq]

# -------------------------
# Motif implementations
# -------------------------

def development_lead(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    # Knights / bishops developed (off starting rank / files)
    white_knights = list(board.pieces(chess.KNIGHT, chess.WHITE))
    black_knights = list(board.pieces(chess.KNIGHT, chess.BLACK))
    white_bishops = list(board.pieces(chess.BISHOP, chess.WHITE))
    black_bishops = list(board.pieces(chess.BISHOP, chess.BLACK))

    white_dev = sum(1 for sq in white_knights if chess.square_rank(sq) > 0) \
                + sum(1 for sq in white_bishops if chess.square_rank(sq) > 0)
    black_dev = sum(1 for sq in black_knights if chess.square_rank(sq) < 7) \
                + sum(1 for sq in black_bishops if chess.square_rank(sq) < 7)

    diff = white_dev - black_dev
    if abs(diff) >= 1:
        side = "white" if diff > 0 else "black"
        motifs.append(
            make_motif(
                "development_lead",
                "Development Lead",
                EX_DEV_LEAD,
                side=side,
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"white_dev": white_dev, "black_dev": black_dev}
            )
        )
    return motifs

def king_safety_lag(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    open_files, semi_white, semi_black = open_or_semi_open_files(board)
    central_files = [3, 4]  # d and e

    for color in [chess.WHITE, chess.BLACK]:
        ksq = board.king(color)
        if ksq is None:
            continue
        # "Not castled": king still on original file (rough heuristic)
        start_rank = 0 if color == chess.WHITE else 7
        if chess.square_rank(ksq) == start_rank and chess.square_file(ksq) in (3, 4):
            # Check open/semi-open central files pointing at king
            files_of_interest = [f for f in central_files if f in open_files]
            if not files_of_interest:
                continue
            # If there are enemy rooks/queens on those files or attacking near king, flag
            enemy = not color
            dangerous = False
            for f in files_of_interest:
                for r in range(8):
                    sq = chess.square(f, r)
                    p = board.piece_at(sq)
                    if p and p.color == enemy and p.piece_type in (chess.ROOK, chess.QUEEN):
                        dangerous = True
                        break
                if dangerous:
                    break
            if dangerous:
                motifs.append(
                    make_motif(
                        "king_safety_lag",
                        "King Safety Lag",
                        EX_KING_SAFETY_LAG,
                        side=side_name(color),
                        severity="warning",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta
                    )
                )
    return motifs

def open_file_control(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    open_files, _, _ = open_or_semi_open_files(board)

    for color in [chess.WHITE, chess.BLACK]:
        for f in open_files:
            # Is there a rook/queen of color on or behind this file controlling it?
            has_ctrl = False
            for r in range(8):
                sq = chess.square(f, r)
                p = board.piece_at(sq)
                if p and p.color == color and p.piece_type in (chess.ROOK, chess.QUEEN):
                    has_ctrl = True
                    break
            if has_ctrl:
                motifs.append(
                    make_motif(
                        "open_file_control",
                        "Open File Control",
                        EX_OPEN_FILE_CONTROL,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"file": f}
                    )
                )
    return motifs

def semi_open_file(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    _, semi_white, semi_black = open_or_semi_open_files(board)

    if semi_white:
        motifs.append(
            make_motif(
                "semi_open_file",
                "Semi-Open File",
                EX_SEMI_OPEN_FILE,
                side="white",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"files": semi_white}
            )
        )
    if semi_black:
        motifs.append(
            make_motif(
                "semi_open_file",
                "Semi-Open File",
                EX_SEMI_OPEN_FILE,
                side="black",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"files": semi_black}
            )
        )
    return motifs

def bishop_pair(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        bishops = list(board.pieces(chess.BISHOP, color))
        if len(bishops) >= 2:
            motifs.append(
                make_motif(
                    "bishop_pair",
                    "Bishop Pair",
                    EX_BISHOP_PAIR,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )
    return motifs

def bad_good_bishop(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        bishops = list(board.pieces(chess.BISHOP, color))
        if not bishops:
            continue
        own_pawns = list(board.pieces(chess.PAWN, color))
        for bq in bishops:
            bishop_color = (chess.square_color(bq))  # True if light square
            pawns_same_color = sum(1 for sq in own_pawns if chess.square_color(sq) == bishop_color)
            mobility = len(legal_moves_from(board, bq))
            # rough: many same-colored pawns and low mobility => bad bishop
            if pawns_same_color >= 3 and mobility <= 4:
                motifs.append(
                    make_motif(
                        "bad_bishop",
                        "Bad Bishop / Good Bishop",
                        EX_BAD_GOOD_BISHOP,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"pawns_same_color": pawns_same_color, "mobility": mobility}
                    )
                )
    return motifs

def isolated_pawn(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        pawns = list(board.pieces(chess.PAWN, color))
        for sq in pawns:
            f = chess.square_file(sq)
            neighbor_files = [f - 1, f + 1]
            has_neighbor = False
            for nf in neighbor_files:
                if 0 <= nf <= 7 and file_pawns(board, nf, color):
                    has_neighbor = True
                    break
            if not has_neighbor:
                motifs.append(
                    make_motif(
                        "isolated_pawn",
                        "Isolated Pawn",
                        EX_ISOLATED_PAWN,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"square": sq}
                    )
                )
    return motifs

def doubled_pawns(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        for f in range(8):
            pawns = file_pawns(board, f, color)
            if len(pawns) >= 2:
                motifs.append(
                    make_motif(
                        "doubled_pawns",
                        "Doubled Pawns",
                        EX_DOUBLED_PAWNS,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"file": f, "count": len(pawns)}
                    )
                )
    return motifs

def passed_pawn(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        pawns = list(board.pieces(chess.PAWN, color))
        for sq in pawns:
            f = chess.square_file(sq)
            r = chess.square_rank(sq)
            direction = 1 if color == chess.WHITE else -1
            enemy = not color
            blocked = False
            # scan forward ranks
            rr = r + direction
            while 0 <= rr <= 7:
                for nf in (f - 1, f, f + 1):
                    if 0 <= nf <= 7:
                        forward_sq = chess.square(nf, rr)
                        p = board.piece_at(forward_sq)
                        if p and p.color == enemy and p.piece_type == chess.PAWN:
                            blocked = True
                            break
                if blocked:
                    break
                rr += direction
            if not blocked:
                motifs.append(
                    make_motif(
                        "passed_pawn",
                        "Passed Pawn",
                        EX_PASSED_PAWN,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"square": sq}
                    )
                )
    return motifs

def pawn_majority(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    # Queenside: files 0-2, kingside: 5-7
    for color in [chess.WHITE, chess.BLACK]:
        pawns = list(board.pieces(chess.PAWN, color))
        qside = sum(1 for sq in pawns if chess.square_file(sq) in (0, 1, 2))
        kside = sum(1 for sq in pawns if chess.square_file(sq) in (5, 6, 7))
        enemy = not color
        epawns = list(board.pieces(chess.PAWN, enemy))
        eq = sum(1 for sq in epawns if chess.square_file(sq) in (0, 1, 2))
        ek = sum(1 for sq in epawns if chess.square_file(sq) in (5, 6, 7))
        if qside > eq:
            motifs.append(
                make_motif(
                    "pawn_majority",
                    "Pawn Majority (Queenside / Kingside)",
                    EX_PAWN_MAJORITY,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"wing": "queenside"}
                )
            )
        if kside > ek:
            motifs.append(
                make_motif(
                    "pawn_majority",
                    "Pawn Majority (Queenside / Kingside)",
                    EX_PAWN_MAJORITY,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"wing": "kingside"}
                )
            )
    return motifs

def absolute_and_relative_pins(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        ksq = board.king(color)
        if ksq is None:
            continue
        for sq in board.pieces(chess.PAWN, color) | board.pieces(chess.KNIGHT, color) | \
                  board.pieces(chess.BISHOP, color) | board.pieces(chess.ROOK, color) | \
                  board.pieces(chess.QUEEN, color):
            if board.is_pinned(color, sq):
                # Determine if absolute (pinned to king) or relative
                # In python-chess, pinned piece is pinned to king, so treat as absolute
                motifs.append(
                    make_motif(
                        "absolute_pin",
                        "Absolute Pin",
                        EX_ABSOLUTE_PIN,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"square": sq}
                    )
                )
    # Relative pins are harder; do a simple ray-based heuristic:
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        for sq in board.pieces(chess.BISHOP, enemy) | board.pieces(chess.ROOK, enemy) | board.pieces(chess.QUEEN, enemy):
            attacker = sq
            directions = []
            p = board.piece_at(attacker)
            if p.piece_type in (chess.BISHOP, chess.QUEEN):
                directions += [chess.DIAGONAL_NORTHEAST, chess.DIAGONAL_NORTHWEST,
                               chess.DIAGONAL_SOUTHEAST, chess.DIAGONAL_SOUTHWEST]
            if p.piece_type in (chess.ROOK, chess.QUEEN):
                directions += [chess.BB_FILE_A, chess.BB_FILE_H, chess.BB_RANK_1, chess.BB_RANK_8]
            # Instead of bitboard directions, do simple geometric rays:
            # (we'll approximate relative pins elsewhere if needed)
            pass  # keep it simple for MVP
    return motifs

def hanging_piece(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        for sq in range(64):
            p = board.piece_at(sq)
            if not p or p.color != color:
                continue
            attackers = board.attackers(enemy, sq)
            defenders = board.attackers(color, sq)
            if len(attackers) > len(defenders) == 0:
                motifs.append(
                    make_motif(
                        "hanging_piece",
                        "Hanging Piece/material",
                        EX_HANGING,
                        side=side_name(color),
                        severity="warning",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"square": sq}
                    )
                )
    return motifs

def fork(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    # Simple: knight forks only (most common & easy)
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        knights = list(board.pieces(chess.KNIGHT, color))
        for sq in knights:
            attacks = board.attacks(sq)
            targets = []
            for t in attacks:
                p = board.piece_at(t)
                if p and p.color == enemy and p.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.KING):
                    targets.append(p.piece_type)
            if len(targets) >= 2:
                motifs.append(
                    make_motif(
                        "fork",
                        "Fork",
                        EX_FORK,
                        side=side_name(color),
                        severity="tactical",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"from": sq}
                    )
                )
    return motifs

def opposite_side_castling(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is None or bk is None:
        return motifs
    # kingside castling squares: g1/g8, queenside: c1/c8
    def castle_side(ksq, color):
        if ksq in (chess.G1, chess.G8):
            return "kingside"
        if ksq in (chess.C1, chess.C8):
            return "queenside"
        return None

    w_side = castle_side(wk, chess.WHITE)
    b_side = castle_side(bk, chess.BLACK)
    if w_side and b_side and w_side != b_side:
        motifs.append(
            make_motif(
                "opposite_side_castling",
                "Opposite Side Castling",
                EX_OPP_SIDE_CASTLE,
                side=None,
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta
            )
        )
    return motifs

def knight_on_rim(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    rim_squares_white = [chess.A3, chess.H3]
    rim_squares_black = [chess.A6, chess.H6]
    for color in [chess.WHITE, chess.BLACK]:
        rim_sqs = rim_squares_white if color == chess.WHITE else rim_squares_black
        for sq in board.pieces(chess.KNIGHT, color):
            if sq in rim_sqs:
                # Only really call it out if eval dropped vs previous (rough heuristic)
                if prev_eval is not None and eval_delta <= -30:  # -0.3 pawns
                    motifs.append(
                        make_motif(
                            "knight_on_rim",
                            "Knight on the rim is dim",
                            EX_KNIGHT_RIM,
                            side=side_name(color),
                            severity="info",
                            eval_cp=eval_cp,
                            eval_delta_cp=eval_delta,
                            extra={"square": sq}
                        )
                    )
    return motifs

def f2_f7_weakness(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    # f2/f7 squares
    sq_white = chess.F2
    sq_black = chess.F7
    for color, sq in ((chess.WHITE, sq_white), (chess.BLACK, sq_black)):
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.PAWN or p.color != color:
            continue
        enemy = not color
        # Check if enemy bishop+queen or knight+queen aiming there
        attackers = board.attackers(enemy, sq)
        has_knight = any(board.piece_at(a).piece_type == chess.KNIGHT for a in attackers if board.piece_at(a))
        has_bishop = any(board.piece_at(a).piece_type == chess.BISHOP for a in attackers if board.piece_at(a))
        has_queen = any(board.piece_at(a).piece_type == chess.QUEEN for a in attackers if board.piece_at(a))
        if (has_knight and has_queen) or (has_knight and has_bishop):
            motifs.append(
                make_motif(
                    "f2_f7_weakness",
                    "F2/F7 Weakness",
                    EX_F2_F7,
                    side=side_name(color),
                    severity="tactical",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )
    return motifs

def c2_c7_weakness(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color, sq in ((chess.WHITE, chess.C2), (chess.BLACK, chess.C7)):
        p = board.piece_at(sq)
        if not p or p.piece_type != chess.PAWN or p.color != color:
            continue
        enemy = not color
        attackers = board.attackers(enemy, sq)
        has_knight = any(board.piece_at(a).piece_type == chess.KNIGHT for a in attackers if board.piece_at(a))
        has_bishop = any(board.piece_at(a).piece_type == chess.BISHOP for a in attackers if board.piece_at(a))
        has_queen = any(board.piece_at(a).piece_type == chess.QUEEN for a in attackers if board.piece_at(a))
        if (has_knight and has_queen) or (has_knight and has_bishop):
            motifs.append(
                make_motif(
                    "c2_c7_weakness",
                    "C2/C7 Weakness",
                    EX_C2_C7,
                    side=side_name(color),
                    severity="tactical",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )
    return motifs

def take_the_center(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    # Very simple: check if a side has both central pawns advanced (e4+d4 or e5+d5)
    white_pawns = list(board.pieces(chess.PAWN, chess.WHITE))
    black_pawns = list(board.pieces(chess.PAWN, chess.BLACK))
    white_center = {sq for sq in white_pawns if sq in (chess.E4, chess.D4)}
    black_center = {sq for sq in black_pawns if sq in (chess.D5, chess.E5)}
    if len(white_center) >= 2:
        motifs.append(
            make_motif(
                "take_the_center",
                "Take The Center",
                EX_TAKE_CENTER,
                side="white",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta
            )
        )
    if len(black_center) >= 2:
        motifs.append(
            make_motif(
                "take_the_center",
                "Take The Center",
                EX_TAKE_CENTER,
                side="black",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta
            )
        )
    return motifs

def never_push_f_pawn(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    # If f-pawn advanced (off starting square) before castling and eval worsened
    for color, start_sq in ((chess.WHITE, chess.F2), (chess.BLACK, chess.F7)):
        p_start = board.piece_at(start_sq)
        has_f_pawn_on_file = bool(file_pawns(board, chess.square_file(start_sq), color))
        enemy = not color
        ksq = board.king(color)
        # Not yet castled (rough)
        start_rank = 0 if color == chess.WHITE else 7
        not_castled = ksq is not None and chess.square_rank(ksq) == start_rank
        if not_castled and not p_start and has_f_pawn_on_file:
            # Only complain if eval dropped
            if prev_eval is not None and eval_delta <= -30:
                motifs.append(
                    make_motif(
                        "never_push_f_pawn",
                        "Never Push f3/f6",
                        EX_NEVER_PUSH_F,
                        side=side_name(color),
                        severity="warning",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta
                    )
                )
    return motifs

def connect_the_rooks(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        if not king_sq:
            continue
        start_rank = 0 if color == chess.WHITE else 7
        # Castled kings are on c or g file usually
        castled = chess.square_rank(king_sq) == start_rank and chess.square_file(king_sq) in (2, 6)
        if not castled:
            continue
        # Minor pieces developed (off back rank)
        minors = list(board.pieces(chess.BISHOP, color)) + list(board.pieces(chess.KNIGHT, color))
        all_developed = all(chess.square_rank(sq) != start_rank for sq in minors)
        if not all_developed:
            continue
        # If queen is still on back rank between rooks, suggest connecting
        rooks = list(board.pieces(chess.ROOK, color))
        if len(rooks) < 2:
            continue
        queen_sq = next(iter(board.pieces(chess.QUEEN, color)), None)
        if queen_sq is None:
            continue
        # Rough: queen on starting rank and between rook files
        q_rank = chess.square_rank(queen_sq)
        r_files = sorted(chess.square_file(r) for r in rooks)
        q_file = chess.square_file(queen_sq)
        if q_rank == start_rank and r_files[0] < q_file < r_files[-1]:
            motifs.append(
                make_motif(
                    "connect_the_rooks",
                    "Connect the rooks",
                    EX_CONNECT_ROOKS,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )
    return motifs

def minor_piece_trapped(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color
        for piece_type in (chess.BISHOP, chess.KNIGHT, chess.ROOK, chess.QUEEN):
            for sq in board.pieces(piece_type, color):
                moves = legal_moves_from(board, sq)
                if len(moves) <= 1:
                    # if the square is attacked and possible destinations are also bad, call it trapped
                    if board.is_attacked_by(enemy, sq):
                        motifs.append(
                            make_motif(
                                "minor_piece_trapped",
                                "Minor Piece Trapped",
                                EX_MINOR_TRAPPED,
                                side=side_name(color),
                                severity="warning",
                                eval_cp=eval_cp,
                                eval_delta_cp=eval_delta,
                                extra={"square": sq, "legal_moves": len(moves)}
                            )
                        )
    return motifs

# =============================
# NEW MOTIFS (FULL BLOCK)
# =============================

EX_OUTPOST = (
    "Outpost — a square protected by pawns and occupiable by a knight where an opponent piece cannot easily dislodge and "
    "there are absolutely no pawns that can dislodge it. Essentially, there must be a piece (rook, bishop, knight) trade "
    "to dislodge it. The knight on an outpost dominates squares often making it a significantly more valuable piece relative "
    "to others as indicated by an evaluation."
)

def outpost(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        for knight_sq in board.pieces(chess.KNIGHT, color):
            # knight must be advanced
            rank = chess.square_rank(knight_sq)
            if color == chess.WHITE and rank < 3:
                continue
            if color == chess.BLACK and rank > 4:
                continue

            # defended by pawn
            defended_by_pawn = any(
                board.piece_at(sq)
                and board.piece_at(sq).piece_type == chess.PAWN
                and board.piece_at(sq).color == color
                for sq in board.attackers(color, knight_sq)
            )
            if not defended_by_pawn:
                continue

            # enemy pawns cannot attack it
            attacked_by_enemy_pawn = any(
                board.piece_at(sq)
                and board.piece_at(sq).piece_type == chess.PAWN
                and board.piece_at(sq).color == enemy
                for sq in board.attackers(enemy, knight_sq)
            )
            if attacked_by_enemy_pawn:
                continue

            motifs.append(
                make_motif(
                    "outpost",
                    "Outpost",
                    EX_OUTPOST,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"square": knight_sq}
                )
            )

    return motifs


# -------------------------------
# WEAK SQUARE
# -------------------------------

EX_WEAK_SQUARE = (
    "Weak Square — square in enemy camp that cannot be protected by pawns easily. "
    "Control of a square can often dictate the flow of a game, particularly in the center or near a king."
)

def weak_square(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    central_squares = [chess.D5, chess.E5, chess.D4, chess.E4]

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        for sq in central_squares:
            # must be in enemy camp
            if color == chess.WHITE and chess.square_rank(sq) <= 3:
                continue
            if color == chess.BLACK and chess.square_rank(sq) >= 4:
                continue

            # opponent must control it
            if not board.is_attacked_by(enemy, sq):
                continue

            # own pawn cannot defend
            pawn_defenders = [
                a for a in board.attackers(color, sq)
                if board.piece_at(a)
                and board.piece_at(a).piece_type == chess.PAWN
            ]
            if pawn_defenders:
                continue

            motifs.append(
                make_motif(
                    "weak_square",
                    "Weak Square",
                    EX_WEAK_SQUARE,
                    side=side_name(enemy),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"square": sq}
                )
            )

    return motifs


# -------------------------------
# MINORITY ATTACK SETUP
# -------------------------------

EX_MINORITY_ATTACK = (
    "Minority Attack Setup — pawn structure aiming for minority attack (e.g., a-b-c vs a-b pawns). "
    "Detect: pawn majority/opponent structure matches minority attack patterns."
)

def minority_attack_setup(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    patterns = {
        chess.WHITE: ([chess.B2, chess.C2], [chess.A7, chess.B7, chess.C7]),
        chess.BLACK: ([chess.B7, chess.C7], [chess.A2, chess.B2, chess.C2])
    }

    for color in [chess.WHITE, chess.BLACK]:
        own_pawns, target_structure = patterns[color]
        enemy = not color

        owns = [sq for sq in own_pawns if board.piece_at(sq) and board.piece_at(sq).color == color]
        enemies = [sq for sq in target_structure if board.piece_at(sq) and board.piece_at(sq).color == enemy]

        if len(owns) >= 1 and len(enemies) >= 2:
            motifs.append(
                make_motif(
                    "minority_attack_setup",
                    "Minority Attack Setup",
                    EX_MINORITY_ATTACK,
                    side=side_name(color),
                    severity="info"
                )
            )

    return motifs


# -------------------------------
# DISCOVERY ATTACK
# -------------------------------

EX_DISCOVERY_ATTACK = (
    "Discovery Attack – when a piece moves unveiling the line of sight of another piece onto a more valuable or undefended piece."
)

def discovery_attack(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last_move = getattr(board, "last_move_uci", None)
    if not last_move:
        return motifs

    try:
        move = chess.Move.from_uci(last_move)
    except:
        return motifs

    to_sq = move.to_square

    directions = [
        (1,0),( -1,0),(0,1),(0,-1),
        (1,1),(-1,1),(1,-1),(-1,-1)
    ]

    for dx, dy in directions:
        f = chess.square_file(to_sq)
        r = chess.square_rank(to_sq)
        f += dx
        r += dy

        while 0 <= f <= 7 and 0 <= r <= 7:
            sq = chess.square(f, r)
            p = board.piece_at(sq)

            if p:
                # discovered piece behind the moved piece
                if p.color == board.turn and p.piece_type in (chess.ROOK, chess.BISHOP, chess.QUEEN):
                    motifs.append(
                        make_motif(
                            "discovery_attack",
                            "Discovery Attack",
                            EX_DISCOVERY_ATTACK,
                            side=side_name(p.color),
                            severity="tactical",
                            eval_cp=eval_cp,
                            eval_delta_cp=eval_delta
                        )
                    )
                    return motifs
                break

            f += dx
            r += dy

    return motifs


# -------------------------------
# DOUBLE CHECK
# -------------------------------

EX_DOUBLE_CHECK = (
    "Double Check – When two pieces place the opponent’s king into check."
)

def double_check(board, move_number, eval_cp, prev_eval=None):
    motifs = []
    for color in [chess.WHITE, chess.BLACK]:
        king_sq = board.king(color)
        if not king_sq:
            continue
        attackers = list(board.attackers(not color, king_sq))
        if len(attackers) >= 2:
            motifs.append(
                make_motif(
                    "double_check",
                    "Double Check",
                    EX_DOUBLE_CHECK,
                    side=side_name(not color),
                    severity="tactical",
                    eval_cp=eval_cp
                )
            )
    return motifs


# -------------------------------
# PIECE SACRIFICE
# -------------------------------

EX_PIECE_SAC = (
    "Piece Sacrifice – When an attacking player either captures a lower value piece purposefully losing material or leaves a minor piece "
    "or higher for a winning or advantageous position."
)

def piece_sacrifice(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    try:
        m = chess.Move.from_uci(last)
    except:
        return motifs

    moved_piece = board.piece_at(m.to_square)
    if not moved_piece:
        return motifs

    enemy = not moved_piece.color

    attackers = board.attackers(enemy, m.to_square)
    defenders = board.attackers(moved_piece.color, m.to_square)

    if len(attackers) > len(defenders):
        if prev_eval is not None and eval_delta >= -10:
            motifs.append(
                make_motif(
                    "piece_sacrifice",
                    "Piece Sacrifice",
                    EX_PIECE_SAC,
                    side=side_name(moved_piece.color),
                    severity="brilliant",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )

    return motifs


# -------------------------------
# INTERMEZZO
# -------------------------------

EX_INTERMEZZO = (
    "Intermezzo/counter threat – When there is a threat from the opponent but the defending player makes an in-between forcing move "
    "like a check before responding."
)

def intermezzo(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    if board.is_check():
        moved_piece = board.piece_at(chess.Move.from_uci(last).to_square)
        if moved_piece:
            motifs.append(
                make_motif(
                    "intermezzo",
                    "Intermezzo / Counter Threat",
                    EX_INTERMEZZO,
                    side=side_name(moved_piece.color),
                    severity="tactical",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )

    return motifs


# -------------------------------
# ATTRACTION
# -------------------------------

EX_ATTRACTION = (
    "Attraction – When a player lures an opponent’s piece to a more favorable square to set up a tactical idea."
)

def attraction(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    try:
        m = chess.Move.from_uci(last)
    except:
        return motifs

    p = board.piece_at(m.to_square)
    if p and p.piece_type in (chess.KING, chess.QUEEN):
        if prev_eval is not None and eval_delta >= -20:
            motifs.append(
                make_motif(
                    "attraction",
                    "Attraction",
                    EX_ATTRACTION,
                    side=side_name(not p.color),
                    severity="tactical",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta
                )
            )

    return motifs


# -------------------------------
# DEFLECTION
# -------------------------------

EX_DEFLECTION = (
    "Deflection – When a player disrupts an opponent’s piece from defending another piece via a sacrifice or forcing threat."
)

def deflection(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    try:
        m = chess.Move.from_uci(last)
    except:
        return motifs

    moved_piece = board.piece_at(m.to_square)
    if not moved_piece:
        return motifs

    enemy = not moved_piece.color
    attacked = board.attacks(m.to_square)

    for sq in attacked:
        target = board.piece_at(sq)
        if target and target.color == enemy:
            defenders = board.attackers(enemy, sq)
            if defenders and prev_eval is not None and eval_delta > 30:
                motifs.append(
                    make_motif(
                        "deflection",
                        "Deflection",
                        EX_DEFLECTION,
                        side=side_name(moved_piece.color),
                        severity="tactical",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"target": sq}
                    )
                )

    return motifs


# -------------------------------
# CLEARANCE SACRIFICE
# -------------------------------

EX_CLEARANCE_SAC = (
    "Clearance Sacrifice – When a player sacrifices a piece to clear a square or open a line for a more powerful piece to attack."
)

def clearance_sacrifice(board, move_number, eval_cp, prev_eval=None):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    try:
        m = chess.Move.from_uci(last)
    except:
        return motifs

    moved_piece = board.piece_at(m.to_square)
    if not moved_piece:
        return motifs

    vacated = m.from_square

    for sq in board.attackers(moved_piece.color, vacated):
        attacker = board.piece_at(sq)
        if attacker and attacker.piece_type in (chess.ROOK, chess.QUEEN, chess.BISHOP):
            if prev_eval is not None and eval_delta > 50:
                motifs.append(
                    make_motif(
                        "clearance_sacrifice",
                        "Clearance Sacrifice",
                        EX_CLEARANCE_SAC,
                        side=side_name(moved_piece.color),
                        severity="brilliant",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta
                    )
                )

    return motifs


# -------------------------------
# XRAY / POTENTIAL ENERGY
# -------------------------------

EX_XRAY = (
    "XRAY/ Potential Energy – When a piece placement allows it to have a future vision of a more valuable piece or square "
    "setting up future tactical ideas."
)

def xray(board, move_number, eval_cp, prev_eval=None):
    motifs = []

    for color in [chess.WHITE, chess.BLACK]:
        for sq in (
            board.pieces(chess.QUEEN, color)
            | board.pieces(chess.ROOK, color)
            | board.pieces(chess.BISHOP, color)
        ):
            directions = [
                (1,0),( -1,0),(0,1),(0,-1),
                (1,1),(1,-1),(-1,1),(-1,-1)
            ]
            for dx,dy in directions:
                f = chess.square_file(sq) + dx
                r = chess.square_rank(sq) + dy
                while 0 <= f <= 7 and 0 <= r <= 7:
                    sq2 = chess.square(f, r)
                    p = board.piece_at(sq2)
                    if p:
                        if p.color != color:
                            motifs.append(
                                make_motif(
                                    "xray",
                                    "XRAY / Potential Energy",
                                    EX_XRAY,
                                    side=side_name(color),
                                    severity="info"
                                )
                            )
                        break
                    f += dx
                    r += dy

    return motifs


# -------------------------
# Main dispatcher
# -------------------------

MOTIF_FUNCTIONS = [
    development_lead,
    king_safety_lag,
    open_file_control,
    semi_open_file,
    bishop_pair,
    bad_good_bishop,
    isolated_pawn,
    doubled_pawns,
    passed_pawn,
    pawn_majority,
    absolute_and_relative_pins,
    hanging_piece,
    fork,
    opposite_side_castling,
    knight_on_rim,
    f2_f7_weakness,
    c2_c7_weakness,
    take_the_center,
    never_push_f_pawn,
    connect_the_rooks,
    minor_piece_trapped,

    # NEW ones:
    outpost,
    weak_square,
    minority_attack_setup,
    discovery_attack,
    double_check,
    piece_sacrifice,
    intermezzo,
    attraction,
    deflection,
    clearance_sacrifice,
    xray,
]


def detect_motifs(board: chess.Board, move_number: int, eval, prev_eval=None):
    """
    Central entrypoint used by app.py.

    board       : python-chess Board, already set to the *current* FEN.
    move_number : 1-based (or board.fullmove_number from /api/motifs).
    eval        : evaluation in centipawns (positive = better for White).
    prev_eval   : previous move's evaluation in centipawns, or None.
    """
    eval_cp = eval
    motifs = []
    for fn in MOTIF_FUNCTIONS:
        try:
            res = fn(board, move_number, eval_cp, prev_eval)
            if res:
                motifs.extend(res)
        except Exception:
            # Fail-soft: a broken motif should not kill everything.
            continue
    return motifs
