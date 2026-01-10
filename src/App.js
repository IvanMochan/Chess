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
  const [explanation, setExplanation] = useState(null);
  const [isExplaining, setIsExplaining] = useState(false);
  const gameReady = Array.isArray(fenList) && fenList.length > 0;

  const API = process.env.REACT_APP_API_URL || "https://chess-x7ns.onrender.com";

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
      console.log("Backend Response:", result);

      if (response.ok) {
        alert("PGN uploaded successfully!");
        setGameId(result.game_id);
        setFenList(result.moves);

        setAnalysisStarted(false);

        setGameSummary(null);
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

  useEffect(() => {
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

    const run = async () => {
      setIsExplaining(true);
      try {
        const res = await fetch(`${API}/explain_move/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ game_id: gameId, ply, depth: 14 }),
        });

        const data = await res.json();
        if (res.ok) setExplanation(data);
        else setExplanation(null);
      } catch (e) {
        console.error("Explain move error:", e);
        setExplanation(null);
      } finally {
        setIsExplaining(false);
      }
    };

    run();
  }, [analysisStarted, analysisState.currentMoveIndex, gameId, gameReady]);

  return (
    <div className="container">
      <div className="chessboard-container">
        <Chessboard
          fenList={fenList}
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
          currentMoveIndex={analysisState.currentMoveIndex}
          explanation={explanation}
          isExplaining={isExplaining}
        />
      </div>
    </div>
  );
}

export default App;
