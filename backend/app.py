import io
import chess.pgn
from flask import Flask, request, jsonify
from flask_cors import CORS
from stockfish import Stockfish
import os
from multiprocessing import Pool, cpu_count
from concurrent.futures import ThreadPoolExecutor
from motifs import detect_motifs
import google.generativeai as genai


# -------------------------
# GEMINI CONFIG
# -------------------------
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
GEM_MODEL = genai.GenerativeModel("gemini-2.0-flash")

app = Flask(__name__)
CORS(app)

# -------------------------
# STOCKFISH CROSS-PLATFORM
# -------------------------
if os.name == "nt":
    STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish.exe")
elif os.path.exists("/opt/homebrew/bin/stockfish"):
    STOCKFISH_PATH = "/opt/homebrew/bin/stockfish"
elif os.path.exists("/usr/bin/stockfish"):
    STOCKFISH_PATH = "/usr/bin/stockfish"
else:
    raise FileNotFoundError("Stockfish binary not found.")


executor = ThreadPoolExecutor(max_workers=2)


def get_fresh_engine():
    return Stockfish(path=STOCKFISH_PATH, depth=18)


def evaluate_fen(fen):
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


# -------------------------
# GEMINI ENDPOINT
# -------------------------
@app.route("/api/gemini_summary", methods=["POST"])
def gemini_summary():
    data = request.get_json()
    evaluations = data.get("evaluations", [])

    limited = evaluations[:15]  # first 15 moves

    prompt = "Analyze the following chess positions.\n"
    prompt += "For each move, explain the strategy, ideas, and mistakes.\n\n"

    for ev in limited:
        prompt += f"Move {ev['move_number']} — Eval {ev['eval']}\n"
        prompt += f"FEN: {ev['fen']}\n"
        prompt += f"Best move: {ev['best_move']}\n\n"

    try:
        response = GEM_MODEL.generate_content(prompt)
        return jsonify({"analysis": response.text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# FULL PGN EVALUATION
# -------------------------
@app.route("/api/evaluate_pgn", methods=["POST"])
def evaluate_pgn():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    pgn_text = file.read().decode("utf-8")

    try:
        game = chess.pgn.read_game(io.StringIO(pgn_text))
        board = game.board()

        fens = []
        for move in game.mainline_moves():
            board.push(move)
            fens.append(board.fen())

        with Pool(processes=max(1, cpu_count() - 1)) as pool:
            results = pool.map(evaluate_fen, fens)

        prev_eval = None
        board = game.board()

        for i, r in enumerate(results):
            r["move_number"] = i + 1

            board.set_fen(r["fen"])
            motifs = detect_motifs(
                board,
                move_number=i + 1,
                eval=r["score"] * 100,
                prev_eval=prev_eval
            )
            r["motifs"] = motifs
            r["eval_delta"] = None if prev_eval is None else r["score"] * 100 - prev_eval
            prev_eval = r["score"] * 100

        return jsonify({
            "count": len(results),
            "evaluations": results
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# -------------------------
# SINGLE POSITION EVAL
# -------------------------
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
        evaluation = future.result(timeout=2)

        if evaluation["type"] == "cp":
            score = evaluation["value"] / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"
        else:
            eval_str = f"Mate in {evaluation['value']}"

        stockfish = get_fresh_engine()
        stockfish.set_fen_position(fen)
        best_move = stockfish.get_best_move()

        return jsonify({
            "eval": eval_str,
            "numeric_eval": evaluation["value"],
            "best_move": best_move,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
print("Gemini key loaded?", bool(os.getenv("GEMINI_API_KEY")))
