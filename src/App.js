import React, { useMemo, useRef, useState } from 'react';
import Chessground from 'react-chessground';
import 'chessground/assets/chessground.base.css';
import 'chessground/assets/chessground.brown.css';
import 'chessground/assets/chessground.cburnett.css';

 // Correct CSS path for chessground
import './App.css';
import { Chess } from 'chess.js';

// Generate all squares (a1..h8)
const FILES = ['a','b','c','d','e','f','g','h'];
const RANKS = ['1','2','3','4','5','6','7','8'];
const ALL_SQUARES = (() => {
  const arr = [];
  for (const f of FILES) for (const r of RANKS) arr.push(f + r);
  return arr;
})();

function computeDests(chess) {
  const dests = new Map();
  for (const s of ALL_SQUARES) {
    const moves = chess.moves({ square: s, verbose: true });
    if (moves.length) dests.set(s, moves.map(m => m.to));
  }
  return dests;
}

export default function App() {
  const [game, setGame] = useState(() => new Chess());
  const [fen, setFen] = useState(() => game.fen());
  const [orientation, setOrientation] = useState('white');
  const [lastMove, setLastMove] = useState(null);
  const [history, setHistory] = useState([]);
  const boardRef = useRef(null);

  // recompute legal destinations from current game state
  const dests = useMemo(() => computeDests(game), [game, fen]);

  const turnColor = useMemo(() => (game.turn() === 'w' ? 'white' : 'black'), [game, fen]);

  function safeMove(from, to) {
    const move = game.move({ from, to, promotion: 'q' });
    if (move) {
      setFen(game.fen());
      setHistory(game.history());
      setLastMove([from, to]);
    }
    return !!move;
  }

  function onMove(from, to) {
    safeMove(from, to);
  }

  function resetBoard() {
    const fresh = new Chess();
    setGame(fresh);
    setFen(fresh.fen());
    setHistory([]);
    setLastMove(null);
  }

  function flipBoard() {
    setOrientation(prev => (prev === 'white' ? 'black' : 'white'));
  }

  function moveE2E4() {
    safeMove('e2', 'e4');
  }

  // Programmatic example: set a FEN manually (optional helper)
  function setStartPos() {
    const c = new Chess();
    setGame(c);
    setFen(c.fen());
    setHistory([]);
    setLastMove(null);
  }

  return (
    <div className="container">
      <h1 style={{marginBottom: 12}}>♟️ React + Chessground + chess.js</h1>
      <div className="badge" style={{marginBottom: 16}}>
        <span>Turn:</span>
        <strong>{turnColor === 'white' ? 'White' : 'Black'}</strong>
      </div>

      <div className="grid">
        <div className="card">
          <div className="controls">
            <button onClick={moveE2E4}>Play e2→e4</button>
            <button onClick={flipBoard}>Flip board</button>
            <button onClick={resetBoard}>Reset</button>
            <button onClick={setStartPos} title="Reset to start FEN">Start FEN</button>
          </div>

          <Chessground
            ref={boardRef}
            width={520}
            height={520}
            orientation={orientation}
            fen={fen}
            turnColor={turnColor}
            lastMove={lastMove}
            animation={{ enabled: true, duration: 200 }}
            highlight={{ lastMove: true, check: true }}
            draggable={{ enabled: true }}
            movable={{
              free: false,           // only allow legal moves
              color: 'both',
              dests,
              showDests: true
            }}
            onMove={onMove}
          />
        </div>

        <div className="card">
          <div style={{marginBottom: 12}}>
            <label>Current FEN</label>
            <input readOnly value={fen} />
          </div>
          <div className="history">
            <label>Move History (SAN)</label>
            {history.length === 0 ? (
              <p className="small">No moves yet</p>
            ) : (
              <ol>
                {history.map((mv, idx) => (
                  <li key={idx}>{mv}</li>
                ))}
              </ol>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}