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
echo  테스트 가상환경 셋업이 완료되었습니다!
echo ===================================================


:: 테스트 실행
python .\main.py

:: 가상 환경 비활성화
call deactivate
pause