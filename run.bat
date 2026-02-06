@echo off
if not exist .venv (
    echo Virtual environment not found. Creating...
    py -3.13 -m venv .venv
    call .venv\Scripts\activate
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate
)
echo Starting GenaBot...
python -m bot
pause
