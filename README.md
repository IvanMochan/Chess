# ♟️ Chess Analysis App

A web-based chess analysis tool that lets you upload a PGN file, replay the game move by move, and get engine-powered evaluations, move quality classification, and human-readable explanations.


## ✨ Features

* Upload and parse PGN files

* Interactive chessboard replay

* Stockfish engine analysis

* Evaluation bar synced with current position

* Move quality classification:

* Perfect, Best, Good, Okay, Bad, Blunder

* Visual indicators (colored dots) on played moves

* Game summary (move quality counts for White & Black)

* Step-by-step explanations for bad moves and blunders

* Clean, custom UI with coordinates (a–h, 1–8)


## 🧱 Tech Stack

- Frontend: React

- Backend: FastAPI (Python)

- Engine: Stockfish

- Chess logic: python-chess


## 📂 Workflow

1. Visit https://ivanmochan.github.io/Chess/

2. Upload a PGN file

3. View the game summary

4. Toggle to step-by-step analysis

5. Navigate moves and inspect evaluations & explanations