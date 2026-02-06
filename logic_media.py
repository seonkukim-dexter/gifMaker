import os
import threading
import numpy as np
from tkinter import filedialog, messagebox
from PIL import Image
import video_engine
from utils import natural_sort_key
from constants import FILETYPES_SINGLE, FILETYPES_SEQUENCE, VIDEO_EXTS, IMAGE_EXTS

class MediaMixin:
    """파일 및 폴더 로드, 미디어 분석 관련 로직"""

    def select_file(self):
        # [수정] 단일 파일 불러오기에도 최근 경로 적용 (통일성 유지)
        initial_dir = self.last_save_dir if self.last_save_dir and os.path.exists(self.last_save_dir) else None
        path = filedialog.askopenfilename(filetypes=FILETYPES_SINGLE, initialdir=initial_dir)
        if path:
            self.last_save_dir = os.path.dirname(path) # 경로 업데이트
            self.export_format_var.set("GIF")
            self._update_export_ui(self.export_format_var.get())
            self.load_new_video(path)

    def select_folder(self):
        # [기존] 폴더 불러오기 (이미 적용됨)
        initial_dir = self.last_save_dir if self.last_save_dir and os.path.exists(self.last_save_dir) else None
        folder = filedialog.askdirectory(initialdir=initial_dir)
        
        if folder:
            self.last_save_dir = os.path.dirname(folder)
            self._process_folder_path(folder)

    def select_sequence_files(self):
        # [수정] 시퀀스 파일 불러오기에도 최근 경로 적용
        initial_dir = self.last_save_dir if self.last_save_dir and os.path.exists(self.last_save_dir) else None
        paths = filedialog.askopenfilenames(filetypes=FILETYPES_SEQUENCE, initialdir=initial_dir)
        
        if not paths: return
        paths = list(paths)
        
        # [수정] 선택 성공 시 최근 경로 업데이트
        if paths:
            self.last_save_dir = os.path.dirname(paths[0])

        if len(paths) == 1:
            f_path = paths[0]; folder = os.path.dirname(f_path)
            prefix, num, ext, sep = video_engine.get_sequence_info(os.path.basename(f_path))
            if num:
                try:
                    siblings = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(ext.lower())]
                    valid_seq = []
                    for s in siblings:
                        s_prefix, s_num, s_ext, s_sep = video_engine.get_sequence_info(os.path.basename(s))
                        if s_prefix == prefix and s_ext.lower() == ext.lower() and s_sep == sep and s_num is not None:
                            valid_seq.append(s)
                    if len(valid_seq) > 1: paths = valid_seq
                except: pass
        paths.sort(key=lambda x: natural_sort_key(os.path.basename(x)))
        self.load_new_sequence(paths)
    
    def load_new_video(self, path, edit_job=None):
        if self.is_loading: return
        self._set_loading_ui_state(True)
        self.frame_cache = {} 
        self.video_path = path
        self.progress_bar.set(0)
        self.progress_bar.grid(row=8, column=0, pady=10, padx=50, sticky="ew")
        self.progress_label.grid(row=9, column=0, pady=5)
        self.progress_label.configure(text="영상 데이터 분석 중...")
        self.proxy_progress_bar.pack_forget(); self.is_proxy_ready = False; self.is_proxy_generating = False; self.proxy_clip = None
        self.current_load_id += 1; threading.Thread(target=self._load_video_task, args=(path, edit_job, self.current_load_id), daemon=True).start()

    def _load_video_task(self, path, edit_job, load_id):
        try:
            from moviepy import VideoFileClip 
            
            if load_id != self.current_load_id: 
                self.after(0, lambda: self._set_loading_ui_state(False))
                return
            
            new_clip = VideoFileClip(path, has_mask=path.lower().endswith('.gif'))
            self.source_clip = new_clip
            self.duration, self.fps, thumbs, total_thumbs = new_clip.duration, new_clip.fps or 24, [], 12
            self.proxy_enabled_var.set(False); self.is_proxy_ready = False
            
            for i in range(total_thumbs):
                if load_id != self.current_load_id: return
                ft = max(0.01, min(self.duration - 0.01, (self.duration / total_thumbs) * i))
                with self.clip_access_lock: frame = new_clip.get_frame(ft)
                thumbs.append(Image.fromarray(frame.astype('uint8')))
                self.after(0, lambda p=(i + 1)/total_thumbs, c=i+1: (self.progress_bar.set(p), self.progress_label.configure(text=f"데이터 분석 중... ({c}/{total_thumbs})")))
            
            if load_id == self.current_load_id: 
                self.after(0, lambda: (setattr(self, 'clip', new_clip), self._init_video_ui(thumbs, edit_job)))
        except Exception as e:
            if load_id == self.current_load_id:
                self.after(0, lambda m=str(e): (self._set_loading_ui_state(False), messagebox.showerror("오류", f"파일 로드 실패: {m}")))
        finally:
            if load_id == self.current_load_id:
                self.after(0, lambda: (self.progress_bar.grid_remove(), self.progress_label.grid_remove()))

    def load_new_sequence(self, paths, edit_job=None):
        if not paths: return
        self._set_loading_ui_state(True)
        self.frame_cache = {}
        self.is_proxy_ready = False; self.is_proxy_active = False; self.proxy_clip = None
        self.video_path, self.sequence_paths = "Image Sequence", paths
        self.export_format_var.set("WebM"); self._update_export_ui(self.export_format_var.get())
        self.progress_bar.set(0); self.progress_bar.grid(row=8, column=0, pady=10, padx=50, sticky="ew")
        self.progress_label.grid(row=9, column=0, pady=5); self.progress_label.configure(text="시퀀스 분석 및 썸네일 생성 중...")
        self.current_load_id += 1; threading.Thread(target=self._load_sequence_task, args=(paths, edit_job, self.current_load_id), daemon=True).start()

    def _load_sequence_task(self, paths, edit_job, load_id):
        self.frame_cache = {}
        try:
            target_fps = int(self.fps_input_var.get() or 24)
            self.clip = video_engine.get_sequence_clip(paths, target_fps)
            if self.clip is None: 
                self.after(0, lambda: self._set_loading_ui_state(False)); return
            if load_id != self.current_load_id: 
                self.after(0, lambda: self._set_loading_ui_state(False)); return
            self.duration, self.fps, thumbs, total_thumbs = self.clip.duration, target_fps, [], 12
            self.source_clip = self.clip; self.is_proxy_ready = True 
            total_frames = len(paths); sample_indices = np.linspace(0, total_frames - 1, total_thumbs, dtype=int)
            for idx, f_idx in enumerate(sample_indices):
                if load_id != self.current_load_id: return
                t_pos = f_idx / target_fps
                frame = self.clip.get_frame(min(self.duration - 0.001, t_pos))
                thumbs.append(Image.fromarray(frame.astype('uint8')))
                p_val = 0.5 + ((idx + 1) / total_thumbs * 0.5)
                self.after(0, lambda v=p_val: self.progress_bar.set(v))
            if load_id == self.current_load_id: 
                self.after(0, lambda: self._init_video_ui(thumbs, edit_job))
        except Exception as e:
            if load_id == self.current_load_id:
                self.after(0, lambda m=str(e): (self._set_loading_ui_state(False), messagebox.showerror("오류", f"시퀀스 로드 실패: {m}")))
        finally:
            if load_id == self.current_load_id:
                self.after(0, lambda: (self.progress_bar.grid_remove(), self.progress_label.grid_remove()))

    def _process_folder_path(self, folder):
        self.open_queue_window()
        if self.queue_window:
            self.queue_window.append_log(f"폴더 스캔 시작: {folder}")

        self._set_loading_ui_state(True)
        self.progress_bar.set(0); self.progress_bar.grid(row=8, column=0, pady=10, padx=50, sticky="ew")
        self.progress_label.grid(row=9, column=0, pady=5); self.progress_label.configure(text="폴더 내 미디어 파일 분석 중...")
        threading.Thread(target=self._scan_folder_task, args=(folder,), daemon=True).start()

    def _scan_folder_task(self, folder):
        is_thumb_mode = (self.export_format_var.get() == "Thumbnail")
        ui_width = int(self.combo_width.get())
        ui_color_settings = {
            "color_correction": self.color_correction_var.get(),
            "exposure": self.exposure_var.get(), "gamma": self.gamma_var.get(),
            "contrast": self.contrast_var.get(), "saturation": self.saturation_var.get(),
            "tint": self.tint_var.get(), "temperature": self.temperature_var.get()
        }

        all_files = []
        for r, d, files in os.walk(folder):
            for f in files: all_files.append(os.path.join(r, f))

        new_jobs, sequences = [], {}

        for f_path in all_files:
            l_f = f_path.lower()
            if l_f.endswith(IMAGE_EXTS):
                prefix, num, ext, sep = video_engine.get_sequence_info(os.path.basename(f_path))
                if num:
                    key = (os.path.dirname(f_path), prefix, ext.lower(), sep)
                    if key not in sequences: sequences[key] = []
                    sequences[key].append(f_path)
        
        used_in_sequence = set()
        for key, paths in sequences.items():
            if len(paths) > 1:
                used_in_sequence.update(paths)
                display_name = video_engine.get_sequence_display_name(paths)
                paths.sort(key=lambda x: natural_sort_key(os.path.basename(x)))
                job = {"path": "Image Sequence", "filename": display_name, "status": "대기", "sequence_paths": paths, "start": 0, "end": -1, "fps": 24, "video_fps": 24, "width": ui_width if is_thumb_mode else 1280, "loop": 0, "crop": [0,0,1,1], "crop_enabled": False, "thumb_img": None, "transparent": True, "export_format": "Thumbnail" if is_thumb_mode else "WebM", "seq_format": self.seq_format_var.get(), "bitrate": "2", "is_sequence": True, "color_settings": ui_color_settings if is_thumb_mode else {}}
                new_jobs.append(job)

        for v in all_files:
            l_v = v.lower()
            if l_v.endswith(VIDEO_EXTS) and v not in used_in_sequence:
                job = {"path": v, "filename": os.path.basename(v), "status": "대기", "start": 0, "end": -1, "fps": 24, "video_fps": 24, "width": ui_width if is_thumb_mode else 1280, "loop": 0, "crop": [0,0,1,1], "crop_enabled": False, "thumb_img": None, "transparent": True, "export_format": "Thumbnail" if is_thumb_mode else "GIF", "seq_format": self.seq_format_var.get(), "bitrate": "2", "color_settings": ui_color_settings if is_thumb_mode else {}}
                new_jobs.append(job)

        if not new_jobs:
            self.after(0, lambda: (self._set_loading_ui_state(False), self.progress_bar.grid_remove(), self.progress_label.grid_remove(), messagebox.showinfo("알림", "지원되는 파일이 없습니다.")))
            return
        self._process_queue_items_background(new_jobs)