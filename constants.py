# 프로그램 정보
APP_VERSION = "2.2.2" # (핫픽스) MP4, WebM에 오디오가 있는 경우 에러나는 문제 수정
APP_TITLE = "Dexter GIF Maker by wondermc"
GITHUB_USER = "seonkukim-dexter"
GITHUB_REPO = "gifMaker"
VERSION_CHECK_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/version.json"

# UI 설정 상수
RESOLUTIONS = ["320", "480", "640", "800", "1280", "1920"]
DEFAULT_WIDTH = "1280"
FPS_OPTIONS = [1, 60] # Min, Max
DEFAULT_FPS = 24

# 포맷 관련 상수
EXPORT_FORMATS = ["GIF", "MP4", "WebM", "WebP", "Sequence", "Thumbnail"]
SEQUENCE_FORMATS = ["JPG", "PNG", "WebP", "GIF"]
DEFAULT_EXPORT_FORMAT = "GIF"
DEFAULT_SEQ_FORMAT = "PNG"

# 파일 확장자 필터
FILETYPES_SINGLE = [("Single Files", "*.mp4 *.mkv *.mov *.avi *.webm *.gif")]
FILETYPES_SEQUENCE = [("Sequence Files", "*.png *.jpg *.jpeg *.gif *.exr *.tga *.bmp *.tiff *.webp")]
FILETYPES_JSON = [("JSON", "*.json")]

# 지원 확장자 목록 (로직 판별용)
VIDEO_EXTS = ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.gif')
IMAGE_EXTS = ('.gif', '.png', '.jpg', '.jpeg', '.exr', '.tga', '.bmp', '.tiff', '.webp')

# 색보정 기본값 설정 (이름, 최소, 최대, 기본값)
COLOR_CONFIGS = [
    ("노출", -100.0, 100.0, 0.0),
    ("감마", 0.1, 3.0, 1.0),
    ("대비", -100.0, 100.0, 0.0),
    ("채도", 0.0, 3.0, 1.0),
    ("틴트", -100.0, 100.0, 0.0),
    ("색온도", -100.0, 100.0, 0.0)
]