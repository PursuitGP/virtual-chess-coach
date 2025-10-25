from flask import Flask, request, jsonify
from flask_cors import CORS
import chess
import chess.engine
import os

app = Flask(__name__)
CORS(app)

# Path to Stockfish binary (you’ll add this later)
STOCKFISH_PATH = os.path.join(os.path.dirname(__file__), "stockfish", "stockfish.exe")

def make_engine():
    return chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)

@app.route("/")
def home():
    return "✅ Stockfish backend is running!"

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json()
    fen = data.get("fen")
    depth = data.get("depth", 12)

    if not fen:
        return jsonify({"error": "FEN required"}), 400

    board = chess.Board(fen)
    engine = make_engine()

    try:
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        best_move = info.get("pv", [None])[0]
        score = info["score"].white().score(mate_score=10000)
        return jsonify({
            "best_move": best_move.uci() if best_move else None,
            "score": score
        })
    finally:
        engine.quit()

if __name__ == "__main__":
    app.run(debug=True)
