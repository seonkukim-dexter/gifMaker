@echo off
@chcp 65001 1> NUL 2> NUL
echo ===================================================
echo [1/3] 빌드 전용 가상환경(venv) 생성 및 라이브러리 설치 중...
echo ===================================================

:: 기존 빌드 잔해 삭제 (캐시 및 이전 빌드 데이터로 인한 오류 방지)
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"
if exist "GifMaker_Portable.spec" del /q "GifMaker_Portable.spec"

:: 가상환경 폴더가 없다면 생성합니다.
if not exist "build_env" (
echo 가상환경을 생성하는 중입니다...
python -m venv build_env
)

:: 가상환경을 활성화합니다.
call build_env\Scripts\activate

:: 가상환경 내부에서 필수 및 의존성 라이브러리를 모두 설치합니다.
python -m pip install --upgrade pip
pip install moviepy customtkinter pillow tkinterdnd2 proglog tqdm pyinstaller imageio-ffmpeg decorator imageio

echo.
echo ===================================================
echo [2/3] PyInstaller를 이용한 초강력 단일 포터블 파일 빌드 시작...
echo (모든 라이브러리 데이터를 강제로 포함하므로 시간이 걸립니다)
echo ===================================================

:: --collect-all 옵션을 사용하여 moviepy 및 의존성 라이브러리의 모든 리소스를 포함시킵니다.
:: --collect-submodules를 추가하여 moviepy 내부의 모든 하위 모듈을 수집합니다.

pyinstaller --noconsole --onefile ^
--icon="gifMaker.ico" ^
--collect-all tkinterdnd2 ^
--collect-all customtkinter ^
--collect-all moviepy ^
--collect-all imageio ^
--collect-submodules moviepy ^
--hidden-import moviepy.editor ^
--hidden-import moviepy.video.io.VideoFileClip ^
--hidden-import moviepy.audio.io.AudioFileClip ^
--hidden-import moviepy.video.VideoClip ^
--hidden-import proglog ^
--hidden-import tqdm ^
--hidden-import decorator ^
--hidden-import imageio_ffmpeg ^
--name "gifMaker" ^
main.py

echo.
echo ===================================================
echo [3/3] 빌드 완료! 가상환경을 해제합니다.
echo 결과물: dist/gifMaker.exe
echo ===================================================
call deactivate
pause