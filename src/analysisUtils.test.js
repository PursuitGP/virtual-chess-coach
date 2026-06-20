import {
  buildExplanationMap,
  evaluationForBar,
  evaluationLabel,
  fullMoveCount,
  movePositionLabel,
  pointColor,
  readJsonResponse,
} from "./analysisUtils";

test("formats centipawn and mate evaluations for the board", () => {
  expect(
    evaluationLabel({ type: "cp", pawns: 0.42, display: "+0.42" })
  ).toBe("+0.42");
  expect(evaluationForBar({ type: "mate", value: -3 })).toBe(-10);
  expect(evaluationForBar({ type: "cp", pawns: 1.25 })).toBe(1.25);
});

test("classifies evaluation loss from the acting side's perspective", () => {
  expect(
    pointColor({
      side: "white",
      stockfish: { eval_delta_pawns: -3.2 },
    })
  ).toBe("#ef4444");
  expect(
    pointColor({
      side: "black",
      stockfish: { eval_delta_pawns: 2.1 },
    })
  ).toBe("#f97316");
  expect(
    pointColor({
      side: "black",
      stockfish: { eval_delta_pawns: -1.2 },
    })
  ).toBe("#34d399");
});

test("keys validated explanations by ply", () => {
  const explanations = [
    { ply: 1, explanation: "first" },
    { ply: 2, explanation: "second" },
  ];
  const result = buildExplanationMap(explanations);
  expect(result.get(2).explanation).toBe("second");
});

test("formats internal plies as chess full moves", () => {
  expect(fullMoveCount(19)).toBe(10);
  expect(movePositionLabel(0, 0)).toBe("Start position · no game loaded");
  expect(movePositionLabel(0, 19)).toBe("Start position · 10 moves");
  expect(movePositionLabel(1, 19)).toBe("Move 1 · White · 1/10");
  expect(movePositionLabel(2, 19)).toBe("Move 1 · Black · 1/10");
  expect(movePositionLabel(19, 19)).toBe("Move 10 · White · 10/10");
});

test("reports empty API responses without a JSON parser error", async () => {
  const response = { text: async () => "" };
  await expect(
    readJsonResponse(response, "Analysis failed.")
  ).rejects.toThrow("API returned an empty response");
});
