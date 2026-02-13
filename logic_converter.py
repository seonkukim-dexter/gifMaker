import os
import sys
import threading
import json
import subprocess
import tempfile
import numpy as np
import re
import time
from tkinter import filedialog, messagebox
from PIL import Image
import video_engine
from utils import CTKLogger, get_unique_path, RESAMPLING_LANKZOS
from constants import FILETYPES_JSON
from ui_widgets import QueueWindow

class ConverterMixin:
    """변환 실행, 대기열 관리, 배치 처리 로직"""

    # -------------------------------------------------------------------------
    # 즉시 변환 (Single Conversion)
    # -------------------------------------------------------------------------
    def start_conversion_thread(self):
        if not self.clip: return
        fmt = self.export_format_var.get()

        if self.video_path == "Image Sequence" and self.sequence_paths:
            prefix, _, _, _ = video_engine.get_sequence_info(os.path.basename(self.sequence_paths[0]))
            orig_base_name = prefix if prefix else "sequence"
        elif self.video_path and self.video_path != "Image Sequence":
            orig_base_name = os.path.splitext(os.path.basename(self.video_path))[0]
        else:
            orig_base_name = "output"

        ext_map = {"GIF": ".gif", "MP4": ".mp4", "WebM": ".webm", "WebP": ".webp", "Thumbnail": f".{self.seq_format_var.get().lower()}"}
        
        if fmt == "Sequence":
            save_path = filedialog.askdirectory(initialdir=self.last_save_dir)
        else:
            ext = ext_map.get(fmt, ".gif")
            save_path = filedialog.asksaveasfilename(
                defaultextension=ext, 
                initialdir=self.last_save_dir,
                initialfile=orig_base_name + ext
            )
            
        if save_path:
            self.last_save_dir = os.path.dirname(save_path)
            self.btn_convert_now.pack_forget(); self.btn_cancel_immediate.pack(side="left", fill="x", expand=True)
            
            self.progress_bar.set(0)
            self.progress_bar.grid(row=8, column=0, pady=10, padx=50, sticky="ew")
            self.progress_label.grid(row=9, column=0, pady=5)
            self.progress_label.configure(text="변환 준비 중...")
            
            threading.Thread(target=self._convert_task, args=(save_path,), daemon=True).start()

    def _direct_ffmpeg_export(self, job, out_path, logger, total_duration, color_settings=None):
        """
        MoviePy를 우회하여 FFMPEG를 직접 호출합니다. (VFR 최적화 및 속도 대폭 향상)
        사용자의 색보정(PIL 기반)을 FFMPEG 비디오 필터로 번역하여 함께 적용합니다.
        """
        # [수정] imageio_ffmpeg를 통해 환경에 독립적인 확실한 FFMPEG 절대 경로 확보
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            # imageio_ffmpeg가 없는 예외적인 경우에만 시스템 PATH에 의존
            ffmpeg_exe = "ffmpeg"

        start = job.get('start', 0)
        end = job.get('end', -1)
        duration = (total_duration - start) if end == -1 else (end - start)
        
        cmd = [ffmpeg_exe, '-y', '-ss', str(start)]
        cmd.extend(['-i', job['path']])
        cmd.extend(['-t', str(duration)])
        
        vf = []
        # 1. 크롭 필터 적용
        if job.get('crop_enabled'):
            x1, y1, x2, y2 = job['crop']
            rx1, rx2 = min(x1, x2), max(x1, x2)
            ry1, ry2 = min(y1, y2), max(y1, y2)
            cx, cy = f"{rx1}*iw", f"{ry1}*ih"
            cw, ch = f"{rx2 - rx1}*iw", f"{ry2 - ry1}*ih"
            vf.append(f"crop={cw}:{ch}:{cx}:{cy}")
            
        # 2. 리사이즈 필터 적용
        target_w = job.get('width', 1280)
        vf.append(f"scale={target_w}:-2")
        vf.append("format=yuv420p")
        
        # 3. 색보정 필터 적용 (PIL 로직을 FFMPEG 네이티브 필터로 변환)
        if color_settings and color_settings.get('color_correction'):
            # 노출, 대비, 감마, 채도 -> eq 필터 사용
            exp = color_settings.get('exposure', 0) / 100.0  # PIL: 1.0 + val, FFMPEG: -1.0 ~ 1.0 (default 0)
            cont = 1.0 + (color_settings.get('contrast', 0) / 100.0) # FFMPEG: default 1.0
            gam = color_settings.get('gamma', 1.0)
            sat = color_settings.get('saturation', 1.0)
            vf.append(f"eq=brightness={exp}:contrast={cont}:gamma={gam}:saturation={sat}")

            # 틴트, 색온도 -> colorbalance 필터 사용 (Midtones 조정)
            temp = color_settings.get('temperature', 0.0)
            tint = color_settings.get('tint', 0.0)
            rm, gm, bm = 0.0, 0.0, 0.0
            
            if temp > 0:
                rm += temp / 300.0
                bm -= temp / 300.0
            elif temp < 0:
                rm -= abs(temp) / 300.0
                bm += abs(temp) / 300.0
                
            if tint > 0:
                gm += tint / 300.0
            elif tint < 0:
                rm -= abs(tint) / 300.0
                bm -= abs(tint) / 300.0
                
            # FFMPEG colorbalance limit is -1.0 to 1.0
            rm = max(-1.0, min(1.0, rm))
            gm = max(-1.0, min(1.0, gm))
            bm = max(-1.0, min(1.0, bm))
            
            if rm != 0.0 or gm != 0.0 or bm != 0.0:
                vf.append(f"colorbalance=rm={rm}:gm={gm}:bm={bm}")
        
        cmd.extend(['-vf', ",".join(vf)])
        
        bitrate = job.get('bitrate', '2')
        cmd.extend(['-c:v', 'libx264', '-b:v', f"{bitrate}M", '-preset', 'medium', '-threads', '4'])
        cmd.extend(['-c:a', 'aac', '-b:a', '128k'])
        
        # [핵심] VFR 타임스탬프 유동적 유지 (프레임 강제 재샘플링 방지)
        cmd.extend(['-vsync', '0']) 
        
        cmd.append(out_path)

        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True, startupinfo=startupinfo)
        
        time_regex = re.compile(r"time=\s*(\d+):(\d+):(\d+\.\d+)")
        
        for line in proc.stdout:
            if self.cancel_requested:
                proc.kill()
                raise RuntimeError("CANCEL_REQUESTED")
            while self.batch_paused:
                time.sleep(0.5)
                if self.cancel_requested:
                    proc.kill()
                    raise RuntimeError("CANCEL_REQUESTED")
                
            match = time_regex.search(line)
            if match and logger:
                h, m, s = match.groups()
                t_sec = int(h) * 3600 + int(m) * 60 + float(s)
                logger.bars_update('main', index=int(t_sec), total=int(duration))
                
        proc.wait()
        if proc.returncode != 0 and not self.cancel_requested:
            raise RuntimeError(f"FFMPEG Direct Error: {proc.returncode}")
            
        if logger:
            logger.bars_update('main', index=int(duration), total=int(duration))

    def _convert_task(self, save_path):
        try:
            from moviepy import VideoFileClip 
            
            logger = CTKLogger(self, prefix="변환 중...", job_index=None)
            color_settings = {"color_correction": self.color_correction_var.get(), "exposure": self.exposure_var.get(), "gamma": self.gamma_var.get(), "contrast": self.contrast_var.get(), "saturation": self.saturation_var.get(), "tint": self.tint_var.get(), "temperature": self.temperature_var.get()}

            fmt = self.export_format_var.get()
            target_w = int(self.combo_width.get())

            # --- [핵심 수정] MP4 다이렉트 변환 분기 (VFR 끊김 해결) ---
            # 색보정이 켜져 있더라도 번역된 필터를 통해 무조건 다이렉트 변환을 사용하도록 변경!
            if fmt == "MP4" and self.video_path != "Image Sequence":
                job_info = {
                    'start': self.timeline.in_point * self.duration,
                    'end': self.timeline.out_point * self.duration,
                    'crop_enabled': self.crop_enabled_var.get(),
                    'crop': self.crop_coords,
                    'width': target_w,
                    'bitrate': self.webm_bitrate_var.get(),
                    'path': self.video_path
                }
                self._direct_ffmpeg_export(job_info, save_path, logger, self.duration, color_settings)
                if not self.cancel_requested: self.after(0, lambda: messagebox.showinfo("완료", "변환 및 저장이 완료되었습니다."))
                else: self.after(0, lambda: messagebox.showwarning("취소", "변환이 중단되었습니다."))
                return # MoviePy 파이프라인 우회 완료
            # --------------------------------------------------------

            if self.video_path == "Image Sequence":
                main_clip = video_engine.get_sequence_clip(self.sequence_paths, int(self.fps_input_var.get() or 24))
            else:
                has_alpha = self.video_path.lower().endswith(('.gif', '.png', '.webp', '.webm'))
                main_clip = VideoFileClip(self.video_path, has_mask=has_alpha)

            with main_clip:
                if fmt == "Thumbnail":
                    t_pos = self.timeline.play_head * self.duration
                    sub = main_clip.resized(width=target_w) if hasattr(main_clip, 'resized') else main_clip.resize(width=target_w)
                    video_engine.perform_write_single_image(sub, save_path, t_pos, color_settings, self)
                else:
                    st, et = self.timeline.in_point * self.duration, self.timeline.out_point * self.duration
                    sub = main_clip.subclipped(st, et) if hasattr(main_clip, 'subclipped') else main_clip.subclip(st, et)
                    if self.crop_enabled_var.get():
                        vw, vh = sub.size; x1, y1, x2, y2 = self.crop_coords; rx1, rx2, ry1, ry2 = min(x1, x2), max(x1, x2), min(y1, y2), max(y1, y2)
                        sub = sub.cropped(x1=rx1*vw, y1=ry1*vh, x2=rx2*vw, y2=ry2*vh) if hasattr(sub, 'cropped') else sub.crop(x1=rx1*vw, y1=ry1*vh, x2=rx2*vw, y2=ry2*vh)
                    sub = sub.resized(width=target_w) if hasattr(sub, 'resized') else sub.resize(width=target_w)

                    if color_settings.get('color_correction', False):
                        def color_filter(image):
                            pil_img = Image.fromarray(image.astype('uint8'))
                            return np.array(video_engine.apply_color_correction_pil(pil_img, color_settings).convert('RGB'))
                        sub = sub.image_transform(color_filter)

                    final_fps = int(self.fps_input_var.get() or 30)
                    actual_transparent = self.keep_transparency_var.get() and sub.mask is not None
                    
                    if fmt == "Sequence":
                        img_format = os.path.join(save_path, f"{os.path.basename(save_path)}.%04d.{self.seq_format_var.get().lower()}")
                        sub.write_images_sequence(img_format, fps=final_fps, logger=logger)
                    elif fmt == "WebM":
                        temp_audio_path = os.path.join(tempfile.gettempdir(), f"temp_audio_single_{os.getpid()}.ogg")
                        ffmpeg_params = ['-b:v', f"{self.webm_bitrate_var.get()}M", '-auto-alt-ref', '0', '-metadata:s:v:0', 'alpha_mode=1']
                        ffmpeg_params.extend(['-pix_fmt', 'yuva420p'] if actual_transparent else ['-pix_fmt', 'yuv420p'])
                        sub.write_videofile(save_path, fps=final_fps, codec='libvpx-vp9', logger=logger, ffmpeg_params=ffmpeg_params, temp_audiofile=temp_audio_path, remove_temp=True)
                    elif fmt == "WebP": 
                        video_engine.perform_write_webp(sub, save_path, final_fps, logger, int(self.loop_count_var.get() or 0), actual_transparent, self)
                    else: 
                        video_engine.perform_write_gif(sub, save_path, final_fps, logger, int(self.loop_count_var.get() or 0), actual_transparent, self)

            if not self.cancel_requested: self.after(0, lambda: messagebox.showinfo("완료", "변환 및 저장이 완료되었습니다."))
            else: self.after(0, lambda: messagebox.showwarning("취소", "변환이 중단되었습니다."))
        except RuntimeError as e:
            if str(e) == "CANCEL_REQUESTED": self.after(0, lambda: messagebox.showwarning("취소", "변환이 중단되었습니다."))
            else: self.after(0, lambda msg=str(e): messagebox.showerror("오류", f"변환 실패: {msg}"))
        except Exception as e: self.after(0, lambda msg=str(e): messagebox.showerror("오류", f"변환 실패: {msg}"))
        finally: self.after(0, self._finalize_conversion_ui)

    def _finalize_conversion_ui(self):
        self.progress_bar.grid_remove(); self.progress_label.grid_remove(); self.btn_cancel_immediate.pack_forget()
        self.btn_convert_now.pack(side="left", fill="x", expand=True)
    
    def _update_ui_from_logger(self, job_index, percentage, prefix, time_info):
        try:
            if self.progress_bar and self.progress_bar.winfo_exists():
                self.progress_bar.set(percentage)
            if self.progress_label and self.progress_label.winfo_exists():
                self.progress_label.configure(text=f"{prefix} {int(percentage*100)}%{time_info}")
            
            if job_index is not None and self.queue_window and self.queue_window.winfo_exists():
                if job_index in self.job_widgets:
                    widgets = self.job_widgets[job_index]
                    p_bar = widgets.get('progress_bar')
                    if p_bar and p_bar.winfo_exists():
                        p_bar.set(percentage)
        except: pass

    # -------------------------------------------------------------------------
    # 대기열 관리 (Queue Management)
    # -------------------------------------------------------------------------
    def add_to_queue(self):
        if not self.clip: return
        
        cs = {
        "color_correction": self.color_correction_var.get(),
        "exposure": self.exposure_var.get(), "gamma": self.gamma_var.get(),
        "contrast": self.contrast_var.get(), "saturation": self.saturation_var.get(),
        "tint": self.tint_var.get(), "temperature": self.temperature_var.get()
        }

        current_settings = {
        "fps": self.fps, "width": int(self.combo_width.get()), "export_format": self.export_format_var.get(),
        "transparent": self.keep_transparency_var.get(), "loop": int(self.loop_count_var.get() or 0),
        "crop": list(self.crop_coords), "crop_enabled": self.crop_enabled_var.get(),
        "bitrate": self.webm_bitrate_var.get(), "color_settings": cs
        }

        if self.editing_index >= 0:
            idx = self.editing_index
            if 0 <= idx < len(self.queue):
                job = self.queue[idx]
                job.update(current_settings)
                try:
                    with self.clip_access_lock: frame = self.clip.get_frame(job['start'])
                    new_thumb = Image.fromarray(frame.astype('uint8'))
                    new_thumb = video_engine.apply_color_correction_pil(new_thumb, cs)
                    new_thumb.thumbnail((160, 90), RESAMPLING_LANKZOS)
                    job['thumb_img'] = new_thumb
                except: thumb = Image.fromarray(frame.astype('uint8')); thumb.thumbnail((160, 90), RESAMPLING_LANKZOS)            
                job['status'] = "대기"                
            self.editing_index = -1; self.btn_add_queue.configure(text="대기열에 추가", fg_color="#764ba2"); self.btn_cancel_edit.pack_forget(); self._update_ui_state("normal")
        else:
            st = self.timeline.play_head * self.duration if self.export_format_var.get() == "Thumbnail" else self.timeline.in_point * self.duration
            et = self.timeline.out_point * self.duration
            try: 
                with self.clip_access_lock: frame = self.clip.get_frame(st)
                thumb = Image.fromarray(frame.astype('uint8'))
                thumb = video_engine.apply_color_correction_pil(thumb, cs)
                thumb.thumbnail((160, 90), RESAMPLING_LANKZOS)
            except: thumb = Image.fromarray(frame.astype('uint8')); thumb.thumbnail((160, 90), RESAMPLING_LANKZOS)

            job = {
                "thumb_img": thumb, "path": self.video_path,
                "filename": os.path.basename(self.video_path) if self.video_path != "Image Sequence" else video_engine.get_sequence_display_name(self.sequence_paths),
                "start": st, "end": et, "status": "대기", 
                "sequence_paths": getattr(self, 'sequence_paths', None), "is_sequence": (self.video_path == "Image Sequence")
            }
            job.update(current_settings)
            self.queue.append(job)

        if self.queue_window and self.queue_window.winfo_exists(): 
            self.queue_window.update_list()
        else: self.open_queue_window()

    def cancel_edit(self):
        if self.editing_index >= 0 and self.editing_index < len(self.queue):
            job = self.queue[self.editing_index]
            self.fps = int(job.get('fps', 30))
            self.fps_slider.set(self.fps); self.fps_input_var.set(str(self.fps))
            self.combo_width.set(str(job.get('width', 1280)))
            st = job.get('start', 0); et = job.get('end', self.duration)
            self.timeline.update_points(st, et if et != -1 else self.duration, self.duration, play_head=st, fps=self.fps)
            self.crop_coords = list(job.get('crop', [0,0,1,1])); self.crop_enabled_var.set(job.get('crop_enabled', False))
            self.loop_count_var.set(str(job.get('loop', 0))); self.keep_transparency_var.set(job.get('transparent', True))
            fmt = job.get('export_format', "GIF"); self.export_format_var.set(fmt); self._update_export_ui(fmt)
            cs = job.get('color_settings', {})
            self.exposure_var.set(cs.get('exposure', 0.0)); self.gamma_var.set(cs.get('gamma', 1.0))
            self.contrast_var.set(cs.get('contrast', 0.0)); self.saturation_var.set(cs.get('saturation', 1.0))
            self.tint_var.set(cs.get('tint', 0.0)); self.temperature_var.set(cs.get('temperature', 0.0))
            self.color_correction_var.set(cs.get('color_correction', False)); self.toggle_color_panel()
            self.update_preview_frame(st)
        
        self.editing_index = -1; self.btn_add_queue.configure(text="대기열에 추가", fg_color="#764ba2")
        self.btn_cancel_edit.pack_forget(); self._update_ui_state("normal")
        if self.queue_window and self.queue_window.winfo_exists(): self.queue_window.update_list()

    def open_queue_window(self):
        if not self.queue_window or not self.queue_window.winfo_exists(): self.queue_window = QueueWindow(self)
        self.queue_window.deiconify(); self.queue_window.attributes("-topmost", True); self.queue_window.lift(); self.queue_window.focus_force()
        self.after(100, lambda: self.queue_window.attributes("-topmost", False) if self.queue_window and self.queue_window.winfo_exists() else None)

    def clear_queue(self): 
        if messagebox.askyesno("확인", "대기열을 비우시겠습니까?"): 
            self.queue, self.editing_index = [], -1; self.btn_add_queue.configure(text="대기열에 추가", fg_color="#764ba2")
            self.btn_cancel_edit.pack_forget(); self._update_ui_state("normal")
            if self.queue_window and self.queue_window.winfo_exists(): 
                self.queue_window.update_list()
                self.queue_window.append_log("대기열 전체 삭제됨")

    def remove_from_queue(self, idx): 
        if idx < len(self.queue):
            self.queue.pop(idx)
            if self.editing_index == idx: self.cancel_edit()
            elif self.editing_index > idx: self.editing_index -= 1
            if self.queue_window: self.queue_window.update_list()

    def load_job_for_edit(self, index):
        if self.is_loading: return
        if index >= len(self.queue): return
        job = self.queue[index]
        if job.get('status') == "파일 없음": 
            self.after(0, lambda: messagebox.showwarning("주의", "원본 파일이 없습니다.")); return
        self.deiconify(); self.lift(); self.focus_force()
        self.editing_index, self.current_load_id, self.fps = index, self.current_load_id + 1, job.get('fps', 24)
        self._update_ui_state("edit"); self.fps_input_var.set(str(int(self.fps))); self.fps_slider.set(int(self.fps)); self.update()
        if job.get('is_sequence') and job.get('sequence_paths'): 
            self.sequence_paths = job['sequence_paths']; self.load_new_sequence(self.sequence_paths, edit_job=job)
        else: self.load_new_video(job['path'], edit_job=job)
        self.btn_add_queue.configure(text="항목 수정 완료", fg_color="#e67e22")
        if self.queue_window and self.queue_window.winfo_exists(): self.queue_window.update_list()

    # -------------------------------------------------------------------------
    # 일괄 변환 (Batch Conversion)
    # -------------------------------------------------------------------------
    def start_batch_conversion(self, convert_all=False):
        selected = [idx for idx, var in self.queue_window.check_vars.items() if var.get()]
        if not selected: return messagebox.showwarning("알림", "항목을 선택하세요.")
        save_dir = filedialog.askdirectory(initialdir=self.last_save_dir)
        if save_dir:
            self.last_save_dir = save_dir
            self.is_batch_converting = True
            if self.queue_window and self.queue_window.winfo_exists():
                self.queue_window.update_list()
            threading.Thread(target=self._batch_task, args=(save_dir, selected), daemon=True).start()
    
    def bulk_update_selected_items(self, indices, new_settings):
        if not indices: return
        for idx in indices:
            if 0 <= idx < len(self.queue):
                job = self.queue[idx]
                job.update(new_settings)
                job['status'] = "대기"

        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.update_list()

    def _batch_task(self, save_dir, selected_indices):
        from moviepy import VideoFileClip 
        
        total, success_count = len(selected_indices), 0
        self.cancel_requested = False 
        
        self.after(0, lambda: self.queue_window.append_log(f"=== 일괄 변환 프로세스 시작 (총 {total}개 항목) ==="))
        self.after(0, lambda: self.queue_window.append_log(f"저장 경로: {save_dir}"))

        try:
            for i, q_idx in enumerate(selected_indices):
                if self.cancel_requested: break
                job = self.queue[q_idx]
                fname = job['filename']
                
                try:
                    job['status'] = "진행중"; self.after(0, lambda: self.queue_window.update_list() if self.queue_window else None)
                    self.after(0, lambda n=fname, c=i+1, t=total: self.queue_window.append_log(f"[{c}/{t}] 변환 시작: {n}"))
                    
                    base_name, fmt = os.path.splitext(job['filename'])[0], job.get('export_format', "GIF")
                    
                    if fmt == "Thumbnail":
                        ext = f".{job.get('seq_format', 'PNG').lower()}"
                        out_path = get_unique_path(os.path.join(save_dir, f"{base_name}_thumb{ext}"))
                    elif fmt == "Sequence":
                        out_path = get_unique_path(os.path.join(save_dir, base_name))
                        if not os.path.exists(out_path): os.makedirs(out_path)
                    else:
                        ext = {"GIF": ".gif", "MP4": ".mp4", "WebM": ".webm", "WebP": ".webp"}.get(fmt, ".gif")
                        out_path = get_unique_path(os.path.join(save_dir, f"{base_name}{ext}"))

                    logger = CTKLogger(self, prefix=f"({i+1}/{total})", job_index=q_idx, total_jobs=total)
                    
                    # --- [핵심 수정] MP4 다이렉트 처리 (VFR 끊김 해결) ---
                    batch_cs = job.get('color_settings', {})
                    # 색보정 설정이 있어도 번역된 필터를 통해 무조건 다이렉트 변환을 사용하도록 변경!
                    if fmt == "MP4" and not job.get('is_sequence'):
                        meta = video_engine.get_video_metadata(job['path'])
                        total_duration = meta['duration'] if meta else 0
                        
                        self._direct_ffmpeg_export(job, out_path, logger, total_duration, batch_cs)
                        job['status'] = "완료"
                        success_count += 1
                        self.after(0, lambda n=fname: self.queue_window.append_log(f"완료: {n}"))
                        continue # MoviePy 로직 스킵
                    # ----------------------------------------------------

                    if job.get('is_sequence'):
                        c = video_engine.get_sequence_clip(job['sequence_paths'], job['fps'])
                    else:
                        has_alpha = job['path'].lower().endswith(('.gif', '.png', '.webp', '.webm'))
                        c = VideoFileClip(job['path'], has_mask=has_alpha)
                    
                    with c:
                        target_w = job['width']
                        if fmt == "Thumbnail":
                            c_res = c.resized(width=target_w) if hasattr(c, 'resized') else c.resize(width=target_w)
                            video_engine.perform_write_single_image(c_res, out_path, job['start'], job.get('color_settings', {}), self)
                        else:
                            st, et = max(0, job['start']), min(c.duration, (job['end'] if job['end'] != -1 else c.duration))
                            sub = c.subclipped(st, et) if hasattr(c, 'subclipped') else c.subclip(st, et)
                            if job.get('crop_enabled'):
                                vw, vh = sub.size; x1, y1, x2, y2 = job['crop']
                                sub = sub.cropped(x1=min(x1,x2)*vw, y1=min(y1,y2)*vh, x2=max(x1,x2)*vw, y2=max(y1,y2)*vh)
                            sub = sub.resized(width=target_w) if hasattr(sub, 'resized') else sub.resize(width=target_w)
                            
                            batch_cs = job.get('color_settings', {})
                            if batch_cs.get('color_correction'):
                                def b_filter(img): return np.array(video_engine.apply_color_correction_pil(Image.fromarray(img.astype('uint8')), batch_cs).convert('RGB'))
                                sub = sub.image_transform(b_filter)
                            
                            actual_transparent = job.get('transparent') and sub.mask is not None

                            if fmt == "Sequence":
                                img_format = os.path.join(out_path, f"{os.path.basename(out_path)}.%04d.{job.get('seq_format', 'JPG').lower()}")
                                sub.write_images_sequence(img_format, fps=job['fps'], logger=logger)
                            elif fmt == "WebM":
                                temp_audio_path = os.path.join(tempfile.gettempdir(), f"temp_audio_batch_{q_idx}_{os.getpid()}.ogg")
                                pix_fmt = 'yuva420p' if actual_transparent else 'yuv420p'
                                # [수정] withmask 인자 제거
                                sub.write_videofile(out_path, fps=job['fps'], codec='libvpx-vp9', logger=logger, ffmpeg_params=['-pix_fmt', pix_fmt], temp_audiofile=temp_audio_path, remove_temp=True)
                            elif fmt == "WebP": 
                                video_engine.perform_write_webp(sub, out_path, job['fps'], logger, job.get('loop', 0), actual_transparent, self)
                            else: 
                                video_engine.perform_write_gif(sub, out_path, job['fps'], logger, job.get('loop', 0), actual_transparent, self)
                    
                    job['status'], success_count = "완료", success_count + 1
                    self.after(0, lambda n=fname: self.queue_window.append_log(f"완료: {n}"))

                except RuntimeError as e: 
                    msg = str(e)
                    job['status'] = "취소됨" if msg == "CANCEL_REQUESTED" else f"실패: {msg[:20]}"
                    self.after(0, lambda n=fname, m=msg: self.queue_window.append_log(f"오류 ({n}): {m}"))
                except Exception as e: 
                    msg = str(e)
                    job['status'] = f"실패: {msg[:20]}"
                    self.after(0, lambda n=fname, m=msg: self.queue_window.append_log(f"오류 ({n}): {m}"))
                self.after(0, lambda: self.queue_window.update_list() if self.queue_window else None)
            
        finally: 
            self.is_batch_converting = False
            self.after(0, self._reset_batch_ui)
            self.after(0, lambda: self.queue_window.append_log(f"=== 일괄 변환 종료 (성공: {success_count}/{len(selected_indices)}) ==="))

    def _reset_batch_ui(self):
        if self.queue_window and self.queue_window.winfo_exists():
            if hasattr(self.queue_window, 'control_btn_frame'):
                self.queue_window.control_btn_frame.pack_forget()
            if hasattr(self.queue_window, 'btn_batch') and self.queue_window.btn_batch:
                self.queue_window.btn_batch.configure(text="일괄 변환 시작", fg_color="#2d9d78")
            if hasattr(self.queue_window, 'btn_pause') and self.queue_window.btn_pause:
                try: self.queue_window.btn_pause.configure(text="일시정지")
                except: pass
            self.queue_window.update_list()
        self.progress_bar.grid_remove()
        self.progress_label.grid_remove()

    def export_queue_to_json(self):
        path = filedialog.asksaveasfilename(defaultextension=".json")
        if path:
            data = [{k: v for k, v in j.items() if k != 'thumb_img'} for j in self.queue]
            with open(path, 'w', encoding='utf-8') as f: json.dump(data, f, ensure_ascii=False, indent=4)

    def import_queue_from_json(self):
        path = filedialog.askopenfilename(filetypes=FILETYPES_JSON)
        if path:
            try:
                json_dir = os.path.dirname(path); imported_data = json.load(open(path, 'r', encoding='utf-8'))
                self.progress_bar.set(0); self.progress_bar.grid(row=8, column=0, pady=10, padx=50, sticky="ew"); self.progress_label.grid(row=9, column=0, pady=5); self.progress_label.configure(text="대기열 불러오는 중..."); self.current_load_id += 1; threading.Thread(target=self._process_queue_items_background, args=(imported_data, json_dir), daemon=True).start()
            except Exception as e: self.after(0, lambda msg=str(e): messagebox.showerror("오류", f"불러오기 실패: {msg}"))

    def _process_queue_items_background(self, items, json_dir=None):
        total = len(items)
        if total == 0: self.after(0, self._finalize_processing, []); return

        def analysis_thread():
            valid_items = video_engine.bulk_analyze_items_parallel(items, max_workers=8)
            self.after(0, lambda: self._finalize_processing(valid_items))
        
        threading.Thread(target=analysis_thread, daemon=True).start()

    def _finalize_processing(self, valid_items):
        self.queue.extend(valid_items); self.progress_bar.grid_remove(); self.progress_label.grid_remove(); self._set_loading_ui_state(False)
        if self.queue_window and self.queue_window.winfo_exists(): self.queue_window.update_list()
        else: self.open_queue_window()

    # -------------------------------------------------------------------------
    # 기타 핸들러 (Misc Handlers)
    # -------------------------------------------------------------------------
    def handle_drop(self, event):
        if self.is_loading: return
        paths = self.tk.splitlist(event.data)
        if paths:
            first_path = paths[0]
            if os.path.isdir(first_path): self._process_folder_path(first_path)
            else: self.load_new_video(first_path)

    def toggle_batch_pause(self):
        self.batch_paused = not self.batch_paused
        if self.queue_window and self.queue_window.winfo_exists():
            new_text = "일괄 변환 재개" if self.batch_paused else "일괄 변환 취소"
            self.queue_window.btn_batch.configure(text=new_text)
            self.queue_window.append_log(f"상태 변경: {new_text}")

    def cancel_conversion(self, force=False):
        if force or messagebox.askyesno("확인", "진행 중인 변환 작업을 중단하시겠습니까?"):
            self.cancel_requested = True; self.batch_paused = False 
            if self.queue_window: self.queue_window.append_log("사용자에 의한 변환 중단 요청됨")

    def open_directory(self, path):
        if path and os.path.exists(path):
            if sys.platform == 'win32': os.startfile(path)
            elif sys.platform == 'darwin': subprocess.Popen(['open', path])
            else: subprocess.Popen(['xdg-open', path])

    def open_source_folder(self, path, seq_paths=None):
        target = seq_paths[0] if seq_paths else path
        if target and os.path.exists(target):
            folder = os.path.dirname(target); self.open_directory(folder)