import io
import chess.pgn
from flask import Flask, request, jsonify
from flask_cors import CORS
from stockfish import Stockfish
import os
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

        # Run stockfish evals in parallel
        with Pool(processes=max(1, cpu_count() - 1)) as pool:
            results = pool.map(evaluate_fen, fens)

        # Add move numbers
        for i, r in enumerate(results):
            r["move_number"] = i + 1

        # ----------------------------------------
        # 🟦 NEW: Motif detection integration
        # ----------------------------------------
        prev_eval = None
        for i, r in enumerate(results):
            fen = r["fen"]
            numeric_eval = r["score"] * 100  # convert back to cp for consistency

            board.set_fen(fen)

            motifs = detect_motifs(
                board,
                move_number=i + 1,
                eval=numeric_eval,
                prev_eval=prev_eval
            )

            r["motifs"] = motifs
            r["eval_delta"] = None if prev_eval is None else numeric_eval - prev_eval
            prev_eval = numeric_eval
        # ----------------------------------------

        return jsonify({"count": len(results), "evaluations": results})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


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

        return jsonify({
            "eval": eval_str,
            "numeric_eval": evaluation["value"],
            "best_move": best_move,
            "ideas": [
                f"Stockfish suggests {best_move} as the best move.",
                "Keep your pieces active and king safe.",
                "Look for tactical opportunities."
            ]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
