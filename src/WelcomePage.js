import React from "react";
import "./WelcomePage.css";

export default function WelcomePage({ onStart }) {
  return (
    <div className="welcome-container">
      <div className="welcome-content">
        <h1 className="welcome-title">Welcome to Virtual Chess Coach</h1>
        <p className="welcome-subtitle">
          Analyze your games, detect motifs, and improve your strategy.
        </p>

        <button
          className="welcome-start-btn"
          onClick={onStart}> 
      
          Start
        </button>
      </div>
    </div>
  );
}
