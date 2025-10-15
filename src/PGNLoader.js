import React, { useState } from "react";
import { Chess } from "chess.js";

/**
 * PGNLoader (Compat + Fallback)
 * - Tries chess.loadPgn (v1) -> chess.load_pgn (v0.13) -> custom SAN replay
 * - Ultra-compat normalization + preview
 */
export default function PGNLoader({ onParsed }) {
  const [error, setError] = useState("");
  const [headers, setHeaders] = useState(null);
  const [normalizedText, setNormalizedText] = useState("");
  const [normalize, setNormalize] = useState(true);

  const KEEP_TAGS = new Set([
    "Event","Site","Date","Round","White","Black","Result",
    "WhiteElo","BlackElo","ECO","EventDate","Annotator","TimeControl",
    "UTCDate","UTCTime","Variant"
  ]);

  // ---------- helpers ----------
  function splitHeaderAndMoves(txt) {
    const i = txt.indexOf("\n\n");
    if (i === -1) return { header: "", body: txt };
    return { header: txt.slice(0, i), body: txt.slice(i + 2) };
  }

  function cleanHeaders(headerBlock) {
    if (!headerBlock) return "";
    const lines = headerBlock.split("\n").map(l => l.trim()).filter(Boolean);
    const kept = [];
    for (const line of lines) {
      const m = line.match(/^\[([A-Za-z0-9_]+)\s+"(.*)"\]$/);
      if (m) {
        const tag = m[1], val = m[2];
        if (KEEP_TAGS.has(tag)) kept.push(`[${tag} "${val}"]`);
      }
    }
    return kept.join("\n");
  }

  function stripCommentsRAVNAG(text) {
    // Remove PGN comments `{...}` and RAV/notes `(...)`, remove NAGs `$n`
    let s = text.replace(/\{[\s\S]*?\}/g, " ");
    s = s.replace(/\([\s\S]*?\)/g, " ");
    s = s.replace(/\$\d+/g, " ");
    return s;
  }

  function normalizePGN(raw) {
    if (!raw) return "";
    let text = raw.replace(/^\ufeff/, "").replace(/\r\n/g, "\n").replace(/\u00A0/g, " ");
    let { header, body } = splitHeaderAndMoves(text);
    header = header.trimEnd();
    if (header) {
      body = body.replace(/^\s*\n+/, "\n");
    } else {
      // try to discover header lines
      const lines = text.split("\n");
      let lastHeader = -1;
      for (let i = 0; i < lines.length; i++) {
        const l = lines[i].trim();
        if (/^\[[A-Za-z0-9_]+ ".+"\]$/.test(l)) lastHeader = i;
        else if (lastHeader !== -1) break;
      }
      if (lastHeader !== -1) {
        header = lines.slice(0, lastHeader + 1).join("\n").trim();
        body = lines.slice(lastHeader + 1).join("\n");
      } else {
        header = "";
        body = text;
      }
    }

    header = cleanHeaders(header);

    // Fix split tokens & extra spaces after move numbers
    body = body.replace(/(\d+)\s*\.\s*\n\s*/g, "$1.");
    body = body.replace(/(\d+)\s*\.\s+/g, "$1.");
    body = body.replace(/(\d+)\s*\.\.\.\s*\n\s*/g, "$1...");
    body = body.replace(/(\d+)\s*\.\.\.\s+/g, "$1...");

    // Remove comments / RAV / NAGs
    body = stripCommentsRAVNAG(body);

    // Collapse whitespace/newlines
    body = body.replace(/\s*\n\s*/g, " ").replace(/\s{2,}/g, " ").trim();

    // Keep only one trailing result
    const res = body.match(/\b(1-0|0-1|1\/2-1\/2)\b/g);
    if (res) {
      const last = res[res.length - 1];
      body = body.replace(/\b(1-0|0-1|1\/2-1\/2)\b/g, "").trim();
      body = (body + " " + last).trim();
    }

    if (!header) header = `[Event "PGN"]\n[Site "?"]\n[Date "?"]\n[Round "?"]\n[White "?"]\n[Black "?"]\n[Result "*"]`;
    return header + "\n\n" + body;
  }

  // Fallback: build headers + SAN tokens manually and replay
  function parseByReplay(text) {
    const { header, body } = splitHeaderAndMoves(text);
    const hdrs = {};
    header.split("\n").forEach(line => {
      const m = line.match(/^\[([A-Za-z0-9_]+)\s+"(.*)"\]$/);
      if (m) hdrs[m[1]] = m[2];
    });
    // strip comments/RAV/NAGs again just in case
    let movetext = stripCommentsRAVNAG(body);
    // remove results
    movetext = movetext.replace(/\b(1-0|0-1|1\/2-1\/2)\b/g, " ").trim();
    // drop move numbers like "12." or "12..."
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
      if (ok) {
        return { headers: chess.header ? chess.header() : {}, moves: chess.history({ verbose: true }) };
      }
    }
    if (typeof chess.load_pgn === "function") {
      ok = chess.load_pgn(text, { sloppy: true });
      if (ok) {
        return { headers: chess.header ? chess.header() : {}, moves: chess.history({ verbose: true }) };
      }
    }
    // Fall back to replaying SAN tokens ourselves
    return parseByReplay(text);
  }

  // ---------- UI handlers ----------
  function handleFile(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pgn")) {
      setError("Please select a .pgn file.");
      return;
    }
    const reader = new FileReader();
    reader.onload = (evt) => {
      const raw = String(evt.target.result || "");
      const cleaned = normalize ? normalizePGN(raw) : raw;
      setNormalizedText(cleaned);
      try {
        const { headers: hdrs, moves } = tryParseCompat(cleaned);
        setHeaders(hdrs);
        setError("");
        onParsed && onParsed({ headers: hdrs, moves, raw: cleaned });
      } catch (err) {
        console.error("PGN parse error (final):", err);
        setError(err?.message || "Could not parse PGN.");
      }
    };
    reader.readAsText(file);
  }

  return (
    <div>
      <div style={{display:'flex', alignItems:'center', justifyContent:'space-between', gap:12}}>
     
        <label style={{display:'flex', alignItems:'center', gap:6, fontSize:14}}>
          <input type="checkbox" checked={normalize} onChange={(e)=>setNormalize(e.target.checked)} />
          Toggle Normalize
        </label>
      </div>

      <input type="file" accept=".pgn" onChange={handleFile} className="pgn-upload" />

      {error && <p className="error">{error}</p>}

      

      {normalize && normalizedText && (
        <details style={{marginTop:8}}>
          <summary className="small">Show normalized PGN preview</summary>
          <pre style={{whiteSpace:'pre-wrap', background:'#0b1220', border:'1px solid #1f2937', padding:8, borderRadius:8, marginTop:6}}>
{normalizedText}
          </pre>
        </details>
      )}
    </div>
  );
}
