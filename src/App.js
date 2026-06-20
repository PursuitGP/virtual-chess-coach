import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Chessground from "react-chessground";
import "chessground/assets/chessground.base.css";
import "chessground/assets/chessground.brown.css";
import "chessground/assets/chessground.cburnett.css";
import { Chess } from "chess.js";
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

import PGNLoader from "./PGNLoader";
import {
  apiUrl,
  buildExplanationMap,
  evaluationForBar,
  evaluationLabel,
  fullMoveCount,
  movePositionLabel,
  pointColor,
  readJsonResponse,
} from "./analysisUtils";
import "./App.css";

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

function replayMoves(moves, target) {
  const replay = new Chess();
  for (let index = 0; index < target; index += 1) {
    const move = moves[index];
    replay.move({
      from: move.from,
      to: move.to,
      promotion: move.promotion || "q",
    });
  }
  return replay;
}

function movePairs(moves) {
  const pairs = [];
  for (let index = 0; index < moves.length; index += 2) {
    pairs.push({
      number: Math.floor(index / 2) + 1,
      white: moves[index]?.san || "",
      black: moves[index + 1]?.san || "",
    });
  }
  return pairs;
}

function formatPercent(value) {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}

function hasCompleteEvidence(analysis) {
  return Boolean(
    analysis?.providers?.stockfish?.available &&
      analysis?.providers?.lichess?.available &&
      analysis?.providers?.motifs?.available
  );
}

function LichessMove({ label, move }) {
  if (!move) {
    return (
      <div className="evidence-row">
        <span>{label}</span>
        <strong>No matching sample</strong>
      </div>
    );
  }
  return (
    <div className="evidence-row">
      <span>{label}</span>
      <strong>
        {move.san || move.uci} · {formatPercent(move.popularity_pct)}
        <small>
          W {formatPercent(move.white_win_pct)} · D{" "}
          {formatPercent(move.draw_pct)} · B{" "}
          {formatPercent(move.black_win_pct)}
        </small>
      </strong>
    </div>
  );
}

function useBoardSize() {
  const [size, setSize] = useState(560);
  useEffect(() => {
    const resize = () => {
      const available = Math.max(300, window.innerWidth - 64);
      setSize(Math.min(600, available));
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  return size;
}

export default function App() {
  const [game, setGame] = useState(() => new Chess());
  const [orientation, setOrientation] = useState("white");
  const [pgnMoves, setPgnMoves] = useState([]);
  const [pgnHeaders, setPgnHeaders] = useState(null);
  const [plyIndex, setPlyIndex] = useState(0);
  const [pgnOpen, setPgnOpen] = useState(true);

  const [analysis, setAnalysis] = useState(null);
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);

  const [perspective, setPerspective] = useState("both");
  const [ratingGroup, setRatingGroup] = useState("");
  const [coaching, setCoaching] = useState(null);
  const [coachingLoading, setCoachingLoading] = useState(false);
  const [coachingError, setCoachingError] = useState(null);
  const [health, setHealth] = useState(null);
  const [reviewElapsed, setReviewElapsed] = useState(0);

  const reviewRef = useRef(null);
  const requestIdRef = useRef(0);
  const reviewLoading = analysisLoading || coachingLoading;

  const boardSize = useBoardSize();
  const fen = game.fen();
  const turnColor = game.turn() === "w" ? "white" : "black";
  const dests = useMemo(() => computeDests(game), [game]);
  const pairs = useMemo(() => movePairs(pgnMoves), [pgnMoves]);

  const currentRecord =
    plyIndex > 0 ? analysis?.positions?.[plyIndex - 1] || null : null;
  const explanationMap = useMemo(
    () => buildExplanationMap(coaching?.explanations),
    [coaching]
  );
  const currentExplanation = explanationMap.get(plyIndex) || null;

  const lastMove =
    plyIndex > 0 && pgnMoves[plyIndex - 1]
      ? [pgnMoves[plyIndex - 1].from, pgnMoves[plyIndex - 1].to]
      : null;

  const goTo = useCallback(
    (target) => {
      const bounded = Math.max(0, Math.min(target, pgnMoves.length));
      setPlyIndex(bounded);
      setGame(replayMoves(pgnMoves, bounded));
    },
    [pgnMoves]
  );

  useEffect(() => {
    const onKeyDown = (event) => {
      const tag = event.target?.tagName?.toLowerCase();
      if (["input", "textarea", "select"].includes(tag)) return;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        goTo(plyIndex - 1);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        goTo(plyIndex + 1);
      } else if (event.key === "Home") {
        event.preventDefault();
        goTo(0);
      } else if (event.key === "End") {
        event.preventDefault();
        goTo(pgnMoves.length);
      } else if (event.key.toLowerCase() === "f") {
        setOrientation((value) => (value === "white" ? "black" : "white"));
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [goTo, plyIndex, pgnMoves.length]);

  useEffect(() => {
    fetch(apiUrl("/api/health"))
      .then((response) =>
        readJsonResponse(response, "The API health check failed.")
      )
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    if (!reviewLoading) {
      setReviewElapsed(0);
      return undefined;
    }
    const started = Date.now();
    const timer = window.setInterval(() => {
      setReviewElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [reviewLoading]);

  function resetReview() {
    requestIdRef.current += 1;
    setGame(new Chess());
    setPgnMoves([]);
    setPgnHeaders(null);
    setPlyIndex(0);
    setAnalysis(null);
    setAnalysisError(null);
    setCoaching(null);
    setCoachingError(null);
    setPgnOpen(true);
  }

  function moveBoard(from, to) {
    if (pgnMoves.length) return;
    const copy = new Chess(game.fen());
    const move = copy.move({ from, to, promotion: "q" });
    if (move) setGame(copy);
  }

  async function onPGNParsed({ headers, moves, file }) {
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    setPgnHeaders(headers || {});
    setPgnMoves(Array.isArray(moves) ? moves : []);
    setGame(new Chess());
    setPlyIndex(0);
    setAnalysis(null);
    setCoaching(null);
    setCoachingError(null);
    setAnalysisError(null);
    setAnalysisLoading(true);
    setPgnOpen(false);
    window.setTimeout(() => reviewRef.current?.focus(), 0);

    const formData = new FormData();
    formData.append("file", file);
    if (ratingGroup) formData.append("rating_group", ratingGroup);

    try {
      const response = await fetch(apiUrl("/api/analyze"), {
        method: "POST",
        body: formData,
      });
      const data = await readJsonResponse(
        response,
        "The PGN could not be analyzed."
      );
      if (!response.ok) {
        throw new Error(data.error || "The PGN could not be analyzed.");
      }
      if (requestId !== requestIdRef.current) return;
      setAnalysis(data);
      setPgnHeaders(data.metadata || headers || {});
      goTo(0);
      setAnalysisLoading(false);

      if (!hasCompleteEvidence(data)) {
        setCoachingError({
          message:
            "AI coaching requires complete Stockfish, Lichess, and motif evidence.",
          retryable: false,
          code: "evidence_incomplete",
        });
        return;
      }

      await generateCoaching(data, perspective, requestId);
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setAnalysisError(error.message || "The PGN could not be analyzed.");
      setPgnOpen(true);
    } finally {
      if (requestId === requestIdRef.current) {
        setAnalysisLoading(false);
      }
    }
  }

  async function generateCoaching(
    analysisPackage = analysis,
    requestedPerspective = perspective,
    requestId = requestIdRef.current
  ) {
    if (!analysisPackage) return;
    setCoachingLoading(true);
    setCoachingError(null);
    setCoaching(null);

    try {
      const response = await fetch(apiUrl("/api/explain"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          analysis: analysisPackage,
          perspective: requestedPerspective,
        }),
      });
      const data = await readJsonResponse(
        response,
        "AI coaching could not be generated."
      );
      if (!response.ok) {
        const error = new Error(
          data.error || "AI coaching could not be generated."
        );
        error.retryable = data.retryable !== false;
        error.code = data.code;
        throw error;
      }
      if (requestId !== requestIdRef.current) return;
      setCoaching(data);
    } catch (error) {
      if (requestId !== requestIdRef.current) return;
      setCoachingError({
        message: error.message || "AI coaching could not be generated.",
        retryable: error.retryable !== false,
        code: error.code,
      });
    } finally {
      if (requestId === requestIdRef.current) {
        setCoachingLoading(false);
      }
    }
  }

  function changePerspective(value) {
    setPerspective(value);
    setCoaching(null);
    setCoachingError(null);
    if (analysis && hasCompleteEvidence(analysis)) {
      generateCoaching(analysis, value);
    }
  }

  const chartPoints = useMemo(
    () =>
      (analysis?.positions || []).map((record) => ({
        x: record.ply,
        y: evaluationForBar(record.stockfish?.evaluation),
        color: pointColor(record),
      })),
    [analysis]
  );

  const chartData = {
    datasets: [
      {
        label: "Stockfish evaluation",
        data: chartPoints,
        borderColor: "#d8e2dc",
        borderWidth: 2,
        tension: 0.25,
        pointRadius: 4,
        pointBackgroundColor: chartPoints.map((point) => point.color),
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    maintainAspectRatio: false,
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
                  borderColor: "#7dd3fc",
                  borderWidth: 2,
                },
              }
            : {},
      },
    },
    scales: {
      x: {
        type: "linear",
        min: 1,
        max: Math.max(analysis?.analyzed_plies || 1, 1),
        ticks: { color: "#94a3b8", precision: 0 },
        grid: { color: "rgba(148, 163, 184, 0.08)" },
      },
      y: {
        suggestedMin: -5,
        suggestedMax: 5,
        ticks: { color: "#94a3b8" },
        grid: { color: "rgba(148, 163, 184, 0.08)" },
      },
    },
  };

  const barEvaluation = evaluationForBar(
    currentRecord?.stockfish?.evaluation
  );
  const barHeight = Math.min(100, Math.max(0, 50 + barEvaluation * 5));
  const aiAvailable = health?.capabilities?.gemini?.ready;
  const lichessConfigured = health?.capabilities?.lichess?.configured;
  const evidenceComplete = hasCompleteEvidence(analysis);
  const totalFullMoves = fullMoveCount(pgnMoves.length);

  return (
    <main className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Evidence-grounded AI chess analysis</p>
          <h1>Virtual Chess Coach</h1>
          <p className="hero-copy">
            Stockfish calculation, Lichess opening statistics, and custom chess
            motifs become structured evidence for position-specific AI coaching.
          </p>
        </div>
        <div className="pipeline" aria-label="Analysis pipeline">
          <span>PGN</span>
          <b>→</b>
          <span>Evidence</span>
          <b>→</b>
          <span>AI Coach</span>
        </div>
      </header>

      <section className="workspace">
        <div className="board-column">
          <div
            className="panel board-panel"
            ref={reviewRef}
            tabIndex={-1}
          >
            <div className="toolbar">
              <button
                type="button"
                onClick={() =>
                  setOrientation((value) =>
                    value === "white" ? "black" : "white"
                  )
                }
              >
                Flip board
              </button>
              <button type="button" onClick={resetReview}>
                New game
              </button>
              <span className="toolbar-spacer" />
              <button
                type="button"
                onClick={() => goTo(0)}
                disabled={!plyIndex}
                aria-label="Go to start"
              >
                ⏮
              </button>
              <button
                type="button"
                onClick={() => goTo(plyIndex - 1)}
                disabled={!plyIndex}
                aria-label="Previous move"
              >
                ◀
              </button>
              <span className="move-counter">
                {movePositionLabel(plyIndex, pgnMoves.length)}
              </span>
              <button
                type="button"
                onClick={() => goTo(plyIndex + 1)}
                disabled={plyIndex >= pgnMoves.length}
                aria-label="Next move"
              >
                ▶
              </button>
              <button
                type="button"
                onClick={() => goTo(pgnMoves.length)}
                disabled={plyIndex >= pgnMoves.length}
                aria-label="Go to end"
              >
                ⏭
              </button>
            </div>

            <div className="board-wrap">
              <div className="eval-label">
                {evaluationLabel(currentRecord?.stockfish?.evaluation)}
              </div>
              <div className="eval-bar" aria-label="Stockfish evaluation">
                <div
                  className="eval-fill"
                  style={{ height: `${barHeight}%` }}
                />
              </div>
              <Chessground
                width={boardSize}
                height={boardSize}
                orientation={orientation}
                fen={fen}
                turnColor={turnColor}
                lastMove={lastMove}
                animation={{ enabled: true, duration: 180 }}
                highlight={{ lastMove: true, check: true }}
                draggable={{ enabled: !pgnMoves.length }}
                movable={{
                  free: false,
                  color: pgnMoves.length ? undefined : "both",
                  dests,
                  showDests: true,
                }}
                onMove={moveBoard}
              />
            </div>

            <div className="chart-wrap">
              {chartPoints.length ? (
                <Line data={chartData} options={chartOptions} />
              ) : (
                <div className="empty-state">
                  Upload a PGN to build the Stockfish evaluation history.
                </div>
              )}
            </div>
          </div>

          <div className="panel">
            <button
              type="button"
              className="panel-toggle"
              onClick={() => setPgnOpen((value) => !value)}
            >
              <span>PGN intake</span>
              <span>{pgnOpen ? "Hide" : "Show"}</span>
            </button>
            {pgnOpen && (
              <div className="panel-body">
                {pgnHeaders && (
                  <div className="game-heading">
                    <strong>
                      {pgnHeaders.White || "White"} vs{" "}
                      {pgnHeaders.Black || "Black"}
                    </strong>
                    <span>
                      {[pgnHeaders.Event, pgnHeaders.Date, pgnHeaders.Result]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </div>
                )}
                <label htmlFor="rating-group">
                  Compare player choices by Lichess rating pool
                </label>
                <select
                  id="rating-group"
                  value={ratingGroup}
                  onChange={(event) => setRatingGroup(event.target.value)}
                  disabled={analysisLoading}
                >
                  <option value="">All ratings</option>
                  <option value="0">Below 1000</option>
                  <option value="1000">1000–1199</option>
                  <option value="1200">1200–1399</option>
                  <option value="1400">1400–1599</option>
                  <option value="1600">1600–1799</option>
                  <option value="1800">1800–1999</option>
                  <option value="2000">2000–2199</option>
                  <option value="2200">2200–2499</option>
                  <option value="2500">2500+</option>
                </select>
                <p className="muted">
                  Master statistics remain unfiltered. This filter changes the
                  aggregate Lichess player comparison.
                </p>
                <PGNLoader onParsed={onPGNParsed} />
                {analysisLoading && (
                  <div className="notice working">
                    Reviewing {totalFullMoves} chess moves with Stockfish,
                    Lichess, and motif detection…
                  </div>
                )}
                {analysisError && (
                  <div className="notice error">{analysisError}</div>
                )}
                {analysis && !analysisLoading && (
                  <div className="notice success">
                    Analyzed {fullMoveCount(analysis.analyzed_plies)} of{" "}
                    {fullMoveCount(analysis.total_plies)} chess moves.
                    {coachingLoading
                      ? " AI coaching is being generated automatically."
                      : coaching
                        ? " Coaching is ready."
                        : ""}
                  </div>
                )}
                {analysis?.warnings?.map((warning) => (
                  <div className="notice warning" key={warning}>
                    {warning}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <aside className="insight-column">
          <section className="panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Current position</p>
                <h2>Evidence</h2>
              </div>
              {currentRecord && (
                <span className="ply-badge">
                  Move {currentRecord.fullmove_number} ·{" "}
                  {currentRecord.side === "white" ? "White" : "Black"}:{" "}
                  {currentRecord.played_move.san}
                </span>
              )}
            </div>

            {!currentRecord ? (
              <div className="empty-state">
                Step to an analyzed move to inspect its evidence.
              </div>
            ) : (
              <div className="evidence-stack">
                <div className="evidence-block">
                  <h3>Stockfish</h3>
                  <div className="evidence-row">
                    <span>Evaluation</span>
                    <strong>
                      {evaluationLabel(currentRecord.stockfish.evaluation)}
                    </strong>
                  </div>
                  <div className="evidence-row">
                    <span>Change</span>
                    <strong>
                      {currentRecord.stockfish.eval_delta_pawns == null
                        ? "—"
                        : `${currentRecord.stockfish.eval_delta_pawns > 0 ? "+" : ""}${currentRecord.stockfish.eval_delta_pawns.toFixed(2)}`}
                    </strong>
                  </div>
                  <div className="evidence-row">
                    <span>Best move</span>
                    <strong>
                      {currentRecord.stockfish.best_move || "Unavailable"}
                    </strong>
                  </div>
                  <p className="line">
                    Best line:{" "}
                    {(
                      currentRecord.stockfish.top_lines?.[0]?.moves_san ||
                      currentRecord.stockfish.top_lines?.[0]?.moves_uci ||
                      []
                    ).join(" ") || "Unavailable"}
                  </p>
                </div>

                <div className="evidence-block">
                  <h3>Lichess Explorer</h3>
                  <p className="opening-name">
                    {currentRecord.lichess.opening
                      ? `${currentRecord.lichess.opening.eco || ""} ${currentRecord.lichess.opening.name || ""}`.trim()
                      : "No named opening returned"}
                  </p>
                  {currentRecord.lichess.opening_context?.description && (
                    <p className="opening-context">
                      {currentRecord.lichess.opening_context.description}
                    </p>
                  )}
                  <LichessMove
                    label="Master games"
                    move={currentRecord.lichess.masters.played_move}
                  />
                  <LichessMove
                    label="Lichess games"
                    move={currentRecord.lichess.players.played_move}
                  />
                  <p className="line">
                    Classification: {currentRecord.lichess.theory_status}
                  </p>
                  <p className="line">
                    Practical signal:{" "}
                    {currentRecord.lichess.practical_signal?.classification ||
                      "Unavailable"}
                  </p>
                  {currentRecord.lichess.practical_candidates?.length > 0 && (
                    <div className="candidate-list">
                      <strong>Engine-backed practical continuations</strong>
                      {currentRecord.lichess.practical_candidates.map(
                        (candidate) => (
                          <div key={candidate.uci}>
                            <span>
                              #{candidate.stockfish_rank} {candidate.uci}
                            </span>
                            <small>
                              {candidate.label}
                              {candidate.masters
                                ? ` · masters ${formatPercent(
                                    candidate.masters.popularity_pct
                                  )}`
                                : ""}
                              {candidate.players
                                ? ` · players ${formatPercent(
                                    candidate.players.popularity_pct
                                  )}`
                                : ""}
                            </small>
                          </div>
                        )
                      )}
                    </div>
                  )}
                  {lichessConfigured === false && (
                    <p className="notice warning">
                      Add a server-side LICHESS_TOKEN to load master and player
                      statistics.
                    </p>
                  )}
                </div>

                <div className="evidence-block">
                  <h3>Detected concepts</h3>
                  {currentRecord.motifs?.length ? (
                    <ul className="motif-list">
                      {currentRecord.motifs.map((motif, index) => (
                        <li key={`${motif.id}-${index}`}>
                          <strong>
                            {motif.name}
                            {motif.confidence && (
                              <small>{motif.confidence} confidence</small>
                            )}
                          </strong>
                          <span>{motif.explanation}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="muted">No motif fired for this position.</p>
                  )}
                  {currentRecord.motif_candidates_suppressed > 0 && (
                    <p className="muted motif-suppressed">
                      {currentRecord.motif_candidates_suppressed} experimental
                      detector candidate
                      {currentRecord.motif_candidates_suppressed === 1
                        ? ""
                        : "s"}{" "}
                      withheld pending validation.
                    </p>
                  )}
                </div>
              </div>
            )}
          </section>

          <section className="panel coach-panel">
            <div className="section-heading">
              <div>
                <p className="eyebrow">Synthesis layer</p>
                <h2>AI Coach</h2>
              </div>
              <span
                className={`status-dot ${
                  coachingLoading
                    ? "working"
                    : coaching
                      ? "ready"
                      : coachingError
                        ? "failed"
                        : ""
                }`}
                title="AI coaching status"
              />
            </div>

            <label htmlFor="perspective">Coaching perspective</label>
            <select
              id="perspective"
              value={perspective}
              onChange={(event) => changePerspective(event.target.value)}
              disabled={analysisLoading || coachingLoading}
            >
              <option value="both">Both sides</option>
              <option value="white">White</option>
              <option value="black">Black</option>
            </select>

            {analysis && (
              <button
                type="button"
                className="primary-action"
                onClick={() => generateCoaching()}
                disabled={
                  !evidenceComplete ||
                  coachingLoading ||
                  aiAvailable === false
                }
              >
                {coachingLoading
                  ? "Gemini is synthesizing evidence…"
                  : coaching
                    ? "Regenerate AI coaching"
                    : "Retry AI coaching"}
              </button>
            )}

            {aiAvailable === false && (
              <div className="notice warning">
                Gemini is not configured on this server. The evidence pipeline
                remains available, but completed coaching requires Gemini.
              </div>
            )}
            {analysis && !evidenceComplete && (
              <div className="notice warning">
                AI coaching is paused until Stockfish, Lichess, and motif
                evidence are all available. Your completed evidence remains
                visible.
              </div>
            )}

            {coachingError && (
              <div className="notice error">
                <strong>AI coaching was not generated.</strong>
                <span>{coachingError.message}</span>
                {coachingError.retryable && (
                  <button type="button" onClick={() => generateCoaching()}>
                    Retry coaching
                  </button>
                )}
              </div>
            )}

            {coachingLoading && (
              <div className="coach-loading">
                <span />
                <span />
                <span />
              </div>
            )}

            {!coaching && !coachingLoading && !coachingError && (
              <div className="empty-state">
                Upload a game to run the complete review automatically.
              </div>
            )}

            {coaching && plyIndex === 0 && (
              <div className="notice success">
                Coaching is ready. Step through the analyzed moves to read it.
              </div>
            )}

            {currentExplanation && (
              <article className="coaching-copy">
                <p className="coach-move">
                  Move {Math.ceil(currentExplanation.ply / 2)} ·{" "}
                  {currentExplanation.side} · {currentExplanation.move}
                </p>
                <p>{currentExplanation.explanation}</p>
                <div className="lesson">
                  <strong>Practical lesson</strong>
                  <span>{currentExplanation.lesson}</span>
                </div>
                <details>
                  <summary>Evidence used</summary>
                  <ul>
                    {currentExplanation.evidence_refs.map((reference) => (
                      <li key={reference}>{reference}</li>
                    ))}
                  </ul>
                </details>
              </article>
            )}
          </section>

          <section className="panel">
            <div className="section-heading">
              <h2>Move history</h2>
            </div>
            <div className="history">
              {pairs.length ? (
                <table>
                  <tbody>
                    {pairs.map((pair, pairIndex) => (
                      <tr key={pair.number}>
                        <td>{pair.number}.</td>
                        <td>
                          {pair.white && (
                            <button
                              type="button"
                              className={
                                plyIndex === pairIndex * 2 + 1
                                  ? "history-move active"
                                  : "history-move"
                              }
                              onClick={() => goTo(pairIndex * 2 + 1)}
                            >
                              {pair.white}
                            </button>
                          )}
                        </td>
                        <td>
                          {pair.black && (
                            <button
                              type="button"
                              className={
                                plyIndex === pairIndex * 2 + 2
                                  ? "history-move active"
                                  : "history-move"
                              }
                              onClick={() => goTo(pairIndex * 2 + 2)}
                            >
                              {pair.black}
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="muted">No PGN loaded.</p>
              )}
            </div>
          </section>
        </aside>
      </section>

      {reviewLoading && (
        <div className="review-overlay" role="status" aria-live="polite">
          <div className="review-card">
            <div className="review-spinner" />
            <p className="eyebrow">Automatic game review</p>
            <h2>
              {analysisLoading
                ? `Analyzing ${totalFullMoves} chess moves`
                : "Writing your coaching"}
            </h2>
            <p>
              {analysisLoading
                ? "Stockfish, Lichess, and the motif engine are building position evidence."
                : "Gemini is turning the completed evidence into move-by-move instruction."}
            </p>
            <div className="review-steps">
              <span className={!analysisLoading ? "done" : "active"}>
                1. Chess evidence
              </span>
              <span className={coachingLoading ? "active" : ""}>
                2. AI coaching
              </span>
            </div>
            <small>{reviewElapsed}s elapsed · please keep this tab open</small>
          </div>
        </div>
      )}
    </main>
  );
}
