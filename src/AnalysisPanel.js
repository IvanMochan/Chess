import './Chessboard.css';

const AnalysisPanel = ({
  gameSummary,
  analysisEval,
  analysisBest,
  isAnalyzing,
  error,
  gameReady,
  analysisStarted,
  onToggleView,
  currentMoveIndex,
  explanation,
  isExplaining,
}) => {
  const formatEval = (a) => {
    if (currentMoveIndex === 0) return "+0.00";

    if (!a) return '—';
    if (a.score_mate !== null && a.score_mate !== undefined) {
      const side = a.score_mate > 0 ? "White" : "Black";
      return `Mate in ${Math.abs(a.score_mate)} (${side})`;
    }
    if (typeof a.score_cp === "number") {
      const pawns = a.score_cp / 100;
      const sign = pawns > 0 ? "+" : "";
      return `${sign}${pawns.toFixed(2)}`;
    }
    return "N/A";
  };

  const countsWhite = gameSummary?.counts_white || {
    perfect: 0, best: 0, good: 0, okay: 0, bad: 0, blunder: 0
  };
  const countsBlack = gameSummary?.counts_black || {
    perfect: 0, best: 0, good: 0, okay: 0, bad: 0, blunder: 0
  };

  return (
    <div className="analysis-panel">
      <div style={{ fontWeight: 600 }}>Analysis</div>

      {!gameReady && (
        <div className="analysis-placeholder">
          Upload a PGN to see summary.
        </div>
      )}

      {gameReady && !analysisStarted && (
        <div className="analysis-content">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Game summary</div>

          {!gameSummary && (
            <div className="analysis-placeholder">Building summary…</div>
          )}
          {gameSummary && (
            <div className="summary">
              <div className="summary-header">
                <div className="summary-players">
                  <span className="player white">{gameSummary.white_name || "White"}</span>
                  <span className="vs">vs</span>
                  <span className="player black">{gameSummary.black_name || "Black"}</span>
                </div>

                <div className="summary-winner">
                  Winner: <strong>{gameSummary.winner || "Unknown"}</strong>
                  <span style={{ opacity: 0.8 }}> ({gameSummary.result || "*"})</span>
                </div>
              </div>

              <div className="summary-grid">
                {[
                  ["perfect", "Perfect"],
                  ["best", "Best"],
                  ["good", "Good"],
                  ["okay", "Okay"],
                  ["bad", "Bad"],
                  ["blunder", "Blunder"],
                ].map(([key, label]) => (
                  <div key={key} className={`summary-row ${key}`}>
                    <div className="summary-left">
                      {gameSummary.counts_white?.[key] ?? 0}
                    </div>

                    <div className="summary-mid">
                      {label}
                    </div>

                    <div className="summary-right">
                      {gameSummary.counts_black?.[key] ?? 0}
                    </div>
                  </div>
                ))}
              </div>
            </div>
)}
        </div>
      )}

      {gameReady && analysisStarted && (
        <div className="analysis-content">
          <div style={{ fontWeight: 600, marginBottom: 6 }}>Step-by-step</div>

          {(isAnalyzing || isExplaining) && (
            <div className="analysis-placeholder">Analyzing…</div>
          )}

          {error && !(isAnalyzing || isExplaining) && (
            <div className="analysis-error">{error}</div>
          )}

          {currentMoveIndex === 0 && (
            <div className="analysis-placeholder">
              Make the first move (Next) to see move explanation.
            </div>
          )}

          {currentMoveIndex > 0 && explanation && !(isAnalyzing || isExplaining) && (
            <div style={{ display: "grid", gap: 6 }}>
              <div><strong>Move played:</strong> {explanation.played_move_uci || "—"}</div>
              <div><strong>Quality:</strong> {explanation.quality || "—"}</div>
              <div><strong>Engine best:</strong> {explanation.best_move_uci || "—"}</div>
              {/*<div><strong>Eval:</strong> {formatEval(analysisEval)}</div> /*}
              {/* <div><strong>PV:</strong> {explanation.pv_uci?.length ? explanation.pv_uci.join(" ") : "—"}</div> */}
              {/*<div><strong>Eval before:</strong> {explanation.eval_before >= 0 ? "+" : ""}{explanation.eval_before.toFixed(2)}</div>   */}
              <div><strong>Eval:</strong> {explanation.eval_after >= 0 ? "+" : ""}{explanation.eval_after.toFixed(2)}</div>

              {Array.isArray(explanation.bullets) && explanation.bullets.length > 0 && (
                <div style={{ marginTop: 6 }}>
                  <strong>Explanation:</strong>
                  <ul style={{ margin: "6px 0 0 18px", padding: 0 }}>
                    {explanation.bullets.map((b, i) => (
                      <li key={i}>{b}</li>
                    ))}
                  </ul>
                </div>
              )}

              {explanation?.opponent_pv_san?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div style={{ fontWeight: 700 }}>Opponent best continuation:</div>
                  <div style={{ marginTop: 4 }}>
                    {explanation.opponent_pv_san.join(" ")}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {gameReady && (
        <button onClick={onToggleView} style={{ width: "100%", marginTop: 12 }}>
          {analysisStarted ? "Game summary" : "Step-by-step analysis"}
        </button>
      )}
    </div>
  );
};

export default AnalysisPanel;
