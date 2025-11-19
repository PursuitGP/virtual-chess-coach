# app.py
import io
import os
import chess.pgn
import requests
from functools import lru_cache
from flask import Flask, request, jsonify
from flask_cors import CORS
from stockfish import Stockfish
from multiprocessing import Pool, cpu_count
from concurrent.futures import ThreadPoolExecutor
from motifs import detect_motifs

app = Flask(__name__)
CORS(app)

# Detect platform and choose correct Stockfish binary path
if os.name == "nt":
    # WINDOWS
    STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish.exe")
elif os.path.exists("/opt/homebrew/bin/stockfish"):
    # MAC (M1/M2)
    STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
elif os.path.exists("/usr/bin/stockfish"):
    # LINUX
    STOCKFISH_PATH = "/usr/bin/stockfish"
else:
    raise FileNotFoundError("Could not find Stockfish binary for your system.")

executor = ThreadPoolExecutor(max_workers=2)

def get_fresh_engine():
    """Create a fresh Stockfish instance for each process."""
    return Stockfish(path=STOCKFISH_PATH, depth=18)

def evaluate_fen(fen):
    """Worker function for multiprocessing — runs one Stockfish eval."""
    try:
        engine = get_fresh_engine()
        engine.set_fen_position(fen)
        info = engine.get_evaluation()

        if info["type"] == "cp":
            score = info["value"] / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"
        else:
            eval_str = f"Mate in {info['value']}"
            score = 10 if info["value"] > 0 else -10

        return {
            "fen": fen,
            "score": score,
            "eval": eval_str,
            "best_move": engine.get_best_move(),
        }
    except Exception as e:
        return {"fen": fen, "error": str(e)}

# ----------------------
# Lichess Opening Explorer integration
# ----------------------
# We'll use the public explorer endpoints hosted at explorer.lichess.ovh
# We cache responses heavily to avoid rate limits and repeated work.

LICHESS_BASE = "https://explorer.lichess.ovh"
MIN_GAMES_THRESHOLD = 500  # reliability threshold (per your request)
TOP_N = 3  # top 3 moves for masters and players
REQUEST_TIMEOUT = 5  # seconds for each HTTP request

# Simple lru cache (in-memory). For a production app you'd want redis or memcached.
@lru_cache(maxsize=10000)
def fetch_lichess_explorer(fen: str, db: str = "masters", play: str = None, rating: str = None):
    """
    Fetch opening explorer data from explorer.lichess.ovh.
    db: 'masters' (top masters), 'lichess' (lichess db), or 'player' (player db)
    play: comma-separated UCI moves to play from the fen (for continuations)
    rating: string like '1600-2000' for rating filter (optional)
    """
    endpoint_map = {
        "masters": "/masters",
        "lichess": "/lichess",
        "player": "/player"
    }
    endpoint = endpoint_map.get(db, "/masters")
    url = f"{LICHESS_BASE}{endpoint}"
    params = {"fen": fen}
    if play:
        # the API accepts a 'play' query param with comma-separated UCIs
        params["play"] = play
    if rating:
        # player endpoint may accept rating groups; pass through if provided
        params["ratings"] = rating

    try:
        resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
        else:
            # non-200 -> return empty structure
            return {}
    except Exception:
        # network error or timeout -> return empty
        return {}

def summarize_move_entry(entry, total_games):
    """
    Normalize a move entry from the Lichess response into our small dict.
    entry: { 'uci': 'e2e4', 'san': 'e4', 'white': X, 'black': Y, 'draws': Z, 'averageRating': R }
    """
    if not entry:
        return None
    played = entry.get("white", 0) + entry.get("black", 0) + entry.get("draws", 0)
    popularity = 0.0
    if total_games and total_games > 0:
        popularity = played / total_games * 100.0
    total_outcomes = played if played > 0 else 1
    white_win_rate = entry.get("white", 0) / total_outcomes * 100.0
    black_win_rate = entry.get("black", 0) / total_outcomes * 100.0
    draw_rate = entry.get("draws", 0) / total_outcomes * 100.0
    return {
        "uci": entry.get("uci"),
        "san": entry.get("san"),
        "played": played,
        "popularity_pct": round(popularity, 2),
        "white_win_pct": round(white_win_rate, 2),
        "black_win_pct": round(black_win_rate, 2),
        "draw_pct": round(draw_rate, 2),
        "avg_rating": entry.get("averageRating")
    }

def get_top_moves_with_continuations(fen: str, db: str = "masters", top_n: int = TOP_N):
    """
    Returns top_n moves for the given fen from the specified db (masters/lichess/player).
    Also fetches a one-ply continuation for each top move (Option B).
    Output:
    {
      "total_games": N,
      "moves": [ { ... summarized move ... , "continuation": [ { ... } ] }, ... ],
      "reliable": True/False
    }
    """
    data = fetch_lichess_explorer(fen, db=db)
    moves = data.get("moves", []) if isinstance(data, dict) else []
    # compute total games at this node from sum of move counts
    total_games = sum((m.get("white", 0) + m.get("black", 0) + m.get("draws", 0)) for m in moves) or data.get("totalGames", 0) or 0
    results = []
    # take top_n moves (they are usually ordered)
    for m in moves[:top_n]:
        summary = summarize_move_entry(m, total_games)
        # fetch continuation: call the same endpoint but with play=<uci>
        cont_data = fetch_lichess_explorer(fen, db=db, play=m.get("uci"))
        cont_moves = cont_data.get("moves", []) if isinstance(cont_data, dict) else []
        # pick top continuation SANs (we'll include up to top_n next moves, simplified)
        cont_summaries = [summarize_move_entry(cm, sum((c.get("white",0)+c.get("black",0)+c.get("draws",0)) for c in cont_moves) or 1) for cm in cont_moves[:top_n]]
        summary["continuation"] = cont_summaries
        results.append(summary)
    reliable = total_games >= MIN_GAMES_THRESHOLD
    return {"total_games": total_games, "moves": results, "reliable": reliable}

# ----------------------
# Helper to compute deviation and produce theory object
# ----------------------
def compute_theory_deviation(fen: str, last_move_uci: str):
    """
    Query masters and lichess/player dbs and compute:
    - top 3 master moves (with continuation)
    - top 3 player moves (with continuation)
    - if the last_move_uci is in the top master moves (i.e., is book)
    - return 'theory' dict to embed into each move result
    """
    masters = get_top_moves_with_continuations(fen, db="masters", top_n=TOP_N)
    players = get_top_moves_with_continuations(fen, db="lichess", top_n=TOP_N)  # lichess endpoint aggregates all lichess games

    masters_uci_list = [m["uci"] for m in masters["moves"] if m and m.get("uci")]
    players_uci_list = [m["uci"] for m in players["moves"] if m and m.get("uci")]

    is_theory_move = last_move_uci in masters_uci_list
    # severity heuristics: not in masters & low popularity or small master sample -> major
    severity = "none"
    if not is_theory_move:
        # if masters total games < threshold => mark 'unknown' (because masters database is small)
        if not masters["reliable"]:
            severity = "unknown-reliability"
        else:
            # find popularity among masters
            popularity = 0.0
            for m in masters["moves"]:
                if m["uci"] == last_move_uci:
                    popularity = m.get("popularity_pct", 0.0)
                    break
            if popularity == 0.0:
                severity = "major-deviance"
            elif popularity < 5.0:
                severity = "minor-deviance"
            else:
                severity = "moderate-deviance"
    else:
        severity = "in-book"

    return {
        "masters": masters,
        "players": players,
        "is_in_masters_top": is_theory_move,
        "severity": severity
    }

# ----------------------
# Main Flask endpoints (modified evaluate_pgn to include Lichess data)
# ----------------------
@app.route("/api/evaluate_pgn", methods=["POST"])
def evaluate_pgn():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    pgn_text = file.read().decode("utf-8")

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        board = game.board()

        # Collect up to first 10 move FENs + last-move ucis (MVP limit)
        fens = []
        last_move_uci_list = []
        for i, move in enumerate(game.mainline_moves()):
            if i >= 10:
                break
            board.push(move)
            fens.append(board.fen())
            last_move_uci_list.append(move.uci())

        # If no moves (empty PGN), return early
        if not fens:
            return jsonify({"count": 0, "evaluations": []})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # -----------------------------
    # 1) Run Stockfish evaluations in parallel (workers do only SF eval)
    # -----------------------------
    with Pool(processes=max(1, cpu_count() - 1)) as pool:
        results = pool.map(evaluate_fen, fens)

    # -----------------------------
    # 2) Post-process results in main process
    # -----------------------------
    prev_eval = None
    analysis_board = game.board()  # fresh board to set_fen for each position

    for i, r in enumerate(results):
        r["move_number"] = i + 1

        fen = r.get("fen")
        numeric_eval = None
        if "score" in r and isinstance(r["score"], (int, float)):
            numeric_eval = r["score"] * 100

        # prepare analysis board and attach last_move_uci
        try:
            analysis_board.set_fen(fen)
        except Exception:
            analysis_board = chess.Board(fen)

        analysis_board.last_move_uci = last_move_uci_list[i] if i < len(last_move_uci_list) else None

        # Run motif detection
        try:
            motifs = detect_motifs(
                analysis_board,
                move_number=i + 1,
                eval=numeric_eval if numeric_eval is not None else 0,
                prev_eval=prev_eval
            )
        except Exception as e:
            motifs = {"error": f"motif detection error: {str(e)}"}

        r["motifs"] = motifs
        r["eval_delta"] = None if prev_eval is None or numeric_eval is None else numeric_eval - prev_eval

        # Lichess theory deviation
        try:
            theory = compute_theory_deviation(fen, analysis_board.last_move_uci)
            r["lichess"] = {
                "masters": theory.get("masters"),
                "players": theory.get("players"),
                "is_in_masters_top": theory.get("is_in_masters_top"),
                "severity": theory.get("severity")
            }
        except Exception as e:
            r["lichess"] = {"error": f"lichess fetch error: {str(e)}"}

        if numeric_eval is not None:
            prev_eval = numeric_eval

    return jsonify({"count": len(results), "evaluations": results})



@app.route("/api/coach", methods=["POST"])
def analyze_position():
    """Single FEN evaluation — used for live board updates."""
    data = request.get_json()
    if not data or "fen" not in data:
        return jsonify({"error": "Missing FEN"}), 400

    fen = data["fen"]

    def run_stockfish_eval(fen):
        engine = get_fresh_engine()
        engine.set_fen_position(fen)
        return engine.get_evaluation()

    try:
        # Run asynchronously in thread executor
        future = executor.submit(run_stockfish_eval, fen)
        evaluation = future.result(timeout=2)

        if evaluation["type"] == "cp":
            score = evaluation["value"] / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"
        else:
            eval_str = f"Mate in {evaluation['value']}"

        stockfish = get_fresh_engine()
        stockfish.set_fen_position(fen)
        best_move = stockfish.get_best_move()

        # Attach lichess masters / players top moves for this single fen
        try:
            masters = get_top_moves_with_continuations(fen, db="masters", top_n=TOP_N)
            players = get_top_moves_with_continuations(fen, db="lichess", top_n=TOP_N)
            theory = {
                "masters": masters,
                "players": players,
                "is_in_masters_top": False  # can't check "last_move" here (no last_move provided)
            }
        except Exception:
            theory = {"error": "lichess fetch failed"}

        return jsonify({
            "eval": eval_str,
            "numeric_eval": evaluation["value"],
            "best_move": best_move,
            "ideas": [
                f"Stockfish suggests {best_move} as the best move.",
                "Keep your pieces active and king safe.",
                "Look for tactical opportunities."
            ],
            "lichess": theory
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/api/motifs", methods=["POST"])
def motifs_endpoint():
    """
    Minimal poster endpoint for frontend testing.
    Accepts JSON: { "fen": "<FEN string>" }
    Returns: { "motifs": [...] }
    """
    data = request.get_json() or {}
    fen = data.get("fen")
    if not fen:
        return jsonify({"error": "Missing fen"}), 400
    try:
        board = chess.Board(fen)
        # Use minimal placeholders for move_number/eval/prev_eval so motifs work.
        motifs = detect_motifs(board, move_number=0, eval=0, prev_eval=None)
        return jsonify({"motifs": motifs})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Run the app
    app.run(host="127.0.0.1", port=5000, debug=True)
    
