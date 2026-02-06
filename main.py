import sys
import os
from app_main import VideoToGifApp

def main():
    # macOS 포크 안전성 설정
    if sys.platform == "darwin":
        os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
        os.environ["OS_ACTIVITY_MODE"] = "disable"

    # 애플리케이션 실행
    app = VideoToGifApp()
    app.mainloop()

if __name__ == "__main__":
    main()