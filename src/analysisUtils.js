const configuredBase = (process.env.REACT_APP_API_BASE_URL || "").replace(
  /\/$/,
  ""
);

export function apiUrl(path) {
  return `${configuredBase}${path}`;
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
