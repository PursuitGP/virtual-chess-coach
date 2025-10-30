# ♜ Virtual Chess Coach  
*A modern React app built with **react-chessground** + **chess.js** — minimal, extensible, and AI-ready.*

---

## 🚀 Quick Start

```bash
npm install
npm start
```

Runs on **Create React App (CRA)** — no TypeScript required.

---

## 🧩 Core Features

### ♟️ Board & Playback
- Fully interactive **drag-and-drop** board using `react-chessground`
- Legal move validation powered by `chess.js`
- Flip board orientation (`F` key or button)
- Reset game to start (`R` key or button)
- Move forward/backward step-by-step
- **Skip to Start/End** buttons and keyboard shortcuts:
  - ← / → : Step through moves  
  - Home / End : Jump to first or last move  
  - **R** : Reset board  
  - **F** : Flip board

---

### 📂 PGN Handling
- Upload `.pgn` files and auto-parse via `chess.js`
- **PGN normalization** (headers cleaned, comments removed, result preserved)
- Collapsible **Normalized PGN preview** with:
  - 📋 **Copy to Clipboard**
  - ▸ Show / ▾ Hide toggle  
- Error handling for invalid or malformed PGNs
- Displays metadata (Event, Site, Date, Players, Result)

---

### 🧠 Coach Sidebar *(new)*
- Dedicated **AI Coach panel** ready for backend integration
- Sends current **FEN**, **move history**, and **metadata** as payload
- Mocked response for development with:
  - Opening name  
  - Engine evaluation  
  - Positional ideas / suggestions
- Animated **status indicator** (Idle / Busy / Success / Error)
- Collapsible “Payload Preview” (for debugging)
- Ready for future backend with:
  - ChatGPT commentary  
  - Stockfish evaluations  
  - Lichess opening lookup

---

### 💡 UI / UX Enhancements
- Refined **dark minimalist** layout
- Smooth **last-move glow with fade-out**
- Clean button set with hover/active states
- Compact **keyboard shortcut guide**
- Responsive layout scales for small screens
- Unified styling for PGN, Coach, and controls

---

## 🪴 Project Structure

```
src/
 ├─ App.js               # Main board, state, and controls
 ├─ PGNLoader.js         # File input, normalization, and parsing
 ├─ App.css              # Dark theme + layout + animations
 └─ assets/              # Icons / logos (optional)
```

---


## 🧭 Roadmap

- [ ] Connect Node/Express backend  
- [ ] Integrate Stockfish WASM for engine evaluations  
- [ ] Implement ChatGPT “Explain Move” mode  
- [ ] Save/load user games  
- [ ] Visualize evaluations graphically  
- [ ] Add theme switcher (dark/light/high contrast)

---

## 🧰 Dependencies

- **react** (Create React App)
- **react-chessground**
- **chess.js**

---



