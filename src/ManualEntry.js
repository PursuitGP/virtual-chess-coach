import React, { useMemo, useState } from "react";
import Chessground from "react-chessground";
import { Chess } from "chess.js";

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
const RANKS = ["1", "2", "3", "4", "5", "6", "7", "8"];
const ALL_SQUARES = FILES.flatMap((file) =>
  RANKS.map((rank) => `${file}${rank}`)
);

function computeDests(chess) {
  const destinations = new Map();
  for (const square of ALL_SQUARES) {
    const moves = chess.moves({ square, verbose: true });
    if (moves.length) {
      destinations.set(
        square,
        moves.map((move) => move.to)
      );
    }
  }
  return destinations;
}

function replayMoves(moves) {
  const replay = new Chess();
  for (const move of moves) {
    replay.move({
      from: move.from,
      to: move.to,
      promotion: move.promotion || "q",
    });
  }
  return replay;
}

function manualResult(chess) {
  if (chess.isCheckmate()) {
    return chess.turn() === "w" ? "0-1" : "1-0";
  }
  if (chess.isDraw()) return "1/2-1/2";
  return "*";
}

export default function ManualEntry({ boardSize, onCancel, onReady }) {
  const [moves, setMoves] = useState([]);
  const [orientation, setOrientation] = useState("white");
  const game = useMemo(() => replayMoves(moves), [moves]);
  const dests = useMemo(() => computeDests(game), [game]);
  const lastMove = moves.length
    ? [moves[moves.length - 1].from, moves[moves.length - 1].to]
    : null;

  function moveBoard(from, to) {
    const next = replayMoves(moves);
    const move = next.move({ from, to, promotion: "q" });
    if (move) setMoves(next.history({ verbose: true }));
  }

  function finishEntry() {
    if (!moves.length) return;
    const completed = replayMoves(moves);
    const result = manualResult(completed);
    const termination = completed.isCheckmate()
      ? "checkmate"
      : completed.isDraw()
        ? "normal"
        : "unterminated";

    completed.header(
      "Event",
      "Manual game entry",
      "Site",
      "Virtual Chess Coach",
      "White",
      "White",
      "Black",
      "Black",
      "Result",
      result,
      "Termination",
      termination
    );

    const pgn = completed.pgn();
    onReady?.({
      headers: completed.getHeaders(),
      moves: completed.history({ verbose: true }),
      file: new File([pgn], "manual_game.pgn", {
        type: "application/x-chess-pgn",
      }),
      raw: pgn,
    });
  }

  return (
    <section className="manual-entry" aria-labelledby="manual-entry-title">
      <div className="manual-entry-heading">
        <div>
          <p className="eyebrow">Manual game entry</p>
          <h1 id="manual-entry-title">Play the moves on the board</h1>
          <p>
            Enter the game from the starting position. Every legal move is
            converted into PGN automatically.
          </p>
        </div>
        <button type="button" className="ghost-action" onClick={onCancel}>
          Back to upload
        </button>
      </div>

      <div className="manual-entry-grid">
        <div className="manual-board">
          <Chessground
            width={boardSize}
            height={boardSize}
            orientation={orientation}
            fen={game.fen()}
            turnColor={game.turn() === "w" ? "white" : "black"}
            lastMove={lastMove}
            animation={{ enabled: true, duration: 180 }}
            highlight={{ lastMove: true, check: true }}
            draggable={{ enabled: true }}
            movable={{
              free: false,
              color: "both",
              dests,
              showDests: true,
            }}
            onMove={moveBoard}
          />
        </div>

        <div className="manual-sidebar">
          <div>
            <p className="eyebrow">Move list</p>
            <h2>
              {moves.length
                ? `${Math.ceil(moves.length / 2)} move${moves.length > 2 ? "s" : ""} entered`
                : "Start with White's first move"}
            </h2>
          </div>

          <div className="manual-moves" aria-live="polite">
            {moves.length ? (
              Array.from({ length: Math.ceil(moves.length / 2) }, (_, index) => (
                <div className="manual-move-row" key={index + 1}>
                  <span>{index + 1}.</span>
                  <strong>{moves[index * 2]?.san || ""}</strong>
                  <strong>{moves[index * 2 + 1]?.san || ""}</strong>
                </div>
              ))
            ) : (
              <p>No moves entered yet.</p>
            )}
          </div>

          {game.isGameOver() && (
            <div className="notice success">
              {game.isCheckmate()
                ? "Checkmate recorded. The result will be included in the PGN."
                : "The board has reached a drawn position."}
            </div>
          )}

          <div className="manual-actions">
            <button
              type="button"
              onClick={() => setMoves((current) => current.slice(0, -1))}
              disabled={!moves.length}
            >
              Undo move
            </button>
            <button
              type="button"
              onClick={() => setMoves([])}
              disabled={!moves.length}
            >
              Reset board
            </button>
            <button
              type="button"
              onClick={() =>
                setOrientation((current) =>
                  current === "white" ? "black" : "white"
                )
              }
            >
              Flip board
            </button>
          </div>

          <p className="manual-note">
            Promotions default to a queen. You can submit an unfinished game;
            the coach will analyze every move entered.
          </p>

          <button
            type="button"
            className="primary-action ready-action"
            onClick={finishEntry}
            disabled={!moves.length}
          >
            Ready for analysis
          </button>
        </div>
      </div>
    </section>
  );
}
