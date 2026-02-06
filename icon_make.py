from PIL import Image
import os

# 1. 파일명 설정
app = "gifMaker"
input_png = "%s.png" % app

# 파일 존재 여부 확인
if not os.path.exists(input_png):
    print("[오류] %s 파일이 존재하지 않습니다. PNG 파일을 준비해 주세요." % input_png)
else:
    img = Image.open(input_png)

    # 2. 아이콘 사이즈 정의
    # Windows (.ico): 16~256 사이즈 위주
    # macOS (.icns): 16~1024 사이즈까지 대응 (512@2x가 1024임)
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icns_sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)]

    # 3. .ico 저장 (Windows용)
    img.save("%s.ico" % app, sizes=ico_sizes)
    print("✅ %s.ico --> 생성 완료!" % app)

    # 4. .icns 저장 (macOS용)
    # Pillow는 이미지 사이즈가 충분히 크면 자동으로 필요한 리소스셋을 생성합니다.
    img.save("%s.icns" % app, append_images=[img], sizes=icns_sizes)
    print("✅ %s.icns --> 생성 완료!" % app)

    print("\n이제 macOS 빌드 스크립트(build_mac.sh)에서 .icns 파일을 사용하도록 수정하세요.")