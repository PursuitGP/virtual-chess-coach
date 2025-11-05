from flask import Flask, request, jsonify
from flask_cors import CORS
from stockfish import Stockfish
import os

app = Flask(__name__)
CORS(app)

STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish.exe")

def get_fresh_stockfish():
    """Create a fresh Stockfish instance each call to avoid stale state."""
    return Stockfish(path=STOCKFISH_PATH, depth=18)

@app.route("/api/coach", methods=["POST"])
def analyze_position():
    data = request.get_json()
    if not data or "fen" not in data:
        return jsonify({"error": "Missing FEN"}), 400

    fen = data["fen"]
    try:
        stockfish = get_fresh_stockfish()
        stockfish.set_fen_position(fen)
        evaluation = stockfish.get_evaluation()

        # Convert evaluation to numeric and readable format
        if evaluation["type"] == "cp":
            score = evaluation["value"] / 100.0
            eval_str = f"{'+' if score >= 0 else ''}{score:.2f}"
        else:
            eval_str = f"Mate in {evaluation['value']}"

        best_move = stockfish.get_best_move()
        ideas = [
            f"Stockfish suggests {best_move} as the best move.",
            "Try to improve king safety and piece activity.",
            "Control the center and look for tactical opportunities."
        ]

        return jsonify({
            "eval": eval_str,
            "numeric_eval": evaluation["value"],  # ← add numeric value for the frontend bar
            "best_move": best_move,
            "ideas": ideas
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
