import React, { useState, useEffect, useCallback, useRef } from 'react';
import './Chessboard.css';

const initialBoard = [
  ['br','bn','bb','bq','bk','bb','bn','br'],
  ['bp','bp','bp','bp','bp','bp','bp','bp'],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  [null,null,null,null,null,null,null,null],
  ['wp','wp','wp','wp','wp','wp','wp','wp'],
  ['wr','wn','wb','wq','wk','wb','wn','wr'],
];

const FILES = ["a","b","c","d","e","f","g","h"];
const RANKS = ["8","7","6","5","4","3","2","1"];
const API = process.env.REACT_APP_API_URL || "https://chess-x7ns.onrender.com";

const EvalBar = ({ analysis, currentMoveIndex }) => {
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

  const evalToPawns = (a) => {
    if (!a) return 0;
    if (a.score_mate !== null && a.score_mate !== undefined) return a.score_mate > 0 ? 99 : -99;
    if (typeof a.score_cp === "number") return a.score_cp / 100;
    return 0;
  };

  const pawns = (currentMoveIndex === 0) ? 0 : evalToPawns(analysis);
  const whitePercent = ((clamp(pawns, -8, 8) + 8) / 16) * 100;

  const label =
    analysis?.score_mate !== null && analysis?.score_mate !== undefined
      ? `M${Math.abs(analysis.score_mate)}`
      : `${pawns >= 0 ? "+" : ""}${pawns.toFixed(2)}`;

  return (
    <div className="evalbar" aria-label="Evaluation bar">
      <div className="evalbar-black" />
      <div className="evalbar-white" style={{ height: `${whitePercent}%` }} />
      <div className="evalbar-midline" />
      <div className="evalbar-label">{label}</div>
    </div>
  );
};

const Chessboard = ({ 
  fenList, 
  restoreMoveIndex, 
  showMoveDots = true, 
  onAnalysisChange, 
  externalEval, 
  explanation, 
  movesSan = [], 
  onSelectMoveIndex,
  currentMoveIndex: controlledMoveIndex
}) => {
  const [board, setBoard] = useState(initialBoard);
  const [currentMoveIndex, setCurrentMoveIndex] = useState(0);

  const [analysis, setAnalysis] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [analysisError, setAnalysisError] = useState(null);
  const [analysisCache, setAnalysisCache] = useState({});
  const abortRef = useRef(null);
  const lastRestoreAppliedRef = useRef(null);

  const createBoardFromFEN = useCallback((fen) => {
    const b = Array(8).fill(null).map(() => Array(8).fill(null));
    const rows = fen.split(' ')[0].split('/');

    for (let row = 0; row < 8; row++) {
      let col = 0;
      for (let char of rows[row]) {
        if (isNaN(char)) {
          const isWhite = char === char.toUpperCase();
          const pieceType = char.toLowerCase();
          b[row][col] = isWhite ? `w${pieceType}` : `b${pieceType}`;
          col++;
        } else {
          col += parseInt(char, 10);
        }
      }
    }
    return b;
  }, []);

  const gameReady = Array.isArray(fenList) && fenList.length > 0;
  const displayedMoveIndex =
  typeof controlledMoveIndex === "number"
    ? controlledMoveIndex
    : currentMoveIndex;
  const currentFen = gameReady ? fenList[displayedMoveIndex] : null;
  const evalFromExplanation =
  explanation && typeof explanation.eval_after === "number"
    ? { score_cp: explanation.eval_after * 100, score_mate: null }
    : null;

  const prevIndex = gameReady && displayedMoveIndex > 0 ? displayedMoveIndex - 1 : null;
  const prevFen = (prevIndex !== null) ? fenList[prevIndex] : null;

  const panelEval = gameReady ? analysisCache[displayedMoveIndex] || null : null;

  const panelBest = prevIndex !== null ? analysisCache[prevIndex] || null : null;

  useEffect(() => {
    if (!gameReady) {
      setBoard(initialBoard);
      setCurrentMoveIndex(0);

      setAnalysis(null);
      setAnalysisError(null);
      setIsAnalyzing(false);
      setAnalysisCache({});
      return;
    }

    if (currentFen) {
      setBoard(createBoardFromFEN(currentFen));
    }
  }, [gameReady, currentFen, createBoardFromFEN]);

  useEffect(() => {
    if (!gameReady) return;

    setCurrentMoveIndex(0);
    setAnalysis(null);
    setAnalysisError(null);
    setIsAnalyzing(false);
    setAnalysisCache({});
  }, [gameReady, fenList]);

  useEffect(() => {
    if (!gameReady || !currentFen) {
      setAnalysis(null);
      setAnalysisError(null);
      setIsAnalyzing(false);
      return;
    }

    const needCurrent = analysisCache[currentMoveIndex] == null;
    const needPrev = (prevIndex !== null) && (analysisCache[prevIndex] == null);

    if (!needCurrent && !needPrev) {
      setAnalysis(panelBest || panelEval || null);
      setAnalysisError(null);
      setIsAnalyzing(false);
      return;
    }

    if (abortRef.current) abortRef.current.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    let didFinish = false;

    const fetchOne = async (fen) => {
      const res = await fetch(`${API}/analyze_fen/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fen, depth: 14 }),
        signal: controller.signal,
      });
      const data = await res.json();
      return { ok: res.ok, data };
    };

    const run = async () => {
      setIsAnalyzing(true);
      setAnalysisError(null);

      try {
        if (needCurrent) {
          const r = await fetchOne(currentFen);
          if (controller.signal.aborted) return;
          if (!r.ok) {
            setAnalysisError(r.data?.message || "Analysis failed");
            return;
          }
          setAnalysisCache((prev) => ({ ...prev, [currentMoveIndex]: r.data }));
        }

        if (needPrev && prevFen) {
          const r2 = await fetchOne(prevFen);
          if (controller.signal.aborted) return;
          if (!r2.ok) {
            setAnalysisError(r2.data?.message || "Analysis failed");
            return;
          }
          setAnalysisCache((prev) => ({ ...prev, [prevIndex]: r2.data }));
        }

        setAnalysis(panelBest || panelEval || null);
      } catch (e) {
        if (e.name === "AbortError") return;
        setAnalysisError(e.message || "Analysis failed");
      } finally {
        didFinish = true;
        setIsAnalyzing(false);
      }
    };
    run();

    return () => {
      if (!didFinish) controller.abort();
    };
  }, [gameReady, currentFen, currentMoveIndex, prevIndex, prevFen, panelEval, panelBest]);

  useEffect(() => {
    if (typeof onAnalysisChange !== "function") return;

    onAnalysisChange({
      analysisEval: panelEval,     
      analysisBest: panelBest,     
      isAnalyzing,
      analysisError,
      currentMoveIndex: displayedMoveIndex,
      gameReady,
      currentFen,
    });
  }, [panelEval, panelBest, isAnalyzing, analysisError, displayedMoveIndex, gameReady, currentFen, onAnalysisChange]);

  useEffect(() => {
    if (!gameReady) return;
    if (typeof controlledMoveIndex === "number") return;
    if (typeof restoreMoveIndex !== "number") return;

    setCurrentMoveIndex(Math.max(0, Math.min(restoreMoveIndex, fenList.length - 1)));
  }, [restoreMoveIndex, controlledMoveIndex, gameReady, fenList.length]);

  useEffect(() => {
    if (!gameReady) return;
    if (typeof controlledMoveIndex !== "number") return;

    const clamped = Math.max(0, Math.min(controlledMoveIndex, fenList.length - 1));
    if (clamped !== currentMoveIndex) setCurrentMoveIndex(clamped);
  }, [controlledMoveIndex, gameReady, fenList.length, currentMoveIndex]);


  const renderSquare = (row, col) => {
    const piece = board[row][col];
    const isWhiteSquare = (row + col) % 2 === 0;
    const pieceImage = piece ? `${process.env.PUBLIC_URL}/images/${piece}.png` : null;

    const dot =
      showMoveDots &&
      explanation &&
      typeof explanation.to_row === "number" &&
      typeof explanation.to_col === "number" &&
      explanation.to_row === row &&
      explanation.to_col === col
        ? explanation.quality
        : null;

    return (
      <div
        key={`${row}-${col}`}
        className={`square ${isWhiteSquare ? 'white' : 'black'}`}
      >
        {dot && <div className={`move-dot ${dot}`} />}
        {piece && <img src={pieceImage} alt={piece} />}
      </div>
    );
  };


  const classifyMove = (evalBefore, evalAfter, isWhiteMove) => {
    if (!evalBefore || !evalAfter) return null;
    const toPawnsWhitePOV = (a) => {
      if (a.score_mate !== null && a.score_mate !== undefined) {
        return a.score_mate > 0 ? 100 : -100;
      }
      return (typeof a.score_cp === "number" ? a.score_cp : 0) / 100;
    };

    const before = toPawnsWhitePOV(evalBefore);
    const after = toPawnsWhitePOV(evalAfter);
    const impact = isWhiteMove ? (after - before) : (before - after);

    if (impact <= -2.0) return "blunder"; 
    if (impact <= -0.75) return "bad";        
    return "good";                        
  };

  const getMoveToSquare = (fenBefore, fenAfter) => {
    if (!fenBefore || !fenAfter) return null;

    const b1 = createBoardFromFEN(fenBefore);
    const b2 = createBoardFromFEN(fenAfter);

    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        if (b1[r][c] !== b2[r][c] && b2[r][c]) {
          return { row: r, col: c };
        }
      }
    }
    return null;
  };

  const lastMoveInfo = (() => {
    if (displayedMoveIndex < 1) return null;

    const beforeIdx = displayedMoveIndex - 1;
    const afterIdx = displayedMoveIndex;

    const evalBefore = analysisCache[beforeIdx];
    const evalAfter = analysisCache[afterIdx];

    if (!evalBefore || !evalAfter) return null;

    const fenBefore = fenList[beforeIdx];
    const fenAfter = fenList[afterIdx];

    const toSquare = getMoveToSquare(fenBefore, fenAfter);
    if (!toSquare) return null;

    const sideToMove = fenBefore.split(" ")[1] === "w";

    const classification = classifyMove(
      evalBefore,
      evalAfter,
      sideToMove
    );

    return {
      toSquare,
      classification,
    };
  })();

  return (
    <div>
      <div className="board-row">
        <EvalBar
          analysis={evalFromExplanation ?? externalEval ?? panelEval} 
          currentMoveIndex={displayedMoveIndex}
        />

        <div className="board-area">
          <div className="board-with-right-coords">
            <div className="chessboard">
              {board.map((row, rowIndex) => (
                <div key={rowIndex} className="row">
                  {row.map((_, colIndex) => renderSquare(rowIndex, colIndex))}
                </div>
              ))}
            </div>

            <div className="coords-right">
              {RANKS.map((r) => (
                <div key={r} className="coord-cell">{r}</div>
              ))}
            </div>
          </div>

          <div className="coords-bottom">
            {FILES.map((f) => (
              <div key={f} className="coord-cell">{f}</div>
            ))}
          </div>
        </div>
      </div>
      <div style={{ marginTop: 8 }}>
        Move index: {gameReady ? displayedMoveIndex : "-"}
      </div>
    </div>
  );
};

export default Chessboard;
