import io
import os
from multiprocessing import Pool, cpu_count

from flask import Flask, request, jsonify
from flask_cors import CORS

import chess
import chess.pgn
import chess.engine

# -------------------------
# Optional motifs import
# -------------------------
try:
    from motifs import detect_motifs
except Exception:
    def detect_motifs(board, move_number=None, eval=None, prev_eval=None):
        return []


# -------------------------
# Optional Gemini config
# -------------------------
try:
    import google.generativeai as genai

    genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
    GEM_MODEL = genai.GenerativeModel("gemini-2.0-flash")
except Exception:
    genai = None
    GEM_MODEL = None


# -------------------------
# Flask app
# -------------------------
app = Flask(__name__)
CORS(app)


# -------------------------
# Stockfish / engine helpers
# -------------------------
def get_stockfish_path() -> str:
    """Return a Stockfish binary path, trying env var first."""
    env_path = os.getenv("STOCKFISH_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    # Windows: look for local stockfish.exe
    if os.name == "nt":
        candidate = os.path.join(os.getcwd(), "stockfish.exe")
        return candidate

    # macOS/Linux: assume stockfish in PATH
    return "stockfish"


ENGINE_PATH = get_stockfish_path()


def evaluate_fen(args):
    """
    Worker function for multiprocessing.

    args: (fen, san, index)
    Returns dict:
      {
        "fen": fen,
        "san": san,
        "move_index": index,
        "score": float pawns,
        "score_str": string,
        "best_move": SAN or None
      }
    """
    fen, san, index = args

    try:
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
    except Exception as e:
        return {
            "fen": fen,
            "san": san,
            "move_index": index,
            "score": 0.0,
            "score_str": "0.00",
            "best_move": None,
            "engine_error": str(e),
        }

    try:
        board = chess.Board(fen)
        info = engine.analyse(board, chess.engine.Limit(depth=15))

        score_obj = info["score"].pov(chess.WHITE)
        cp = score_obj.score(mate_score=100000)

        # convert to pawns
        score_pawns = cp / 100.0
        score_str = f"{score_pawns:.2f}"

        # get best move from PV
        best_move_san = None
        pv = info.get("pv")
        if pv:
            mv = pv[0]
            try:
                best_move_san = board.san(mv)
            except Exception:
                best_move_san = mv.uci()

        return {
            "fen": fen,
            "san": san,
            "move_index": index,
            "score": score_pawns,
            "score_str": score_str,
            "best_move": best_move_san,
        }

    finally:
        try:
            engine.quit()
        except Exception:
            pass


# -------------------------
# /api/evaluate_pgn
# -------------------------
@app.route("/api/evaluate_pgn", methods=["POST"])
def evaluate_pgn():
    """
    Accepts multipart/form-data with key 'file' (a PGN).

    Returns JSON:
      {
        "count": N,
        "evaluations": [
          {
            "fen": "...",
            "san": "e4",
            "move_index": 0,
            "move_number": 1,
            "score": 0.23,
            "score_str": "0.23",
            "best_move": "c5",
            "motifs": [...],      # from motifs.py (list of dicts or strings)
            "eval_delta": 12.0    # in centipawns, relative to previous move
          },
          ...
        ]
      }
    """
    try:
        if "file" not in request.files:
            return jsonify({"error": "No PGN file uploaded under key 'file'."}), 400

        raw = request.files["file"].read().decode("utf-8", errors="ignore")
        game = chess.pgn.read_game(io.StringIO(raw))
        if game is None:
            return jsonify({"error": "Unable to parse PGN."}), 400

        board = game.board()
        move_data = []

        # build list of (san, fen-after-move)
        for mv in game.mainline_moves():
            san = board.san(mv)
            board.push(mv)
            move_data.append({"san": san, "fen": board.fen()})

        if not move_data:
            return jsonify({"count": 0, "evaluations": []}), 200

        eval_args = [(md["fen"], md["san"], idx) for idx, md in enumerate(move_data)]

        with Pool(processes=max(1, cpu_count() - 1)) as pool:
            raw_results = pool.map(evaluate_fen, eval_args)

        # Attach motifs + eval_delta (in centipawns)
        final_results = []
        prev_eval_cp = None

        for i, r in enumerate(raw_results):
            cp_now = r["score"] * 100.0
            eval_delta = None if prev_eval_cp is None else cp_now - prev_eval_cp

            try:
                b = chess.Board(r["fen"])
                motifs = detect_motifs(
                    b,
                    move_number=i + 1,
                    eval=cp_now,
                    prev_eval=prev_eval_cp,
                )
            except Exception:
                motifs = []

            annotated = dict(r)
            annotated["move_number"] = i + 1
            annotated["motifs"] = motifs
            annotated["eval_delta"] = eval_delta

            final_results.append(annotated)
            prev_eval_cp = cp_now

        return jsonify({"count": len(final_results), "evaluations": final_results}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# /api/coach (single FEN eval – optional)
# -------------------------
@app.route("/api/coach", methods=["POST"])
def coach():
    """
    Very small helper: evaluate a single FEN.
    Expects JSON: { "fen": "<FEN>" }
    Returns: { "eval": "+0.45", "numeric": 0.45, "best_move": "Nf3" }
    """
    try:
        data = request.get_json() or {}
        fen = data.get("fen")
        if not fen:
            return jsonify({"error": "Missing 'fen' in body"}), 400

        board = chess.Board(fen)
        engine = chess.engine.SimpleEngine.popen_uci(ENGINE_PATH)
        try:
            info = engine.analyse(board, chess.engine.Limit(depth=15))
            score_obj = info["score"].pov(chess.WHITE)
            cp = score_obj.score(mate_score=100000)
            score_pawns = cp / 100.0

            if abs(cp) >= 100000:
                eval_str = "Mate"
            else:
                eval_str = f"{score_pawns:.2f}"

            best_move_san = None
            pv = info.get("pv")
            if pv:
                mv = pv[0]
                try:
                    best_move_san = board.san(mv)
                except Exception:
                    best_move_san = mv.uci()

            return jsonify(
                {"eval": eval_str, "numeric": score_pawns, "best_move": best_move_san}
            ), 200
        finally:
            try:
                engine.quit()
            except Exception:
                pass

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# /api/gemini_move (per-ply explanation)
# -------------------------
@app.route("/api/gemini_move", methods=["POST"])
def gemini_move():
    """
    Explain ONE half-move (ply) in 2–3 sentences.

    Expects JSON:
      {
        "move_index": 0,
        "full_move_number": 1,
        "color": "White"|"Black",
        "san": "Ng5",
        "score_before": 0.2,
        "score_after": -5.3,
        "best_move": "d5" or null,
        "motifs": [ ... ]   # list of strings or dicts from detect_motifs
      }

    Returns:
      { "summary": "<plain text>" }
    """
    if GEM_MODEL is None:
        return jsonify({"error": "Gemini model is not configured on the server."}), 500

    try:
        data = request.get_json() or {}

        move_index = data.get("move_index")
        full_move_number = data.get("full_move_number") or 0
        color = data.get("color") or (
            "White" if (isinstance(move_index, int) and move_index % 2 == 0) else "Black"
        )

        san = data.get("san") or "this move"
        score_before = data.get("score_before")
        score_after = data.get("score_after")
        best_move = data.get("best_move") or "No clearly better move found."
        motifs = data.get("motifs") or []

        # numeric delta
        delta = None
        if isinstance(score_before, (int, float)) and isinstance(score_after, (int, float)):
            delta = score_after - score_before

        # turn motifs (which may be dicts) into short labels
        motif_labels = []
        for m in motifs:
            if isinstance(m, str):
                motif_labels.append(m)
            elif isinstance(m, dict):
                # common keys from motifs.py: "name", "type", maybe "detail"
                label = (
                    m.get("name")
                    or m.get("type")
                    or m.get("id")
                    or str(m)
                )
                motif_labels.append(label)
            else:
                motif_labels.append(str(m))

        motifs_str = ", ".join(motif_labels) if motif_labels else "None"

        prompt = f"""
You are a chess coach for a beginner–intermediate player (around 800–1500 Elo).

You are explaining a SINGLE move (a half-move) from the opening phase.

Full move number: {full_move_number}
Side that played the move: {color}
Move played: {san}

Evaluation in pawns:
- Before the move: {score_before}
- After the move:  {score_after}
- Change in evaluation: {delta}

Engine's better move (if any): {best_move}
Detected motifs (tactical/positional ideas): {motifs_str}

Your task:
- In 2–3 short, clear sentences, explain this one move only.
- Say whether it is strong, normal, inaccurate, a mistake, or a blunder (based on eval change).
- Explain WHY the eval changed in human terms, using motifs when relevant (forks, hanging pieces, weak squares, king safety, etc.).
- If the best move is clearly better, briefly explain what it would have achieved.
- Do NOT mention other moves from the game.
- Do NOT output JSON; answer in plain English only.
"""

        try:
            result = GEM_MODEL.generate_content(prompt)
            text = getattr(result, "text", "").strip() or "No explanation available."
            return jsonify({"summary": text}), 200
        except Exception as model_exc:
            # Handle quota / 429 etc. more nicely
            msg = str(model_exc)
            if "429" in msg or "quota" in msg.lower():
                return jsonify(
                    {
                        "error": "Gemini quota or rate limit exceeded. Please wait or reduce requests."
                    }
                ), 429
            return jsonify({"error": msg}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Using engine at:", ENGINE_PATH)
    print("Gemini configured:", GEM_MODEL is not None)
    app.run(host="127.0.0.1", port=5000, debug=True)
