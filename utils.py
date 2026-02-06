import os
import sys
import re
import time
from PIL import Image

# -------------------------------------------------------------------------
# Pillow 버전 호환성 처리 (상수가 아닌 객체이므로 유틸리티/호환성 영역에 유지)
# -------------------------------------------------------------------------
try:
    RESAMPLING_LANKZOS = Image.Resampling.LANKZOS
    RESAMPLING_BILINEAR = Image.Resampling.BILINEAR
except AttributeError:
    # 구버전 Pillow 대응
    RESAMPLING_LANKZOS = getattr(Image, "LANKZOS", getattr(Image, "ANTIALIAS", None))
    RESAMPLING_BILINEAR = getattr(Image, "BILINEAR", None)

# -------------------------------------------------------------------------
# OS 플랫폼 환경 설정 (macOS 포크 안전성)
# -------------------------------------------------------------------------
if sys.platform == "darwin":
    os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
    os.environ["OS_ACTIVITY_MODE"] = "disable"

# -------------------------------------------------------------------------
# Drag and Drop 라이브러리 가용성 확인
# -------------------------------------------------------------------------
HAS_DND = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except (ImportError, RuntimeError, Exception):
    HAS_DND = False

# -------------------------------------------------------------------------
# 유틸리티 함수
# -------------------------------------------------------------------------
def natural_sort_key(s):
    """
    숫자가 포함된 문자열을 사람이 인식하는 순서대로 정렬하기 위한 키 생성
    예: ['frame1.png', 'frame2.png', 'frame10.png']
    """
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]

def format_timecode(seconds, fps=24):
    """
    초(seconds) 단위를 00:00:00:00 (시:분:초:프레임) 형식의 타임코드로 변환
    """
    if fps is None or fps <= 0:
        fps = 24
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    f = int(round((seconds % 1) * fps))
    if f >= fps:
        f = 0
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"

def get_unique_path(path):
    """
    파일 저장 시 동일한 이름이 존재할 경우, 파일명 뒤에 _1, _2 등을 붙여 고유한 경로 반환
    """
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"

# -------------------------------------------------------------------------
# MoviePy ProgressBarLogger 상속 및 커스텀 구현
# -------------------------------------------------------------------------
try:
    from proglog import ProgressBarLogger
    class CTKLogger(ProgressBarLogger):
        """
        MoviePy의 변환 과정을 모니터링하고 메인 앱의 UI(프로그레스 바, 라벨)를
        Thread-safe하게 업데이트하는 로거 클래스입니다.
        """
        def __init__(self, master_app, prefix="", job_index=None, total_jobs=1):
            super().__init__()
            self.master_app = master_app
            self.prefix = prefix
            self.job_index = job_index  # None이면 단일 변환, 숫자면 일괄 변환의 인덱스
            self.total_jobs = total_jobs
            self.start_time = time.time()

        def bars_update(self, bar, index, total=None):
            # bar(예: 'main') 정보 초기화 및 업데이트
            if bar not in self.state['bars']:
                self.state['bars'][bar] = {'index': 0, 'total': total if total else 1}
            
            if total is not None:
                self.state['bars'][bar]['total'] = total
            self.state['bars'][bar]['index'] = index
            self.callback()

        def callback(self, **changes):
            # 사용자의 취소 요청 확인
            if self.master_app.cancel_requested:
                raise RuntimeError("CANCEL_REQUESTED")
            
            # 일시 정지 상태일 경우 대기
            while self.master_app.batch_paused:
                if self.master_app.cancel_requested:
                    raise RuntimeError("CANCEL_REQUESTED")
                time.sleep(0.5)

            # 진행률 계산 및 시간 정보 갱신
            for message in self.state['bars'].values():
                if message['total'] > 0:
                    percentage = message['index'] / message['total']
                    if message['index'] >= message['total'] - 1:
                        percentage = 1.0
                        
                    elapsed = time.time() - self.start_time
                    if percentage > 0.01:
                        est_total_for_one = elapsed / percentage
                        rem_this = int(est_total_for_one - elapsed)
                        # 전체 일괄 변환 시 남은 시간 합산 계산
                        rem_total = int(rem_this + (est_total_for_one * (self.total_jobs - (self.job_index if self.job_index is not None else 0) - 1)))
                        time_info = f" (남은 시간: {max(0, rem_this)}초 / 전체: {max(0, rem_total)}초)"
                    else:
                        time_info = " (계산 중...)"

                    # 메인 스레드(UI 스레드)에 안전하게 업데이트 요청
                    if self.master_app:
                        self.master_app.after(0, lambda p=percentage, ti=time_info: 
                            self.master_app._update_ui_from_logger(self.job_index, p, self.prefix, ti))
except ImportError:
    class CTKLogger:
        """MoviePy 관련 로깅 라이브러리가 없을 경우를 대비한 대체 클래스"""
        def __init__(self, *args, **kwargs): pass
        def bars_update(self, *args, **kwargs): pass
        def callback(self, *args, **kwargs): pass