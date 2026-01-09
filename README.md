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


## 🚀 How to Run

1. Backend

    Make sure Stockfish and Node.js are installed and accessible.
    (https://stockfishchess.org/download/)
    (https://nodejs.org/en/download)
    
    Powershell:

        pip install fastapi

        pip install uvicorn

        pip install python-chess

        $env:STOCKFISH_PATH="C:\(path to stockfish)\stockfish-windows-x86-64-avx2.exe"

        uvicorn main:app --reload

2. Frontend

    Bash:

        npm install

        npm start


## 📂 Workflow

1. Upload a PGN file

2. View the game summary

3. Toggle to step-by-step analysis

4. Navigate moves and inspect evaluations & explanations