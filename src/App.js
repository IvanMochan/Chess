import React, { useState, useEffect, useCallback, useRef  } from 'react';
import Chessboard from './Chessboard';
import AnalysisPanel from './AnalysisPanel';
import MoveList from './MoveList';
import './App.css';

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [gameId, setGameId] = useState(null);
  const [fenList, setFenList] = useState([]);
  const [movesSan, setMovesSan] = useState([])
  const [analysisStarted, setAnalysisStarted] = useState(false);
  const [gameSummary, setGameSummary] = useState(null);
  const [analysisState, setAnalysisState] = useState({
    analysisEval: null,
    analysisBest: null,
    isAnalyzing: false,
    analysisError: null,
    currentMoveIndex: 0,
    gameReady: false,
    currentFen: null,
  });
  const updateAnalysisState = useCallback((next) => {
    if (!next || typeof next !== "object") return;

    setAnalysisState((prev) => {
      const merged = { ...prev, ...next };

      const same =
        prev.analysisEval === merged.analysisEval &&
        prev.analysisBest === merged.analysisBest &&
        prev.isAnalyzing === merged.isAnalyzing &&
        prev.analysisError === merged.analysisError &&
        prev.currentMoveIndex === merged.currentMoveIndex &&
        prev.gameReady === merged.gameReady &&
        prev.currentFen === merged.currentFen;

      return same ? prev : merged;
    });
  }, []);


  const [explanationCache, setExplanationCache] = useState({});
  const [explanation, setExplanation] = useState(null);
  const [isExplaining, setIsExplaining] = useState(false);
  const [alternateExplanation, setAlternateExplanation] = useState(null);

  const gameReady = Array.isArray(fenList) && fenList.length > 0;
  //const API = process.env.REACT_APP_API_URL || "https://chess-x7ns.onrender.com";
  const API = "https://chess-x7ns.onrender.com";
  console.log("API:", API)
  const [viewMode, setViewMode] = useState("main");
  const [anchorMoveIndex, setAnchorMoveIndex] = useState(null);
  const [alternateLine, setAlternateLine] = useState({
    fens: [],
    movesSAN: [],
    startPly: null,
    index: 0,
  });

  const [mainMoveIndex, setMainMoveIndex] = useState(0);

  const panelMoveIndex =
  viewMode === "alternate"
    ? (anchorMoveIndex ?? analysisState.currentMoveIndex)
    : analysisState.currentMoveIndex;

  useEffect(() => {
    if (viewMode === "main") {
      setMainMoveIndex(analysisState.currentMoveIndex);
    }
  }, [viewMode, analysisState.currentMoveIndex]);


  const handleFileChange = async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setSelectedFile(file);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API}/upload_pgn/`, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (response.ok) {
        setViewMode("main");
        setAnchorMoveIndex(null);
        setAlternateLine({ fens: [], movesSAN: [], startPly: null, index: 0 });

        setGameId(result.game_id);
        setFenList(result.moves);
        setMovesSan(result.moves_san || []);

        setAnalysisStarted(false);
        setGameSummary(null);

        setExplanationCache({});
        setExplanation(null);
        setIsExplaining(false);
        setAlternateExplanation(null);

        fetchGameSummary(result.game_id);
      } else {
        alert(result.message || "Upload failed");
      }
    } catch (error) {
      alert("Error uploading file");
    } finally {
      event.target.value = "";
    }
  };

  const fetchGameSummary = async (newGameId) => {
    try {
      setGameSummary(null);
      const res = await fetch(`${API}/analyze_game/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ game_id: newGameId, depth: 12 }),
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data?.message || "Failed to analyze game");
      setGameSummary(data);
    } catch (e) {
      console.error("analyze_game error:", e);
      setGameSummary(null);
    }
  };

  const onToggleView = () => setAnalysisStarted((v) => !v);

  const showAlternateLine = async (moveIndexPressed) => {
    if (!gameId) return;
    if (typeof moveIndexPressed !== "number" || moveIndexPressed <= 0) return;

    setAnchorMoveIndex(moveIndexPressed);

    const ply = moveIndexPressed;

    try {
      const res = await fetch(`${API}/alternate_line/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          game_id: gameId,
          ply,
          depth: 14,
          max_plies: 10,
        }),
      });

      const data = await res.json();
      if (!res.ok) return;

      setAlternateLine({
        fens: data.fens,
        movesSAN: data.moves_san,
        startPly: data.start_ply,
        index: 0,
      });

      setMainMoveIndex(analysisState.currentMoveIndex);
      setViewMode("alternate");
    } catch (e) {
      console.error("alternate_line error:", e);
    }

    try {
      const res2 = await fetch(`${API}/explain_alternate/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          game_id: gameId,
          ply: moveIndexPressed,
          depth: 14,
        }),
      });

      const data2 = await res2.json();
      if (res2.ok) setAlternateExplanation(data2);
      else setAlternateExplanation(null);
    } catch {
      setAlternateExplanation(null);
    }
  };

  useEffect(() => {
    if (viewMode !== "main") return;
    if (typeof anchorMoveIndex !== "number") return;

    setAnalysisState((prev) => ({ ...prev, currentMoveIndex: anchorMoveIndex }));
    setAnchorMoveIndex(null);
  }, [viewMode, anchorMoveIndex]);

  useEffect(() => {
    if (viewMode !== "main") return;
    if (!analysisStarted) {
      setExplanation(null);
      setIsExplaining(false);
      return;
    }
    if (!gameId || !gameReady) return;

    const ply = analysisState.currentMoveIndex;
    if (ply <= 0) {
      setExplanation(null);
      setIsExplaining(false);
      return;
    }

    const cached = explanationCache[ply];
    if (cached) {
      setExplanation(cached);
      setIsExplaining(false);
      return;
    }

    const run = async () => {
      setIsExplaining(true);
      try {
        const res = await fetch(`${API}/explain_move/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ game_id: gameId, ply, depth: 14 }),
        });

        const data = await res.json();
        if (res.ok) {
          setExplanationCache((prev) => ({ ...prev, [ply]: data }));
          setExplanation(data);
        } else {
          setExplanation(null);
        }
      } catch (e) {
        console.error("Explain move error:", e);
        setExplanation(null);
      } finally {
        setIsExplaining(false);
      }
    };

    run();
  }, [analysisStarted, analysisState.currentMoveIndex, gameId, gameReady, explanationCache, viewMode]);

  const activeFenList =
  viewMode === "alternate"
    ? alternateLine.fens
    : fenList;

  return (
    <>
    <div className="app-logo">
      <img
        src={`${process.env.PUBLIC_URL}/images/logo.png`}
        alt="App logo"
      />
    </div>
    <div className="app-scale">
      <div className="container">
        <div className="chessboard-container">
          <Chessboard
            fenList={activeFenList}
            movesSan={viewMode === "main" ? movesSan : alternateLine.movesSAN}
            currentMoveIndex={
              viewMode === "main" ? analysisState.currentMoveIndex : alternateLine.index
            }
            onSelectMoveIndex={
              viewMode === "main"
                ? (idx) => setAnalysisState((prev) => ({ ...prev, currentMoveIndex: idx }))
                : (idx) => setAlternateLine((prev) => ({ ...prev, index: idx }))
            }
            showMoveDots={viewMode === "main"}
            onAnalysisChange={viewMode === "main" ? updateAnalysisState : undefined}
            externalEval={analysisState.analysisEval}
            explanation={explanation}
          />
        </div>

        <div className="movelist-container">
          <div className="movelist-title">Moves</div>

          {viewMode === "main" ? (
            gameReady && (
              <MoveList
                movesSan={movesSan}
                activePly={analysisState.currentMoveIndex}
                maxPly={fenList.length - 1}
                onSelectPly={(ply) =>
                  setAnalysisState((prev) => ({ ...prev, currentMoveIndex: ply }))
                }
              />
            )
          ) : (
            alternateLine.fens.length > 0 && (
              <MoveList
                movesSan={alternateLine.movesSAN}
                activePly={alternateLine.index}
                maxPly={alternateLine.fens.length - 1}
                onSelectPly={(idx) =>
                  setAlternateLine((prev) => ({ ...prev, index: idx }))
                }
              />
            )
          )}
        </div>
        <div className="file-upload-container">
          <h2>Upload PGN File</h2>
          <label className="file-input-wrapper">
            <span className="file-input-button">Select a File</span>
            <input
              type="file"
              accept=".pgn"
              onChange={handleFileChange}
            />
          </label>
          {gameReady && (
            <button onClick={onToggleView} style={{ width: "100%", marginTop: 12 }}>
              {analysisStarted ? "Game summary" : "Step-by-step analysis"}
            </button>
          )}
          <div className="analysis-panel-wrapper">
            <AnalysisPanel
              gameSummary={gameSummary}
              analysisEval={analysisState.analysisEval}
              analysisBest={analysisState.analysisBest}
              isAnalyzing={analysisState.isAnalyzing}
              error={analysisState.analysisError}
              gameReady={gameReady}
              analysisStarted={analysisStarted}
              onToggleView={onToggleView}
              currentMoveIndex={panelMoveIndex}
              explanation={explanation}
              alternateExplanation={alternateExplanation}
              isExplaining={isExplaining}
              viewMode={viewMode}
              setViewMode={setViewMode}
              setAlternateLine={setAlternateLine}
              showAlternateLine={showAlternateLine}
            />
          </div>
        </div>
      </div>
    </div>
    </>
  );
}

export default App;
