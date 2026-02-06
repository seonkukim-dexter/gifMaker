import os
import sys
import json
import urllib.request
import subprocess
import threading
from tkinter import messagebox
import constants as const  # 상수 모듈 임포트

# -------------------------------------------------------------------------
# 업데이트 확인 및 다이얼로그
# -------------------------------------------------------------------------
def check_for_updates(app_instance):
    """원격 서버의 version.json을 확인하여 업데이트 여부 판별"""
    try:
        with urllib.request.urlopen(const.VERSION_CHECK_URL) as r:
            data = json.loads(r.read().decode())
            if data.get("version", const.APP_VERSION) > const.APP_VERSION:
                app_instance.latest_update_data = data
                app_instance.after(0, lambda: show_update_dialog(app_instance, data["version"]))
    except: pass

def show_update_dialog(app_instance, v):
    if messagebox.askyesno("업데이트", f"새 버전 v{v}가 발견되었습니다. 업데이트할까요?"):
        threading.Thread(target=perform_update, args=(app_instance,), daemon=True).start()

# -------------------------------------------------------------------------
# 업데이트 실행 로직 (플랫폼별 분기)
# -------------------------------------------------------------------------
def perform_update(app_instance):
    """플랫폼에 맞는 업데이트 바이너리 다운로드 및 설치 프로세스 실행"""
    try:
        # UI 업데이트: 진행 표시
        app_instance.after(0, lambda: (app_instance.progress_bar.grid(row=8, column=0, pady=10), 
                                      app_instance.progress_label.grid(row=9, column=0), 
                                      app_instance.progress_label.configure(text="업데이트 다운로드 중...")))
        
        current_app_path = os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__)
        app_name = os.path.basename(current_app_path)

        # -------------------------------------------------------------------------
        # Windows 업데이트 로직
        # -------------------------------------------------------------------------
        if sys.platform == "win32":
            download_url = app_instance.latest_update_data.get("win_url")
            temp_exe = "update_temp.exe"
            urllib.request.urlretrieve(download_url, temp_exe)
            
            bat_path = "update.bat"
            # 배치 파일 생성: 기존 프로세스 종료 대기 -> 파일 교체 -> 재실행
            with open(bat_path, "w", encoding='cp949') as f:
                f.write(f'''@echo off
setlocal enabledelayedexpansion
title Update in Progress...
echo Waiting for program to close...

:LOOP
taskkill /F /IM "{app_name}" >nul 2>&1
timeout /t 2 /nobreak >nul

move /y "{temp_exe}" "{current_app_path}" >nul 2>&1
if errorlevel 1 (
echo Current file is locked. Retrying in 2 seconds...
goto LOOP
)

echo Update Successful! Starting application...
timeout /t 1 /nobreak >nul
start "" "{current_app_path}"
del "%~f0"
exit
''')
            subprocess.Popen([bat_path], shell=True)
            app_instance.after(0, app_instance.quit)

        # -------------------------------------------------------------------------
        # macOS 업데이트 로직
        # -------------------------------------------------------------------------
        elif sys.platform == "darwin":
            download_url = app_instance.latest_update_data.get("mac_url")
            temp_zip = "/tmp/gifMaker_update.zip"
            urllib.request.urlretrieve(download_url, temp_zip)
            
            temp_dir = "/tmp/gifMaker_temp"
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            os.makedirs(temp_dir)
            
            target_path = current_app_path
            # PyInstaller로 빌드된 앱 번들(.app)의 상위 경로 찾기
            if getattr(sys, 'frozen', False):
                # Contents/MacOS/executable -> .app 폴더
                target_path = os.path.dirname(os.path.dirname(os.path.dirname(current_app_path)))
            
            current_pid = os.getpid()
            
            # 쉘 스크립트 생성: 종료 대기 -> 압축 해제 -> 교체 -> 권한 복구 -> 재실행
            updater_script_path = "/tmp/gifmaker_updater.sh"
            with open(updater_script_path, "w") as f:
                f.write(f'''#!/bin/bash
    LOG="/tmp/gifmaker_update.log"
    echo "Starting update process..." > "$LOG"

    echo "Waiting for PID {current_pid} to exit..." >> "$LOG"
    while kill -0 {current_pid} 2>/dev/null; do sleep 1; done

    echo "Unzipping update from {temp_zip}..." >> "$LOG"
    /usr/bin/unzip -o "{temp_zip}" -d "{temp_dir}" >> "$LOG" 2>&1

    NEW_APP=$(find "{temp_dir}" -name "*.app" -maxdepth 2 | head -n 1)
    echo "New app found at: $NEW_APP" >> "$LOG"

    if [ -d "$NEW_APP" ]; then
    echo "Replacing old app at: {target_path}" >> "$LOG"
    rm -rf "{target_path}" >> "$LOG" 2>&1
    /usr/bin/ditto "$NEW_APP" "{target_path}" >> "$LOG" 2>&1

    echo "Fixing permissions and quarantine..." >> "$LOG"
    /usr/bin/xattr -dr com.apple.quarantine "{target_path}" >> "$LOG" 2>&1
    /bin/chmod -R 755 "{target_path}" >> "$LOG" 2>&1

    echo "Restarting application..." >> "$LOG"
    /usr/bin/open "{target_path}" >> "$LOG" 2>&1
    echo "Update complete!" >> "$LOG"
    else
    echo "ERROR: New app bundle not found in extracted files." >> "$LOG"
    fi

    rm -rf "{temp_dir}"
    rm -f "{temp_zip}"
    rm -f "$0"
    ''')  
            os.chmod(updater_script_path, 0o755)
            # 관리자 권한으로 스크립트 실행
            apple_script = f'do shell script "{updater_script_path} > /dev/null 2>&1 &" with administrator privileges'
            app_instance.after(0, lambda: messagebox.showinfo("업데이트", "관리자 승인 후 업데이트가 시작됩니다.\n앱이 종료된 후 자동으로 재시작됩니다."))
            subprocess.Popen(["osascript", "-e", apple_script])
            app_instance.after(1000, app_instance.quit)
            
    except Exception as e:
        app_instance.after(0, lambda m=str(e): messagebox.showerror("실패", f"업데이트 오류: {m}"))
    finally:
        app_instance.after(0, lambda: (app_instance.progress_bar.pack_forget(), app_instance.progress_label.pack_forget()))