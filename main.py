from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os

import chess
import chess.pgn
import chess.engine
from io import StringIO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

games_data = {}

# PGN upload

@app.post("/upload_pgn/")
async def upload_pgn(file: UploadFile = File(...)):
    content = await file.read()
    try:
        pgn_data = content.decode("utf-8")
        pgn = chess.pgn.read_game(StringIO(pgn_data))

        if pgn is None:
            return JSONResponse(content={"message": "Error parsing PGN"}, status_code=400)

        fens = get_fen_positions(pgn)
        moves_uci = [m.uci() for m in pgn.mainline_moves()]
        white_name, black_name, result, winner = pgn_winner_info(pgn)

        game_id = len(games_data) + 1
        games_data[game_id] = {
            "pgn": pgn_data,
            "game": pgn,
            "moves": fens,
            "moves_uci": moves_uci,
            "white_name": white_name,
            "black_name": black_name,
            "result": result,
            "winner": winner,
        }

        return JSONResponse(
            content={
                "message": "PGN uploaded successfully",
                "game_id": game_id,
                "moves": fens,
                "moves_uci": moves_uci,
                "white_name": white_name,
                "black_name": black_name,
                "result": result,
                "winner": winner,
            },
            status_code=200
        )

    except Exception as e:
        return JSONResponse(content={"message": str(e)}, status_code=400)

def pgn_winner_info(game: chess.pgn.Game):
    white = (game.headers.get("White") or "White").strip()
    black = (game.headers.get("Black") or "Black").strip()
    result = (game.headers.get("Result") or "*").strip()

    if result == "1-0":
        winner = "White"
    elif result == "0-1":
        winner = "Black"
    elif result == "1/2-1/2":
        winner = "Draw"
    else:
        winner = "Unknown"

    return white, black, result, winner

def get_fen_positions(pgn):
    board = pgn.board()
    fens = [board.fen()]

    for mv in pgn.mainline_moves():
        board.push(mv)
        fens.append(board.fen())

    return fens



# Stockfish engine

ENGINE = None


def _resolve_stockfish_path():
    if os.environ.get("STOCKFISH_PATH"):
        return os.environ["STOCKFISH_PATH"]

    here = os.path.dirname(os.path.abspath(__file__))
    bundled = os.path.join(here, "engine", "chmod +x stockfish-ubuntu-x86-64-avx2")
    if os.path.exists(bundled):
        return bundled

    return "stockfish"

@app.on_event("startup")
def startup():
    global ENGINE
    path = _resolve_stockfish_path()
    ENGINE = chess.engine.SimpleEngine.popen_uci(path)
    

@app.on_event("shutdown")
def shutdown():
    global ENGINE
    if ENGINE is None:
        return

    try:
        ENGINE.quit()
    except (chess.engine.EngineTerminatedError, OSError, BrokenPipeError):
        pass
    except Exception:
        pass
    finally:
        ENGINE = None

def eval_from_info(info):
    score = info.get("score")
    if not score:
        return 0.0

    mate = score.pov(chess.WHITE).mate()
    if mate is not None:
        return 100.0 if mate > 0 else -100.0

    cp = score.pov(chess.WHITE).score(mate_score=100000) or 0
    return cp / 100.0


def classify_impact(impact):
    if impact <= -2.0:
        return "blunder"
    if impact <= -0.75:
        return "bad"
    if impact >= 3.0:
        return "perfect"
    if impact >= 1.5:
        return "best"
    if impact >= 0.5:
        return "good"
    return "okay"



# Single-position analysis

class AnalyzeRequest(BaseModel):
    fen: str
    depth: int = 14

@app.post("/analyze_fen/")
async def analyze_fen(req: AnalyzeRequest):
    board = chess.Board(req.fen)
    info = ENGINE.analyse(board, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info, list):
        info = info[0]

    eval_cp = eval_from_info(info)
    pv = info.get("pv", [])

    return {
        "fen": req.fen,
        "depth": req.depth,
        "score_cp": eval_cp * 100,
        "best_move_uci": pv[0].uci() if pv else None,
        "pv_uci": [m.uci() for m in pv],
    }



# Game summary 

class AnalyzeGameRequest(BaseModel):
    game_id: int
    depth: int = 12

@app.post("/analyze_game/")
async def analyze_game(req: AnalyzeGameRequest):
    game = games_data.get(req.game_id)
    if not game:
        return JSONResponse(content={"message": "Unknown game_id"}, status_code=404)

    fens = game["moves"]
    evals = []

    for fen in fens:
        board = chess.Board(fen)
        info = ENGINE.analyse(board, chess.engine.Limit(depth=req.depth), multipv=1)
        if isinstance(info, list):
            info = info[0]
        evals.append(eval_from_info(info))

    counts_white = {k: 0 for k in ["perfect","best","good","okay","bad","blunder"]}
    counts_black = {k: 0 for k in ["perfect","best","good","okay","bad","blunder"]}

    for i in range(len(fens) - 1):
        fen_before = fens[i]
        is_white = fen_before.split(" ")[1] == "w"

        impact = (evals[i+1] - evals[i]) if is_white else (evals[i] - evals[i+1])
        cls = classify_impact(impact)

        if is_white:
            counts_white[cls] += 1
        else:
            counts_black[cls] += 1

    return {
        "white_name": game.get("white_name", "White"),
        "black_name": game.get("black_name", "Black"),
        "result": game.get("result", "*"),
        "winner": game.get("winner", "Unknown"),
        "counts_white": counts_white,
        "counts_black": counts_black,
    }



# Move explanation

class ExplainMoveRequest(BaseModel):
    game_id: int
    ply: int
    depth: int = 14

PIECE_VALUE = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

PIECE_NAME = {
    chess.PAWN: "pawn",
    chess.KNIGHT: "knight",
    chess.BISHOP: "bishop",
    chess.ROOK: "rook",
    chess.QUEEN: "queen",
    chess.KING: "king",
}

def _uci_to_san(board: chess.Board, uci: str) -> str:
    try:
        mv = chess.Move.from_uci(uci)
        return board.san(mv)
    except Exception:
        return uci

def _engine_best_line(board: chess.Board, depth: int):
    info = ENGINE.analyse(board, chess.engine.Limit(depth=depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}
    pv = info.get("pv", [])
    best = pv[0] if pv else None
    return info, pv, best

def _capture_explain(board: chess.Board, reply: chess.Move) -> Optional[str]:
    if not reply:
        return None
    if not board.is_capture(reply):
        return None

    captured = board.piece_at(reply.to_square)
    if not captured:
        return "wins material with a capture."

    name = PIECE_NAME.get(captured.piece_type, "piece")
    val = PIECE_VALUE.get(captured.piece_type, 0)
    if val >= 3:
        return f"wins your {name}."
    return f"wins a {name}."

def _hanging_piece_bullet(board_after: chess.Board, mover_color: bool) -> Optional[str]:

    opponent = not mover_color

    hung = []

    for sq, piece in board_after.piece_map().items():
        if piece.color != mover_color:
            continue

        val = PIECE_VALUE.get(piece.piece_type, 0)
        if val < 3:
            continue  

        attackers = len(board_after.attackers(opponent, sq))
        if attackers == 0:
            continue

        defenders = len(board_after.attackers(mover_color, sq))

        if defenders == 0 or attackers > defenders:
            hung.append((val, piece, sq, attackers, defenders))

    if not hung:
        return None

    hung.sort(reverse=True, key=lambda x: x[0])
    _, piece, sq, attackers, defenders = hung[0]
    name = PIECE_NAME.get(piece.piece_type, "piece")
    square_name = chess.square_name(sq)
    if defenders == 0:
        return f"leaves your {name} on {square_name} hanging (attacked and undefended)."
    return f"leaves your {name} on {square_name} under-defended ({attackers} attackers vs {defenders} defenders)."

def _short_pv_san(board: chess.Board, pv_moves, plies: int = 2):
    out = []
    tmp = board.copy()
    for mv in pv_moves[:plies]:
        try:
            out.append(tmp.san(mv))
        except Exception:
            out.append(mv.uci())
        try:
            tmp.push(mv)
        except Exception:
            break
    return " ".join(out)

def pv_to_uci(pv, limit=6):
    return [m.uci() for m in pv[:limit]]

def pv_to_san(board: chess.Board, pv, limit=6):
    out = []
    tmp = board.copy()
    for mv in pv[:limit]:
        try:
            out.append(tmp.san(mv))
        except Exception:
            out.append(mv.uci())
        try:
            tmp.push(mv)
        except Exception:
            break
    return out

def _material_white_minus_black(board: chess.Board) -> int:
    score = 0
    for p in board.piece_map().values():
        v = PIECE_VALUE.get(p.piece_type, 0)
        score += v if p.color == chess.WHITE else -v
    return score

def _material_delta_for_mover(board_start: chess.Board, board_end: chess.Board, mover_is_white: bool) -> int:
    """
    Returns positive if mover gained material, negative if mover lost material.
    """
    start = _material_white_minus_black(board_start)
    end = _material_white_minus_black(board_end)
    delta_white_pov = end - start
    return delta_white_pov if mover_is_white else -delta_white_pov

def _tactic_capture_phrase(board_after: chess.Board, pv_opp) -> str | None:
    """
    Describes PV[0] capture more accurately:
    - 'recaptures your queen (trade)' when PV[1] recaptures back
    - 'wins your queen' when no immediate recapture in PV
    """
    if not pv_opp or len(pv_opp) == 0:
        return None

    first = pv_opp[0]
    if not board_after.is_capture(first):
        return None

    captured = board_after.piece_at(first.to_square)
    if not captured:
        return "captures material."

    name = PIECE_NAME.get(captured.piece_type, "piece")
    val = PIECE_VALUE.get(captured.piece_type, 0)

    tmp = board_after.copy()
    tmp.push(first)

    if len(pv_opp) >= 2 and tmp.is_capture(pv_opp[1]):
        return f"recaptures your {name} (trade)."

    if val >= 3:
        return f"wins your {name}."
    return f"wins a {name}."



@app.post("/explain_move/")
async def explain_move(req: ExplainMoveRequest):
    game = games_data.get(req.game_id)
    if not game:
        return JSONResponse(content={"message": "Unknown game_id"}, status_code=404)

    fens = game["moves"]
    moves_uci = game["moves_uci"]

    if req.ply <= 0 or req.ply >= len(fens):
        return JSONResponse(content={"message": "Invalid ply"}, status_code=400)

    fen_before = fens[req.ply - 1]
    fen_after = fens[req.ply]

    played_move = moves_uci[req.ply - 1]

    board_before = chess.Board(fen_before)
    board_after = chess.Board(fen_after)

    info_before = ENGINE.analyse(board_before, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info_before, list):
        info_before = info_before[0]

    info_after = ENGINE.analyse(board_after, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info_after, list):
        info_after = info_after[0]

    eval_before = eval_from_info(info_before)
    eval_after = eval_from_info(info_after)

    pv = info_before.get("pv", [])
    best_move = pv[0].uci() if pv else None

    is_white = fen_before.split(" ")[1] == "w"
    impact = (eval_after - eval_before) if is_white else (eval_before - eval_after)
    quality = classify_impact(impact)
    bullets = []
    bullets.append(f"Evaluation changed from {eval_before:+.2f} to {eval_after:+.2f}.")
    played_san = _uci_to_san(board_before, played_move)
    best_san = _uci_to_san(board_before, best_move) if best_move else None
    opponent_pv_uci = []
    opponent_pv_san = []

    if quality in ("bad", "blunder"):
        info_opp = ENGINE.analyse(board_after, chess.engine.Limit(depth=req.depth), multipv=1)
        if isinstance(info_opp, list):
            info_opp = info_opp[0] if info_opp else {}
        pv_opp = info_opp.get("pv", []) or []
        opponent_pv_uci = pv_to_uci(pv_opp, limit=6)
        opponent_pv_san = pv_to_san(board_after, pv_opp, limit=6)


        if pv_opp:
            opp_best = pv_opp[0]
            opp_san = _uci_to_san(board_after, opp_best.uci())

            cap_phrase = _tactic_capture_phrase(board_after, pv_opp)
            gives_check = board_after.gives_check(opp_best)

            if cap_phrase and gives_check:
                bullets.append(f"After {played_san}, opponent can play {opp_san} — it {cap_phrase[:-1]} and gives check.")
            elif cap_phrase:
                bullets.append(f"After {played_san}, opponent can play {opp_san} — it {cap_phrase}")
            elif gives_check:
                bullets.append(f"After {played_san}, opponent can play {opp_san} — it gives check.")
            else:
                bullets.append(f"After {played_san}, opponent’s best reply is {opp_san}.")

            bullets.append(f"Main line: {_short_pv_san(board_after, pv_opp, plies=4)}")

            tmp = board_after.copy()
            for mv in pv_opp[:4]:
                try:
                    tmp.push(mv)
                except Exception:
                    break

            mover_is_white = (fen_before.split(" ")[1] == "w")
            mat_delta = _material_delta_for_mover(board_after, tmp, mover_is_white)
            if mat_delta != 0:
                sign = "+" if mat_delta > 0 else ""
                bullets.append(f"Material change over this line: {sign}{mat_delta}.")


    if best_move and played_move == best_move:
        bullets.append("This matches the engine’s best move.")
    elif best_move:
        bullets.append(f"Engine preferred {best_san} instead of {played_san}.")
    else:
        bullets.append("Engine best move not available for this position.")

    if impact <= -0.75:
        bullets.append(f"This costs about {abs(impact):.2f} pawns.")
    elif impact >= 0.5:
        bullets.append(f"This gains about {impact:.2f} pawns.")

    mv = chess.Move.from_uci(played_move)
    to_sq = mv.to_square  
    to_file = chess.square_file(to_sq)  
    to_rank = chess.square_rank(to_sq)  

    to_row = 7 - to_rank
    to_col = to_file

    return {
        "ply": req.ply,
        "played_move_uci": played_move,
        "best_move_uci": best_move,
        "pv_uci": [m.uci() for m in pv][:8],
        "eval_before": eval_before,
        "eval_after": eval_after,
        "impact_mover": impact,
        "quality": quality,
        "bullets": bullets,
        "to_row": to_row,
        "to_col": to_col,
        "opponent_pv_uci": opponent_pv_uci,
        "opponent_pv_san": opponent_pv_san,
    }
