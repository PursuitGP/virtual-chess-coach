export const MOTIF_GLOSSARY = {
  "fork": {
    title: "Fork",
    short: "One piece attacks two or more enemy pieces at the same time.",
    long: "A fork is a tactical motif where a single piece simultaneously attacks two or more enemy pieces. Because the opponent can usually save only one target, forks often win decisive material. Knights are particularly famous for creating powerful forks due to their unique movement pattern.",
    example: "A knight jumping to f7, attacking the king with check and simultaneously attacking the rook."
  },

  "pin": {
    title: "Pin",
    short: "A piece cannot move without exposing a more valuable piece behind it.",
    long: "A pin occurs when a piece cannot move because doing so would expose a more valuable piece on the same line. Pins can be 'absolute' (king behind the piece) or 'relative' (queen/rook behind it). Pins limit mobility, often fixing pieces in place and enabling further tactical or positional gains.",
    example: "A bishop on g5 pinning a knight on f6 to the queen on d8."
  },

  "skewer": {
    title: "Skewer",
    short: "A more valuable piece is attacked and must move, exposing a less valuable piece behind it.",
    long: "A skewer is the tactical opposite of a pin: the more valuable piece is in front. When the attacked piece moves out of danger, it exposes a lower-value piece or target behind it. Skewers are typically delivered by bishops, rooks, or queens along long files and diagonals.",
    example: "A rook checking a king on the same file, forcing it to move and exposing a rook behind it."
  },

  "discovered attack": {
    title: "Discovered Attack",
    short: "One piece moves, unveiling an attack from another piece.",
    long: "A discovered attack occurs when a piece moves out of the way to reveal an attack from a second piece behind it. If the moving piece also creates a threat, the opponent may be unable to respond to both threats simultaneously. When the revealed attack is check, it becomes a discovered check — one of the strongest tactical motifs.",
    example: "A bishop moving to uncover a rook's attack against the opponent’s queen."
  },

  "x-ray": {
    title: "X-Ray Attack",
    short: "A piece attacks through an enemy piece to a target behind it.",
    long: "An X-ray attack occurs when a piece exerts pressure through another piece — friendly or enemy — onto a more valuable target. Even though the front piece blocks the attack, the underlying pressure affects tactical decisions and can win material if the front piece moves or is forced to move.",
    example: "A rook on e1 X-raying the king on e8 through an enemy rook."
  },

  "trapped piece": {
    title: "Trapped Piece",
    short: "A piece has no safe squares and is likely to be lost.",
    long: "A trapped piece is one that has been deprived of mobility. It may still be on the board, but it cannot move to any square without being captured. Recognizing trapped pieces allows players to win material without immediate tactics — simply by restricting escape squares.",
    example: "A knight on the rim (e.g., h5) that is surrounded by pawns and attacked multiple times."
  },

  "back-rank weakness": {
    title: "Back Rank Weakness",
    short: "The king is trapped behind its own pawns on the back rank.",
    long: "A back-rank weakness occurs when a king has no escape squares due to unmoved pawns on the back rank. This makes checkmate threats with rooks or queens very strong. Even if mate isn't possible, the defender is often forced into passive play to guard against it.",
    example: "White plays Re8+, delivering mate because the black king cannot escape behind its pawns."
  },

  "weak f7": {
    title: "Weak f7/F2 Square",
    short: "The f7 or f2 pawn is only protected by the king early in the game.",
    long: "The f7 (or f2) pawn is the weakest point in the initial position because it is protected only by the king. Many opening traps and attacks revolve around exploiting this vulnerability, especially with knights and bishops in the early game.",
    example: "Ng5 attacking f7 combined with Bc4, threatening Nxf7+."
  },

  "center break": {
    title: "Center Break",
    short: "A pawn thrust challenges or opens the center.",
    long: "A center break is a pawn advance aimed at undermining the opponent's central pawn structure. Strong players use center breaks to open lines for their pieces, increase activity, and punish overextended or poorly coordinated positions.",
    example: "The move ...d5 in the Sicilian Defense striking at White’s center."
  },

  "overextension": {
    title: "Overextension",
    short: "Pawns or pieces advance too far, becoming hard to defend.",
    long: "Overextension happens when a player pushes pawns or pieces aggressively without the necessary support. Although the position may appear dominant, overextended units become targets because they cannot be defended easily. Opponents exploit overextension by counterattacking the stretched pawn or piece.",
    example: "White pushes pawns to e5 and f5 too early, allowing Black to strike back with ...d6 and ...Nc6."
  },

  "undefended piece": {
    title: "Undefended Piece",
    short: "A piece is left without protection and becomes vulnerable to tactics.",
    long: "An undefended piece (also called a 'hanging piece') is one that is not protected by any friendly unit. These pieces are common tactical targets for forks, pins, skewers, and discovered attacks. Strong players constantly scan for loose pieces on the board.",
    example: "A knight on c4 left undefended and attacked by a bishop."
  },

  "tempo loss": {
    title: "Tempo Loss",
    short: "A move forces you to lose time or makes your earlier moves ineffective.",
    long: "Losing a tempo means wasting a move or being forced to move the same piece repeatedly. Tempo loss often results from being attacked, having to defend threats, or making ineffective plans. In dynamic positions, losing even a single tempo can shift the initiative to the opponent.",
    example: "A bishop that must retreat repeatedly because it was developed too early."
  },

  "pawn break": {
    title: "Pawn Break",
    short: "A pawn advance that opens lines or undermines the opponent’s structure.",
    long: "A pawn break is a thematic pawn push designed to open files, activate pieces, or weaken the opponent’s pawn structure. Good players prepare pawn breaks by coordinating pieces first. Poorly timed pawn breaks can backfire and create weaknesses instead.",
    example: "White playing c4 in a Caro-Kann to break open the center."
  },

  "isolated pawn": {
    title: "Isolated Pawn",
    short: "A pawn with no friendly pawns on adjacent files.",
    long: "An isolated pawn (IQP) cannot be protected by another pawn and often becomes a long-term weakness. However, isolated pawns are not always bad — they frequently grant open lines and active piece play, especially for the side with the IQP. Whether it's a strength or weakness depends on piece activity.",
    example: "White’s pawn on d4 in many Queen's Gambit structures."
  },

  "doubled pawns": {
    title: "Doubled Pawns",
    short: "Two pawns stacked on the same file after a capture.",
    long: "Doubled pawns occur when one pawn captures onto a square occupied by another pawn of the same color. They often cannot defend each other and can become targets. However, doubled pawns can also open files or control key central squares, depending on the position.",
    example: "White recaptures on c3 with the b2 pawn, creating doubled c-pawns."
  }
};
