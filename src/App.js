import WelcomePage from "./WelcomePage";
import React, { useMemo, useState, useEffect } from "react";
import Chessground from "react-chessground";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./App.css";
import { Chess } from "chess.js";
import PGNLoader from "./PGNLoader";
import { Line } from "react-chartjs-2";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
} from "chart.js";
import annotationPlugin from "chartjs-plugin-annotation";

ChartJS.register(
  CategoryScale,
  LinearScale,
  LineElement,
  PointElement,
  Tooltip,
  Legend,
  annotationPlugin
);

const FILES = ["a", "b", "c", "d", "e", "f", "g", "h"];
const RANKS = ["1", "2", "3", "4", "5", "6", "7", "8"];
const ALL_SQUARES = FILES.flatMap((f) => RANKS.map((r) => f + r));

function computeDests(chess) {
  const dests = new Map();
  for (const s of ALL_SQUARES) {
    const moves = chess.moves({ square: s, verbose: true });
    if (moves.length) dests.set(s, moves.map((m) => m.to));
  }
  return dests;
}

// Format SAN array into full-move pairs: [{num, white, black}]
function sanToPairs(sanList) {
  const out = [];
  for (let i = 0; i < sanList.length; i += 2) {
    out.push({
      num: Math.floor(i / 2) + 1,
      white: sanList[i],
      black: sanList[i + 1] || "",
    });
  }
  return out;
}

export default function App() {
  const [showWelcome, setShowWelcome] = useState(true);

  const [game, setGame] = useState(() => new Chess());
  const [fen, setFen] = useState(() => game.fen());
  const [orientation, setOrientation] = useState("white");
  const [lastMove, setLastMove] = useState(null);
  const [displayHistory, setDisplayHistory] = useState([]); // SAN tokens

  // PGN & replay
  const [pgnHeaders, setPgnHeaders] = useState(null);
  const [pgnMoves, setPgnMoves] = useState([]); // verbose from PGNLoader
  const [plyIndex, setPlyIndex] = useState(0);

  // Engine evals
  const [evaluation, setEvaluation] = useState(0); // current position eval in pawns
  const [allEvaluations, setAllEvaluations] = useState([]); // list from backend

  // Gemini per-move summaries
  const [geminiLoading, setGeminiLoading] = useState(false);
  const [geminiError, setGeminiError] = useState(null);
  const [geminiSummaries, setGeminiSummaries] = useState([]); // one summary per ply
  const [geminiProgress, setGeminiProgress] = useState({ done: 0, total: 0 });

  // Board size
  const [boardSize, setBoardSize] = useState(600);

  // Backend loading flag for PGN evaluation
  const [isEvaluating, setIsEvaluating] = useState(false);

  const dests = useMemo(() => computeDests(game), [game, fen]);
  const turnColor = game.turn() === "w" ? "white" : "black";

  function syncFrom(ch) {
    setGame(ch);
    setFen(ch.fen());
    setDisplayHistory(ch.history()); // SAN list
  }

  function onMove(from, to) {
    const ch = new Chess(game.fen());
    const mv = ch.move({ from, to, promotion: "q" });
    if (mv) {
      setLastMove([from, to]);
      syncFrom(ch);
      // (Optional) could call /api/coach here for "live" eval of casual moves
    }
  }

  function resetBoard() {
    const fresh = new Chess();
    syncFrom(fresh);
    setPlyIndex(0);
    setLastMove(null);
    setEvaluation(0);
  }

  function flipBoard() {
    setOrientation((o) => (o === "white" ? "black" : "white"));
  }

  function stepTo(index) {
    const target = Math.max(0, Math.min(index, pgnMoves.length));
    const replay = new Chess();
    for (let i = 0; i < target; i++) {
      replay.move(pgnMoves[i]);
    }

    setLastMove(
      target > 0 ? [pgnMoves[target - 1].from, pgnMoves[target - 1].to] : null
    );
    setPlyIndex(target);
    syncFrom(replay);

    // Update eval bar using precomputed evaluations
    if (target === 0 || !allEvaluations.length) {
      setEvaluation(0);
    } else {
      const ev = allEvaluations[target - 1];
      const val =
        ev && ev.score !== undefined && ev.score !== null
          ? Number(ev.score)
          : 0;
      setEvaluation(val);
    }
  }

  function nextPly() {
    stepTo(plyIndex + 1);
  }
  function prevPly() {
    stepTo(plyIndex - 1);
  }
  function goToStart() {
    stepTo(0);
  }
  function goToEnd() {
    stepTo(pgnMoves.length);
  }

  const movePairs = sanToPairs(displayHistory);

  // --- Review graph data ---
  const points = useMemo(() => {
    if (!allEvaluations.length) return [];

    return allEvaluations.map((e, i) => {
      const scoreNow = Number(e.score ?? 0);
      if (i === 0) {
        return { x: 1, y: scoreNow, color: "#00ff00" }; // first move
      }
      const prev = Number(allEvaluations[i - 1]?.score ?? 0);
      const delta = scoreNow - prev;
      const drop = Math.abs(delta);

      let color = "#00ff00"; // good
      if (drop > 0.5 && drop <= 1.5) color = "#ffd700"; // inaccuracy
      else if (drop > 1.5 && drop <= 3.0) color = "#ff8c00"; // mistake
      else if (drop > 3.0) color = "#ff0000"; // blunder

      return { x: i + 1, y: scoreNow, color };
    });
  }, [allEvaluations]);

  const chartData = {
    datasets: [
      {
        label: "Evaluation",
        data: points,
        borderColor: "#ffffff",
        borderWidth: 2,
        tension: 0.3,
        fill: {
          target: "origin",
          above: "rgba(255,255,255,0.15)",
          below: "rgba(0,0,0,0.25)",
        },
        pointRadius: 5,
        pointBackgroundColor: points.map((p) => p.color),
      },
    ],
  };

  const chartOptions = useMemo(
    () => ({
      animation: { duration: 400 },
      scales: {
        x: {
          type: "linear",
          min: 1,
          max: allEvaluations.length || 1,
          grid: { display: false },
          title: { display: true, text: "Moves" },
          ticks: {
            color: "#ccc",
            stepSize: 2,
          },
        },
        y: {
          min: -10,
          max: 10,
          grid: { color: "rgba(255,255,255,0.1)" },
          ticks: { color: "#ccc" },
        },
      },
      plugins: {
        legend: { display: false },
        annotation: {
          annotations: {
            current: {
              type: "line",
              xMin: plyIndex + 1,
              xMax: plyIndex + 1,
              borderColor: "cyan",
              borderWidth: 2,
            },
          },
        },
      },
      responsive: true,
      maintainAspectRatio: false,
    }),
    [allEvaluations.length, plyIndex]
  );

  // --- Keyboard navigation ---
  useEffect(() => {
    const isTyping = (el) => {
      if (!el) return false;
      const tag = (el.tagName || "").toLowerCase();
      return (
        tag === "input" ||
        tag === "textarea" ||
        tag === "select" ||
        el.isContentEditable
      );
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
        case "r":
        case "R":
          e.preventDefault();
          resetBoard();
          break;
        case "f":
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
  }, [prevPly, nextPly, goToEnd, resetBoard, flipBoard]);

  // --- Which Gemini summary do we show for current ply? ---
  const currentSummaryIndex =
    geminiSummaries.length > 0
      ? Math.max(0, Math.min(plyIndex - 1, geminiSummaries.length - 1))
      : -1;

  const currentGeminiSummary =
    currentSummaryIndex >= 0 ? geminiSummaries[currentSummaryIndex] : "";

  // --- PGN upload handler ---
  async function onPGNParsed({ headers, moves, file }) {
    setIsEvaluating(true);
    setPgnHeaders(headers || {});
    setPgnMoves(Array.isArray(moves) ? moves : []);
    setPlyIndex(0);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("http://127.0.0.1:5000/api/evaluate_pgn", {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      console.log("evaluate_pgn response:", data);

      if (data.evaluations) {
        setAllEvaluations(data.evaluations);
        const firstScore =
          data.evaluations[0] && data.evaluations[0].score != null
            ? Number(data.evaluations[0].score)
            : 0;
        setEvaluation(firstScore);

        // preload starting board
        const fresh = new Chess();
        syncFrom(fresh);

        // kick off Gemini per-move explanations
        askGemini(data.evaluations);
      } else {
        console.error("No evaluations returned:", data);
      }
    } catch (err) {
      console.error("Error uploading PGN:", err);
    } finally {
      setIsEvaluating(false);
    }
  }

  // --- Gemini per-move explanations (first 15 full moves / 30 plies) ---
  async function askGemini(evaluations) {
    if (!evaluations || !evaluations.length) return;

    // Restrict to first 30 plies (15 full moves)
    const limited = evaluations.slice(0, 30);

    setGeminiLoading(true);
    setGeminiError(null);
    setGeminiSummaries(Array(limited.length).fill(null));
    setGeminiProgress({ done: 0, total: limited.length });

    const newSummaries = Array(limited.length).fill(null);

    for (let i = 0; i < limited.length; i++) {
      const ev = limited[i];

      const scoreAfter = Number(ev.score ?? 0);
      const scoreBefore =
        i > 0 ? Number(limited[i - 1]?.score ?? 0) : 0;

      const fullMoveNumber = Math.floor(i / 2) + 1;
      const color = i % 2 === 0 ? "White" : "Black";

      const san =
        ev.san ||
        `Move ${fullMoveNumber} (${color})`;

      const bestMove = ev.best_move || null;
      const motifs = ev.motifs || [];

      try {
        const res = await fetch("http://127.0.0.1:5000/api/gemini_move", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            move_index: i,
            full_move_number: fullMoveNumber,
            color,
            san,
            score_before: scoreBefore,
            score_after: scoreAfter,
            best_move: bestMove,
            motifs,
          }),
        });

        const data = await res.json();

        if (!res.ok || data.error) {
          console.error("Gemini move error:", data.error || res.status);
          // Only show a generic error once, but keep going for other moves
          setGeminiError(
            (prev) =>
              prev ||
              (res.status === 429
                ? "Gemini quota or rate limit exceeded. Some moves were not analyzed."
                : "Gemini could not analyze some moves.")
          );
          newSummaries[i] = null;
        } else {
          newSummaries[i] = data.summary;
        }
      } catch (err) {
        console.error("Gemini fetch failed:", err);
        setGeminiError(
          (prev) => prev || "Could not reach Gemini backend for some moves."
        );
        newSummaries[i] = null;
      }

      setGeminiSummaries([...newSummaries]);
      setGeminiProgress((prev) => ({ ...prev, done: i + 1 }));

      // small delay to avoid hammering free-tier quota too hard
      await new Promise((res) => setTimeout(res, 250));
    }

    setGeminiLoading(false);
  }

  if (showWelcome) {
    return <WelcomePage onStart={() => setShowWelcome(false)} />;
  }

  return (
    <div className="container wide">
      <h1 style={{ marginBottom: 12 }}>♜ Virtual Chess Coach</h1>

      <div className="badge" style={{ marginBottom: 12 }}>
        <span>Turn:&nbsp;</span>
        <strong>{turnColor === "white" ? "White" : "Black"}</strong>
      </div>

      <div className="grid grid-2">
        {/* LEFT: Board + evals */}
        <div className="card">
          {/* Controls */}
          <div className="controls">
            <button onClick={flipBoard}>Flip board</button>
            <button onClick={resetBoard}>Reset</button>

            <button
              onClick={goToStart}
              disabled={plyIndex === 0}
              title="Skip to start (R)"
            >
              ⏮
            </button>
            <button onClick={prevPly} disabled={plyIndex === 0}>
              ◀
            </button>
            <button
              onClick={nextPly}
              disabled={plyIndex >= pgnMoves.length}
            >
              ▶
            </button>
            <button
              onClick={goToEnd}
              disabled={plyIndex >= pgnMoves.length}
              title="Skip to end (End)"
            >
              ⏭
            </button>

            <span className="small" style={{ marginLeft: 8 }}>
              {pgnMoves.length > 0
                ? `Move ${plyIndex}/${pgnMoves.length}`
                : "No PGN loaded"}
            </span>

            <div className="size-control">
              <label>Board size: {boardSize}px</label>
              <input
                type="range"
                min="480"
                max="720"
                step="10"
                value={boardSize}
                onChange={(e) =>
                  setBoardSize(Number(e.target.value))
                }
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
            <span>
              <kbd className="kbd">←</kbd>/
              <kbd className="kbd">→</kbd> step
            </span>
            <span>
              <kbd className="kbd">End</kbd> skip
            </span>
            <span>
              <kbd className="kbd">R</kbd> reset
            </span>
            <span>
              <kbd className="kbd">F</kbd> flip
            </span>
          </div>

          {/* Evaluation bar + board */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "5px",
              marginTop: "16px",
            }}
          >
            {/* Eval bar */}
            <div
              className="eval-bar-container"
              style={{
                height: `${boardSize}px`,
                width: "40px",
                background: "#000",
                borderRadius: "4px",
                position: "relative",
                overflow: "hidden",
              }}
            >
              <div
                className="eval-bar-fill"
                style={{
                  position: "absolute",
                  bottom: 0,
                  width: "100%",
                  background: "#fff",
                  height: `${Math.min(
                    100,
                    Math.max(0, 50 + evaluation * 5)
                  )}%`,
                  transition: "height 0.3s ease",
                }}
              ></div>

              <div
                style={{
                  position: "absolute",
                  top: `${100 - Math.min(
                    100,
                    Math.max(0, 50 + evaluation * 5)
                  )}%`,
                  width: "100%",
                  fontSize: "15px",
                  textAlign: "center",
                  fontWeight: "bold",
                  color: "#000000ff",
                  textShadow: "0 0 4px rgba(0, 0, 0, 0)",
                }}
              >
                {evaluation > 0
                  ? `+${evaluation.toFixed(2)}`
                  : evaluation.toFixed(2)}
              </div>
            </div>

            {/* Chessboard */}
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
              movable={{
                free: false,
                color: "both",
                dests,
                showDests: true,
              }}
              onMove={onMove}
            />
          </div>

          {/* Review graph */}
          <div
            style={{
              height: 160,
              marginTop: 12,
              background: "#222",
              borderRadius: 6,
              padding: "6px",
            }}
          >
            {allEvaluations.length ? (
              <Line data={chartData} options={chartOptions} />
            ) : (
              <p
                className="small"
                style={{ textAlign: "center", color: "#888" }}
              >
                Load a PGN to see evaluation review graph
              </p>
            )}
          </div>
        </div>

        {/* RIGHT: PGN loader + Gemini + history */}
        <div className="card">
          <div className="panel-header">
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span role="img" aria-label="folder">
                📂
              </span>
              <strong>PGN Loader</strong>
            </div>
            <div className="panel-meta">
              {pgnHeaders && (
                <div className="pgn-meta">
                  <div>
                    <strong>
                      {pgnHeaders.White || "White"}
                    </strong>{" "}
                    vs{" "}
                    <strong>
                      {pgnHeaders.Black || "Black"}
                    </strong>
                  </div>
                  <div>
                    {pgnHeaders.Event || "Event"} •{" "}
                    {pgnHeaders.Site || "Site"} •{" "}
                    {pgnHeaders.Date || "Date"} •{" "}
                    {pgnHeaders.Result || ""}
                  </div>
                </div>
              )}
            </div>
          </div>

          <PGNLoader onParsed={onPGNParsed} />

          {isEvaluating && (
            <p style={{ color: "orange" }}>
              🔄 Evaluating entire PGN... please wait.
            </p>
          )}

          {!isEvaluating && allEvaluations.length > 0 && (
            <p style={{ color: "green" }}>
              ✅ PGN fully evaluated!
            </p>
          )}

          <div style={{ marginTop: 12 }}>
            <label>Current FEN</label>
            <input readOnly value={fen} />
          </div>

          {/* Gemini panel */}
          <div className="card gemini-card" style={{ marginTop: 16 }}>
            <div className="panel-header">
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span role="img" aria-label="sparkles">
                  ✨
                </span>
                <strong>Gemini Move Explanation</strong>
              </div>
              <div className="panel-meta small dim">
                AI explanation for the current move (first 15 full moves).
              </div>
            </div>

            {geminiLoading && (
              <p className="small" style={{ color: "orange" }}>
                🔄 Gemini is analyzing… {geminiProgress.done}/
                {geminiProgress.total}
              </p>
            )}

            {geminiError && (
              <p style={{ color: "red" }}>❌ {geminiError}</p>
            )}

            {!geminiLoading && currentGeminiSummary && (
              <div
                className="gemini-output mono"
                style={{
                  whiteSpace: "pre-wrap",
                  marginTop: "0.75rem",
                }}
              >
                {currentGeminiSummary}
              </div>
            )}

            {!geminiLoading && !currentGeminiSummary && (
              <p
                className="small dim"
                style={{ marginTop: "0.75rem" }}
              >
                No explanation for this move yet. Try stepping to a
                move within the first 15 full moves.
              </p>
            )}
          </div>

          {/* Move history */}
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
