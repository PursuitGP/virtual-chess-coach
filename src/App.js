import React, { useMemo, useState } from "react";
import Chessground from "react-chessground";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./App.css";
import { Chess } from "chess.js";
import PGNLoader from "./PGNLoader";
import { useEffect } from "react";

const FILES = ["a","b","c","d","e","f","g","h"];
const RANKS = ["1","2","3","4","5","6","7","8"];
const ALL_SQUARES = FILES.flatMap(f => RANKS.map(r => f + r));



function isTyping(node) {
    if (!node) return false;
    const tag = (node.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || node.isContentEditable;
}



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

    useEffect(() => {
        const isTyping = (el) => {
            if (!el) return false;
            const tag = (el.tagName || "").toLowerCase();
            return tag === "input" || tag === "textarea" || tag === "select" || el.isContentEditable;
        };

        const onKeyDown = (e) => {
            if (isTyping(e.target)) return;

            switch (e.key) {
                case "ArrowLeft":
                    e.preventDefault();
                    prevPly();
                    break;
                case "ArrowRight":
                    e.preventDefault();
                    nextPly();
                    break;
             
                case "End":
                    e.preventDefault();
                    goToEnd();
                    break;
                case "r": // NEW: reset board
                case "R":
                    e.preventDefault();
                    resetBoard();
                    break;
                case "f": // NEW: flip board
                case "F":
                    e.preventDefault();
                    flipBoard();
                    break;
                default:
                    break;
            }
        };

        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [prevPly, nextPly, goToStart, goToEnd, resetBoard, flipBoard]);


    function nextPly() { safeStepTo(plyIndex + 1); }
    function prevPly() { safeStepTo(plyIndex - 1); }

    function goToStart() { safeStepTo(0); }
    function goToEnd() { safeStepTo(pgnMoves.length); }

    const movePairs = sanToPairs(displayHistory);

    // Clamp target index into [0, pgnMoves.length]
    function safeStepTo(i) {
        const max = Array.isArray(pgnMoves) ? pgnMoves.length : 0;
        stepTo(Math.max(0, Math.min(max, i)));
    }


    // --- Coach sidebar state ---
    const [coachOpen, setCoachOpen] = React.useState(true);
    const [coachLoading, setCoachLoading] = React.useState(false);
    const [coachData, setCoachData] = React.useState(null);
    const [coachError, setCoachError] = React.useState(null);

    // Build the payload we’ll send (FEN + SAN history up to current ply)
    const coachPayload = React.useMemo(() => {
        const movesSoFar = Array.isArray(displayHistory)
            ? displayHistory.slice(0, Math.max(0, Math.min(displayHistory.length, plyIndex)))
            : [];
        return {
            fen,
            moves: movesSoFar,          // SAN list
            ply: plyIndex,
            headers: pgnHeaders || {},  // Event, Site, White, Black, etc.
        };
    }, [fen, displayHistory, plyIndex, pgnHeaders]);

    async function handleAskCoach() {
        setCoachOpen(true);
        setCoachError(null);
        setCoachLoading(true);
        setCoachData(null);

        try {
            // If your backend isn’t ready yet, keep this console.log
            console.log("Coach request payload:", coachPayload);

            // Uncomment when backend is ready:
            // const res = await fetch("/api/coach", {
            //   method: "POST",
            //   headers: { "Content-Type": "application/json" },
            //   body: JSON.stringify(coachPayload),
            // });
            // if (!res.ok) throw new Error(`HTTP ${res.status}`);
            // const data = await res.json();
            // setCoachData(data);

            // Temporary demo: fake response so UI shows something
            await new Promise(r => setTimeout(r, 700));
            setCoachData({
                opening: "King's Gambit (C30) — gist",
                eval: "+0.3 (Stockfish depth 18)",
                ideas: [
                    "Control center with d4 next; watch …Qh4+ tactics.",
                    "If …exf4, consider Nf3 and Bc4 pressure.",
                ],
                note: "Replace this with real backend data later.",
            });
        } catch (err) {
            setCoachError(err.message || "Coach backend not reachable.");
        } finally {
            setCoachLoading(false);
        }
    }

    return (

    <div className="container wide">
      <h1 style={{ marginBottom: 12 }}>♜ Chess Coach - Chessgrounds w/ PGN Parsing</h1>

      <div className="badge" style={{ marginBottom: 12 }}>
        <span>Turn:&nbsp;</span><strong>{turnColor === "white" ? "White" : "Black"}</strong>
      </div>
      

      <div className="grid grid-2">
                <div className="card">
                    {/* Control Dashboard */}
                    <div className="controls">
                        <button onClick={flipBoard}>Flip board</button>
                        <button onClick={resetBoard}>Reset</button>

                        <button onClick={goToStart} disabled={plyIndex === 0} title="Skip to start (R)">⏮</button>
                        <button onClick={prevPly} disabled={plyIndex === 0}>◀</button>
                        <button onClick={nextPly} disabled={plyIndex >= pgnMoves.length}>▶</button>
                        <button onClick={goToEnd} disabled={plyIndex >= pgnMoves.length} title="Skip to end (End)">⏭</button>

                        <span className="small" style={{ marginLeft: 8 }}>
                            {pgnMoves.length > 0 ? `Move ${plyIndex}/${pgnMoves.length}` : "No PGN loaded"}
                        </span>
                        <div className="size-control">
                            <label>Board size: {boardSize}px</label>
                            <input
                                type="range"
                                min="480" max="720" step="10"
                                value={boardSize}
                                onChange={(e) => setBoardSize(Number(e.target.value))}
                            />
                        </div>
                    </div>

                   {/* Shortcut guide */}
                    <div
                        className="shortcut-guide small"
                        style={{
                            marginTop: 8,
                            display: "flex",
                            gap: 12,
                            flexWrap: "wrap",
                            alignItems: "center",
                            opacity: 0.8,
                        }}
                    >
                        <span style={{ opacity: 0.9 }}>Shortcuts:</span>
                        <span><kbd className="kbd">←</kbd>/<kbd className="kbd">→</kbd> step</span>
                        <span><kbd className="kbd">End</kbd> skip</span>
                        <span><kbd className="kbd">R</kbd> reset</span>
                        <span><kbd className="kbd">F</kbd> flip</span>
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

                   {/* --- COACH SIDEBAR --- */}
                    <div className="card coach-card">
                        <div className="panel-header">
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <span role="img" aria-label="brain">🧠</span>
                                <strong>Coach</strong>
                                <span className={`status-dot ${coachLoading ? 'busy' : coachData ? 'ok' : coachError ? 'err' : 'idle'}`} />
                            </div>
                            <div className="panel-meta small dim">
                                Explanations and ideas for the current position.
                            </div>
                        </div>

                        <div className="coach-actions" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                            <button
                                className="btn"
                                onClick={handleAskCoach}
                                disabled={coachLoading || !pgnMoves?.length}
                                title="Send FEN + move history to Coach"
                            >
                                {coachLoading ? "Analyzing…" : "Ask Coach"}
                            </button>
                            <button
                                className="btn ghost"
                                onClick={() => setCoachOpen(o => !o)}
                                title={coachOpen ? "Collapse" : "Expand"}
                            >
                                {coachOpen ? "Hide" : "Show"}
                            </button>
                            <span className="small dim">Sends FEN + moves</span>
                        </div>

                        {coachOpen && (
                            <>
                                {/* Loading skeleton */}
                                {coachLoading && (
                                    <div className="coach-skeleton">
                                        <div className="sk-line" />
                                        <div className="sk-line" />
                                        <div className="sk-line short" />
                                    </div>
                                )}

                                {/* Error */}
                                {!coachLoading && coachError && (
                                    <div className="coach-error">
                                        <strong>Error:</strong> {coachError}
                                        <div className="small dim" style={{ marginTop: 6 }}>
                                            Is the backend running? Expected POST <code>/api/coach</code>.
                                        </div>
                                    </div>
                                )}

                                {/* Data */}
                                {!coachLoading && !coachError && coachData && (
                                    <div className="coach-result">
                                        {coachData.opening && (
                                            <div className="coach-row">
                                                <span className="pill">Opening</span>
                                                <div className="mono">{coachData.opening}</div>
                                            </div>
                                        )}
                                        {coachData.eval && (
                                            <div className="coach-row">
                                                <span className="pill">Eval</span>
                                                <div className="mono">{coachData.eval}</div>
                                            </div>
                                        )}
                                        {coachData.ideas?.length > 0 && (
                                            <div className="coach-row">
                                                <span className="pill">Ideas</span>
                                                <ul className="coach-list">
                                                    {coachData.ideas.map((t, i) => <li key={i}>{t}</li>)}
                                                </ul>
                                            </div>
                                        )}
                                        {coachData.note && (
                                            <div className="small dim" style={{ marginTop: 8 }}>
                                                {coachData.note}
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* Payload preview (dev only) */}
                                {!coachLoading && !coachData && !coachError && (
                                    <details className="coach-payload">
                                        <summary className="small">Payload preview</summary>
                                        <pre>{JSON.stringify(coachPayload, null, 2)}</pre>
                                    </details>
                                )}
                            </>
                        )}
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
