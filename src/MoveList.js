import React from "react";
import "./MoveList.css"

export default function MoveList({
  movesSan = [],
  activePly = 0,
  maxPly,
  onSelectPly,
}) {
  if (!Array.isArray(movesSan) || movesSan.length === 0) return null;

  const canPrev = activePly > 0;
  const canNext = typeof maxPly === "number" && activePly < maxPly;
  const goToFirstMove = () => {
    onSelectPly?.(0);
  };

  const goToLastMove = () => {
    onSelectPly?.(movesSan.length);
  };

  const rows = [];
  for (let i = 0; i < movesSan.length; i += 2) {
    const moveNo = Math.floor(i / 2) + 1;
    const whitePly = i + 1;
    const blackPly = i + 2;

    rows.push(
      <div className="movelist-row" key={i}>
        <span className="movelist-num">{moveNo}.</span>

        <button
          type="button"
          className={
            "movelist-link" + (activePly === whitePly ? " active" : "")
          }
          onClick={() => onSelectPly?.(whitePly)}
        >
          {movesSan[i]}
        </button>

        {movesSan[i + 1] && (
          <button
            type="button"
            className={
              "movelist-link" + (activePly === blackPly ? " active" : "")
            }
            onClick={() => onSelectPly?.(blackPly)}
          >
            {movesSan[i + 1]}
          </button>
        )}
      </div>
    );
  }

  return (
    <>
      <div className="movelist-nav movelist-nav--compact">
        <button
            type="button"
            disabled={!canPrev}
            onClick={goToFirstMove}
            title="First move"
        >
            ⏮
        </button>

        <button
            type="button"
            disabled={!canPrev}
            onClick={() => onSelectPly?.(activePly - 1)}
            title="Previous move"
        >
            ◀ Previous
        </button>

        <button
            type="button"
            disabled={!canNext}
            onClick={() => onSelectPly?.(activePly + 1)}
            title="Next move"
        >
            Next ▶
        </button>

        <button
            type="button"
            disabled={!canNext}
            onClick={goToLastMove}
            title="Last move"
        >
            ⏭
        </button>
        </div>
      <div className="movelist-scroll">{rows}</div>
    </>
  );
}
