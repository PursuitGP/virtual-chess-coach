import React, { useMemo, useState } from "react";
import Chessground from "react-chessground";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import "./App.css";
import { Chess } from "chess.js";
import PGNLoader from "./PGNLoader";
import { useEffect } from "react";
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

function isTyping(node) {
  if (!node) return false;
  const tag = (node.tagName || "").toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    node.isContentEditable
  );
}

function computeDests(chess) {
  const dests = new Map();
  for (const s of ALL_SQUARES) {
    const moves = chess.moves({ square: s, verbose: true });
    if (moves.length)
      dests.set(
        s,
        moves.map((m) => m.to)
      );
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
  const [game, setGame] = useState(() => new Chess());
  const [fen, setFen] = useState(() => game.fen());
  const [orientation, setOrientation] = useState("white");
  const [lastMove, setLastMove] = useState(null);
  const [displayHistory, setDisplayHistory] = useState([]); // SAN tokens

  // PGN state
  const [pgnHeaders, setPgnHeaders] = useState(null);
  const [pgnMoves, setPgnMoves] = useState([]); // verbose
  const [plyIndex, setPlyIndex] = useState(0);
  const [pgnOpen, setPgnOpen] = useState(false);

  //Eval
  //Eval
  const [evaluation, setEvaluation] = useState(0); // numeric for bar height
  const [allEvaluations, setAllEvaluations] = useState([]);
  const [evalLabel, setEvalLabel] = useState("0.00"); // text shown on bar

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
    const gameCopy = new Chess(game.fen());
    const move = gameCopy.move({ from, to, promotion: "q" });
    if (move) {
      setLastMove([from, to]);
      syncFrom(gameCopy);
      //analyzePosition(gameCopy.fen()); // ask backend for eval after each move
    }
  }

  function resetBoard() {
    const fresh = new Chess();
    syncFrom(fresh);
    setPlyIndex(0);
    setLastMove(null);
    setEvaluation(0); // reset the eval bar
  }

  function flipBoard() {
    setOrientation((o) => (o === "white" ? "black" : "white"));
  }

  function stepTo(index) {
    const target = Math.max(0, Math.min(index, pgnMoves.length));
    const replay = new Chess();
    for (let i = 0; i < target; i++) replay.move(pgnMoves[i]);

    setLastMove(
      target > 0 ? [pgnMoves[target - 1].from, pgnMoves[target - 1].to] : null
    );
    setPlyIndex(target);
    syncFrom(replay);

    // 🔥 Use the *explicit* ply we just computed
    testMotifsAndAPI(replay.fen(), target);

    // ✅ Evaluation logic already uses `target`
    const evalForMove = allEvaluations[target - 1];

    let numeric = 0;
    let label = "0.00";

    if (evalForMove) {
      numeric = typeof evalForMove.score === "number" ? evalForMove.score : 0;

      const sfRaw = evalForMove.sf_raw;

      if (sfRaw && sfRaw.type === "mate") {
        const v = typeof sfRaw.value === "number" ? sfRaw.value : 0;

        if (v === 0) {
          let sideToMove = "w";
          try {
            const parts = evalForMove.fen.split(" ");
            sideToMove = parts[1] === "b" ? "b" : "w";
          } catch {}

          const winner = sideToMove === "w" ? "black" : "white";

          label = winner === "white" ? "#W" : "#B";
          numeric = winner === "white" ? 10 : -10;
        } else {
          const n = Math.abs(v);
          const side = v > 0 ? "white" : "black";

          label = side === "white" ? `M${n}` : `-M${n}`;
          numeric = side === "white" ? 10 : -10;
        }
      } else if (
        typeof evalForMove.eval === "string" &&
        /^-?M\d+$/i.test(evalForMove.eval.trim())
      ) {
        label = evalForMove.eval.trim();
      } else {
        label = (numeric >= 0 ? "+" : "") + numeric.toFixed(2);
      }
    }

    setEvaluation(numeric);
    setEvalLabel(label);
  }
  // classify each move by drop severity (in pawn units)
  // --- Review Graph Computation ---

  const iconForColor = (color) => {
    if (color === "#00ff00") return "✅"; // good move
    if (color === "#ffd700") return "❓"; // inaccuracy
    if (color === "#ff8c00") return "?!"; // mistake
    if (color === "#ff0000") return "❌"; // blunder
    return "";
  };
  const points = useMemo(() => {
    return allEvaluations.map((e, i) => {
      if (i === 0) return { x: i + 1, y: e.score, color: "#00ff00" }; // start
      const prev = allEvaluations[i - 1]?.score ?? 0;
      const delta = e.score - prev;
      const drop = Math.abs(delta);

      let color = "#00ff00"; // green: good move
      if (drop > 0.5 && drop <= 1.5) color = "#ffd700"; // yellow: inaccuracy
      else if (drop > 1.5 && drop <= 3.0) color = "#ff8c00"; // orange: mistake
      else if (drop > 3.0) color = "#ff0000"; // red: blunder

      return { x: i + 1, y: e.score, color };
    });
  }, [allEvaluations]);

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

  /*  function nextPly() {
  if (plyIndex < pgnMoves.length) {
    const newPly = plyIndex + 1;
    const replay = new Chess();
    for(let i = 0; i < newPly; i++) {
      replay.move(pgnMoves[i]);
    }
    syncFrom(replay);
    setPlyIndex(newPly);
   // analyzePosition(replay.fen());
  }
}

   // function prevPly() { safeStepTo(plyIndex - 1); }
   function prevPly() {
  if (plyIndex > 0) {
    const newPly = plyIndex - 1;
    const replay = new Chess();
    for (let i = 0; i < newPly; i++) {
      replay.move(pgnMoves[i]);
    }
    syncFrom(replay);
    setPlyIndex(newPly);
    analyzePosition(replay.fen()); // ✅ update eval
  }
}


    function goToStart() { safeStepTo(0); }
    function goToEnd() { safeStepTo(pgnMoves.length); }
*/
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
  // --- Gemini Explanations state ---
  const [geminiLoading, setGeminiLoading] = useState(false);
  const [geminiError, setGeminiError] = useState(null);
  const [geminiMoves, setGeminiMoves] = useState(null);

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
          title: { display: true, text: "Ply (w/b)" },
          ticks: {
            color: "#ccc",
            stepSize: 1,
            callback: (value) => {
              const ply = Number(value);
              if (!Number.isFinite(ply) || ply < 1) return "";
              const fullMove = Math.ceil(ply / 2);
              const isWhite = ply % 2 === 1;
              // 1w, 1b, 2w, 2b, ...
              return isWhite ? `${fullMove}w` : `${fullMove}b`;
            },
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
          annotations:
            plyIndex > 0
              ? {
                  current: {
                    type: "line",
                    xMin: plyIndex,
                    xMax: plyIndex,
                    borderColor: "cyan",
                    borderWidth: 2,
                  },
                }
              : {},
        },
      },
      responsive: true,
      maintainAspectRatio: false,
    }),
    [allEvaluations.length, plyIndex]
  );

  // Build the payload we’ll send (FEN + SAN history up to current ply)
  const coachPayload = React.useMemo(() => {
    const movesSoFar = Array.isArray(displayHistory)
      ? displayHistory.slice(
          0,
          Math.max(0, Math.min(displayHistory.length, plyIndex))
        )
      : [];
    return {
      fen,
      moves: movesSoFar, // SAN list
      ply: plyIndex,
      headers: pgnHeaders || {}, // Event, Site, White, Black, etc.
    };
  }, [fen, displayHistory, plyIndex, pgnHeaders]);

  //Backend//

  const [isEvaluating, setIsEvaluating] = useState(false);

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

      if (data.evaluations) {
        setAllEvaluations(data.evaluations);

        // 🔥 AUTO-GENERATE GEMINI EXPLANATIONS
        if (data.evaluations?.length) {
          generateGeminiExplanations(pgnHeaders?.Raw || "", data.evaluations);
        }

        const first = data.evaluations[0];

        let numeric = 0;
        let label = "0.00";

        if (first) {
          numeric = typeof first.score === "number" ? first.score : 0;

          const sfRaw = first.sf_raw;

          function fenToMoveTurn(fen) {
            try {
              return fen.split(" ")[1] === "w" ? "w" : "b";
            } catch {
              return "w";
            }
          }

          // Prefer raw Stockfish mate info if present
          // ----- MATE EVAL -----
          if (sfRaw && sfRaw.type === "mate") {
            const v = typeof sfRaw.value === "number" ? sfRaw.value : 0;

            // Use the ACTUAL replayed FEN (correct position)
            let sideToMove = "w";

            if (v === 0) {
              // Mate delivered on this move
              const winner = sideToMove === "w" ? "black" : "white";
              numeric = winner === "white" ? 10 : -10;
              label = winner === "white" ? "#W" : "#B";
            } else {
              // Mate-in-N
              const n = Math.abs(v);
              const side = v > 0 ? "white" : "black";
              numeric = side === "white" ? 10 : -10;
              label = side === "white" ? `M${n}` : `-M${n}`;
            }

            setEvaluation(numeric);
            setEvalLabel(label);
            return;
          }
        }

        setEvaluation(numeric);
        setEvalLabel(label);

        const fresh = new Chess();
        syncFrom(fresh);
      } else {
        console.error("No evaluations returned:", data);
      }
    } catch (err) {
      console.error("Error uploading PGN:", err);
    } finally {
      setIsEvaluating(false);
    }
  }

  async function generateGeminiExplanations(fullPGN, evaluations) {
    setGeminiLoading(true);
    setGeminiError(null);
    setGeminiMoves(null);

    try {
      const body = {
        pgn: fullPGN || "",
        evaluations,
      };

      const res = await fetch("http://127.0.0.1:5000/api/gemini_explanations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();
      if (data.error) throw new Error(data.error);

      setGeminiMoves(data.explanations);
    } catch (err) {
      console.error("Gemini error:", err);
      setGeminiError(err.message || "Gemini explanation failed.");
    } finally {
      setGeminiLoading(false);
    }
  }

  async function analyzePosition(currentFen) {
    setCoachLoading(true);
    try {
      const res = await fetch("http://127.0.0.1:5000/api/coach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen: currentFen }),
      });

      const data = await res.json();
      if (data.error) {
        console.error("Backend error:", data.error);
        return;
      }

      // Convert eval string to numeric bar value
      let evalValue = 0;
      let label = "0.00";

      if (data.eval && data.eval.includes("Mate")) {
        const m = data.eval.match(/-?\d+/);
        if (m) {
          const n = parseInt(m[0], 10);
          label = n < 0 ? `-M${Math.abs(n)}` : `M${n}`;
          evalValue = n < 0 ? -10 : 10;
        } else {
          label = "M";
          evalValue = 10;
        }
      } else if (data.eval) {
        evalValue = parseFloat(data.eval);
        if (Math.abs(evalValue) > 10) evalValue = evalValue / 100;
        label = (evalValue >= 0 ? "+" : "") + evalValue.toFixed(2);
      }

      setEvaluation(evalValue);
      setEvalLabel(label);

      console.log("Eval:", evalValue, "Best move:", data.best_move);
    } catch (err) {
      console.error("Error calling backend:", err);
    } finally {
      setCoachLoading(false);
    }
  }

  async function updateEvaluation(fen) {
    try {
      const res = await fetch("http://127.0.0.1:5000/api/coach", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen }),
      });
      const data = await res.json();
      if (data.eval) setEvaluation(parseFloat(data.eval));
    } catch (err) {
      console.error("Eval fetch failed:", err);
    }
  }

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
      await new Promise((r) => setTimeout(r, 700));
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

  async function handleExplainGame() {
    if (!allEvaluations.length) return;

    setGeminiLoading(true);
    setGeminiError(null);
    setGeminiMoves(null);

    try {
      const body = {
        pgn: pgnHeaders?.Raw || "", // PGNLoader gives full PGN or we leave blank
        evaluations: allEvaluations,
      };

      const res = await fetch("http://127.0.0.1:5000/api/gemini_explanations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();
      if (data.error) throw new Error(data.error);

      setGeminiMoves(data.explanations);
    } catch (err) {
      console.error("Gemini error:", err);
      setGeminiError(err.message || "Gemini explanation failed.");
    } finally {
      setGeminiLoading(false);
    }
  }

  // --- Motif & Lichess Test Panel ---
  const [motifInfo, setMotifInfo] = useState(null);
  const [motifLoading, setMotifLoading] = useState(false);
  const [motifError, setMotifError] = useState(null);

  // Set this to whatever you want (default 20)
  const MIN_GAMES_THRESHOLD = 20;

  async function testMotifsAndAPI(fen, ply) {
    setMotifLoading(true);
    setMotifError(null);
    setMotifInfo(null);

    try {
      console.log("Testing motifs for:", fen, "at ply", ply);

      // Use the explicit ply corresponding to THIS FEN
      const last = ply > 0 ? pgnMoves[ply - 1] : null;
      const prev = ply > 1 ? pgnMoves[ply - 2] : null;
      // NEW: compute previous Fen
      let prevFen = null;
      if (ply > 0) {
        const replayPrev = new Chess();
        for (let i = 0; i < ply - 1; i++) replayPrev.move(pgnMoves[i]);
        prevFen = replayPrev.fen();
      }

      const lastUci = last && last.from && last.to ? last.from + last.to : null;

      const prevUci = prev && prev.from && prev.to ? prev.from + prev.to : null;

      const evalForMove = ply > 0 ? allEvaluations[ply - 1] || {} : {};
      const numericEval =
        typeof evalForMove.score === "number" ? evalForMove.score : 0;
      const sfRaw = evalForMove.sf_raw || null;

      const motifPayload = {
        fen,
        prev_fen: prevFen, // <----- NEW
        last_move_uci: lastUci,
        prev_move_uci: prevUci,
        eval: numericEval,
        sf_raw: sfRaw,
        move_number: ply,
      };

      const motifRes = await fetch("http://127.0.0.1:5000/api/motifs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(motifPayload),
      });

      const motifData = await motifRes.json();

      // Lichess masters explorer
      const encodedFen = encodeURIComponent(fen);
      const lichessRes = await fetch(
        `https://explorer.lichess.ovh/masters?fen=${encodedFen}&moves=10`
      );
      const lichessData = await lichessRes.json();

      const totalGames =
        (lichessData.white || 0) +
        (lichessData.black || 0) +
        (lichessData.draws || 0);

      const meetsThreshold = totalGames >= MIN_GAMES_THRESHOLD;

      setMotifInfo({
        fen,
        motifs: motifData.motifs || [],
        lichess: lichessData,
        totalGames,
        meetsThreshold,
      });
    } catch (err) {
      console.error(err);
      setMotifError(err.message || "Motif tester failed");
    } finally {
      setMotifLoading(false);
    }
  }

  return (
    <div className="container wide">
      <h1 style={{ marginBottom: 12 }}>♜ Virtual Chess Coach</h1>

      <div className="badge" style={{ marginBottom: 12 }}>
        <span>Turn:&nbsp;</span>
        <strong>{turnColor === "white" ? "White" : "Black"}</strong>
      </div>

      <div className="grid grid-2">
        {/* LEFT COLUMN */}
        <div className="card">
          {/* Control Dashboard */}
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
            <button onClick={nextPly} disabled={plyIndex >= pgnMoves.length}>
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
            <span>
              <kbd className="kbd">←</kbd>/<kbd className="kbd">→</kbd> step
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

          {/* Evaluation Bar + Board */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "8px",
              marginTop: "16px",
            }}
          >
            {/* Eval label */}
            <div
              style={{
                minWidth: 48,
                textAlign: "right",
                fontSize: "16px",
                fontWeight: "bold",
              }}
            >
              {evalLabel}
            </div>

            {/* Evaluation Bar */}
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
                  height: `${Math.min(100, Math.max(0, 50 + evaluation * 5))}%`,
                  transition: "height 0.3s ease",
                }}
              />
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
              movable={{ free: false, color: "both", dests, showDests: true }}
              onMove={onMove}
            />
          </div>

          {/* STOCKFISH GRAPH */}
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

          {/* --- MOTIF / API TEST PANEL (unchanged except location) --- */}
          <div
            className="card"
            style={{ marginTop: 16, background: "#111", padding: 12 }}
          >
            <h3 style={{ marginBottom: 8 }}>🔍 Motif + API Test</h3>

            {motifLoading && (
              <p style={{ color: "orange" }}>Checking motifs...</p>
            )}
            {motifError && <p style={{ color: "red" }}>❌ {motifError}</p>}

            {motifInfo && (
              <div style={{ fontSize: "0.85em", color: "#ccc" }}>
                <p>
                  <strong>FEN:</strong> {motifInfo.fen}
                </p>
                <p>
                  <strong>Master DB games:</strong> {motifInfo.totalGames}
                </p>

                {motifInfo.meetsThreshold ? (
                  <p style={{ color: "lightgreen" }}>
                    ✔ Meets min threshold ({MIN_GAMES_THRESHOLD})
                  </p>
                ) : (
                  <p style={{ color: "yellow" }}>
                    ⚠ Not enough master games (need {MIN_GAMES_THRESHOLD})
                  </p>
                )}

                <hr style={{ opacity: 0.2 }} />

                <p>
                  <strong>Detected motifs:</strong>
                </p>
                {motifInfo.motifs.length ? (
                  <ul>
                    {motifInfo.motifs.map((m, i) => (
                      <li key={i} style={{ marginBottom: "6px" }}>
                        <strong>{m.name}</strong> — {m.explanation}
                        <br />
                        <span style={{ fontSize: "0.8em", opacity: 0.7 }}>
                          {m.side} • {m.severity} • Δ {m.eval_delta_cp}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p style={{ opacity: 0.6 }}>No motifs detected.</p>
                )}

                <hr style={{ opacity: 0.2 }} />

                <p style={{ opacity: 0.7 }}>Raw Lichess DB Response (debug):</p>
                <pre
                  style={{
                    maxHeight: 150,
                    overflowY: "auto",
                    background: "#000",
                    padding: 8,
                    borderRadius: 4,
                    color: "#0f0",
                  }}
                >
                  {JSON.stringify(motifInfo.lichess, null, 2)}
                </pre>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="card">
          {/* --- COLLAPSIBLE PGN LOADER --- */}
          <div
            onClick={() => setPgnOpen((o) => !o)}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              padding: "10px 12px",
              background: "#222",
              borderRadius: 6,
              cursor: "pointer",
              userSelect: "none",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span role="img" aria-label="folder">
                📂
              </span>
              <strong>PGN Loader</strong>
            </div>

            <span style={{ fontSize: "18px", opacity: 0.8 }}>
              {pgnOpen ? "▾" : "▸"}
            </span>
          </div>

          {pgnOpen && (
            <div
              className="card"
              style={{ background: "#111", padding: 12, marginTop: 12 }}
            >
              {pgnHeaders && (
                <div className="pgn-meta" style={{ marginBottom: 10 }}>
                  <div>
                    <strong>{pgnHeaders.White || "White"}</strong> vs{" "}
                    <strong>{pgnHeaders.Black || "Black"}</strong>
                  </div>
                  <div>
                    {pgnHeaders.Event || "Event"} • {pgnHeaders.Site || "Site"}{" "}
                    • {pgnHeaders.Date || "Date"} • {pgnHeaders.Result || ""}
                  </div>
                </div>
              )}

              <PGNLoader onParsed={onPGNParsed} />

              {isEvaluating && (
                <p style={{ color: "orange" }}>
                  🔄 Evaluating entire PGN... please wait.
                </p>
              )}
              {!isEvaluating && allEvaluations.length > 0 && (
                <p style={{ color: "green" }}>✅ PGN fully evaluated!</p>
              )}

              <div style={{ marginTop: 12 }}>
                <label>Current FEN</label>
                <input readOnly value={fen} />
              </div>
            </div>
          )}

          {/* --- COACH SIDEBAR --- */}
          <div className="card coach-card" style={{ marginTop: 16 }}>
            <div className="panel-header">
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span role="img" aria-label="brain">
                  🧠
                </span>
                <strong>Coach</strong>
                <span
                  className={`status-dot ${
                    coachLoading
                      ? "busy"
                      : coachData
                      ? "ok"
                      : coachError
                      ? "err"
                      : "idle"
                  }`}
                />
              </div>
              <div className="panel-meta small dim">
                Explanations and ideas for the current position.
              </div>
            </div>

            {/* Gemini Explanations */}
            <div
              className="card"
              style={{ marginTop: 12, background: "#111", padding: 12 }}
            >
              <h3 style={{ marginBottom: 8 }}>🤖 Full Game Explanation</h3>

              {geminiLoading && (
                <p style={{ color: "orange" }}>Gemini is thinking...</p>
              )}

              {geminiError && <p style={{ color: "red" }}>❌ {geminiError}</p>}

              {geminiMoves &&
                plyIndex > 0 &&
                plyIndex <= geminiMoves.length && (
                  <div style={{ marginTop: 4 }}>
                    <p style={{ whiteSpace: "pre-wrap" }}>
                      {geminiMoves[plyIndex - 1]}
                    </p>
                  </div>
                )}

              {geminiMoves &&
                plyIndex === 0 &&
                !geminiLoading &&
                !geminiError && (
                  <p className="small" style={{ color: "#aaa", marginTop: 4 }}>
                    Step through the moves (← / →) to see explanations.
                  </p>
                )}
            </div>

            {/* Coach Actions */}
            <div
              className="coach-actions"
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                marginBottom: 8,
              }}
            >
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
                onClick={() => setCoachOpen((o) => !o)}
                title={coachOpen ? "Collapse" : "Expand"}
              >
                {coachOpen ? "Hide" : "Show"}
              </button>
              <span className="small dim">Sends FEN + moves</span>
            </div>

            {/* Coach Expanded */}
            {coachOpen && (
              <>
                {coachLoading && (
                  <div className="coach-skeleton">
                    <div className="sk-line" />
                    <div className="sk-line" />
                    <div className="sk-line short" />
                  </div>
                )}

                {!coachLoading && coachError && (
                  <div className="coach-error">
                    <strong>Error:</strong> {coachError}
                    <div className="small dim" style={{ marginTop: 6 }}>
                      Is the backend running? Expected POST{" "}
                      <code>/api/coach</code>.
                    </div>
                  </div>
                )}

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
                          {coachData.ideas.map((t, i) => (
                            <li key={i}>{t}</li>
                          ))}
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

                {!coachLoading && !coachData && !coachError && (
                  <details className="coach-payload">
                    <summary className="small">Payload preview</summary>
                    <pre>{JSON.stringify(coachPayload, null, 2)}</pre>
                  </details>
                )}
              </>
            )}
          </div>

          {/* MOVE HISTORY */}
          <div className="history" style={{ marginTop: 16 }}>
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
