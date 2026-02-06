#!/usr/bin/env bash

# 스크립트 실행 중 에러 발생 시 즉시 중단
set -e

echo "=========================================="
echo "      macOS Application Build Start       "
echo "=========================================="

# 1. Python3 설치 여부 및 Tkinter 확인
if ! command -v python3 &> /dev/null; then
    echo "[Error] Python3가 설치되어 있지 않습니다. 'brew install python'을 먼저 실행하세요."
    exit 1
fi

echo "[Check] Tkinter 설치 여부 확인 중..."
if ! python3 -c "import tkinter" &> /dev/null; then
    echo "----------------------------------------------------------"
    echo "[Error] Tkinter가 설치되어 있지 않습니다."
    echo "macOS Homebrew 환경에서는 아래 명령어를 실행해야 합니다:"
    echo "  brew install python-tk"
    echo "----------------------------------------------------------"
    exit 1
fi

# 2. 가상 환경 설정
echo "[Step 1] 가상 환경(venv) 설정 중..."
# 만약 pip 실행 파일이 없거나 깨졌다면 삭제 후 재생성
if [ ! -f ".venv/bin/pip" ]; then
    echo " -> 가상 환경이 없거나 손상되었습니다. 새로 생성합니다."
    rm -rf .venv
    python3 -m venv .venv
else
    echo " -> 기존 가상 환경을 사용합니다."
fi

# 가상 환경 활성화
source .venv/bin/activate

# 3. 필수 라이브러리 설치
echo "[Step 2] 필요한 라이브러리 설치 중..."
pip install --upgrade pip
pip install moviepy customtkinter pillow tkinterdnd2 proglog tqdm pyinstaller imageio-ffmpeg decorator imageio

#if [ -f "requirements.txt" ]; then
#    pip install -r requirements.txt
#fi

echo ""
echo "=========================================="
echo "   테스트 가상환경 셋업이 완료되었습니다!          "
echo "=========================================="

# 테스트 실행
python3 ./main.py

# 가상 환경 비활성화
deactivate