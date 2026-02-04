import React, { useState, useEffect } from 'react';
import Chessboard from './Chessboard';
import AnalysisPanel from './AnalysisPanel';
import './App.css';

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [gameId, setGameId] = useState(null);
  const [fenList, setFenList] = useState([]);
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

  const [explanationCache, setExplanationCache] = useState({});
  const [explanation, setExplanation] = useState(null);
  const [isExplaining, setIsExplaining] = useState(false);
  const [alternateExplanation, setAlternateExplanation] = useState(null);

  const gameReady = Array.isArray(fenList) && fenList.length > 0;
  const API = process.env.REACT_APP_API_URL || "https://chess-x7ns.onrender.com";

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


  const handleFileChange = (event) => {
    setSelectedFile(event.target.files[0]);
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

  const handleFileUpload = async () => {
    if (!selectedFile) {
      alert("Please select a PGN file.");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);

    try {
      const response = await fetch(`${API}/upload_pgn/`, {
        method: "POST",
        body: formData,
      });

      const result = await response.json();

      if (response.ok) {
        setViewMode("main");
        setAnchorMoveIndex(null);
        setAlternateLine({
          fens: [],
          movesSAN: [],
          startPly: null,
          index: 0,
        });

        setGameId(result.game_id);
        setFenList(result.moves);

        setAnalysisStarted(false);
        setGameSummary(null);

        setExplanationCache({});
        setExplanation(null);
        setIsExplaining(false);

        fetchGameSummary(result.game_id);
      } else {
        alert(result.message);
      }
    } catch (error) {
      alert("Error uploading file");
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
    <div className="container">
      <div className="chessboard-container">
        <Chessboard
          fenList={activeFenList}
          restoreMoveIndex={viewMode === "main" ? anchorMoveIndex : undefined}
          showMoveDots={viewMode === "main"}
          onAnalysisChange={setAnalysisState}
          externalEval={analysisState.analysisEval}
          explanation={explanation}
        />
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
        <button onClick={handleFileUpload}>Upload</button>
        {gameId && <p>Game ID: {gameId}</p>}

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
  );
}

export default App;
