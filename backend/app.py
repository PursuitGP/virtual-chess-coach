# app.py (improved, replace your existing file with this)
from dotenv import load_dotenv
load_dotenv()
import io
import os
import logging
import chess.pgn
import requests
from functools import lru_cache
from flask import Flask, request, jsonify
from flask_cors import CORS
from stockfish import Stockfish
from multiprocessing import Pool, cpu_count
from concurrent.futures import ThreadPoolExecutor
from motifs import detect_motifs
import google.generativeai as genai
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

for m in genai.list_models():
    print(m.name, m.supported_generation_methods)

# Load from .env
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

GEMINI_MODEL = genai.GenerativeModel("gemini-2.5-flash")


# ---------- basic logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

app = Flask(__name__)
CORS(app)

# Detect platform and choose correct Stockfish binary path
if os.name == "nt":
    # WINDOWS
    STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish.exe")
elif os.path.exists("/opt/homebrew/bin/stockfish"):
    # MAC (M1/M2/M4)
    STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
elif os.path.exists("/usr/bin/stockfish"):
    # LINUX
    STOCKFISH_PATH = "/usr/bin/stockfish"
else:
    raise FileNotFoundError("Could not find Stockfish binary for your system.")

executor = ThreadPoolExecutor(max_workers=2)

def get_fresh_engine():
    """Create a fresh Stockfish instance for each worker/thread."""
    try:
        return Stockfish(path=STOCKFISH_PATH, depth=18)
    except Exception as e:
        logging.exception("Stockfish engine creation failed")
        raise

def evaluate_fen(fen):
    """
    Evaluate a FEN using Stockfish and return:
    - type: "cp" or "mate"
    - value: centipawns or mate-number
    - score (frontend numeric)
    - eval_str ("+0.52", "-M3")
    - pv: principal variation list
    """

    try:
        engine = get_fresh_engine()
        engine.set_fen_position(fen)

        # FULL INFO FOR MOTIF ENGINE & FRONTEND
        raw_eval = engine.get_evaluation()      # {"type": "cp", "value": X}
        try:
            info = engine.get_top_moves(3)      # each: {'Move': 'e2e4', 'Centipawn': 23}
            pv = [m["Move"] for m in info] if info else []
        except:
            pv = []

        if raw_eval["type"] == "cp":
            cp = raw_eval["value"]
            score = cp / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"

        elif raw_eval["type"] == "mate":
            m = raw_eval["value"]         # mate distance
            side = "white" if m > 0 else "black"
            score = 10 if m > 0 else -10
            eval_str = f"{'-' if m < 0 else ''}M{abs(m)}"

        else:
            cp = 0
            score = 0
            eval_str = "0.00"

        # Best move
        try:
            best_move = engine.get_best_move()
        except:
            best_move = None

# ---- INSERT THIS EXACTLY HERE ----
# PV LIST FIX
        try:
            info = engine.get_top_moves(3)
            pv_list = [m["Move"] for m in info] if info else []
        except:
            pv_list = []
# ----------------------------------

    
        return {
            "fen": fen,
            "sf_raw": raw_eval,
            "pv": pv_list if pv_list else pv,  # <-- safest option
            "score": score,
            "eval": eval_str,
            "best_move": best_move,
        }


    except Exception as e:
        logging.exception("eval failed")
        return {"fen": fen, "error": str(e)}


# ----------------------
# Lichess Opening Explorer integration (robust)
# ----------------------
LICHESS_BASE = "https://explorer.lichess.ovh"
MIN_GAMES_THRESHOLD = 20   # lowered for openings; adjust as you want
TOP_N = 2                  # top 2 moves (per your request)
REQUEST_TIMEOUT = 5        # seconds for each HTTP request
MAX_RETRIES = 2

# Use a single session for benefit of connection pooling
session = requests.Session()
session.headers.update({
    "User-Agent": "VirtualChessCoach/1.0 (+https://example.local)",
    "Accept": "application/json"
})

@lru_cache(maxsize=10000)
def fetch_lichess_explorer(fen: str, db: str = "masters", play: str = None, rating: str = None):
    """
    Fetch opening explorer data from explorer.lichess.ovh with simple retry/backoff.
    Returns a dict (or empty dict on failure).
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
        params["play"] = play
    if rating:
        params["ratings"] = rating

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    logging.warning("Non-JSON response from lichess explorer for fen=%s db=%s", fen, db)
                    return {}
            else:
                logging.warning("Lichess explorer returned status %s for fen=%s db=%s", resp.status_code, fen, db)
                # small backoff
                if attempt < MAX_RETRIES:
                    continue
                return {}
        except requests.RequestException as e:
            logging.warning("Lichess explorer request exception (attempt %d): %s", attempt, str(e))
            if attempt < MAX_RETRIES:
                continue
            return {}
    return {}

def summarize_move_entry(entry, total_games):
    if not entry:
        return None
    played = entry.get("white", 0) + entry.get("black", 0) + entry.get("draws", 0)
    total_games = total_games or 1
    popularity = (played / total_games * 100.0) if total_games > 0 else 0.0
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
    Returns top_n moves for the given fen from the specified db and one-ply continuation summaries.
    """
    data = fetch_lichess_explorer(fen, db=db)
    if not isinstance(data, dict):
        data = {}

    moves = data.get("moves", []) or []
    # compute total games at this node from data if possible
    total_games = 0
    try:
        # each move has counts; fallback to data['totalGames']
        total_games = sum((m.get("white", 0) + m.get("black", 0) + m.get("draws", 0)) for m in moves) or data.get("totalGames", 0) or 0
    except Exception:
        total_games = data.get("totalGames", 0) or 0

    results = []
    for m in moves[:top_n]:
        try:
            summary = summarize_move_entry(m, total_games)
            # fetch continuation (one-ply deeper) using play param (uci string)
            cont_data = fetch_lichess_explorer(fen, db=db, play=m.get("uci"))
            cont_moves = (cont_data.get("moves", []) if isinstance(cont_data, dict) else []) or []
            cont_tot = sum((c.get("white",0)+c.get("black",0)+c.get("draws",0)) for c in cont_moves) or 1
            cont_summaries = [summarize_move_entry(cm, cont_tot) for cm in cont_moves[:top_n]]
            summary["continuation"] = cont_summaries
            results.append(summary)
        except Exception:
            logging.exception("Error summarizing move from lichess data")
            continue

    reliable = total_games >= MIN_GAMES_THRESHOLD
    return {"total_games": total_games, "moves": results, "reliable": reliable}

def compute_theory_deviation(fen: str, last_move_uci: str):
    """
    Query masters and lichess/player dbs and compute a small theory object.
    """
    masters = get_top_moves_with_continuations(fen, db="masters", top_n=TOP_N)
    players = get_top_moves_with_continuations(fen, db="lichess", top_n=TOP_N)

    masters_uci_list = [m.get("uci") for m in masters.get("moves", []) if m and m.get("uci")]
    players_uci_list = [m.get("uci") for m in players.get("moves", []) if m and m.get("uci")]

    is_theory_move = last_move_uci in masters_uci_list if last_move_uci else False

    severity = "none"
    if not is_theory_move:
        if not masters.get("reliable", False):
            severity = "unknown-reliability"
        else:
            popularity = 0.0
            for m in masters.get("moves", []):
                if m.get("uci") == last_move_uci:
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
# Main Flask endpoints
# ----------------------
@app.route("/api/evaluate_pgn", methods=["POST"])
def evaluate_pgn():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    try:
        pgn_text = file.read().decode("utf-8")
    except Exception:
        pgn_text = file.read().decode(errors="ignore")

    # -----------------------------
    # Parse PGN
    # -----------------------------
    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        if game is None:
            return jsonify({"error": "Could not parse PGN"}), 400

        board = game.board()
        MAX_FULLMOVES = 10

        fens = []
        last_move_uci_list = []

        for move in game.mainline_moves():
            board.push(move)
            fens.append(board.fen())
            last_move_uci_list.append(move.uci())

            if board.fullmove_number > MAX_FULLMOVES:
                break

        if not fens:
            return jsonify({"count": 0, "evaluations": []})

    except Exception as e:
        logging.exception("PGN parsing failed")
        return jsonify({"error": str(e)}), 500

    # -----------------------------
    # Evaluate positions with Stockfish
    # -----------------------------
    try:
        with Pool(processes=max(1, cpu_count() - 1)) as pool:
            results = pool.map(evaluate_fen, fens)
    except Exception:
        logging.exception("Parallel Stockfish evaluation failed, falling back to sequential")
        results = [evaluate_fen(f) for f in fens]

    # -----------------------------
    # Post-processing + motif detection
    # -----------------------------
    prev_eval = None
    analysis_board = game.board()

    for i, r in enumerate(results):
        r["move_number"] = i + 1
        fen = r.get("fen")

        # Numeric eval → cp
        numeric_eval = None
        if isinstance(r.get("score"), (int, float)):
            numeric_eval = int(r["score"] * 100)

        # CAPTURE moves BEFORE set_fen()
        # Correct move wiring
        current_uci = last_move_uci_list[i] if i < len(last_move_uci_list) else None
        prev_uci = last_move_uci_list[i-1] if i > 0 else None
        prev_board = analysis_board.copy()



        # Load FEN (clears history)
        try:
            analysis_board.set_fen(fen)
            r["ply_index"] = i + 1
            r["fullmove_number"] = analysis_board.fullmove_number
            r["side_to_move"] = "white" if analysis_board.turn == chess.WHITE else "black"
        except Exception:
            analysis_board = chess.Board(fen)

        # SAFE MERGE SF RAW + PV
        sf_merge = r.get("sf_raw") or {}
        sf_merge = dict(sf_merge)
        sf_merge["pv"] = r.get("pv", [])

        # ----------------------------------------------------
        # 🔥 RUN MOTIF DETECTION (INSIDE LOOP — THE FIX)
        # ----------------------------------------------------
        try:
            motifs = detect_motifs(
                board=analysis_board,
                prev_board=prev_board,        # <--- NEW
                move_number=i + 1,
                eval_cp=numeric_eval if numeric_eval is not None else 0,
                prev_eval=prev_eval,
                sf_raw=sf_merge,
                last_move_uci=current_uci,
                prev_move_uci=prev_uci,
            )

            r["motifs"] = motifs
        except Exception as e:
            logging.exception("Motif detection error")
            r["motifs"] = {"error": f"motif detection error: {str(e)}"}

        # Eval delta
        if numeric_eval is not None and prev_eval is not None:
            r["eval_delta"] = numeric_eval - prev_eval
        else:
            r["eval_delta"] = None

        # -----------------------------
        # LICHESS THEORY
        # -----------------------------
        try:
            theory = compute_theory_deviation(fen, current_uci)
            r["lichess"] = {
                "masters": theory.get("masters"),
                "players": theory.get("players"),
                "is_in_masters_top": theory.get("is_in_masters_top"),
                "severity": theory.get("severity"),
            }
        except Exception as e:
            logging.exception("Lichess fetch error")
            r["lichess"] = {"error": f"lichess fetch error: {str(e)}"}

        # Save eval for next iteration
        if numeric_eval is not None:
            prev_eval = numeric_eval

    return jsonify({"count": len(results), "evaluations": results})




@app.route("/api/coach", methods=["POST"])
def analyze_position():
    data = request.get_json()
    if not data or "fen" not in data:
        return jsonify({"error": "Missing FEN"}), 400

    fen = data["fen"]

    def run_stockfish_eval(fen):
        engine = get_fresh_engine()
        engine.set_fen_position(fen)
        return engine.get_evaluation()

    try:
        future = executor.submit(run_stockfish_eval, fen)
        evaluation = future.result(timeout=5)

        # Normalize eval
        if evaluation["type"] == "cp":
            cp = evaluation["value"]
            score = cp / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"

        elif evaluation["type"] == "mate":
            m = evaluation["value"]
            score = 10 if m > 0 else -10
            eval_str = f"{'-' if m < 0 else ''}M{abs(m)}"
        else:
            score = 0
            eval_str = "0.00"

        # Best move + PV
        stockfish = get_fresh_engine()
        stockfish.set_fen_position(fen)

        try:
            best_move = stockfish.get_best_move()
        except:
            best_move = None

        # PV LIST FIX
        try:
            info = stockfish.get_top_moves(3)
            pv_list = [m["Move"] for m in info] if info else []
        except:
            pv_list = []

        # Lichess data
        try:
            masters = get_top_moves_with_continuations(fen, db="masters", top_n=TOP_N)
            players = get_top_moves_with_continuations(fen, db="lichess", top_n=TOP_N)
            theory = {"masters": masters, "players": players, "is_in_masters_top": False}
        except:
            logging.exception("Lichess fetch failed in /api/coach")
            theory = {"error": "lichess fetch failed"}

        return jsonify({
            "eval": eval_str,
            "numeric_eval": evaluation.get("value", 0),
            "best_move": best_move,
            "ideas": [
                f"Stockfish suggests {best_move} as the best move." if best_move else "Stockfish gave no best move.",
                "Keep your pieces active and king safe.",
                "Look for tactical opportunities."
            ],
            "lichess": theory,
            "sf_raw": evaluation,
            "pv": pv_list
        })

    except Exception as e:
        logging.exception("/api/coach failed")
        return jsonify({"error": str(e)}), 500


@app.route("/api/motifs", methods=["POST"])
def motifs_endpoint():
    data = request.get_json() or {}

    fen = data.get("fen")
    if not fen:
        return jsonify({"error": "Missing fen"}), 400

    try:
        # Current board
        board = chess.Board(fen)

        # -------------------------
        # NEW: previous board via prev_fen
        # -------------------------
        prev_fen = data.get("prev_fen")
        prev_board = chess.Board(prev_fen) if prev_fen else None

        # -------------------------
        # Normalize eval → eval_cp in centipawns
        # -------------------------
        raw_eval = data.get("eval", 0)

        if isinstance(raw_eval, str):
            try:
                eval_cp = int(float(raw_eval) * 100)
            except:
                eval_cp = 0
        else:
            try:
                eval_cp = int(raw_eval)
            except:
                eval_cp = 0

        prev_eval = data.get("prev_eval")
        sf_raw = data.get("sf_raw") or {}

        # Move wiring sent from frontend
        last_uci = data.get("last_move_uci")
        prev_uci = data.get("prev_move_uci")

        move_number = data.get("move_number", board.fullmove_number)

        # -------------------------
        # Run motif detection
        # -------------------------
        motifs = detect_motifs(
            board=board,
            prev_board=prev_board,          # <-- CRITICAL
            move_number=move_number,
            eval_cp=eval_cp,
            prev_eval=prev_eval,
            sf_raw=sf_raw,
            last_move_uci=last_uci,
            prev_move_uci=prev_uci,
        )

        return jsonify({"motifs": motifs})

    except Exception as e:
        logging.exception("motifs endpoint error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/gemini_explanations", methods=["POST"])
def gemini_explanations():
    """
    Input JSON:
    {
        "pgn": "...",
        "evaluations": [ { fen, eval, motifs, lichess, ... }, ... ]
    }
    Output:
    {
        "explanations": [ "Move 1 explanation...", "Move 2...", ... ]
    }
    """
    data = request.get_json()

    if not data or "evaluations" not in data:
        return jsonify({"error": "Missing evaluations"}), 400

    evaluations = data["evaluations"]

    # Build a summarized version to reduce token load
    condensed = []
    for ev in evaluations:
        condensed.append({
            "move_number": ev.get("move_number"),
            "fen": ev.get("fen"),
            "eval": ev.get("eval"),
            "eval_delta": ev.get("eval_delta"),
            "motifs": ev.get("motifs"),
            "lichess": ev.get("lichess"),
            "pv": ev.get("pv"),
            "best_move": ev.get("best_move"),
            "side_to_move": ev.get("side_to_move"),
        })

    prompt = f"""
You are a world-class chess coach. 
You will receive a JSON list of move-by-move evaluations.

Each entry includes:
- fullmove_number
- side_to_move (“white” or “black”)
- eval from Stockfish Chess Engine (string)
- eval_delta
- relevant motifs or concepts (list) found at every position
- lichess theory summary
- pv (principal variation)
- best_move
- fen

Your job:
For each entry, produce ONE explanation string (4–6 sentences).

STRICT OUTPUT RULES:
• Output ONLY a JSON array of strings — one per ply.  
• Begin each entry with:
  “Move X (side that just played move) and then go through each subsequent move. Remember chess is half moves. move 1. is 1 for white and 1 for black. 
  We explain every position for both sides 
  using fullmove_number and side_to_move. That is to say every game begins 1 (white), 1(black), 2(wh...).
• Never mention motif names literally. 
  Use motifs ONLY to inform the explanation.
  You CAN mention the motif name literally only if it is a mate (m4,m4, etc.) motif.
• Never mention eval numbers or eval_delta.  
  Describe improvement/deterioration in natural chess language.
• Never include move lists or invented variations. 
  Only refer to the provided PV if needed.
• Never repeat generic lines.
• Tone must be clear, human, instructional — like a real chess coach.
ALWAYS EXPLAIN THE MOVE FROM THE PERSPECTIVE OF THE PLAYER WHO JUST MOVED AND
ENSURE THE EXPLANATION IS CONSISTENT WITH THE MOVES LITERALLY PLAYED. (reflected by the pgn, or list of fens).
• Focus each explanation on:
  - plan behind the move
  - positional ideas
  - tactical consequences
  - why the move is good, inaccurate, or losing
  - how the position changed afterward

Goal:
Produce instructive, followable commentary suitable for club-level players.

Return ONLY the JSON array of explanations.
JSON:
{condensed}
"""


    try:
        reply = GEMINI_MODEL.generate_content(prompt)
        text = reply.text.strip()

        # Safety: extract only JSON array
        import json, re

        # Try direct parse
        try:
            explanations = json.loads(text)
        except:
            # fallback: extract array using regex
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if not match:
                raise ValueError("Gemini did not return JSON")
            explanations = json.loads(match.group(0))


        return jsonify({ "explanations": explanations })

    except Exception as e:
        logging.exception("Gemini generation failed")
        return jsonify({ "error": str(e) }), 500



if __name__ == "__main__":
    logging.info("Starting Virtual Chess Coach backend on 127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
