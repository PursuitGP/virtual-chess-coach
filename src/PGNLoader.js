import React, { useRef, useState } from "react";
import { Chess } from "chess.js";

/**
 * PGNLoader (Compat + Fallback + Paste Support)
 * - File upload with normalization
 * - Paste PGN text and parse it through same normalization + compat pipeline
 * - Creates virtual File so backend can still receive `file`
 */
export default function PGNLoader({ disabled = false, onParsed }) {
  const inputRef = useRef(null);
  const [error, setError] = useState("");
  const [pastedText, setPastedText] = useState("");

  const KEEP_TAGS = new Set([
    "Event",
    "Site",
    "Date",
    "Round",
    "White",
    "Black",
    "Result",
    "WhiteElo",
    "BlackElo",
    "ECO",
    "EventDate",
    "Annotator",
    "TimeControl",
    "UTCDate",
    "UTCTime",
    "Variant",
    "Termination",
  ]);

  // ---------------------- helpers ----------------------
  function splitHeaderAndMoves(txt) {
    const i = txt.indexOf("\n\n");
    if (i === -1) return { header: "", body: txt };
    return { header: txt.slice(0, i), body: txt.slice(i + 2) };
  }

  function cleanHeaders(headerBlock) {
    if (!headerBlock) return "";
    const lines = headerBlock
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    const kept = [];
    for (const line of lines) {
      const m = line.match(/^\[([A-Za-z0-9_]+)\s+"(.*)"\]$/);
      if (m) {
        const tag = m[1],
          val = m[2];
        if (KEEP_TAGS.has(tag)) kept.push(`[${tag} "${val}"]`);
      }
    }
    return kept.join("\n");
  }

  function stripCommentsRAVNAG(text) {
    let s = text.replace(/\{[\s\S]*?\}/g, " ");
    s = s.replace(/\([\s\S]*?\)/g, " ");
    s = s.replace(/\$\d+/g, " ");
    return s;
  }

  function normalizePGN(raw) {
    if (!raw) return "";
    let text = raw
      .replace(/^\ufeff/, "")
      .replace(/\r\n/g, "\n")
      .replace(/\u00A0/g, " ");
    let { header, body } = splitHeaderAndMoves(text);
    header = header.trimEnd();

    if (!header) {
      const lines = text.split("\n");
      let lastHeader = -1;
      for (let i = 0; i < lines.length; i++) {
        const l = lines[i].trim();
        if (/^\[[A-Za-z0-9_]+ ".+"\]$/.test(l)) lastHeader = i;
        else if (lastHeader !== -1) break;
      }
      if (lastHeader !== -1) {
        header = lines
          .slice(0, lastHeader + 1)
          .join("\n")
          .trim();
        body = lines.slice(lastHeader + 1).join("\n");
      } else {
        header = "";
      }
    }

    header = cleanHeaders(header);

    body = body.replace(/(\d+)\s*\.\s*\n\s*/g, "$1.");
    body = body.replace(/(\d+)\s*\.\s+/g, "$1.");
    body = body.replace(/(\d+)\s*\.\.\.\s*\n\s*/g, "$1...");
    body = body.replace(/(\d+)\s*\.\.\.\s+/g, "$1...");
    body = stripCommentsRAVNAG(body);

    body = body
      .replace(/\s*\n\s*/g, " ")
      .replace(/\s{2,}/g, " ")
      .trim();

    const resultPattern = /(?:\b(?:1-0|0-1|1\/2-1\/2)\b|\*)/g;
    const res = body.match(resultPattern);
    if (res) {
      const last = res[res.length - 1];
      body = body.replace(resultPattern, "").trim();
      body = (body + " " + last).trim();
    }

    if (!header) {
      header = `[Event "PGN"]\n[Site "?"]\n[Date "?"]\n[Round "?"]\n[White "?"]\n[Black "?"]\n[Result "*"]`;
    }

    return header + "\n\n" + body;
  }

  // -------------- Fallback SAN replay --------------
  function parseByReplay(text) {
    const { header, body } = splitHeaderAndMoves(text);
    const hdrs = {};
    header.split("\n").forEach((line) => {
      const m = line.match(/^\[([A-Za-z0-9_]+)\s+"(.*)"\]$/);
      if (m) hdrs[m[1]] = m[2];
    });

    let movetext = stripCommentsRAVNAG(body);
    movetext = movetext
      .replace(/(?:\b(?:1-0|0-1|1\/2-1\/2)\b|\*)/g, " ")
      .trim();
    movetext = movetext.replace(/\b\d+\.(\.\.)?/g, " ");
    movetext = movetext.replace(/\s{2,}/g, " ").trim();

    const sanTokens = movetext.split(/\s+/).filter(Boolean);

    const chess = new Chess();
    for (const san of sanTokens) {
      const mv = chess.move(san, { sloppy: true });
      if (!mv) {
        throw new Error(`SAN replay failed at token "${san}"`);
      }
    }
    return { headers: hdrs, moves: chess.history({ verbose: true }) };
  }

  function tryParseCompat(text) {
    const chess = new Chess();
    let ok = false;

    if (typeof chess.loadPgn === "function") {
      ok = chess.loadPgn(text, { sloppy: true });
      if (ok)
        return {
          headers: chess.header?.() || {},
          moves: chess.history({ verbose: true }),
        };
    }
    if (typeof chess.load_pgn === "function") {
      ok = chess.load_pgn(text, { sloppy: true });
      if (ok)
        return {
          headers: chess.header?.() || {},
          moves: chess.history({ verbose: true }),
        };
    }

    return parseByReplay(text);
  }

  // ------------------ UI handlers ------------------
  function processPGN(raw, filename) {
    const cleaned = normalizePGN(raw);

    try {
      const { headers: hdrs, moves } = tryParseCompat(cleaned);
      const normalizedFile = new File([cleaned], filename, {
        type: "application/x-chess-pgn",
      });
      setError("");
      onParsed?.({
        headers: hdrs,
        moves,
        file: normalizedFile,
        raw: cleaned,
      });
    } catch (err) {
      console.error("PGN parse error:", err);
      setError(err?.message || "Could not parse PGN.");
    }
  }

  function handleFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".pgn")) {
      setError("Please select a .pgn file.");
      return;
    }

    const reader = new FileReader();
    reader.onload = (evt) => {
      const raw = String(evt.target.result || "");
      processPGN(raw, file.name);
    };
    reader.readAsText(file);
  }

  function handlePasteParse() {
    if (!pastedText.trim()) {
      setError("Paste a PGN first.");
      return;
    }

    processPGN(pastedText, "pasted_game.pgn");
  }

  async function handleLoadExample() {
    try {
      setError("");
      const response = await fetch("/examples/scholars_mate.pgn");
      if (!response.ok) throw new Error("Example PGN is unavailable.");
      const text = await response.text();
      setPastedText(text);
      processPGN(text, "scholars_mate.pgn");
    } catch (err) {
      setError(err?.message || "Could not load the example game.");
    }
  }

  return (
    <div className="pgn-loader welcome-pgn-loader">
      <input
        ref={inputRef}
        type="file"
        accept=".pgn,application/x-chess-pgn"
        onChange={handleFile}
        className="visually-hidden"
        disabled={disabled}
      />
      <button
        type="button"
        className="upload-action"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
      >
        <span className="upload-icon" aria-hidden="true">
          ↑
        </span>
        <span>
          <strong>Upload your PGN</strong>
          <small>Choose a .pgn file from your device</small>
        </span>
      </button>

      <div className="intake-divider">
        <span>or paste the PGN</span>
      </div>

      <textarea
        rows={7}
        aria-label="Paste PGN text"
        placeholder={'[White "Player"]\n[Black "Opponent"]\n\n1. e4 e5 2. Nf3 Nc6'}
        value={pastedText}
        onChange={(event) => setPastedText(event.target.value)}
        disabled={disabled}
      />

      <div className="paste-actions">
        <button
          type="button"
          className="primary-action"
          onClick={handlePasteParse}
          disabled={disabled || !pastedText.trim()}
        >
          Analyze pasted game
        </button>
        <button
          type="button"
          className="ghost-action"
          onClick={handleLoadExample}
          disabled={disabled}
        >
          Try an example
        </button>
      </div>

      {error && <p className="notice error">{error}</p>}
    </div>
  );
}
