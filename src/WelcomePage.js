import React, { useState } from "react";
import "./WelcomePage.css";

export default function WelcomePage({ onLoadPGN }) {
  const [pgnText, setPgnText] = useState("");

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => setPgnText(event.target.result);
    reader.readAsText(file);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    if (pgnText.trim()) onLoadPGN(pgnText);
  };

  return (
    <div className="welcome-container fade-screen">
      <div className="welcome-card">
        <h1 className="welcome-title">♟️ Virtual Chess Coach</h1>
        <p className="welcome-subtitle">
          Upload a PGN file to analyze your game — or skip directly to explore.
        </p>

        {/* PGN Upload Section */}
        <form onSubmit={handleSubmit} className="welcome-form">
          <label htmlFor="pgnFile" className="welcome-label">
            Choose a PGN file:
          </label>
          <input
            id="pgnFile"
            type="file"
            accept=".pgn"
            onChange={handleFileUpload}
            className="welcome-input"
          />

          <textarea
            placeholder="...or paste PGN text here"
            value={pgnText}
            onChange={(e) => setPgnText(e.target.value)}
            className="welcome-textarea"
          />

          <div className="welcome-buttons">
            <button type="submit" className="btn primary">
              Load PGN
            </button>

            <button
              type="button"
              className="btn ghost"
              onClick={() => onLoadPGN(null)} // ✅ Skip without PGN
            >
              Skip for now
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
