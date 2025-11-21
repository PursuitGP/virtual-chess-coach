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

def make_motif(
    motif_id,
    name,
    explanation,
    side=None,
    severity="info",
    eval_cp=None,
    eval_delta_cp=None,
    extra=None,
    status="present",   # NEW: "present" | "played" | "available"
):
    d = {
        "id": motif_id,
        "name": name,
        "explanation": explanation,
        "side": side,
        "severity": severity,
        "status": status,   # always present in JSON
    }
    if eval_cp is not None:
        d["eval_cp"] = eval_cp
    if eval_delta_cp is not None:
        d["eval_delta_cp"] = eval_delta_cp
    if extra:
        d["extra"] = extra
    return d


def pawn_weakness_type(board, sq, color):
    """
    Classify a pawn as 'isolated', 'doubled', 'backward', or None.
    This is a lightweight heuristic, not engine-perfect.
    """
    file_idx = chess.square_file(sq)
    rank_idx = chess.square_rank(sq)
    enemy = not color

    # Doubled pawns: more than one friendly pawn on this file
    same_file_pawns = [
        p_sq for p_sq in board.pieces(chess.PAWN, color)
        if chess.square_file(p_sq) == file_idx
    ]
    if len(same_file_pawns) > 1:
        return "doubled"

    # Isolated pawn: no friendly pawns on adjacent files
    adj_files = []
    if file_idx > 0:
        adj_files.append(file_idx - 1)
    if file_idx < 7:
        adj_files.append(file_idx + 1)

    has_neighbor = False
    for af in adj_files:
        for r in range(8):
            sq2 = chess.square(af, r)
            p = board.piece_at(sq2)
            if p and p.piece_type == chess.PAWN and p.color == color:
                has_neighbor = True
                break
        if has_neighbor:
            break

    if not has_neighbor:
        return "isolated"

    # Backward pawn: approximate
    # - square in front is attacked by enemy pawns
    # - no friendly pawn on adjacent files that can reasonably support
    direction = 1 if color == chess.WHITE else -1
    front_rank = rank_idx + direction
    if 0 <= front_rank <= 7:
        front_sq = chess.square(file_idx, front_rank)
        # enemy pawns attacking the front square?
        enemy_attackers = board.attackers(enemy, front_sq)
        attacked_by_enemy_pawn = any(
            board.piece_at(a_sq) and
            board.piece_at(a_sq).piece_type == chess.PAWN and
            board.piece_at(a_sq).color == enemy
            for a_sq in enemy_attackers
        )
        if attacked_by_enemy_pawn:
            # check for potential pawn support from adjacent files
            has_support_pawn = False
            for af in adj_files:
                for r in range(8):
                    sq2 = chess.square(af, r)
                    p = board.piece_at(sq2)
                    if p and p.piece_type == chess.PAWN and p.color == color:
                        # rough: supporting pawn not far advanced past this pawn
                        if color == chess.WHITE and r <= rank_idx + 1:
                            has_support_pawn = True
                        elif color == chess.BLACK and r >= rank_idx - 1:
                            has_support_pawn = True
                        if has_support_pawn:
                            break
                if has_support_pawn:
                    break
            if not has_support_pawn:
                return "backward"

    return None

def are_aligned(sq1, sq2, piece_type):
    f1, r1 = chess.square_file(sq1), chess.square_rank(sq1)
    f2, r2 = chess.square_file(sq2), chess.square_rank(sq2)

    df = abs(f1 - f2)
    dr = abs(r1 - r2)

    if piece_type == chess.ROOK:
        return f1 == f2 or r1 == r2
    if piece_type == chess.BISHOP:
        return df == dr
    if piece_type == chess.QUEEN:
        return f1 == f2 or r1 == r2 or df == dr
    return False


def clear_path_except(start, end, board, color):
    """Check squares between start→end contain only the front piece or emptiness."""
    step_f = (chess.square_file(end) - chess.square_file(start))
    step_r = (chess.square_rank(end) - chess.square_rank(start))
    step_f = (step_f > 0) - (step_f < 0)
    step_r = (step_r > 0) - (step_r < 0)

    f = chess.square_file(start) + step_f
    r = chess.square_rank(start) + step_r

    while (f, r) != (chess.square_file(end), chess.square_rank(end)):
        sq = chess.square(f, r)
        pc = board.piece_at(sq)
        if pc:
            # Blocked unless it's exactly the front piece
            if sq != end:
                return False
        f += step_f
        r += step_r
    return True


def battery_has_real_target(rear, front, board, color):
    """
    Check that rear piece attacks a meaningful target beyond front piece.
    """
    # Simulate front moving one step forward to expose line
    targets = list(board.attacks(rear))

    for t in targets:
        piece = board.piece_at(t)
        if piece and piece.color != color:
            # enemy piece in line = meaningful battery
            return True

    return False



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
EX_MEET_CENTER = (
    "When a player takes the center, such as with e4, d4, e5, d5, the opposing side should Counter by meeting the pawn with another direct pawn to STOP its advancement"
    "This is vital as to prevent space grabbing, and also fights for the center control."
)
EX_XRAY = (
    "XRAY / Potential Energy – A sliding piece (bishop, rook, or queen) is positioned on a line "
    "toward a more valuable enemy piece, but a less valuable piece is blocking the path. "
    "This means the attacker is creating a future tactical idea: if the blocker ever moves, "
    "a discovered attack appears instantly. XRAYs indicate pressure, alignment, and future danger "
    "that may become a real tactic later."
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

def development_lead(board, move_number, eval_cp, prev_eval=None, last_move_uci=None, **kwargs):
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    # 🚫 NEW: If last move was a KING move, skip development detection entirely.
    if last_move_uci:
        moved_from = chess.parse_square(last_move_uci[:2])
        if kwargs.get("prev_board") is not None:
            moved_piece = kwargs["prev_board"].piece_at(moved_from)
            if moved_piece and moved_piece.piece_type == chess.KING:
                return motifs   # <-- prevents false positives on king moves

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


def king_safety_lag(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def open_file_control(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def semi_open_file(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

EX_BISHOP_PAIR = (
    "Bishop Pair — having both bishops vs not. Generally, while not a huge impact on lower rated players, "
    "bishops are considered to be preferable to knights as they have more scope or vision of the board. "
    "It is recommended to not trade off a bishop for a knight although seen as an equal trade unless there is a concrete reason."
)

def bishop_pair(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Only fire when one side actually *has* the bishop pair (2 bishops)
    and the other side does not, i.e., after trades/sacs.
    Also avoid spam in the first few moves.
    """
    motifs = []

    # Don't talk about bishop pair on move 1–4; nothing has happened yet.
    if move_number < 5:
        return motifs

    w_bishops = len(board.pieces(chess.BISHOP, chess.WHITE))
    b_bishops = len(board.pieces(chess.BISHOP, chess.BLACK))

    # Neither side has the pair → no motif.
    if w_bishops < 2 and b_bishops < 2:
        return motifs

    # Ignore totally busted positions where eval is just winning for the other side.
    # eval_cp is "better for White if positive".
    if eval_cp is None:
        eval_cp = 0

    # White has the bishop pair, Black does not.
    if w_bishops == 2 and b_bishops < 2 and eval_cp > -100:
        motifs.append(
            make_motif(
                "bishop_pair",
                "Bishop Pair",
                EX_BISHOP_PAIR,
                side="White",
                severity="info" if abs(eval_cp) < 100 else "good",
                eval_cp=eval_cp,
                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            )
        )

    # Black has the bishop pair, White does not.
    if b_bishops == 2 and w_bishops < 2 and eval_cp < 100:
        motifs.append(
            make_motif(
                "bishop_pair",
                "Bishop Pair",
                EX_BISHOP_PAIR,
                side="Black",
                severity="info" if abs(eval_cp) < 100 else "good",
                eval_cp=eval_cp,
                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            )
        )

    return motifs


def bad_good_bishop(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def isolated_pawn(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def doubled_pawns(board, move_number, eval_cp, prev_eval=None, **_):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    for color in [chess.WHITE, chess.BLACK]:
        # group pawns by file
        file_map = {}
        for sq in board.pieces(chess.PAWN, color):
            file = chess.square_file(sq)
            file_map.setdefault(file, []).append(sq)

        for file, pawns in file_map.items():
            if len(pawns) <= 1:
                continue

            # Sort by rank
            pawns_sorted = sorted(pawns, key=lambda s: chess.square_rank(s))

            # Special exception: exd5 positions -> not a weakness
            # If the front pawn is on d5 or d4 and just created doubled pawns, skip.
            front = pawns_sorted[-1]
            if chess.square_file(front) == file and chess.square_rank(front) in (3, 4):
                continue

            motifs.append(
                make_motif(
                    "doubled_pawns",
                    "Doubled Pawns",
                    EX_DOUBLED_PAWNS,
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"file": file},
                )
            )

    return motifs


def passed_pawn(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def pawn_majority(board, move_number, eval_cp, prev_eval=None, **kwargs):
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


def hanging_piece(
    board,
    prev_board=None,
    move_number=None,
    eval_cp=None,
    prev_eval=None,
    last_move_uci=None,   # <--- you already pass this in detect_motifs
    **kwargs,
):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # Extract arrival square of last move
    arrival_sq = None
    if last_move_uci:
        arrival_sq = last_move_uci[2:4]   # "f7", "f2", etc.

    for color in (chess.WHITE, chess.BLACK):
        enemy = not color
        for sq, piece in board.piece_map().items():
            if piece.color != color:
                continue

            attackers = board.attackers(enemy, sq)
            defenders = board.attackers(color, sq)

            # Must be attacked
            if len(attackers) == 0:
                continue

            # Must be badly defended
            if len(defenders) >= len(attackers):
                continue

            # -------------------------------------------------------
            # SPECIAL RULE: intentional knight/bishop sacrifices on f7/f2
            # -------------------------------------------------------
            if arrival_sq in ("f7", "f2"):
                if chess.square_name(sq) == arrival_sq:
                    if piece.piece_type in (chess.KNIGHT, chess.BISHOP):
                        # Skip ONLY for THIS move
                        continue

            # -------------------------------------------------------
            # If not suppressed, emit normally
            # -------------------------------------------------------
            motifs.append(
                make_motif(
                    "hanging_piece",
                    "Hanging Piece/material",
                    EX_HANGING,
                    side=side_name(color),
                    severity="warning",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"square": chess.square_name(sq)},
                )
            )

    return motifs



def fork(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def opposite_side_castling(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def knight_on_rim(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def f2_f7_weakness(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def c2_c7_weakness(board, move_number, eval_cp, prev_eval=None, **kwargs):
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


def take_the_center(
    board,
    move_number,
    eval_cp,
    prev_eval=None,
    sf_raw=None,
    pv=None,
    last_move_uci=None,
    prev_move_uci=None,
    **_,
):
    motifs = []

    last = last_move_uci or getattr(board, "last_move_uci", None)
    prev = prev_move_uci or getattr(board, "prev_move_uci", None)

    if not last or prev is not None:
        return motifs

    try:
        move = chess.Move.from_uci(last)
    except Exception:
        return motifs

    if move.to_square not in (chess.E4, chess.D4):
        return motifs

    piece = board.piece_at(move.to_square)
    if not piece or piece.piece_type != chess.PAWN or piece.color != chess.WHITE:
        return motifs

    other_sq = chess.D4 if move.to_square == chess.E4 else chess.E4
    if board.piece_at(other_sq) is not None:
        return motifs

    motifs.append(
        make_motif(
            "take_the_center",
            "Take The Center",
            EX_TAKE_CENTER,
            side="white",
            severity="info",
            eval_cp=eval_cp,
            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
        )
    )

    return motifs


def meet_the_center(
    board,
    move_number,
    eval_cp,
    prev_eval=None,
    sf_raw=None,
    pv=None,
    last_move_uci=None,
    prev_move_uci=None,
    **_,
):
    motifs = []

    last = last_move_uci or getattr(board, "last_move_uci", None)
    prev = prev_move_uci or getattr(board, "prev_move_uci", None)

    if not last or not prev:
        return motifs

    try:
        last_move = chess.Move.from_uci(last)
        prev_move = chess.Move.from_uci(prev)
    except Exception:
        return motifs

    # we only want the classic 1. e4 e5 / 1. d4 d5 at the start
    if board.fullmove_number > 2:
        return motifs

    pattern = None
    if prev_move.to_square == chess.E4 and last_move.to_square == chess.E5:
        pattern = "e4-e5"
    elif prev_move.to_square == chess.D4 and last_move.to_square == chess.D5:
        pattern = "d4-d5"

    if not pattern:
        return motifs

    piece = board.piece_at(last_move.to_square)
    if not piece or piece.piece_type != chess.PAWN or piece.color != chess.BLACK:
        return motifs

    motifs.append(
        make_motif(
            "meet_the_center",
            "Meet The Center",
            EX_MEET_CENTER,
            side="black",
            severity="info",
            eval_cp=eval_cp,
            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            extra={"pattern": pattern},
        )
    )

    return motifs




def never_push_f_pawn(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def connect_the_rooks(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def minor_piece_trapped(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    **_
):
    """
    Minor Piece Trapped —
    A knight or bishop has *no safe squares* and will lose material
    regardless of what it plays next.

    This motif MUST be extremely strict to avoid false positives.
    """

    motifs = []

    minor_types = (chess.KNIGHT, chess.BISHOP)

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        minors = (
            board.pieces(chess.KNIGHT, color)
            | board.pieces(chess.BISHOP, color)
        )

        for sq in minors:
            piece = board.piece_at(sq)
            if not piece:
                continue

            legal_moves = []
            safe_moves = []

            for move in board.legal_moves:
                if move.from_square != sq:
                    continue
                legal_moves.append(move)

                # simulate move
                tmp = board.copy()
                tmp.push(move)
                dest = move.to_square

                # safe if defenders >= attackers after move
                attackers = len(tmp.attackers(enemy, dest))
                defenders = len(tmp.attackers(color, dest))

                if defenders >= attackers:
                    safe_moves.append(move)

            # trapped = no safe moves AND under attack
            if len(legal_moves) > 0 and len(safe_moves) == 0:
                attackers_now = len(board.attackers(enemy, sq))
                defenders_now = len(board.attackers(color, sq))

                # must actually be losing material
                if attackers_now > defenders_now:
                    motifs.append(
                        make_motif(
                            "minor_piece_trapped",
                            "Minor Piece Trapped",
                            "A minor piece has no safe squares and is certain to lose material.",
                            side=side_name(color),
                            severity="warning",
                            eval_cp=eval_cp,
                            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
                            extra={"piece": chess.square_name(sq)},
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

def outpost(board, move_number, eval_cp, prev_eval=None, **kwargs):
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


def weak_square(board, move_number, eval_cp, prev_eval=None, **_):
    """
    Correct Weak Square logic:
    A weak square forms when the pawn that *could* defend it has advanced,
    making future pawn defense impossible.
    """
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    motifs = []

    # Pawn-advance patterns that create holes
    HOLE_MAP = {
        chess.E4: [chess.D3, chess.F3],
        chess.D4: [chess.C3, chess.E3],
        chess.E5: [chess.D6, chess.F6],
        chess.D5: [chess.C6, chess.E6],
    }

    last = getattr(board, "last_move_uci", None)
    if not last:
        return motifs

    to_sq = chess.parse_square(last[2:4])
    piece = board.piece_at(to_sq)
    if not piece or piece.piece_type != chess.PAWN:
        return motifs

    color = piece.color
    enemy = not color

    # Did a pawn move to a hole-creating square?
    if to_sq not in HOLE_MAP:
        return motifs

    for hole in HOLE_MAP[to_sq]:
        # enemy must control or occupy it
        if not board.is_attacked_by(enemy, hole):
            continue

        # and cannot ever be pawn-defended again
        pawn_defenders = [
            s for s in board.attackers(color, hole)
            if board.piece_at(s) and board.piece_at(s).piece_type == chess.PAWN
        ]
        if pawn_defenders:
            continue

        motifs.append(make_motif(
            "weak_square",
            "Weak Square",
            EX_WEAK_SQUARE,
            side=side_name(enemy),
            severity="info",
            eval_cp=eval_cp,
            eval_delta_cp=eval_delta,
            extra={"square": chess.square_name(hole)}
        ))

    return motifs



# -------------------------------
# MINORITY ATTACK SETUP
# -------------------------------

EX_MINORITY_ATTACK = (
    "Minority Attack Setup — pawn structure aiming for minority attack (e.g., a-b-c vs a-b pawns). "
    "Detect: pawn majority/opponent structure matches minority attack patterns."
)

def minority_attack_setup(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Only trigger when a *real* minority-attackable structure exists:
    - queenside (a–c) majority vs a smaller group
    - at least one minority pawn has advanced
    - not in the very early opening.
    """
    motifs = []

    # Minority attacks are a middlegame plan, not move 2.
    if move_number < 10:
        return motifs

    def queenside_pawns(color):
        return [sq for sq in board.pieces(chess.PAWN, color)
                if chess.square_file(sq) in (0, 1, 2)]  # a, b, c

    def advanced_minority_pawn(color, home_rank):
        # At least one pawn in the a–c files has moved off the home rank
        for sq in queenside_pawns(color):
            if chess.square_rank(sq) != home_rank:
                return True
        return False

    w_qp = queenside_pawns(chess.WHITE)
    b_qp = queenside_pawns(chess.BLACK)

    # White minority attack (classic: White has fewer a–c pawns vs Black)
    if len(w_qp) < len(b_qp) and advanced_minority_pawn(chess.WHITE, home_rank=1):
        motifs.append(
            make_motif(
                "minority_attack_setup",
                "Minority Attack Setup",
                EX_MINORITY_ATTACK,
                side="White",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            )
        )

    # Black minority attack mirrored (less common, but possible)
    if len(b_qp) < len(w_qp) and advanced_minority_pawn(chess.BLACK, home_rank=6):
        motifs.append(
            make_motif(
                "minority_attack_setup",
                "Minority Attack Setup",
                EX_MINORITY_ATTACK,
                side="Black",
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            )
        )

    return motifs



# -------------------------------
# DISCOVERY ATTACK
# -------------------------------

EX_DISCOVERY_ATTACK = (
    "Discovery Attack – when a piece moves unveiling the line of sight of another piece onto a more valuable or undefended piece."
)

EX_DISCOVERY_ATTACK = (
    "Discovered Attack – a piece moves away from a line, revealing a hidden attack "
    "from a rook, bishop, or queen onto an enemy piece."
)

def discovered_attack(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    **_,
):
    """
    Discovered Attack —

    Detects when the LAST MOVE removed a friendly blocker from the line
    between a sliding piece (queen/rook/bishop) and an enemy piece, so that
    AFTER the move the slider now directly attacks that target.

    This is temporal: it only fires on the move where the discovery is
    actually created (e.g. 5...Nxd5 revealing Qd8→Ng5 in your game).
    """
    motifs = []

    if prev_board is None or not last_move_uci:
        return motifs

    # --- 1) Identify what moved in the PREVIOUS position ---
    moved_from_str = last_move_uci[:2]
    moved_to_str = last_move_uci[2:4]
    moved_from = chess.parse_square(moved_from_str)
    moved_to = chess.parse_square(moved_to_str)

    prev_piece = prev_board.piece_at(moved_from)
    if not prev_piece:
        return motifs

    mover_color = prev_piece.color
    enemy = not mover_color

    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # --- 2) All SLIDERS (Q/R/B) of the same color as the moved piece, in prev_board ---
    sliders_bb = (
        prev_board.pieces(chess.QUEEN, mover_color)
        | prev_board.pieces(chess.ROOK, mover_color)
        | prev_board.pieces(chess.BISHOP, mover_color)
    )

    for slider_sq in sliders_bb:
        sf = chess.square_file(slider_sq)
        sr = chess.square_rank(slider_sq)
        mf = chess.square_file(moved_from)
        mr = chess.square_rank(moved_from)

        dx = mf - sf
        dy = mr - sr

        # Must be collinear along rook/ bishop / queen directions
        if dx == 0 and dy != 0:
            step_f, step_r = 0, 1 if dy > 0 else -1
        elif dy == 0 and dx != 0:
            step_f, step_r = 1 if dx > 0 else -1, 0
        elif abs(dx) == abs(dy) and dx != 0:
            step_f = 1 if dx > 0 else -1
            step_r = 1 if dy > 0 else -1
        else:
            continue  # not on same file/rank/diagonal

        # --- 3) In prev_board: slider → ... → moved_from → ... → enemy target ---
        # First non-empty square along that ray must be moved_from.
        f = sf + step_f
        r = sr + step_r
        first_piece_sq = None

        while 0 <= f < 8 and 0 <= r < 8:
            sq = chess.square(f, r)
            p = prev_board.piece_at(sq)
            if p:
                first_piece_sq = sq
                break
            f += step_f
            r += step_r

        if first_piece_sq != moved_from:
            continue  # the moved piece was not the direct blocker

        # Now continue past moved_from to look for an enemy target
        f = mf + step_f
        r = mr + step_r
        target_sq = None
        target_piece = None

        while 0 <= f < 8 and 0 <= r < 8:
            sq = chess.square(f, r)
            p = prev_board.piece_at(sq)
            if p:
                if p.color == enemy:
                    target_sq = sq
                    target_piece = p
                break
            f += step_f
            r += step_r

        if target_sq is None:
            continue  # no enemy behind the blocker

        # --- 4) AFTER the move (current board), slider must actually attack target ---
        attackers_now = board.attackers(mover_color, target_sq)
        if slider_sq not in attackers_now:
            continue  # line is not really open in the current position

        # ✅ We have a REAL discovered attack produced by the last move
        motifs.append(
            make_motif(
                "discovered_attack",
                "Discovered Attack",
                EX_DISCOVERY_ATTACK,
                side=side_name(mover_color),
                severity="tactic",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={
                    "attacker": chess.square_name(slider_sq),
                    "blocker_moved_from": chess.square_name(moved_from),
                    "blocker_moved_to": chess.square_name(moved_to),
                    "target": chess.square_name(target_sq),
                    "target_piece": chess.piece_name(target_piece.piece_type)
                    if target_piece
                    else None,
                },
            )
        )

    return motifs






# -------------------------------
# DOUBLE CHECK
# -------------------------------

EX_DOUBLE_CHECK = (
    "Double Check – When two pieces place the opponent’s king into check."
)

def double_check(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def piece_sacrifice(
    board, prev_board, move_number, eval_cp,
    prev_eval=None, last_move_uci=None, **_
):
    motifs = []

    if not last_move_uci or prev_board is None:
        return motifs

    from_sq = chess.parse_square(last_move_uci[:2])
    to_sq   = chess.parse_square(last_move_uci[2:4])

    moved_piece = prev_board.piece_at(from_sq)

    # Only knights and bishops (the classic sacrificers)
    if not moved_piece or moved_piece.piece_type not in (chess.KNIGHT, chess.BISHOP):
        return motifs

    # Must be a capture
    if prev_board.piece_at(to_sq) is None:
        return motifs

    # Must be into enemy territory
    if moved_piece.color == chess.WHITE:
        if chess.square_rank(to_sq) < 4:
            return motifs
    else:
        if chess.square_rank(to_sq) > 3:
            return motifs

    # Now evaluate "hung-ness"
    attackers = len(board.attackers(not moved_piece.color, to_sq))
    defenders = len(board.attackers(moved_piece.color, to_sq))
    is_hanging = attackers > defenders

    # Must be a SOUND sacrifice (eval stays stable)
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    sound = abs(eval_delta) < 1.5  # tweakable

    if is_hanging and sound:
        motifs.append(
            make_motif(
                "sacrifice",
                "Sound Sacrifice",
                "A deliberate piece sacrifice to expose the king, destroy the pawn shield, or begin a forcing attack.",
                side=side_name(moved_piece.color),
                severity="tactical",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"square": chess.square_name(to_sq)},
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

def intermezzo(board, move_number, eval_cp, prev_eval=None, **kwargs):
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
    "Attraction – When a player lures an opponent’s king onto an exposed "
    "or tactically vulnerable square as part of a forcing combination."
)

EX_ATTRACTION = (
    "Attraction – When a player lures an opponent’s king onto an exposed "
    "or tactically vulnerable square as part of a forcing combination."
)

def attraction(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    prev_move_uci=None,
    **_,
):
    """
    Attraction — the king walks onto the very square where a piece was
    just sacrificed (typically Nxf7, Bxh7+, etc.), stepping into a
    tactically dangerous zone.

    Pattern:
      - Previous move: opponent moves a piece onto square X (often a sac).
      - Last move: king moves to the SAME square X and captures it.
    """
    motifs = []

    if not last_move_uci or not prev_move_uci or prev_board is None:
        return motifs

    # --- Last move: must be a king move ---
    k_from_str = last_move_uci[:2]
    k_to_str   = last_move_uci[2:4]

    k_from = chess.parse_square(k_from_str)
    k_to   = chess.parse_square(k_to_str)

    moved_piece = prev_board.piece_at(k_from)
    if not moved_piece or moved_piece.piece_type != chess.KING:
        return motifs

    king_color = moved_piece.color
    enemy_color = not king_color

    # --- Previous move: piece moved onto the SAME square the king just went to ---
    prev_to_str = prev_move_uci[2:4]
    if prev_to_str != k_to_str:
        return motifs

    prev_to = chess.parse_square(prev_to_str)
    sac_piece = prev_board.piece_at(prev_to)

    # Must actually be an enemy piece the king is capturing
    if not sac_piece or sac_piece.color != enemy_color:
        return motifs

    # Typical attraction: minor/heavy piece sacrifice (N, B, R, Q)
    if sac_piece.piece_type not in (
        chess.KNIGHT,
        chess.BISHOP,
        chess.ROOK,
        chess.QUEEN,
    ):
        return motifs

    # --- SUCCESS: king captured the last-moved attacking piece on that square ---
    motifs.append(
        make_motif(
            "attraction",
            "Attraction",
            "The king is pulled onto the square of a recent sacrifice, "
            "stepping into a tactically vulnerable zone where forcing "
            "moves (checks, forks, or mating nets) often follow.",
            side=side_name(enemy_color),  # side who *sacrificed* and lured the king
            severity="tactical",
            eval_cp=eval_cp,
            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            extra={
                "king_square": chess.square_name(k_to),
                "sacrificed_piece": chess.piece_name(sac_piece.piece_type),
                "sacrifice_square": chess.square_name(prev_to),
            },
        )
    )

    return motifs





# -------------------------------
# DEFLECTION
# -------------------------------

EX_DEFLECTION = (
    "Deflection – When a player disrupts an opponent’s piece from defending another piece via a sacrifice or forcing threat."
)

def deflection(board, move_number, eval_cp, prev_eval=None, **kwargs):
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

def clearance_sacrifice(board, move_number, eval_cp, prev_eval=None, **kwargs):
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


def xray(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    XRAY – valid only when a sliding piece (bishop, rook, queen)
    aims THROUGH a less valuable piece AT:
      - king
      - queen
      - rook
    Never fire for bishops xraying knights or pawns.
    """

    motifs = []

    # Define valid targets AND strictly require target_value > attacker_value
    high_value_targets = {
        chess.KING,
        chess.QUEEN,
        chess.ROOK
    }

    directions = [
        (1,0), (-1,0), (0,1), (0,-1),
        (1,1), (1,-1), (-1,1), (-1,-1)
    ]

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        # All sliding pieces
        sliders = (
            list(board.pieces(chess.ROOK, color)) +
            list(board.pieces(chess.BISHOP, color)) +
            list(board.pieces(chess.QUEEN, color))
        )

        for sq in sliders:
            attacker_piece = board.piece_at(sq)
            attacker_value = piece_value(attacker_piece.piece_type)

            for dx, dy in directions:
                f = chess.square_file(sq)
                r = chess.square_rank(sq)

                blocker_found = False

                nf, nr = f + dx, r + dy
                while 0 <= nf < 8 and 0 <= nr < 8:
                    target_sq = chess.square(nf, nr)
                    p = board.piece_at(target_sq)

                    # Nothing — keep scanning
                    if not p:
                        nf += dx
                        nr += dy
                        continue

                    # Friendly piece stops everything
                    if p.color == color:
                        break

                    # First enemy piece is a blocker unless it's the real target
                    if not blocker_found:
                        blocker_piece = p
                        blocker_found = True
                        nf += dx
                        nr += dy
                        continue

                    # Now p is the BACK piece (the real target)
                    target_piece = p

                    # 🔥 Apply new rules:
                    if (
                        target_piece.piece_type in high_value_targets and
                        piece_value(target_piece.piece_type) > attacker_value
                    ):
                        motifs.append(
                            make_motif(
                                "xray",
                                "XRAY / Potential Energy",
                                "A long-range piece is aligned through a blocker toward a major enemy piece.",
                                side=side_name(color),
                                severity="info",
                                extra={
                                    "attacker": chess.square_name(sq),
                                    "through": chess.square_name(blocker_piece),
                                    "target": chess.square_name(target_sq),
                                },
                            )
                        )

                    break  # stop after the second piece

    return motifs





EX_PUNISHED_F_PAWN = (
    "Deadly queen checks on h4 or h5 that can lead to center forks, trades on g3 or g6 given the f pawn was pushed "
    "(this motif could tie in with never push f7/f3), and subsequent mate on the diagonal or material win via a hanging rook."
)

def punished_f_pawn_queen_attack(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Detect patterns like 1.f3 e5 2.g4 Qh4# or similar queen raids
    exploiting an early f-pawn push and uncastled king.
    """
    motifs = []

    # We care about the side whose king is currently in danger
    # If not in check and eval hasn't swung a lot, skip.
    eval_delta = compute_eval_delta(prev_eval, eval_cp)
    if not board.is_check() and abs(eval_delta) < 150:
        return motifs

    # Side in check (or side that's clearly worse if not strictly in check)
    king_color = board.turn if board.is_check() else (chess.WHITE if eval_cp < -150 else chess.BLACK if eval_cp > 150 else None)
    if king_color is None:
        return motifs

    attacker = not king_color

    # Has the f-pawn of the king side moved off its starting square?
    f_start = chess.F2 if king_color == chess.WHITE else chess.F7
    f_start_piece = board.piece_at(f_start)
    if f_start_piece and f_start_piece.piece_type == chess.PAWN and f_start_piece.color == king_color:
        # f-pawn still on home square → not our pattern
        return motifs

    # Is the attacking queen posted on h4 or h5 (the classic refutation squares)?
    candidate_squares = {chess.H4, chess.H5}
    queen_sqs = list(board.pieces(chess.QUEEN, attacker))
    if not any(q in candidate_squares for q in queen_sqs):
        return motifs

    severity = "winning" if abs(eval_cp) >= 300 else "major"

    motifs.append(
        make_motif(
            "punished_f_pawn_queen_attack",
            "Punished f-pawn push",
            EX_PUNISHED_F_PAWN,
            side=side_name(attacker),
            severity=severity,
            eval_cp=eval_cp,
            eval_delta_cp=eval_delta,
        )
    )

    return motifs

def backward_pawn(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Detect backward pawns for each side, using a simple heuristic.
    """
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    for color in [chess.WHITE, chess.BLACK]:
        for sq in board.pieces(chess.PAWN, color):
            weakness = pawn_weakness_type(board, sq, color)
            if weakness == "backward":
                motifs.append(
                    make_motif(
                        "backward_pawn",
                        "Backward Pawn",
                        EX_BACKWARD_PAWN,
                        side=side_name(color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"square": chess.square_name(sq)},
                    )
                )
    return motifs

def minor_piece_vs_pawn_structure(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    **_
):
    """
    Minor Piece vs Pawn Structure Attack —
    Detects when a knight or bishop applies meaningful, *positional* pressure
    to a structurally weak pawn (isolated, backward, or undefended).

    This motif should NOT fire during tactical capture sequences.
    """

    motifs = []

    # Minor pieces we consider
    minor_types = (chess.KNIGHT, chess.BISHOP)

    # Identify weak pawns by structure (not tactics)
    def is_structurally_weak_pawn(board, sq, color):
        pawn = board.piece_at(sq)
        if not pawn or pawn.piece_type != chess.PAWN or pawn.color != color:
            return False

        files = chess.square_file(sq)
        rank = chess.square_rank(sq)

        # 1) Undefended pawn (positional weakness)
        if len(board.attackers(color, sq)) == 0:
            return True

        # 2) Isolated pawn (no pawn on adjacent files)
        neighbors = []
        if files > 0:
            neighbors.append(board.pieces(chess.PAWN, color) & chess.BB_FILES[files - 1])
        if files < 7:
            neighbors.append(board.pieces(chess.PAWN, color) & chess.BB_FILES[files + 1])

        if all(len(n) == 0 for n in neighbors):
            return True

        # 3) Backward pawn (cannot advance safely, cannot be defended by another pawn)
        # Very simplified but effective:
        pawn_dir = 1 if color == chess.WHITE else -1
        forward_sq = chess.square(files, rank + pawn_dir)
        if board.piece_at(forward_sq) is None:  # can advance
            # check control squares
            attackers = board.attackers(not color, forward_sq)
            defenders = board.attackers(color, forward_sq)
            if len(attackers) > len(defenders):
                return True

        return False

    # Loop over minor pieces applying pressure
    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        minors = (
            board.pieces(chess.KNIGHT, color)
            | board.pieces(chess.BISHOP, color)
        )

        for sq in minors:
            attacks = board.attacks(sq)
            for target in attacks:
                pawn = board.piece_at(target)
                if pawn and pawn.piece_type == chess.PAWN and pawn.color == enemy:

                    # Avoid tactical positions (e.g., immediate captures/exchanges)
                    if last_move_uci:
                        # If the square is in the middle of a tactical sequence, skip
                        if target == chess.parse_square(last_move_uci[2:4]):
                            continue

                    # Structural weakness only
                    if is_structurally_weak_pawn(board, target, enemy):
                        motifs.append(
                            make_motif(
                                "minor_piece_vs_pawn_structure",
                                "Minor Piece vs Pawn Structure Attack",
                                "A minor piece is applying long-term pressure "
                                "to a structurally weak pawn (undefended, isolated, or backward).",
                                side=side_name(color),
                                severity="info",
                                eval_cp=eval_cp,
                                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
                                extra={"piece": chess.square_name(sq),
                                       "pawn": chess.square_name(target)},
                            )
                        )

    return motifs



def skewer(board, move_number, eval_cp, prev_eval=None, **kwargs):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # Piece values
    value = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
        chess.KING: 100
    }

    rook_dirs = [(1,0),(-1,0),(0,1),(0,-1)]
    bishop_dirs = [(1,1),(1,-1),(-1,1),(-1,-1)]

    def dirs_for(piece_type):
        if piece_type == chess.ROOK:
            return rook_dirs
        if piece_type == chess.BISHOP:
            return bishop_dirs
        if piece_type == chess.QUEEN:
            return rook_dirs + bishop_dirs
        return []

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        sliders = (list(board.pieces(chess.ROOK, color)) +
                   list(board.pieces(chess.BISHOP, color)) +
                   list(board.pieces(chess.QUEEN, color)))

        for sq in sliders:
            p = board.piece_at(sq)
            dirs = dirs_for(p.piece_type)

            for dx, dy in dirs:
                path = []
                f, r = chess.square_file(sq), chess.square_rank(sq)

                nf, nr = f + dx, r + dy

                # collect up to two enemy pieces in the line direction
                while 0 <= nf < 8 and 0 <= nr < 8:
                    nsq = chess.square(nf, nr)
                    piece_on = board.piece_at(nsq)

                    if piece_on:
                        if piece_on.color == color:
                            break
                        path.append((nsq, piece_on))
                        if len(path) == 2:
                            break
                    nf += dx
                    nr += dy

                if len(path) != 2:
                    continue

                front_sq, front_piece = path[0]
                back_sq, back_piece = path[1]

                # skewer requires: front piece is MORE valuable target behind
                if value[front_piece.piece_type] >= value[back_piece.piece_type]:
                    continue

                # NEW: ensure front piece is ATTACKED by the slider
                if front_sq not in board.attackers(color, front_sq):
                    continue

                # NEW: ensure front piece is FORCED to move (undefended)
                defenders = board.attackers(enemy, front_sq)
                if len(defenders) > 0:
                    continue

                motifs.append(
                    make_motif(
                        "skewer",
                        "Skewer",
                        EX_SKEWER,
                        side=side_name(color),
                        severity="tactic",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={
                            "attacker": chess.square_name(sq),
                            "front": chess.square_name(front_sq),
                            "back": chess.square_name(back_sq),
                        },
                    )
                )

    return motifs


def battery(board, move_number, eval_cp, prev_eval=None, **kwargs):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # Only queen+rook, queen+bishop, rook+rook count
    def is_slider(pt):
        return pt in (chess.QUEEN, chess.ROOK, chess.BISHOP)

    # For each color
    for color in [chess.WHITE, chess.BLACK]:
        sliders = list(board.pieces(chess.QUEEN, color)) + \
                  list(board.pieces(chess.ROOK, color)) + \
                  list(board.pieces(chess.BISHOP, color))

        for sq in sliders:
            attacker = board.piece_at(sq)
            if not attacker:
                continue

            dirs = []
            if attacker.piece_type == chess.ROOK:
                dirs = [(1,0),(-1,0),(0,1),(0,-1)]
            elif attacker.piece_type == chess.BISHOP:
                dirs = [(1,1),(1,-1),(-1,1),(-1,-1)]
            elif attacker.piece_type == chess.QUEEN:
                dirs = [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]

            for dx,dy in dirs:
                f = chess.square_file(sq)
                r = chess.square_rank(sq)

                seen = []
                nf, nr = f+dx, r+dy
                while 0 <= nf < 8 and 0 <= nr < 8:
                    nsq = chess.square(nf, nr)
                    p = board.piece_at(nsq)
                    if p:
                        seen.append((nsq, p))
                        break
                    nf += dx
                    nr += dy

                # Need two pieces aligned: our slider + another heavy piece
                if len(seen) == 1:
                    nsq, p2 = seen[0]
                    if p2.color == color and is_slider(p2.piece_type):
                        # Extra condition: must point toward an enemy piece
                        # beyond, otherwise it's not a battery with purpose.
                        nf2, nr2 = nf + dx, nr + dy
                        has_target = False
                        while 0 <= nf2 < 8 and 0 <= nr2 < 8:
                            sq2 = chess.square(nf2, nr2)
                            t = board.piece_at(sq2)
                            if t and t.color != color:
                                has_target = True
                                break
                            nf2 += dx
                            nr2 += dy

                        if not has_target:
                            continue

                        motifs.append(
                            make_motif(
                                "battery",
                                "Battery",
                                EX_BATTERY,
                                side=side_name(color),
                                severity="info",
                                eval_cp=eval_cp,
                                eval_delta_cp=eval_delta,
                                extra={
                                    "front": chess.square_name(nsq),
                                    "back": chess.square_name(sq),
                                },
                            )
                        )

    return motifs



def early_queen_exposure(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Early Queen Exposure — queen moved out early and is being attacked, likely losing tempi.
    """
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    if move_number > MAX_OPENING_MOVE:
        return motifs  # only care in the opening

    for color in [chess.WHITE, chess.BLACK]:
        queens = list(board.pieces(chess.QUEEN, color))
        if not queens:
            continue
        qsq = queens[0]

        start_sq = chess.D1 if color == chess.WHITE else chess.D8
        if qsq == start_sq:
            continue  # still on home square, not 'early exposure'

        enemy = not color
        attackers = board.attackers(enemy, qsq)

        # Look for light piece / pawn attackers as a proxy for "being chased"
        chased = False
        for a_sq in attackers:
            p = board.piece_at(a_sq)
            if p and p.color == enemy and p.piece_type in (chess.PAWN, chess.KNIGHT, chess.BISHOP):
                chased = True
                break

        if not chased:
            continue

        motifs.append(
            make_motif(
                "early_queen_exposure",
                "Early Queen Exposure",
                EX_EARLY_QUEEN,
                side=side_name(color),
                severity="warning",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"queen_square": chess.square_name(qsq)},
            )
        )

    return motifs

def equal_trade(board, move_number, eval_cp, prev_eval=None, **kwargs):
    """
    Equal Trade – small change in evaluation after recent exchanges.
    Heuristic: if eval_delta is very small, we flag a likely equal trade.
    """
    motifs = []
    if prev_eval is None:
        return motifs

    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # Tiny eval swing → likely equal trade or quiet move
    if abs(eval_delta) <= 30:  # ~0.3 pawn
        motifs.append(
            make_motif(
                "equal_trade",
                "Equal Trade",
                EX_EQUAL_TRADE,
                side=None,
                severity="info",
                eval_cp=eval_cp,
                eval_delta_cp=eval_delta,
                extra={"eval_delta_cp": eval_delta},
            )
        )

    return motifs

def center_counterstrike(
    board, prev_board, move_number, eval_cp,
    prev_eval=None, last_move_uci=None, prev_move_uci=None, **_
):
    """
    Detects a central pawn counterstrike even if prev_move_uci is missing
    by inferring aggression from the previous board position.
    """

    motifs = []

    if not last_move_uci or prev_board is None:
        return motifs

    # ------------------------------
    # 1) Check last move was pawn → center
    # ------------------------------
    central_squares = {"d4", "d5", "e4", "e5"}
    moved_to = last_move_uci[2:4]

    if moved_to not in central_squares:
        return motifs

    moved_from = chess.parse_square(last_move_uci[:2])
    moved_piece = prev_board.piece_at(moved_from)

    if not moved_piece or moved_piece.piece_type != chess.PAWN:
        return motifs

    pawn_color = moved_piece.color
    enemy = not pawn_color

    # ------------------------------
    # 2) Detect aggressive N/B move directly from prev_board
    # ------------------------------
    aggressive_found = False

    for sq in prev_board.pieces(chess.KNIGHT, enemy) | \
                     prev_board.pieces(chess.BISHOP, enemy):

        rank = chess.square_rank(sq)

        # enemy pieces moved into our half?
        if enemy == chess.WHITE and rank >= 4:
            aggressive_found = True
            aggressor_sq = sq
            break

        if enemy == chess.BLACK and rank <= 3:
            aggressive_found = True
            aggressor_sq = sq
            break

    if not aggressive_found:
        return motifs

    # ------------------------------
    # 3) SUCCESS — create ONE motif
    # ------------------------------
    motifs.append(
        make_motif(
            "center_counterstrike",
            "Center Counterstrike",
            "A central pawn break challenges the advanced attacking piece and tries to seize the initiative back in the middle of the board.",
            side=side_name(pawn_color),
            severity="info",
            eval_cp=eval_cp,
            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            extra={
                "square": moved_to,
                "aggressor": chess.square_name(aggressor_sq),
            },
        )
    )

    return motifs




def defended_hanging_piece(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    sf_raw=None,
    **kwargs,
):
    """
    Defended Hanging Piece — a piece that was previously hanging
    (more attackers than defenders) is now adequately defended or the
    attacking pressure has been reduced so that defenders are at least
    equal to attackers.
    """
    motifs = []

    if prev_board is None:
        return motifs

    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    for sq, piece in board.piece_map().items():
        color = piece.color
        enemy = not color

        # Only consider pieces that were on the SAME square in the previous position
        prev_piece = prev_board.piece_at(sq)
        if not prev_piece or prev_piece.color != color:
            continue

        # Previous state
        prev_attackers = len(prev_board.attackers(enemy, sq))
        prev_defenders = len(prev_board.attackers(color, sq))

        # Current state
        attackers = len(board.attackers(enemy, sq))
        defenders = len(board.attackers(color, sq))

        was_hanging = prev_attackers > prev_defenders and prev_attackers > 0
        now_safe = attackers > 0 and defenders >= attackers

        if was_hanging and now_safe:
            motifs.append(
                make_motif(
                    "defended_hanging_piece",
                    "Defended Hanging Piece",
                    "A previously vulnerable piece is now adequately defended or the attacking pressure has been reduced.",
                    side=side_name(color),
                    severity="info",
                    eval_cp=eval_cp,
                    eval_delta_cp=eval_delta,
                    extra={"square": chess.square_name(sq)},
                )
            )

    return motifs


def bishop_diagonal_pressure(
    board, move_number, eval_cp, prev_eval=None, prev_board=None, **kwargs
):
    """
    Detects when a bishop moves onto a powerful diagonal:
    - aiming at f7 or f2
    - aiming toward the king’s future castling zone (g1, g8)
    """

    motifs = []

    # Must have a previous board to compare
    if prev_board is None:
        return motifs

    # Squares worth highlighting
    critical_squares = {
        chess.F7, chess.F2,        # classical weak points
        chess.G1, chess.G8,        # castling squares
        chess.H7, chess.H2,        # kingside structure
    }

    for color in [chess.WHITE, chess.BLACK]:
        enemy = not color

        # Find bishops that JUST MOVED
        prev_bishops = set(prev_board.pieces(chess.BISHOP, color))
        current_bishops = set(board.pieces(chess.BISHOP, color))

        moved_bishops = current_bishops - prev_bishops
        if not moved_bishops:
            continue

        for sq in moved_bishops:
            directions = [(1,1), (1,-1), (-1,1), (-1,-1)]
            for dx, dy in directions:
                f = chess.square_file(sq)
                r = chess.square_rank(sq)

                nf, nr = f + dx, r + dy
                while 0 <= nf < 8 and 0 <= nr < 8:
                    target = chess.square(nf, nr)

                    # If we hit ANY of our critical squares → motif
                    if target in critical_squares:
                        motifs.append(
                            make_motif(
                                "diagonal_pressure",
                                "Diagonal Pressure",
                                "A bishop has moved onto a lethal diagonal targeting the king’s castling zone or a weak square like f7/f2.",
                                side=side_name(color),
                                severity="info",
                                eval_cp=eval_cp,
                                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
                                extra={
                                    "bishop": chess.square_name(sq),
                                    "target": chess.square_name(target),
                                },
                            )
                        )
                    # stop scanning if any piece blocks
                    if board.piece_at(target):
                        break

                    nf += dx
                    nr += dy

    # ---------------------------------------
    # Remove duplicates safely
    # ---------------------------------------
    unique = {}
    for m in motifs:
        key = (m["name"], m["side"], m["extra"]["bishop"])
        if key not in unique:
            unique[key] = m

    return list(unique.values())



def interference(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    **kwargs,
):
    """
    Interference / Obstruction — a piece steps onto a line between an
    attacking slider (bishop/rook/queen) and a critical target
    (king or f2/f7), cutting off a key line of pressure or future
    tactic.
    """
    motifs = []

    if not last_move_uci or prev_board is None:
        return motifs

    from_sq = chess.parse_square(last_move_uci[:2])
    to_sq = chess.parse_square(last_move_uci[2:4])

    moved_piece = board.piece_at(to_sq)
    if not moved_piece:
        return motifs

    blocker_color = moved_piece.color

    def ray_between(a, b):
        """Return squares strictly between a and b if they are aligned along a rook/bishop line."""
        af, ar = chess.square_file(a), chess.square_rank(a)
        bf, br = chess.square_file(b), chess.square_rank(b)
        df, dr = bf - af, br - ar

        step_f = step_r = 0

        # Same file (vertical)
        if df == 0 and dr != 0:
            step_f = 0
            step_r = 1 if dr > 0 else -1
        # Same rank (horizontal)
        elif dr == 0 and df != 0:
            step_f = 1 if df > 0 else -1
            step_r = 0
        # Diagonal
        elif abs(df) == abs(dr) and df != 0:
            step_f = 1 if df > 0 else -1
            step_r = 1 if dr > 0 else -1
        else:
            return []

        squares = []
        f, r = af + step_f, ar + step_r
        while (f, r) != (bf, br):
            squares.append(chess.square(f, r))
            f += step_f
            r += step_r
        return squares

    # Look for sliders from the opposite color whose lines to critical
    # targets have just been blocked by the move to to_sq.
    for slider_color in (chess.WHITE, chess.BLACK):
        if slider_color == blocker_color:
            continue  # we care about the *attacker* being blocked

        sliders = (
            prev_board.pieces(chess.BISHOP, slider_color)
            | prev_board.pieces(chess.ROOK, slider_color)
            | prev_board.pieces(chess.QUEEN, slider_color)
        )

        enemy_king_sq = prev_board.king(blocker_color)
        critical_targets = []
        if enemy_king_sq is not None:
            critical_targets.append(enemy_king_sq)

        # f2/f7 weaknesses relative to the side that just blocked
        if blocker_color == chess.WHITE:
            critical_targets.append(chess.F2)
        else:
            critical_targets.append(chess.F7)

        for s in sliders:
            for tgt in critical_targets:
                if tgt is None:
                    continue

                between = ray_between(s, tgt)
                if not between:
                    continue

                # Was the line already blocked before? If yes, this is not a new obstruction.
                blocked_before = any(prev_board.piece_at(sq) for sq in between)
                if blocked_before:
                    continue

                # The moved piece must land somewhere strictly between slider and target
                if to_sq not in between:
                    continue

                # Slider must actually have been attacking the target before
                if not prev_board.is_attacked_by(slider_color, tgt):
                    continue

                # Destination square must have been empty before (so we truly introduce a block)
                if prev_board.piece_at(to_sq) is not None:
                    continue

                motifs.append(
                    make_motif(
                        "interference",
                        "Interference / Obstruction",
                        "A piece steps between an attacker and its target, cutting off a key line of pressure or future tactical idea.",
                        side=side_name(blocker_color),
                        severity="info",
                        eval_cp=eval_cp,
                        eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
                        extra={
                            "blocker": chess.square_name(to_sq),
                            "attacker": chess.square_name(s),
                            "target": chess.square_name(tgt),
                        },
                    )
                )

    return motifs

def fair_trade_sequence_start(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    last_move_uci=None,
    prev_move_uci=None,
    **_
):
    """
    Fair Trade Sequence Start —
    This motif triggers when a capture initiates a likely forcing sequence 
    of trades where neither side clearly wins material.

    Chess principle:
    Many tactical positions contain forcing sequences where exchanged pieces 
    are of equal value and the goal is not winning material, but removing 
    defenders, opening lines, or changing the pawn structure. Recognizing 
    these “fair trades” helps players avoid hallucinating advantages.
    """

    motifs = []

    if not last_move_uci or prev_board is None:
        return motifs

    # --- 1) It must be a capture ---
    from_sq = chess.parse_square(last_move_uci[:2])
    to_sq = chess.parse_square(last_move_uci[2:4])

    moved_piece = prev_board.piece_at(from_sq)
    captured_piece = prev_board.piece_at(to_sq)

    if not moved_piece or not captured_piece:
        return motifs  # Not a capture

    # --- 2) Material must be roughly equal ---
    v_move = piece_value(moved_piece.piece_type)
    v_cap = piece_value(captured_piece.piece_type)

    if v_move != v_cap:
        return motifs  # If unequal, it's a gain/loss motif, not fair trade

    # --- 3) Must be recapturable immediately ---
    enemy_color = not moved_piece.color
    enemy_attackers = list(board.attackers(enemy_color, to_sq))
    our_defenders = list(board.attackers(moved_piece.color, to_sq))

    # Need both sides to attack the square
    if len(enemy_attackers) == 0 or len(our_defenders) == 0:
        return motifs

    # --- 4) Avoid repeated triggers inside same sequence ---
    # If previous move was ALSO a capture of equal material, skip.
    if prev_move_uci:
        prev_from = chess.parse_square(prev_move_uci[:2])
        prev_to = chess.parse_square(prev_move_uci[2:4])
        prev_cap = prev_board.piece_at(prev_to)
        if prev_cap:
            prev_piece = prev_board.piece_at(prev_from)
            if prev_piece and piece_value(prev_piece.piece_type) == piece_value(prev_cap.piece_type):
                return motifs  # already inside trade sequence

    # --- SUCCESS: A new fair trade sequence has just begun ---
    motifs.append(
        make_motif(
            "fair_trade_sequence_start",
            "Fair Trade Sequence Start",
            "A capture has begun a forcing sequence of exchanges where neither side "
            "is expected to win material. These sequences often aim to open lines, "
            "remove defenders, or simplify the position without changing the material balance.",
            side=side_name(moved_piece.color),
            severity="info",
            eval_cp=eval_cp,
            eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            extra={
                "capturing_piece": chess.square_name(from_sq),
                "captured_piece": chess.square_name(to_sq),
                "material_value": v_cap,
            },
        )
    )

    return motifs

# ----------------------------------------------------------
# ABSOLUTE PIN  (pinned to the KING)
# ----------------------------------------------------------

def absolute_pin(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    **_,
):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    for color in (chess.WHITE, chess.BLACK):
        king_sq = board.king(color)
        if king_sq is None:
            continue

        # All pieces except the king can be pinned
        for sq, piece in board.piece_map().items():
            if piece.color != color or piece.piece_type == chess.KING:
                continue

            if board.is_pinned(color, sq):
                motifs.append(
                    make_motif(
                        "absolute_pin",
                        "Absolute Pin",
                        EX_ABSOLUTE_PIN,
                        side=side_name(color),
                        severity="tactical",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={
                            "pinned_piece": chess.square_name(sq),
                            "king": chess.square_name(king_sq),
                        },
                    )
                )

    return motifs

# ----------------------------------------------------------
# RELATIVE PIN (pinned to a more valuable piece, not the king)
# ----------------------------------------------------------

def relative_pin(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    **_,
):
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    # sliding attackers
    sliders = {
        chess.BISHOP: [(1,1),(1,-1),(-1,1),(-1,-1)],
        chess.ROOK:   [(1,0),(-1,0),(0,1),(0,-1)],
        chess.QUEEN:  [(1,1),(1,-1),(-1,1),(-1,-1),(1,0),(-1,0),(0,1),(0,-1)],
    }

    for enemy_color in (chess.WHITE, chess.BLACK):
        own_color = not enemy_color

        for sq in (
            board.pieces(chess.BISHOP, enemy_color)
            | board.pieces(chess.ROOK, enemy_color)
            | board.pieces(chess.QUEEN, enemy_color)
        ):
            attacker = board.piece_at(sq)
            dirs = sliders[attacker.piece_type]

            for dx, dy in dirs:
                f = chess.square_file(sq)
                r = chess.square_rank(sq)

                blockers = []
                behind = None

                nf = f + dx
                nr = r + dy

                while 0 <= nf < 8 and 0 <= nr < 8:
                    nsq = chess.square(nf, nr)
                    p = board.piece_at(nsq)

                    if p:
                        if p.color == own_color:
                            if not blockers:
                                blockers.append((nsq, p))  # first friendly = candidate pinned piece
                            else:
                                # second friendly piece = higher value target (maybe)
                                behind = (nsq, p)
                            break
                        else:
                            break  # enemy piece blocks
                    nf += dx
                    nr += dy

                # Did we find exactly one friendly blocker and a valuable friendly piece behind it?
                if blockers and behind:
                    block_sq, block_piece = blockers[0]
                    behind_sq, behind_piece = behind

                    # must be pinned to a more valuable piece (not king)
                    if behind_piece.piece_type != chess.KING and \
                       piece_value(behind_piece.piece_type) > piece_value(block_piece.piece_type):

                        motifs.append(
                            make_motif(
                                "relative_pin",
                                "Relative Pin",
                                EX_RELATIVE_PIN,
                                side=side_name(own_color),
                                severity="info",
                                eval_cp=eval_cp,
                                eval_delta_cp=eval_delta,
                                extra={
                                    "pinned_piece": chess.square_name(block_sq),
                                    "valuable_piece": chess.square_name(behind_sq),
                                    "attacker": chess.square_name(sq),
                                },
                            )
                        )

    return motifs

def fork_general(
    board,
    prev_board,
    move_number,
    eval_cp,
    prev_eval=None,
    **_,
):
    """
    General fork detection (non-knight forks).
    Detects queen, rook, bishop, pawn, king forks.

    Key patterns:
      - checking + attacking a valuable piece = fork
      - OR attacking 2+ valuable pieces simultaneously
    """
    motifs = []
    eval_delta = compute_eval_delta(prev_eval, eval_cp)

    for color in (chess.WHITE, chess.BLACK):
        enemy = not color

        for sq, piece in board.piece_map().items():
            if piece.color != color:
                continue
            if piece.piece_type == chess.KNIGHT:
                continue  # handled by your original fork()

            attacks = board.attacks(sq)

            king_attacked = False
            valuable_count = 0

            for t in attacks:
                p = board.piece_at(t)
                if not p or p.color != enemy:
                    continue

                if p.piece_type == chess.KING:
                    king_attacked = True
                elif p.piece_type in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                    valuable_count += 1

            # Fork conditions
            if king_attacked and valuable_count >= 1:
                motifs.append(
                    make_motif(
                        "fork",
                        "Fork",
                        EX_FORK,
                        side=side_name(color),
                        severity="tactical",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"forking_piece": chess.square_name(sq)},
                    )
                )

            elif valuable_count >= 2:
                motifs.append(
                    make_motif(
                        "fork",
                        "Fork",
                        EX_FORK,
                        side=side_name(color),
                        severity="tactical",
                        eval_cp=eval_cp,
                        eval_delta_cp=eval_delta,
                        extra={"forking_piece": chess.square_name(sq)},
                    )
                )

    return motifs


# -------------------------
# Main dispatcher
# -------------------------

MOTIF_FUNCTIONS = [

    # --- DEVELOPMENT / KING SAFETY / STRUCTURAL ---
    development_lead,
    king_safety_lag,
    open_file_control,
    semi_open_file,
    bishop_pair,
    bad_good_bishop,
    isolated_pawn,
    doubled_pawns,
    backward_pawn,
    passed_pawn,
    pawn_majority,
    weak_square,                          # FIXED + early-game noise reduced
    outpost,

    # --- PAWN STRUCTURE TARGETING ---
    

    # --- CORE TACTICAL MOTIFS ---
    hanging_piece,
    defended_hanging_piece,               # NEW
    fork,
    skewer,
    battery,
    xray,
    discovered_attack,
    double_check,

    # --- TRADE / MATERIAL / STRATEGIC ---
    equal_trade,
    minor_piece_trapped,
    knight_on_rim,
    f2_f7_weakness,
    c2_c7_weakness,

    # --- CENTER CONTROL (ordering matters: take_center must fire BEFORE meet_center) ---
    take_the_center,
    meet_the_center,                # NEW

    # --- QUEEN / ROOK / KING-TYPE CONCEPTS ---
    early_queen_exposure,
    never_push_f_pawn,
    connect_the_rooks,
    opposite_side_castling,

    # --- ADVANCED TACTICS ---
    piece_sacrifice,
    intermezzo,
    attraction,
    deflection,
    clearance_sacrifice,
    minority_attack_setup,                # more structural/rare
    punished_f_pawn_queen_attack,
    bishop_diagonal_pressure,
    center_counterstrike,
    interference,
    fair_trade_sequence_start,
    absolute_pin,
    relative_pin,
    fork_general,

]




def detect_motifs(
    board: chess.Board,
    prev_board=None,            # <--- NEW
    move_number: int = None,
    eval_cp=None,
    prev_eval=None,
    sf_raw=None,
    last_move_uci=None,
    prev_move_uci=None,
):
    """
    Central entry point for all motif detection.
    Pure pattern-based (no move-number gating), with mate override.
    Passes last/prev move UCI and PV list reliably.
    """
    motifs = []

    # ---- Extract PV from sf_raw if available ----
    sf_pv = []
    if sf_raw and isinstance(sf_raw, dict):
        sf_pv = sf_raw.get("pv", []) or []

    # 🔥 IMPORTANT: prefer the explicit arguments FROM app.py
    last_uci = last_move_uci or getattr(board, "last_move_uci", None)
    prev_uci = prev_move_uci or getattr(board, "prev_move_uci", None)

    # ---------------------------------------------------
    # 0. FORCED MATE OVERRIDE — highest priority
    # ---------------------------------------------------
    if sf_raw and sf_raw.get("type") == "mate":
        mate_val = sf_raw.get("value", 0)
        side = "white" if mate_val > 0 else "black"
        n = abs(mate_val)

        motifs.append(
            make_motif(
                "forced_mate",
                f"Forced Mate in {n}",
                f"There is a forced checkmate in {n} moves for {side}. "
                "All other strategic motifs are irrelevant when a forced win is on the board.",
                side=side,
                severity="critical",
                eval_cp=eval_cp,
                eval_delta_cp=compute_eval_delta(prev_eval, eval_cp),
            )
        )
        return motifs  # STOP — tactical override

    # ---------------------------------------------------
    # 1. NORMAL MOTIF DISPATCH
    # ---------------------------------------------------
    for fn in MOTIF_FUNCTIONS:
        try:
            res = fn(
                board=board,
                prev_board=prev_board,    # <--- NEW
                move_number=move_number,
                eval_cp=eval_cp,
                prev_eval=prev_eval,
                sf_raw=sf_raw,
                pv=sf_pv,
                last_move_uci=last_uci,
                prev_move_uci=prev_uci,
            )

            if res:
                motifs.extend(res)

        except Exception:
            continue  # fail silently per motif

    return motifs


