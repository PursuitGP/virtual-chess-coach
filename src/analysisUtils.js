const configuredBase = (process.env.REACT_APP_API_BASE_URL || "").replace(
  /\/$/,
  ""
);

export function apiUrl(path) {
  return `${configuredBase}${path}`;
}

export async function readJsonResponse(response, fallbackMessage) {
  const text = await response.text();
  if (!text.trim()) {
    throw new Error(
      `${fallbackMessage} The API returned an empty response. Confirm the Flask backend is running.`
    );
  }

  try {
    return JSON.parse(text);
  } catch (_error) {
    throw new Error(
      `${fallbackMessage} The API returned an unexpected response. Confirm the Flask backend and frontend proxy use the same port.`
    );
  }
}

export function fullMoveCount(plyCount) {
  return Math.ceil(Math.max(0, plyCount) / 2);
}

export function movePositionLabel(plyIndex, totalPlies) {
  const totalMoves = fullMoveCount(totalPlies);
  if (plyIndex <= 0) {
    return totalMoves
      ? `Start position · ${totalMoves} move${totalMoves === 1 ? "" : "s"}`
      : "Start position · no game loaded";
  }
  const moveNumber = Math.ceil(plyIndex / 2);
  const side = plyIndex % 2 === 1 ? "White" : "Black";
  return `Move ${moveNumber} · ${side} · ${moveNumber}/${totalMoves}`;
}

export function evaluationLabel(evaluation) {
  return evaluation?.display || "0.00";
}

export function evaluationForBar(evaluation) {
  if (!evaluation) return 0;
  if (evaluation.type === "mate") {
    return evaluation.value >= 0 ? 10 : -10;
  }
  return typeof evaluation.pawns === "number" ? evaluation.pawns : 0;
}

export function pointColor(record) {
  const delta = record?.stockfish?.eval_delta_pawns;
  if (typeof delta !== "number") return "#34d399";
  const sideAdjusted = record.side === "black" ? -delta : delta;
  const loss = Math.max(0, -sideAdjusted);
  if (loss > 3) return "#ef4444";
  if (loss > 1.5) return "#f97316";
  if (loss > 0.5) return "#facc15";
  return "#34d399";
}

export function buildExplanationMap(explanations) {
  const result = new Map();
  if (!Array.isArray(explanations)) return result;
  for (const explanation of explanations) {
    if (
      explanation &&
      Number.isInteger(explanation.ply) &&
      explanation.ply > 0
    ) {
      result.set(explanation.ply, explanation);
    }
  }
  return result;
}

export function moveUci(move) {
  if (!move?.from || !move?.to) return null;
  return `${move.from}${move.to}${move.promotion || ""}`;
}

export function reviewArrowUcis(plyIndex, moves, analysis) {
  const currentStockfish =
    plyIndex > 0
      ? analysis?.positions?.[plyIndex - 1]?.stockfish
      : analysis?.initial_stockfish;
  const bestLine = currentStockfish?.top_lines?.[0]?.moves_uci || [];
  return {
    nextPlayed: moveUci(moves?.[plyIndex]),
    best:
      bestLine[0] ||
      currentStockfish?.best_move ||
      null,
  };
}

export function gameResultSummary(headers, moves) {
  const metadata = headers || {};
  const result = metadata.Result || "*";
  const termination = String(metadata.Termination || "").toLowerCase();
  const finalMove = Array.isArray(moves) && moves.length
    ? moves[moves.length - 1]
    : null;
  const finalSan = finalMove?.san || "";
  const checkmate = finalSan.includes("#") || termination.includes("checkmate");
  const onTime =
    termination.includes("time") ||
    termination.includes("flag") ||
    termination.includes("forfeit");
  const resigned =
    termination.includes("resign") || termination.includes("abandon");

  let winner = null;
  if (result === "1-0") winner = "White";
  if (result === "0-1") winner = "Black";
  if (!winner && checkmate && finalMove) {
    winner = moves.length % 2 === 1 ? "White" : "Black";
  }

  let title = null;
  if (winner && checkmate) title = `${winner} wins by checkmate`;
  else if (winner && onTime) title = `${winner} wins on time`;
  else if (winner && resigned) title = `${winner} wins by resignation`;
  else if (winner) title = `${winner} wins`;
  else if (result === "1/2-1/2") title = "Game drawn";

  if (!title) return null;

  const moveNumber = finalMove ? Math.ceil(moves.length / 2) : null;
  const notation = finalMove
    ? `${moveNumber}${moves.length % 2 === 0 ? "..." : "."} ${finalSan}`
    : null;

  return {
    title,
    notation,
    result,
    reason: checkmate
      ? "checkmate"
      : onTime
        ? "time"
        : resigned
          ? "resignation"
          : result === "1/2-1/2"
            ? "draw"
            : "result",
  };
}
