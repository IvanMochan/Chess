from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import sys

import chess
import chess.pgn
import chess.engine
from io import StringIO

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chess")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

games_data = {}
EXPLAIN_CACHE = {}

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

        board_tmp = pgn.board()
        moves_san = []
        for mv in pgn.mainline_moves():
            moves_san.append(board_tmp.san(mv))
            board_tmp.push(mv)

        white_name, black_name, result, winner = pgn_winner_info(pgn)

        game_id = len(games_data) + 1
        games_data[game_id] = {
            "pgn": pgn_data,
            "game": pgn,
            "moves": fens,
            "moves_uci": moves_uci,
            "moves_san": moves_san,
            "white_name": white_name,
            "black_name": black_name,
            "result": result,
            "winner": winner,
        }

        for k in list(EXPLAIN_CACHE.keys()):
            if k[0] == game_id:
                EXPLAIN_CACHE.pop(k, None)

        return JSONResponse(
            content={
                "message": "PGN uploaded successfully",
                "game_id": game_id,
                "moves": fens,
                "moves_uci": moves_uci,
                "moves_san": moves_san,
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
    bundled = os.path.join(here, "engine", "stockfish-ubuntu-x86-64-avx2")
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
    return "good"



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
    depth: int = 14

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

    counts_white = {k: 0 for k in ["perfect","best","good","bad","blunder"]}
    counts_black = {k: 0 for k in ["perfect","best","good","bad","blunder"]}

    for i in range(len(fens) - 1):
        fen_before = fens[i]
        is_white = fen_before.split(" ")[1] == "w"
        played_move = game["moves_uci"][i]

        # impact (from mover POV)
        impact = (evals[i+1] - evals[i]) if is_white else (evals[i] - evals[i+1])
        cls = classify_impact(impact)

        # "best" should mean: Stockfish's top choice from this position
        try:
            board_before = chess.Board(fen_before)
            info_before = ENGINE.analyse(board_before, chess.engine.Limit(depth=req.depth), multipv=1)
            if isinstance(info_before, list):
                info_before = info_before[0] if info_before else {}
            pv0 = info_before.get("pv", []) or []
            engine_best_uci = pv0[0].uci() if pv0 else None
            if engine_best_uci and played_move == engine_best_uci:
                cls = "best"
        except Exception:
            pass

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

def _best_reply_and_pv_after(board_after: chess.Board, depth: int, max_len: int = 8):
    info = ENGINE.analyse(board_after, chess.engine.Limit(depth=depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}

    pv = info.get("pv", [])
    best_reply = pv[0] if pv else None

    best_reply_uci = best_reply.uci() if best_reply else None
    pv_after_uci = [m.uci() for m in pv[:max_len]]

    pv_after_san = []
    tmp = board_after.copy()
    for mv in pv[:max_len]:
        try:
            pv_after_san.append(tmp.san(mv))
            tmp.push(mv)
        except Exception:
            pv_after_san.append(mv.uci())
            break

    return {
        "best_reply_uci": best_reply_uci,
        "pv_after_uci": pv_after_uci,
        "pv_after_san": pv_after_san,
    }


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

def _hanging_piece_bullet(board_after: chess.Board, mover_color: bool, depth: int) -> Optional[str]:

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

def _find_most_valuable_hung_piece(board: chess.Board, mover_color: bool):
    """
    Returns (square, piece) for the biggest hanging piece of mover_color on board.
    Hanging = attacked by opponent and (undefended OR attackers > defenders).
    """
    opp = not mover_color
    best = None
    for sq, piece in board.piece_map().items():
        if piece.color != mover_color:
            continue
        val = PIECE_VALUE.get(piece.piece_type, 0)
        if val < 3:
            continue

        attackers = len(board.attackers(opp, sq))
        if attackers == 0:
            continue
        defenders = len(board.attackers(mover_color, sq))
        if defenders == 0 or attackers > defenders:
            cand = (val, sq, piece, attackers, defenders)
            if best is None or cand[0] > best[0]:
                best = cand

    if not best:
        return None
    _, sq, piece, attackers, defenders = best
    return (sq, piece, attackers, defenders)

def _is_hanging_sq(board: chess.Board, mover_color: bool, sq: chess.Square) -> bool:
    opp = not mover_color
    attackers = len(board.attackers(opp, sq))
    if attackers == 0:
        return False
    defenders = len(board.attackers(mover_color, sq))
    return defenders == 0 or attackers > defenders

def _piece_word(piece: chess.Piece) -> str:
    return PIECE_NAME.get(piece.piece_type, "piece")

def _top_hanging_piece_details(board_after: chess.Board, mover_color: bool):
    """
    Returns dict with:
    - hung_piece_name, hung_square
    - attackers, defenders
    - attacker_piece_name, attacker_square (one example attacker)
    """
    opp = not mover_color
    best = None 

    for sq, piece in board_after.piece_map().items():
        if piece.color != mover_color:
            continue

        val = PIECE_VALUE.get(piece.piece_type, 0)
        if val < 3:
            continue

        attackers = list(board_after.attackers(opp, sq))
        if not attackers:
            continue

        defenders = list(board_after.attackers(mover_color, sq))
        if not defenders or len(attackers) > len(defenders):
            cand = (val, sq, piece, attackers, defenders)
            if best is None or cand[0] > best[0]:
                best = cand

    if not best:
        return None

    val, sq, piece, attackers, defenders = best

    # pick one concrete attacker square (example)
    attacker_sq = attackers[0]
    attacker_piece = board_after.piece_at(attacker_sq)

    return {
        "hung_piece_name": PIECE_NAME.get(piece.piece_type, "piece"),
        "hung_square": chess.square_name(sq),
        "attackers": len(attackers),
        "defenders": len(defenders),
        "attacker_piece_name": PIECE_NAME.get(attacker_piece.piece_type, "piece") if attacker_piece else "piece",
        "attacker_square": chess.square_name(attacker_sq),
    }

def _overworked_defender_details(board_after: chess.Board, mover_color: bool):
    """
    Detects an overworked defender:
    - Find a mover piece D (defender) that defends >=2 valuable mover pieces (val>=3)
    - Those defended targets are also attacked by the opponent (i.e. actually under pressure)
    Returns structured info to form an explanation.
    """
    opp = not mover_color

    # Build list of "valuable targets under pressure"
    targets = []  # (value, target_sq, target_piece, attackers, defenders)
    for t_sq, t_piece in board_after.piece_map().items():
        if t_piece.color != mover_color:
            continue
        t_val = PIECE_VALUE.get(t_piece.piece_type, 0)
        if t_val < 3:
            continue
        a = len(board_after.attackers(opp, t_sq))
        if a == 0:
            continue
        d = len(board_after.attackers(mover_color, t_sq))
        targets.append((t_val, t_sq, t_piece, a, d))

    if len(targets) < 2:
        return None

    best = None
    # For each potential defender square, count how many pressured targets it defends
    for d_sq, d_piece in board_after.piece_map().items():
        if d_piece.color != mover_color:
            continue
        d_val = PIECE_VALUE.get(d_piece.piece_type, 0)
        if d_val < 3:
            continue  # keep it simple: real pieces, not pawns/king

        defended = []
        for t_val, t_sq, t_piece, a, dd in targets:
            if board_after.is_attacked_by(mover_color, t_sq) and board_after.is_attacked_by(mover_color, t_sq):
                # check this defender specifically attacks the target square
                if d_sq in board_after.attackers(mover_color, t_sq):
                    defended.append((t_val, t_sq, t_piece, a, dd))

        if len(defended) < 2:
            continue

        # Prefer cases where at least one target is "unstable" (attackers >= defenders)
        unstable = any(a >= dd for _, _, _, a, dd in defended)

        # Score: total value defended + bonus for instability (so it triggers when it matters)
        score = sum(t_val for t_val, *_ in defended) + (5 if unstable else 0)

        cand = (score, d_sq, d_piece, defended)
        if best is None or cand[0] > best[0]:
            best = cand

    if not best:
        return None

    _, d_sq, d_piece, defended = best

    # Pick top 2 targets for readable explanation
    defended.sort(reverse=True, key=lambda x: x[0])
    defended = defended[:2]

    return {
        "defender_piece_name": PIECE_NAME.get(d_piece.piece_type, "piece"),
        "defender_square": chess.square_name(d_sq),
        "targets": [
            {
                "piece_name": PIECE_NAME.get(t_piece.piece_type, "piece"),
                "square": chess.square_name(t_sq),
                "attackers": a,
                "defenders": dd,
            }
            for (t_val, t_sq, t_piece, a, dd) in defended
        ],
    }


def _trade_likely_within(board_after: chess.Board, sq: chess.Square, depth: int, max_plies: int = 3) -> bool:
    """
    True if engine PV shows opponent can capture the piece on `sq` and mover can recapture (trade)
    within `max_plies` plies from board_after (opponent to move).
    """
    try:
        info = ENGINE.analyse(board_after, chess.engine.Limit(depth=depth), multipv=1)
        if isinstance(info, list):
            info = info[0] if info else {}
        pv = info.get("pv", []) or []
        pv = pv[:max_plies]

        b = board_after.copy()
        if len(pv) < 2:
            return False

        first = pv[0]  # opponent move
        if not b.is_capture(first) or first.to_square != sq:
            return False

        captured_piece = b.piece_at(sq)
        if not captured_piece:
            return False

        b.push(first)

        second = pv[1]  # mover reply
        if second not in b.legal_moves:
            return False
        
        return b.is_capture(second) and second.to_square == sq
    except Exception:
        return False


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

def _pv_uci_from(board: chess.Board, depth: int, limit: int = 8) -> list[str]:
    info = ENGINE.analyse(board, chess.engine.Limit(depth=depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}
    pv = info.get("pv", []) or []
    return [m.uci() for m in pv[:limit]]

def _uci_sq(u: str) -> tuple[str, str] | None:
    try:
        mv = chess.Move.from_uci(u)
        return (chess.square_name(mv.from_square), chess.square_name(mv.to_square))
    except Exception:
        return None

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

def _material_score(board: chess.Board) -> int:
    # positive = White material advantage
    vals = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
    s = 0
    for ptype, v in vals.items():
        s += len(board.pieces(ptype, chess.WHITE)) * v
        s -= len(board.pieces(ptype, chess.BLACK)) * v
    return s

def _mover_material_delta(board_before: chess.Board, board_after: chess.Board, mover_white: bool) -> int:
    # negative = mover gave material
    before = _material_score(board_before)
    after = _material_score(board_after)
    delta_white = after - before
    return delta_white if mover_white else -delta_white

def _is_hanging(board_after: chess.Board, mover_color: bool, square: chess.Square) -> bool:
    # piece on 'square' is hanging if attacked by opponent and not defended (or attackers > defenders)
    opp = not mover_color
    attackers = len(board_after.attackers(opp, square))
    if attackers == 0:
        return False
    defenders = len(board_after.attackers(mover_color, square))
    return defenders == 0 or attackers > defenders

def _best_reply(board: chess.Board, depth: int):
    info = ENGINE.analyse(board, chess.engine.Limit(depth=depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}
    pv = info.get("pv", [])
    mv = pv[0] if pv else None
    return info, pv, mv

def _eval_pawns_from_board(board: chess.Board, depth: int) -> float:
    info = ENGINE.analyse(board, chess.engine.Limit(depth=depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}
    return eval_from_info(info)

def is_perfect_brilliancy(board_before: chess.Board, board_after: chess.Board, played_uci: str, depth: int) -> tuple[bool, list[str]]:
    """
    Returns (is_perfect, reasons)
    Criteria:
    - played move is best or near-best (small eval loss vs engine best)
    - move sacrifices material (mover loses >= 2 points) and it is NOT immediately regained next ply
    - the sacrificed piece is hanging (capturable) after the move
    - despite the sacrifice, evaluation for mover remains strong after opponent best reply (tactical justification)
    - depth high enough
    """
    reasons = []

    if depth < 14:
        return (False, reasons)

    mover_white = (board_before.turn == chess.WHITE)

    info0, pv0, best0 = _best_reply(board_before, depth)
    best_uci = best0.uci() if best0 else None

    eval_best = eval_from_info(info0)

    try:
        mv_played = chess.Move.from_uci(played_uci)
    except Exception:
        return (False, reasons)

    b_best = board_before.copy()
    if best0 and best0 in b_best.legal_moves:
        b_best.push(best0)
        eval_after_best = _eval_pawns_from_board(b_best, depth)
    else:
        eval_after_best = None

    b_play = board_before.copy()
    if mv_played not in b_play.legal_moves:
        return (False, reasons)
    b_play.push(mv_played)
    eval_after_played = _eval_pawns_from_board(b_play, depth)

    if eval_after_best is not None:
        # compare from mover POV
        mover_eval_best = eval_after_best if mover_white else -eval_after_best
        mover_eval_play = eval_after_played if mover_white else -eval_after_played
        loss_vs_best = mover_eval_best - mover_eval_play  # positive means played is worse
        if loss_vs_best > 0.35:
            return (False, reasons)  # not near-best
        reasons.append("near_best")
    else:
        if best_uci and played_uci != best_uci:
            return (False, reasons)

    # 2) sacrifice: mover material delta is negative by >= 2 (piece/exchange)
    mat_delta = _mover_material_delta(board_before, board_after, mover_white)
    if mat_delta > -1:
        return (False, reasons)
    reasons.append(f"sacrifice_{mat_delta}")

    # 3) not immediately regained: after opponent best reply, mover is still down material
    info1, pv1, opp_best = _best_reply(board_after, depth)
    b_reply = board_after.copy()
    if opp_best and opp_best in b_reply.legal_moves:
        b_reply.push(opp_best)
        mat_delta_after_reply = _mover_material_delta(board_before, b_reply, mover_white)
        if mat_delta_after_reply >= -1:
            return (False, reasons)
        reasons.append("not_immediately_regained")
    else:
        return (False, reasons)

    # 4) hanging piece: the moved-to piece is capturable (classic brilliant pattern)
    to_sq = mv_played.to_square
    if not _is_hanging(b_play, mover_white, to_sq):
        return (False, reasons)
    reasons.append("hanging_piece")

    # 5) tactical justification: despite being down material, eval for mover remains strong
    # (after opponent best reply)
    eval_after_reply = _eval_pawns_from_board(b_reply, depth)
    mover_eval_after_reply = eval_after_reply if mover_white else -eval_after_reply

    if mover_eval_after_reply < 0.80:
        return (False, reasons)
    reasons.append("strong_followup")

    try:
        is_cap = board_before.is_capture(mv_played)
        is_chk = board_before.gives_check(mv_played)
        if (not is_cap) and (not is_chk):
            reasons.append("quiet")
    except Exception:
        pass

    return (True, reasons)


def _is_quiet_move(board: chess.Board, mv: chess.Move) -> bool:
    """Quiet = not capture and not check."""
    return (not board.is_capture(mv)) and (not board.gives_check(mv))


def _move_piece_signature(board: chess.Board, mv: chess.Move):
    """
    Returns (color, piece_type) of moving piece before the move.
    color: True=White, False=Black
    """
    p = board.piece_at(mv.from_square)
    if not p:
        return None
    return (p.color, p.piece_type)


def _recent_same_piece_moved(
    fens: list[str],
    moves_uci: list[str],
    ply: int,
    board_before: chess.Board,
) -> bool:
    """
    True if the SAME piece (same color+type and sitting on the previous destination square)
    was moved by the player on their last or second-last turn.

    ply is 1-based halfmove index.
    Current move: moves_uci[ply-1], position before it: fens[ply-1].
    Previous move of same player: ply-2, and ply-4.
    """
    if ply <= 0:
        return False

    try:
        cur_mv = chess.Move.from_uci(moves_uci[ply - 1])
    except Exception:
        return False

    cur_sig = _move_piece_signature(board_before, cur_mv)
    if not cur_sig:
        return False

    cur_from = cur_mv.from_square

    # check plies: player's last (ply-2) and second-last (ply-4)
    for q in (ply - 2, ply - 4):
        if q <= 0:
            continue
        if q - 1 >= len(moves_uci):
            continue
        if q - 1 >= len(fens):
            continue

        fen_before_q = fens[q - 1]
        try:
            prev_board = chess.Board(fen_before_q)
            prev_mv = chess.Move.from_uci(moves_uci[q - 1])
        except Exception:
            continue

        prev_sig = _move_piece_signature(prev_board, prev_mv)
        if not prev_sig:
            continue

        # must be same color+type
        if prev_sig != cur_sig:
            continue

        # The same piece will now start from where it previously landed
        if prev_mv.to_square != cur_from:
            continue

        # Ignore if previous move was forced/active (capture/check) or escaping check
        if prev_board.is_check():
            continue
        if not _is_quiet_move(prev_board, prev_mv):
            continue

        return True

    return False


def detect_lost_tempo(
    fens: list[str],
    moves_uci: list[str],
    ply: int,
    board_before: chess.Board,
    impact_mover: float,
    best_move_uci: str | None,
) -> bool:
    """
    LOST_TEMPO if:
    - same piece moved on player's last/2nd-last turn
    - current move is quiet
    - current move is not escaping check and not moving an attacked piece away
    - no material gain (quiet implies no capture)
    - (optional) engine preferred something else
    - and impact is mildly negative (avoid flagging good manoeuvres)
    """
    if ply <= 0 or ply - 1 >= len(moves_uci):
        return False

    # avoid marking when player is in check (forced defense)
    if board_before.is_check():
        return False

    try:
        mv = chess.Move.from_uci(moves_uci[ply - 1])
    except Exception:
        return False

    # must be a quiet move (no capture, no check)
    if not _is_quiet_move(board_before, mv):
        return False

    # if the moved piece was under attack, this can be a retreat/defense (NOT tempo loss)
    mover_piece = board_before.piece_at(mv.from_square)
    if mover_piece:
        opp = not mover_piece.color
        if len(board_before.attackers(opp, mv.from_square)) > 0:
            return False

    if not _recent_same_piece_moved(fens, moves_uci, ply, board_before):
        return False

    played = moves_uci[ply - 1]
    if best_move_uci and played == best_move_uci:
        return False

    if impact_mover > -0.20:
        return False

    return True

def _is_castled_king(king_sq: int, color: bool) -> bool:
    """
    Rough castled detection by king square.
    """
    return king_sq in ([chess.G1, chess.C1] if color else [chess.G8, chess.C8])


def _pawn_shield_files_for_castle(kingside: bool) -> set[int]:
    return {5, 6, 7} if kingside else {0, 1, 2, 3}  # kingside: f,g,h ; queenside: a,b,c,d


def _is_pawn_shield_push(board_before: chess.Board, mv: chess.Move) -> bool:
    """
    True if the move is a pawn move from the king's typical pawn shield area.
    Works for both castled and uncastled (assumes typical plan: king tends to castle).
    """
    p = board_before.piece_at(mv.from_square)
    if not p or p.piece_type != chess.PAWN:
        return False

    color = p.color
    king_sq = board_before.king(color)
    if king_sq is None:
        return False

    k_file = chess.square_file(king_sq)
    kingside = k_file >= 4  # if king is on e-file or right -> treat as kingside tendency
    shield_files = _pawn_shield_files_for_castle(kingside)

    from_file = chess.square_file(mv.from_square)
    # only pawn moves from shield files count
    return from_file in shield_files


def _creates_dark_holes_near_castle(board_before: chess.Board, mv: chess.Move) -> bool:
    p = board_before.piece_at(mv.from_square)
    if not p or p.piece_type != chess.PAWN:
        return False

    color = p.color
    king_sq = board_before.king(color)
    if king_sq is None:
        return False

    k_file = chess.square_file(king_sq)
    kingside = k_file >= 4
    if not kingside:
        return False

    from_rank = chess.square_rank(mv.from_square)
    to_rank = chess.square_rank(mv.to_square)
    delta = abs(to_rank - from_rank)

    from_file = chess.square_file(mv.from_square)
    # g/f/h pawn only
    if from_file not in {5, 6, 7}:
        return False

    return delta >= 2  # e.g. g2->g4


def _pv_has_fast_checks_against_mover(board_after: chess.Board, pv_uci: list[str], max_plies: int = 4) -> bool:
    """
    If opponent's PV quickly includes a check against the mover's king, that's a king-safety warning.
    """
    if not pv_uci:
        return False

    b = board_after.copy()
    mover_color = not b.turn
    plies = 0

    for u in pv_uci:
        try:
            mv = chess.Move.from_uci(u)
        except Exception:
            break
        if mv not in b.legal_moves:
            break

        # if side to move is opponent of mover and gives check
        if b.turn != mover_color and b.gives_check(mv):
            return True

        b.push(mv)
        plies += 1
        if plies >= max_plies:
            break

    return False


def detect_opens_king(
    board_before: chess.Board,
    board_after: chess.Board,
    played_move_uci: str,
    mover_is_white: bool,
    impact_mover: float,
    opponent_pv_uci: list[str] | None,
) -> bool:
    """
    OPENS_KING = weakens own king safety.

    We flag it when:
    - move is not forced (not in check before move) and is a quiet pawn move,
    - AND it moves a pawn from the king pawn shield area (especially 2-square pushes),
    - AND (impact is meaningfully negative OR opponent PV quickly contains checks).
    """
    if board_before.is_check():
        return False

    try:
        mv = chess.Move.from_uci(played_move_uci)
    except Exception:
        return False

    # avoid forced/tactical moves
    if board_before.is_capture(mv) or board_before.gives_check(mv):
        return False

    # main trigger: pawn shield push
    shield_push = _is_pawn_shield_push(board_before, mv)
    if not shield_push:
        return False
    holey = _creates_dark_holes_near_castle(board_before, mv)
    pv_checks = _pv_has_fast_checks_against_mover(board_after, opponent_pv_uci or [], max_plies=4)
    if holey and (impact_mover <= -0.20 or pv_checks):
        return True
    if impact_mover <= -0.50:
        return True
    if pv_checks and impact_mover <= -0.20:
        return True

    return False

def _log_reasons(game_id: int, ply: int, played: str, quality: str, reasons: list[str]):
    print(f"[EXPLAIN][game={game_id} ply={ply}] played={played} quality={quality} reasons={reasons}")

class AlternateLineRequest(BaseModel):
    game_id: int
    ply: int
    depth: int = 14
    max_plies: int = 10

@app.post("/alternate_line/")
async def alternate_line(req: AlternateLineRequest):
    game = games_data.get(req.game_id)
    if not game:
        return JSONResponse(content={"message": "Unknown game_id"}, status_code=404)

    fens = game["moves"]
    if req.ply <= 0 or req.ply >= len(fens):
        return JSONResponse(content={"message": "Invalid ply"}, status_code=400)

    fen_before = fens[req.ply - 1]
    board = chess.Board(fen_before)

    info = ENGINE.analyse(board, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info, list):
        info = info[0] if info else {}
    pv = (info.get("pv", []) or [])[: req.max_plies]

    out_fens = [fen_before]
    out_san = []

    tmp = board.copy()
    for mv in pv:
        if mv not in tmp.legal_moves:
            break
        out_san.append(tmp.san(mv))
        tmp.push(mv)
        out_fens.append(tmp.fen())

    return {
        "start_ply": req.ply,
        "fens": out_fens,
        "moves_san": out_san,
        "moves_uci": [m.uci() for m in pv[: len(out_san)]],
    }

class ExplainAlternateRequest(BaseModel):
    game_id: int
    ply: int
    depth: int = 14

@app.post("/explain_alternate/")
async def explain_alternate(req: ExplainAlternateRequest):
    game = games_data.get(req.game_id)
    if not game:
        return JSONResponse(content={"message": "Unknown game_id"}, status_code=404)

    fens = game["moves"]
    moves_uci = game["moves_uci"]

    if req.ply <= 0 or req.ply >= len(fens):
        return JSONResponse(content={"message": "Invalid ply"}, status_code=400)

    fen_before = fens[req.ply - 1]
    played_uci = moves_uci[req.ply - 1]
    board_before = chess.Board(fen_before)
    mover_color = board_before.turn  # True=White, False=Black

    # engine best from BEFORE position
    info0, pv0, best0 = _engine_best_line(board_before, depth=req.depth)
    best_uci = best0.uci() if best0 else None
    if not best_uci:
        return {"ply": req.ply, "bullets": ["Engine best move not available."]}

    # board after PLAYED move
    board_after_played = board_before.copy()
    mv_played = chess.Move.from_uci(played_uci)
    if mv_played in board_after_played.legal_moves:
        board_after_played.push(mv_played)

    # board after BEST move
    board_after_best = board_before.copy()
    mv_best = chess.Move.from_uci(best_uci)
    if mv_best in board_after_best.legal_moves:
        board_after_best.push(mv_best)
    
    bullets = []

    played_pv_uci = _pv_uci_from(board_after_played, req.depth, limit=8)
    best_pv_uci   = _pv_uci_from(board_after_best, req.depth, limit=8)
    
    mover_is_white = (board_before.turn == chess.WHITE)

    opens_played = detect_opens_king(
        board_before=board_before,
        board_after=board_after_played,
        played_move_uci=played_uci,
        mover_is_white=mover_is_white,
        impact_mover=-0.3,
        opponent_pv_uci=played_pv_uci,
    )

    opens_best = detect_opens_king(
        board_before=board_before,
        board_after=board_after_best,
        played_move_uci=best_uci,
        mover_is_white=mover_is_white,
        impact_mover=0.0,
        opponent_pv_uci=best_pv_uci,
    )

    if opens_played and not opens_best:
        sqs = _uci_sq(played_uci)
        if sqs:
            frm, to = sqs
            bullets.append(f"Your move {frm}–{to} loosens the pawn shield around your king.")
            bullets.append(f"The engine line keeps the king safer by not pushing that pawn.")
        else:
            bullets.append("Your move weakens your king’s pawn shield; the engine line keeps the king safer.")


    hung = _top_hanging_piece_details(board_after_played, mover_color)
    if hung:
        sq_name = hung["hung_square"]
        hung_piece = hung["hung_piece_name"]
        attacker_piece = hung["attacker_piece_name"]
        attacker_sq = hung["attacker_square"]
        a = hung["attackers"]
        d = hung["defenders"]

        sq = chess.parse_square(sq_name)
        fixed = not _is_hanging(board_after_best, mover_color, sq)

        moved_piece = board_before.piece_at(mv_best.from_square)
        moved_piece_name = PIECE_NAME.get(moved_piece.piece_type, "piece") if moved_piece else "piece"

        if fixed:
            bullets.append(f"Your {hung_piece} on {sq_name} was hanging: attacked by the opponent’s {attacker_piece} from {attacker_sq}")
            bullets.append(f"({a} attacker{'s' if a!=1 else ''} vs {d} defender{'s' if d!=1 else ''}).")
            bullets.append(f"The best move defends {sq_name} with your {moved_piece_name}.")
        else:
            bullets.append(f"Your {hung_piece} on {sq_name} is hanging: attacked by the opponent’s {attacker_piece} from {attacker_sq}")
            bullets.append(f"({a} attacker{'s' if a!=1 else ''} vs {d} defender{'s' if d!=1 else ''}).")

    ow_played = _overworked_defender_details(board_after_played, mover_color)
    ow_best = _overworked_defender_details(board_after_best, mover_color)

    if ow_played and not ow_best:
        t1, t2 = ow_played["targets"][0], ow_played["targets"][1]
        bullets.append(f"Relieves an overworked {ow_played['defender_piece_name']} on {ow_played['defender_square']}")
        bullets.append(f"The piece was defending your {t1['piece_name']} on {t1['square']} and your {t2['piece_name']} on {t2['square']}.")


    lost_played = detect_lost_tempo(
    fens=fens,
    moves_uci=moves_uci,
    ply=req.ply,
    board_before=board_before,
    impact_mover=-0.3,
    best_move_uci=best_uci,
    )

    lost_best = detect_lost_tempo(
        fens=fens,
        moves_uci=moves_uci,
        ply=req.ply,
        board_before=board_before,
        impact_mover=0.0,
        best_move_uci=best_uci,
    )

    if lost_played and not lost_best:
        mv = chess.Move.from_uci(best_uci)
        piece = board_before.piece_at(mv.from_square)
        piece_name = PIECE_NAME.get(piece.piece_type, "piece") if piece else "piece"
        square_name = chess.square_name(mv.to_square)
        follow_sq = None
        pv = best_pv_uci
        if len(pv) >= 3:
            mv2 = chess.Move.from_uci(pv[1])
            follow_sq = chess.square_name(mv2.to_square)
            
        if req.ply <= 20:
            bullets.append(f"Improves the activity of your {piece_name} by moving it to {square_name}.")
            if follow_sq:
                bullets.append(f"This prepares further improvement, such as a follow-up move to {follow_sq}.")
            else:
                bullets.append("This improves piece coordination without losing tempo.")

        else:
            bullets.append(f"Develops your {piece_name} by placing it on {square_name}.")
            if follow_sq:
                bullets.append(f"This allows you to continue development next, for example by playing to {follow_sq}.")
            else:
                bullets.append("This keeps your development on track without wasting time.")


    return {
        "ply": req.ply,
        "best_move_uci": best_uci,
        "bullets": bullets,
    }


@app.post("/explain_move/")
async def explain_move(req: ExplainMoveRequest):
    cache_key = (req.game_id, req.ply, req.depth)
    cached = EXPLAIN_CACHE.get(cache_key)
    if cached is not None:
        return cached

    print(f"[EXPLAIN] HIT game_id={req.game_id} ply={req.ply}", flush=True)
    sys.stdout.flush()
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

    after_line = _best_reply_and_pv_after(board_after, depth=req.depth, max_len=10)
    opp_best_reply_uci = after_line["best_reply_uci"]
    pv_after_uci = after_line["pv_after_uci"]
    pv_after_san = after_line["pv_after_san"]

    played_san = _uci_to_san(board_before, played_move)
    opp_reply_san = _uci_to_san(board_after, opp_best_reply_uci) if opp_best_reply_uci else None

    info_before = ENGINE.analyse(board_before, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info_before, list):
        info_before = info_before[0]

    info_after = ENGINE.analyse(board_after, chess.engine.Limit(depth=req.depth), multipv=1)
    if isinstance(info_after, list):
        info_after = info_after[0]

    eval_before = eval_from_info(info_before)
    eval_after = eval_from_info(info_after)

    pv = info_before.get("pv", []) or []
    best_move = pv[0].uci() if pv else None

    is_white = fen_before.split(" ")[1] == "w"
    impact = (eval_after - eval_before) if is_white else (eval_before - eval_after)

    debug_reasons = []
    bullets = []

    quality = classify_impact(impact)

    # "best" should mean: Stockfish's top choice from this position
    if best_move and played_move == best_move:
        quality = "best"

    try:
        is_perfect, perfect_reasons = is_perfect_brilliancy(board_before, board_after, played_move, req.depth)
        if is_perfect:
            quality = "perfect"
            debug_reasons.append("PERFECT_BRILLIANT")
            debug_reasons.extend([f"PERFECT:{r}" for r in perfect_reasons])
            bullets.append("Brilliancy: a strong sacrifice that remains tactically justified.")
            logger.info(f"Perfect move detected at ply {req.ply}")
    except Exception:
        pass

    # 2) HANGING_PIECE
    mover_is_white = (fen_before.split(" ")[1] == "w")
    hanging_msg = _hanging_piece_bullet(board_after, mover_is_white, depth=req.depth)
    if hanging_msg:
        debug_reasons.append("HANGING_PIECE")
    if "HANGING_PIECE" in debug_reasons and "LOST_TEMPO" in debug_reasons:
        debug_reasons.remove("LOST_TEMPO")
    print(
        f"[EXPLAIN] game={req.game_id} ply={req.ply} "
        f"played={played_move} quality={quality} reasons={debug_reasons}",
        flush=True
    )
    # bullets.append(f"Evaluation changed from {eval_before:+.2f} to {eval_after:+.2f}.")
    if opp_best_reply_uci:
        bullets.append(f"After {played_san}, opponent’s best reply is {opp_reply_san}.")
        if pv_after_san:
            bullets.append("Example continuation: " + " ".join(pv_after_san[:8]) + ".")
    
    # LOST_TEMPO
    if detect_lost_tempo(
        fens=fens,
        moves_uci=moves_uci,
        ply=req.ply,
        board_before=board_before,
        impact_mover=impact,
        best_move_uci=best_move,
    ):
        debug_reasons.append("LOST_TEMPO")
        bullets.append("Loses tempo: the same piece was moved again without a tactical gain or necessity.")

    played_san = _uci_to_san(board_before, played_move)
    best_san = _uci_to_san(board_before, best_move) if best_move else None
    opponent_pv_uci = []
    opponent_pv_san = []

    # OPENS_KING
    if detect_opens_king(
        board_before=board_before,
        board_after=board_after,
        played_move_uci=played_move,
        mover_is_white=is_white,
        impact_mover=impact,
        opponent_pv_uci=opponent_pv_uci,
    ):
        debug_reasons.append("OPENS_KING")
        bullets.append("Weakens king safety: the pawn shield is loosened.")
        bullets.append("This allows the opponent to get play against your king.")


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

            #bullets.append(f"Main line: {_short_pv_san(board_after, pv_opp, plies=4)}")

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

    _log_reasons(req.game_id, req.ply, played_move, quality, debug_reasons)

    return {
        "ply": req.ply,
        #"played_move_uci": played_move,
        "played_move_san": played_san,
        #"best_move_uci": best_move,
        "best_move_san": best_san,
        "pv_uci": [m.uci() for m in pv][:8],
        "eval_before": eval_before,
        "eval_after": eval_after,
        "impact_mover": impact,
        "quality": quality,
        "bullets": bullets,
        "to_row": to_row,
        "to_col": to_col,
        "opp_best_reply_uci": opp_best_reply_uci,
        "opp_best_reply_san": opp_reply_san,
        "opponent_pv_uci": opponent_pv_uci,
        "opponent_pv_san": opponent_pv_san,
        "pv_after_uci": pv_after_uci[:10] if pv_after_uci else [],
        "pv_after_san": pv_after_san[:10] if pv_after_san else [],
        "debug_reasons": debug_reasons,
    }
