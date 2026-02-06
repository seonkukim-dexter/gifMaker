import os
import time
import numpy as np
import re
import subprocess
import json
from io import BytesIO
from PIL import Image, ImageEnhance, ImageSequence
from moviepy import VideoFileClip, VideoClip
from utils import natural_sort_key, RESAMPLING_LANKZOS
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_sequence_info(filename):
    """
    파일명에서 시퀀스 패턴(접두어, 구분자, 숫자, 확장자) 추출.
    """
    root, ext = os.path.splitext(filename)
    # 파일명 끝의 숫자 패턴 매칭 (예: name_001.gif)
    match = re.search(r'(.*?)([._-]?)(\d+)$', root)
    if match:
        return match.group(1), match.group(3), ext, match.group(2)
    return root, None, ext, ""

def get_sequence_display_name(paths):
    """시퀀스 파일 리스트를 기반으로 사용자에게 보여줄 요약 이름을 생성합니다."""
    if not paths: return "Sequence"
    frame_data = []
    for p in paths:
        fname = os.path.basename(p)
        prefix, num_str, ext, sep = get_sequence_info(fname)
        if num_str is not None:
            frame_data.append((int(num_str), num_str, prefix, ext, sep))
    
    if not frame_data:
        return f"{os.path.basename(os.path.dirname(paths[0]))} (Sequence)"
    
    frame_data.sort(key=lambda x: x[0])
    start_info, end_info = frame_data[0], frame_data[-1]
    return f"{start_info[2]}{start_info[3]} ({start_info[1]}-{end_info[1]})"

def get_video_metadata(path):
    """
    비디오 및 GIF 메타데이터 추출. 
    단일 파일로 처리될 때 호출됩니다.
    """
    if not os.path.exists(path):
        return None
    
    if path.lower().endswith('.gif'):
        try:
            # GIF 파일은 PIL을 사용하여 정확한 프레임 정보를 읽음
            with Image.open(path) as img:
                duration = 0
                frame_count = 0
                for frame in ImageSequence.Iterator(img):
                    duration += frame.info.get('duration', 100)
                    frame_count += 1
                duration /= 1000.0
                return {
                    'width': img.width,
                    'height': img.height,
                    'fps': (frame_count / duration) if duration > 0 else 10.0,
                    'duration': duration if duration > 0 else 0.1
                }
        except Exception:
            pass

    try:
        cmd = ['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', path]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        if result.returncode == 0:
            data = json.loads(result.stdout)
            v_stream = next((s for s in data.get('streams', []) if s.get('codec_type') == 'video'), None)
            if v_stream:
                fps_eval = v_stream.get('avg_frame_rate', '30/1')
                num, den = map(int, fps_eval.split('/')) if '/' in fps_eval else (float(fps_eval), 1)
                fps = num / den if den != 0 else 30
                return {
                    'width': int(v_stream.get('width', 1280)),
                    'height': int(v_stream.get('height', 720)),
                    'fps': fps,
                    'duration': float(data.get('format', {}).get('duration', 0.1))
                }
    except Exception:
        pass

    try:
        with VideoFileClip(path) as clip:
            return {'width': clip.w, 'height': clip.h, 'fps': clip.fps or 30, 'duration': clip.duration}
    except Exception:
        return None

def extract_thumbnail_fast(path, output_w=160):
    """
    매우 빠른 썸네일 추출.
    """
    if not os.path.exists(path):
        return None

    if path.lower().endswith('.gif'):
        try:
            with Image.open(path) as img:
                img.seek(0)
                # copy()를 사용하여 원본 파일 핸들과 연결을 끊고 독립된 메모리 확보
                thumb = img.convert("RGB").copy()
                thumb.thumbnail((output_w, output_w), RESAMPLING_LANKZOS)
                return thumb
        except:
            pass

    try:
        cmd = ['ffmpeg', '-ss', '0.1', '-i', path, '-vframes', '1', '-an', '-sn', 
               '-vf', f'scale={output_w}:-1', '-f', 'image2pipe', '-vcodec', 'png', '-']
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        out, _ = process.communicate(timeout=5)
        if out:
            return Image.open(BytesIO(out))
    except:
        pass

    try:
        with VideoFileClip(path) as clip:
            frame = clip.get_frame(0)
            img = Image.fromarray(frame.astype('uint8'))
            img.thumbnail((output_w, output_w), RESAMPLING_LANKZOS)
            return img
    except:
        return None

def analyze_media_item(item):
    """단일 항목 분석 워커"""
    path = item.get('path')
    if path == "Image Sequence":
        seq_paths = item.get('sequence_paths', [])
        if seq_paths:
            try:
                # 시퀀스의 경우 첫 번째 이미지를 썸네일로 사용
                with Image.open(seq_paths[0]) as img:
                    thumb = img.convert("RGB").copy()
                    thumb.thumbnail((160, 90), RESAMPLING_LANKZOS)
                    item['thumb_img'] = thumb
                    item['width'] = img.size[0]
                    item['height'] = img.size[1]
                    item['status'] = "대기"
                    # 시퀀스인 경우 전체 파일 개수를 기반으로 종료 시간 계산
                    fps = item.get('fps', 24)
                    item['end'] = len(seq_paths) / fps
                    item['video_fps'] = fps
            except:
                item['status'] = "시퀀스 분석 실패"
        return item

    meta = get_video_metadata(path)
    if meta:
        item.update({'video_fps': meta['fps'], 'width': meta['width'], 'height': meta['height'], 
                     'end': meta['duration'], 'status': "대기"})
        item['thumb_img'] = extract_thumbnail_fast(path)
    else:
        item['status'] = "분석 실패"
    return item

def bulk_analyze_items_parallel(items, progress_callback=None, max_workers=4):
    """
    멀티 스레딩 분석 및 실시간 진행률 업데이트.
    progress_callback: (현재_완료_수, 전체_수)를 인자로 받는 함수
    """
    results = [None] * len(items)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 각 아이템에 대한 future 객체 생성 및 인덱스 매핑
        future_to_idx = {executor.submit(analyze_media_item, item): i for i, item in enumerate(items)}
        
        completed_count = 0
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                results[idx] = future.result()
            except Exception:
                results[idx] = items[idx]
                results[idx]['status'] = "심각한 오류"
            
            completed_count += 1
            if progress_callback:
                progress_callback(completed_count, len(items))
                
    return results

def apply_color_correction_pil(pil_img, settings):
    """PIL 이미지를 사용하여 색보정 필터 적용"""
    if not settings.get('color_correction', False) or pil_img is None:
        return pil_img
    
    # 알파 채널 확인 및 모드 변환
    has_alpha = 'A' in pil_img.mode or pil_img.mode == 'P'
    temp_img = pil_img.convert('RGBA') if has_alpha else pil_img.convert('RGB')
    alpha = temp_img.split()[-1] if 'A' in temp_img.mode else None
    img = temp_img.convert('RGB')
    
    # 노출, 대비, 채도 보정
    if settings.get('exposure', 0) != 0:
        img = ImageEnhance.Brightness(img).enhance(1.0 + (settings['exposure'] / 100.0))
    if settings.get('contrast', 0) != 0:
        img = ImageEnhance.Contrast(img).enhance(1.0 + (settings['contrast'] / 100.0))
    if settings.get('saturation', 1.0) != 1.0:
        img = ImageEnhance.Color(img).enhance(settings['saturation'])
    
    # 색온도 보정
    temp = settings.get('temperature', 0)
    if temp != 0:
        r, g, b = img.split()
        if temp > 0:
            r = r.point(lambda i: min(255, int(i * (1 + temp/300))))
            b = b.point(lambda i: max(0, int(i * (1 - temp/300))))
        else:
            at = abs(temp)
            r = r.point(lambda i: max(0, int(i * (1 - at/300))))
            b = b.point(lambda i: min(255, int(i * (1 + at/300))))
        img = Image.merge('RGB', (r, g, b))
        
    # 틴트 보정
    tint = settings.get('tint', 0)
    if tint != 0:
        r, g, b = img.split()
        if tint > 0:
            g = g.point(lambda i: min(255, int(i * (1 + tint/300))))
        else:
            at = abs(tint)
            r = r.point(lambda i: max(0, int(i * (1 - abs(at)/300))))
            b = b.point(lambda i: min(255, int(i * (1 + abs(at)/300))))
        img = Image.merge('RGB', (r, g, b))
        
    # 감마 보정
    gamma = settings.get('gamma', 1.0)
    if gamma != 1.0:
        img = img.point(lambda i: min(255, int(255 * (i / 255) ** (1 / gamma))))
        
    # 알파 채널 복구
    if alpha:
        img = Image.merge('RGBA', (*img.split(), alpha))
    return img

def get_sequence_clip(paths, fps):
    """
    이미지 파일 리스트를 MoviePy 비디오 클립으로 변환합니다.
    캐싱 문제를 방지하기 위해 VideoClip을 사용하며 현재 경로 리스트를 튜플로 고정합니다.
    """
    if not paths: return None
    
    # 경로 리스트를 튜플로 변환하여 불변 상태로 캡처 (클로저 오염 방지)
    current_paths = tuple([os.path.abspath(p) for p in paths])
    # 정렬 (natural_sort 사용)
    current_paths = tuple(sorted(current_paths, key=lambda x: natural_sort_key(os.path.basename(x))))
    
    current_fps = float(fps)
    num_frames = len(current_paths)
    duration = num_frames / current_fps
    
    try:
        with Image.open(current_paths[0]) as first_img:
            current_size = first_img.size
            has_alpha = (first_img.mode in ('RGBA', 'LA') or 
                         (first_img.mode == 'P' and 'transparency' in first_img.info))
    except Exception:
        return None

    def make_rgb_frame(t):
        # 부동 소수점 오차 보정을 위해 아주 작은 값을 더한 뒤 인덱스 계산
        idx = int(t * current_fps + 0.0001)
        idx = max(0, min(num_frames - 1, idx))
        try:
            # Pillow의 내부 캐시를 우회하기 위해 파일을 명시적으로 다시 엶
            with Image.open(current_paths[idx]) as img:
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                return np.array(img)
        except Exception:
            return np.zeros((current_size[1], current_size[0], 3), dtype=np.uint8)

    # VideoClip 생성 (ImageSequenceClip의 자동 캐싱을 피함)
    rgb_clip = VideoClip(make_rgb_frame, duration=duration)
    
    if has_alpha:
        def make_mask_frame(t):
            idx = int(t * current_fps + 0.0001)
            idx = max(0, min(num_frames - 1, idx))
            try:
                with Image.open(current_paths[idx]) as img:
                    if img.mode != 'RGBA':
                        img = img.convert('RGBA')
                    alpha_channel = img.getchannel('A')
                    return np.array(alpha_channel, dtype=np.float32) / 255.0
            except Exception:
                return np.ones((current_size[1], current_size[0]), dtype=np.float32)
        
        mask_clip = VideoClip(make_mask_frame, is_mask=True, duration=duration)
        
        if hasattr(rgb_clip, 'set_mask'):
            rgb_clip = rgb_clip.set_mask(mask_clip)
        elif hasattr(rgb_clip, 'with_mask'):
            rgb_clip = rgb_clip.with_mask(mask_clip)
        else:
            rgb_clip.mask = mask_clip
            
    return rgb_clip

def perform_write_webp(clip, filename, fps, logger, loop, transparent, app_instance):
    """Pillow를 사용하여 WebP 애니메이션 저장"""
    frames = []
    total_frames = int(clip.duration * fps)
    for i in range(total_frames):
        if app_instance.cancel_requested: raise RuntimeError("CANCEL_REQUESTED")
        while app_instance.batch_paused: time.sleep(0.5)
        t = i / fps
        frame = clip.get_frame(t)
        img = Image.fromarray(frame.astype('uint8'))
        if transparent and clip.mask is not None:
            mask_frame = clip.mask.get_frame(t)
            if len(mask_frame.shape) == 3: mask_frame = mask_frame[:, :, 0]
            mask_img = Image.fromarray((mask_frame * 255).astype('uint8'), mode='L')
            img.putalpha(mask_img)
        frames.append(img)
        if logger and i % 5 == 0:
            logger.bars_update('main', index=i + 1, total=total_frames)
    if frames:
        if logger: logger.bars_update('main', index=total_frames, total=total_frames)
        frames[0].save(filename, save_all=True, append_images=frames[1:], 
                       duration=int(1000/fps), loop=loop, quality=85, method=0, lossless=False)

def perform_write_gif(clip, filename, fps, logger, loop, transparent, app_instance):
    """Pillow를 사용하여 GIF 저장"""
    frames = []
    total_frames = int(clip.duration * fps)
    for i in range(total_frames):
        if app_instance.cancel_requested: raise RuntimeError("CANCEL_REQUESTED")
        while app_instance.batch_paused: time.sleep(0.5)
        t = i / fps
        frame = clip.get_frame(t)
        img = Image.fromarray(frame.astype('uint8'))
        if transparent and clip.mask is not None:
            mask_frame = clip.mask.get_frame(t)
            if len(mask_frame.shape) == 3: mask_frame = mask_frame[:, :, 0]
            mask_img = Image.fromarray((mask_frame * 255).astype('uint8'), mode='L')
            img.putalpha(mask_img)
        frames.append(img.convert("RGBA") if transparent else img.convert("RGB"))
        if logger and i % 5 == 0:
            logger.bars_update('main', index=i + 1, total=total_frames)
    if frames:
        if logger: logger.bars_update('main', index=total_frames, total=total_frames)
        save_args = {"save_all": True, "append_images": frames[1:], "duration": int(1000 / fps), "loop": loop, "optimize": True}
        if transparent: frames[0].save(filename, **save_args, transparency=0, disposal=2)
        else: frames[0].save(filename, **save_args)

def perform_write_single_image(clip, filename, timestamp, settings, app_instance):
    """한 프레임을 단일 이미지(JPG, PNG, WebP, GIF)로 저장"""
    try:
        frame = clip.get_frame(timestamp)
        img = Image.fromarray(frame.astype('uint8'))
        
        # 색보정 적용
        if settings.get('color_correction'):
            img = apply_color_correction_pil(img, settings)
            
        # 투명도 및 포맷 처리
        ext = os.path.splitext(filename)[1].lower()
        if ext in ['.jpg', '.jpeg']:
            if img.mode == 'RGBA':
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            else:
                img = img.convert("RGB")
            img.save(filename, "JPEG", quality=95)
        elif ext == '.png':
            img.save(filename, "PNG")
        elif ext == '.webp':
            img.save(filename, "WEBP", lossless=True)
        elif ext == '.gif':
            img.save(filename, "GIF")
        return True
    except Exception as e:
        print(f"이미지 저장 실패: {e}")
        return False