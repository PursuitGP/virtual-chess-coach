import React, { useMemo, useState } from "react";
import Chessground from "react-chessground";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./App.css";
import { Chess } from "chess.js";
import PGNLoader from "./PGNLoader";

const FILES = ["a","b","c","d","e","f","g","h"];
const RANKS = ["1","2","3","4","5","6","7","8"];
const ALL_SQUARES = FILES.flatMap(f => RANKS.map(r => f + r));

function computeDests(chess) {
  const dests = new Map();
  for (const s of ALL_SQUARES) {
    const moves = chess.moves({ square: s, verbose: true });
    if (moves.length) dests.set(s, moves.map(m => m.to));
  }
  return dests;
}

// Format SAN array into full-move pairs: [{num, white, black}]
function sanToPairs(sanList) {
  const out = [];
  for (let i = 0; i < sanList.length; i += 2) {
    out.push({ num: Math.floor(i / 2) + 1, white: sanList[i], black: sanList[i + 1] || "" });
  }
  return out;
}

export default function App() {
  const [game, setGame] = useState(() => new Chess());
  const [fen, setFen] = useState(() => game.fen());
  const [orientation, setOrientation] = useState("white");
  const [lastMove, setLastMove] = useState(null);
  const [displayHistory, setDisplayHistory] = useState([]); // SAN tokens

  // PGN state
  const [pgnHeaders, setPgnHeaders] = useState(null);
  const [pgnMoves, setPgnMoves] = useState([]); // verbose
  const [plyIndex, setPlyIndex] = useState(0);

  // Board size (px)
  const [boardSize, setBoardSize] = useState(600);

  const dests = useMemo(() => computeDests(game), [game, fen]);
  const turnColor = game.turn() === "w" ? "white" : "black";

  function syncFrom(ch) {
    setGame(ch);
    setFen(ch.fen());
    setDisplayHistory(ch.history()); // SAN
  }

  function applyMove(from, to) {
    const ch = new Chess(game.fen());
    const mv = ch.move({ from, to, promotion: "q" });
    if (mv) {
      setLastMove([from, to]);
      syncFrom(ch);
    }
  }

  function onMove(from, to) {
    applyMove(from, to);
  }

  function resetBoard() {
    const fresh = new Chess();
    setLastMove(null);
    setPlyIndex(0);
    syncFrom(fresh);
  }

  function flipBoard() {
    setOrientation(o => (o === "white" ? "black" : "white"));
  }

  // ---- PGN integration ----
  function onPGNParsed({ headers, moves }) {
    setPgnHeaders(headers || {});
    setPgnMoves(Array.isArray(moves) ? moves : []);
    setPlyIndex(0);
    const fresh = new Chess();
    setLastMove(null);
    syncFrom(fresh);
  }

  function stepTo(index) {
    const target = Math.max(0, Math.min(index, pgnMoves.length));
    const replay = new Chess();
    for (let i = 0; i < target; i++) {
      const m = pgnMoves[i];
      replay.move({ from: m.from, to: m.to, promotion: m.promotion || "q" });
    }
    setLastMove(target > 0 ? [pgnMoves[target - 1].from, pgnMoves[target - 1].to] : null);
    setPlyIndex(target);
    syncFrom(replay);
  }

  function nextPly() { stepTo(plyIndex + 1); }
  function prevPly() { stepTo(plyIndex - 1); }

  const movePairs = sanToPairs(displayHistory);

  return (
    <div className="container wide">
      <h1 style={{ marginBottom: 12 }}>♜ Chess Coach - Chessgrounds w/ PGN Parsing</h1>

      <div className="badge" style={{ marginBottom: 12 }}>
        <span>Turn:&nbsp;</span><strong>{turnColor === "white" ? "White" : "Black"}</strong>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <div className="controls">
            <button onClick={flipBoard}>Flip board</button>
            <button onClick={resetBoard}>Reset</button>
            <button onClick={prevPly} disabled={plyIndex === 0}>◀ Prev</button>
            <button onClick={nextPly} disabled={plyIndex >= pgnMoves.length}>Next ▶</button>
            <span className="small" style={{ marginLeft: 8 }}>
              {pgnMoves.length > 0 ? `Move ${plyIndex}/${pgnMoves.length}` : "No PGN loaded"}
            </span>
            <div className="size-control">
              <label>Board size: {boardSize}px</label>
              <input
                type="range"
                min="480"
                max="720"
                step="10"
                value={boardSize}
                onChange={(e) => setBoardSize(Number(e.target.value))}
              />
            </div>
          </div>

          <Chessground
            width={boardSize}
            height={boardSize}
            orientation={orientation}
            fen={fen}
            turnColor={turnColor}
            lastMove={lastMove}
            animation={{ enabled: true, duration: 200 }}
            highlight={{ lastMove: true, check: true }}
            draggable={{ enabled: true }}
            movable={{ free: false, color: "both", dests, showDests: true }}
            onMove={onMove}
          />
        </div>

        <div className="card">
          <div className="panel-header">
            <div style={{display:'flex', alignItems:'center', gap:8}}>
              <span role="img" aria-label="folder">📂</span>
              <strong>PGN Loader</strong>
            </div>
            <div className="panel-meta">
              {pgnHeaders && (
                <div className="pgn-meta">
                  <div><strong>{pgnHeaders.White || "White"}</strong> vs <strong>{pgnHeaders.Black || "Black"}</strong></div>
                  <div>{pgnHeaders.Event || "Event"} • {pgnHeaders.Site || "Site"} • {pgnHeaders.Date || "Date"} • {pgnHeaders.Result || ""}</div>
                </div>
              )}
            </div>
          </div>

          <PGNLoader onParsed={onPGNParsed} />

          <div style={{ marginTop: 12 }}>
            <label>Current FEN</label>
            <input readOnly value={fen} />
          </div>

          <div className="history" style={{ marginTop: 12 }}>
            <label>Move History</label>
            {movePairs.length === 0 ? (
              <p className="small">No moves yet</p>
            ) : (
              <table className="moves-table">
                <tbody>
                  {movePairs.map((row) => (
                    <tr key={row.num}>
                      <td className="mv-num">{row.num}.</td>
                      <td className="mv-san">{row.white}</td>
                      <td className="mv-san">{row.black}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
