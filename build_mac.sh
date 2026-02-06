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
echo "[Step 3] macOS 앱 번들(.app) 빌드 중 (속도 최적화 모드)..."
echo "파일명: gifMaker.py -> 앱이름: gifMaker"

# 4. PyInstaller 실행
# --onedir (-D): 단일 파일 대신 폴더 구조 사용 (실행 속도가 매우 빨라짐)
# --noconfirm: 기존 폴더 자동 삭제
# --collect-all 옵션을 사용하여 moviepy 및 의존성 라이브러리의 모든 리소스를 포함시킵니다.
# --collect-submodules를 추가하여 moviepy 내부의 모든 하위 모듈을 수집합니다.

pyinstaller --noconsole --windowed --onedir --clean --noconfirm \
--icon="gifMaker.icns" \
--collect-all tkinterdnd2 \
--collect-all customtkinter \
--collect-all moviepy \
--collect-all imageio \
--collect-submodules moviepy \
--hidden-import moviepy.editor \
--hidden-import moviepy.video.io.VideoFileClip \
--hidden-import moviepy.audio.io.AudioFileClip \
--hidden-import moviepy.video.VideoClip \
--hidden-import proglog \
--hidden-import tqdm \
--hidden-import decorator \
--hidden-import imageio_ffmpeg \
--name "gifMaker" \
main.py

echo ""
echo "[Step 4] 보안 권한 해제 및 정리..."
if [ -d "dist/gifMaker.app" ]; then
    xattr -cr dist/gifMaker.app
    echo " -> 앱 권한 해제 완료."
fi

echo ""
echo "=========================================="
echo "          빌드가 완료되었습니다!          "
echo "=========================================="
echo "결과물 위치: ./dist/gifMaker.app"
echo ""
echo "🚀 개선 사항: --onefile 대신 --onedir를 사용하여 실행 속도를 개선했습니다."
echo "이제 앱을 실행하면 즉시 UI가 나타날 것입니다."

# 가상 환경 비활성화
deactivate