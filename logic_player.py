import time
import threading
from PIL import Image, ImageTk
from utils import format_timecode, RESAMPLING_BILINEAR, RESAMPLING_LANKZOS
import video_engine

class PlayerMixin:
    """재생, 타임라인, 프리뷰 렌더링 및 크롭 관련 로직"""

    def _init_video_ui(self, thumbs, edit_job):
        self.update()
        is_sequence = (self.video_path == "Image Sequence")
        if is_sequence:
            self.proxy_enabled_var.set(False)
            self.switch_proxy.configure(state="disabled", text="Proxy (시퀀스 제외)")
        else:
            self.switch_proxy.configure(state="normal", text="Proxy 모드")

        self.timeline.update_points(0, self.duration, self.duration, play_head=0, fps=self.fps); self.timeline.set_thumbnails(thumbs)
        is_gif = self.video_path.lower().endswith('.gif') or self.video_path == "Image Sequence"

        has_alpha = self.clip is not None and self.clip.mask is not None

        # Alpha 채널이 없는 경우 체크박스 비활성화 및 해제
        if not has_alpha:
            self.keep_transparency_var.set(False)
            self.check_alpha.configure(state="disabled")
        else:
            self.keep_transparency_var.set(True)
            self.check_alpha.configure(state="normal")

        self.video_aspect_ratio = (self.clip.w / self.clip.h) if self.clip else 1.0

        if edit_job:
            self.fps = int(edit_job['fps']); self.fps_slider.set(self.fps); self.fps_input_var.set(str(self.fps)); self.combo_width.set(str(edit_job['width']))
            self.timeline.update_points(edit_job['start'], edit_job['end'] if edit_job['end'] != -1 else self.duration, self.duration, play_head=edit_job['start'], fps=self.fps)
            self.crop_coords = list(edit_job['crop']); self.crop_enabled_var.set(edit_job.get('crop_enabled', False))
            self.loop_count_var.set(str(edit_job.get('loop', 0))); self.keep_transparency_var.set(edit_job.get('transparent', has_alpha))

            # 수동으로 투명도 설정 적용 (원본에 마스크가 있을 때만 체크 값 수용)
            if has_alpha:
                self.keep_transparency_var.set(edit_job.get('transparent', True))

            fmt = edit_job.get('export_format', "GIF"); self.export_format_var.set(fmt); self._update_export_ui(fmt)
            cs = edit_job.get('color_settings', {})
            self.exposure_var.set(cs.get('exposure', 0.0)); self.gamma_var.set(cs.get('gamma', 1.0)); self.contrast_var.set(cs.get('contrast', 0.0))
            self.saturation_var.set(cs.get('saturation', 1.0)); self.tint_var.set(cs.get('tint', 0.0)); self.temperature_var.set(cs.get('temperature', 0.0))
            self.color_correction_var.set(cs.get('color_correction', False)); self.toggle_color_panel()
            self.btn_cancel_edit.pack(side="left", padx=5)
        else:
            if self.clip:
                self.combo_width.set(str(self.clip.w)); src_fps = int(round(self.fps)) if self.fps else 24
                self.fps_slider.set(max(1, min(60, src_fps))); self.fps_input_var.set(str(self.fps_slider.get())); self.fps = self.fps_slider.get()
            self.crop_coords = [0.0, 0.0, 1.0, 1.0]; self.crop_enabled_var.set(False)
            self.reset_color_vars(); self.color_correction_var.set(False); self.toggle_color_panel()
            self.export_format_var.set("WebM" if is_gif else "GIF"); self._update_export_ui(self.export_format_var.get())
            self.btn_cancel_edit.pack_forget()
        
        self.timeline.update_points(self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.duration, fps=self.fps)
        self.on_timeline_change(self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.timeline.play_head * self.duration)
        self._set_loading_ui_state(False)

    def _set_loading_ui_state(self, is_loading):
        self.is_loading = is_loading
        state = "disabled" if is_loading else "normal"
        self.btn_load_single.configure(state=state)
        self.btn_load_seq.configure(state=state)
        self.btn_load_folder.configure(state=state)
        self.btn_add_queue.configure(state=state)
        self.btn_convert_now.configure(state=state)
        if self.queue_window and self.queue_window.winfo_exists():
            self.queue_window.update_list()

    def _update_ui_state(self, mode="normal"):
        state = "disabled" if mode == "edit" else "normal"
        self.btn_load_single.configure(state=state)
        self.btn_load_seq.configure(state=state)
        self.btn_load_folder.configure(state=state)
        self.btn_convert_now.configure(state=state)

    # [추가] 타임라인 조작 시작 시 호출
    def on_timeline_press(self):
        if self.is_playing:
            self.toggle_playback() # 재생 중지

    # [추가] 타임라인 조작 종료 시 호출 (현재는 비워둠)
    def on_timeline_release(self):
        pass

    def on_timeline_change(self, start, end, play_head, fast=False):
        curr_fps = self.fps
        self.label_tc_in.configure(text=f"{format_timecode(start, curr_fps)}/{int(round(start*curr_fps))}F")
        self.label_tc_out.configure(text=f"{format_timecode(end, curr_fps)}/{int(round(end*curr_fps))}F")
        if self.clip:
            d_txt, f_count = format_timecode(end-start, curr_fps), int(round((end-start)*curr_fps))
            self.label_playback_info.configure(text=f"{d_txt} / {f_count}F | {self.clip.w}x{self.clip.h}")
        if fast:
            if self.preview_update_timer: self.after_cancel(self.preview_update_timer)
            self.preview_update_timer = self.after(30, lambda: self.update_preview_frame(play_head, scrubbing=True))
        else: self.update_preview_frame(play_head, scrubbing=True)

    def update_preview_frame(self, t, force_resize=False, scrubbing=False):
        self.frame_cache = {}
        if not self.clip: return
        acquired = self.render_lock.acquire(blocking= scrubbing)
        if not acquired: return
        try:
            self.preview_canvas.update_idletasks() 
            cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height()
            if cw < 10 or ch < 10: return
            safe_t = max(0, min(t, self.duration - 0.001)); cache_key = (round(safe_t, 3), force_resize)
            if cache_key in self.frame_cache and not force_resize and not self.color_correction_var.get(): img = self.frame_cache[cache_key]
            else:
                img = None
                try:
                    with self.clip_access_lock: frame = self.clip.get_frame(safe_t); img = Image.fromarray(frame.astype('uint8')) 
                    img.thumbnail((cw, ch), RESAMPLING_BILINEAR)
                    if len(self.frame_cache) > 150: self.frame_cache.pop(next(iter(self.frame_cache)))
                    self.frame_cache[cache_key], self.last_preview_img_data, self.last_preview_time = img, img, t
                except: img = self.last_preview_img_data
            if img:
                settings = {"color_correction": self.color_correction_var.get(), "exposure": self.exposure_var.get(), "gamma": self.gamma_var.get(), "contrast": self.contrast_var.get(), "saturation": self.saturation_var.get(), "tint": self.tint_var.get(), "temperature": self.temperature_var.get()}
                c_img = video_engine.apply_color_correction_pil(img, settings); self._render_to_canvas(c_img)
        finally: self.render_lock.release()

    def _render_to_canvas(self, pil_img):
        """프리뷰 캔버스 렌더링 및 크롭 가이드 그리기"""
        try:
            self.last_preview_img = ImageTk.PhotoImage(pil_img); cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height(); cw, ch = max(cw, 10), max(ch, 10); self.preview_canvas.delete("all"); self.preview_canvas.create_image(cw/2, ch/2, image=self.last_preview_img, anchor="center")
            if self.crop_enabled_var.get() and self.crop_coords:
                iw, ih = pil_img.width, pil_img.height; ox, oy = (cw - iw) / 2, (ch - ih) / 2; x1, y1, x2, y2 = self.crop_coords; px1, px2, py1, py2 = ox + min(x1, x2)*iw, ox + max(x1, x2)*iw, oy + min(y1, y2)*ih, oy + max(y1, y2)*ih
                
                # 가이드 라인
                self.preview_canvas.create_rectangle(px1, py1, px2, py2, outline="#ff7700", width=2, dash=(4,4))
                
                # 코너 핸들 강조
                cl, ct, color = 10, 4, "#ff7700" 
                # 좌상
                self.preview_canvas.create_line(px1, py1, px1 + cl, py1, fill=color, width=ct)
                self.preview_canvas.create_line(px1, py1, px1, py1 + cl, fill=color, width=ct)
                # 우상
                self.preview_canvas.create_line(px2, py1, px2 - cl, py1, fill=color, width=ct)
                self.preview_canvas.create_line(px2, py1, px2, py1 + cl, fill=color, width=ct)
                # 좌하
                self.preview_canvas.create_line(px1, py2, px1 + cl, py2, fill=color, width=ct)
                self.preview_canvas.create_line(px1, py2, px1, py2 - cl, fill=color, width=ct)
                # 우하
                self.preview_canvas.create_line(px2, py2, px2 - cl, py2, fill=color, width=ct)
                self.preview_canvas.create_line(px2, py2, px2, py2 - cl, fill=color, width=ct)
                
            self.update_idletasks()
        except: pass

    def toggle_playback(self):
        if not self.clip: return
        if self.is_playing: self.is_playing = False; self.btn_play.configure(text="▶ 재생")
        else: self.is_playing = True; self.btn_play.configure(text="■ 정지"); threading.Thread(target=self._playback_loop, daemon=True).start()

    def _playback_loop(self):
        last_time, st, et, ct = time.time(), self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.timeline.play_head * self.duration
        while self.is_playing:
            loop_start = time.time(); dt = loop_start - last_time; last_time = loop_start; ct += dt
            if ct >= et or ct < st: ct = st
            if self.render_lock.acquire(blocking=False):
                try:
                    local_clip, safe_t = self.clip, max(0, min(ct, self.duration - 0.001)); cache_key = (round(safe_t, 3), False)
                    if cache_key in self.frame_cache and not self.color_correction_var.get(): img = self.frame_cache[cache_key]
                    else:
                        try:
                            with self.clip_access_lock: frame = local_clip.get_frame(safe_t); img = Image.fromarray(frame.astype('uint8')) 
                            self.preview_canvas.update_idletasks(); cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height()
                            if cw < 10: img = self.last_preview_img_data
                            else: img.thumbnail((max(cw,50), max(ch,50)), RESAMPLING_BILINEAR); self.frame_cache[cache_key] = img
                        except: img = self.last_preview_img_data
                    if img:
                        self.last_preview_img_data, self.last_preview_time = img, safe_t
                        settings = {"color_correction": self.color_correction_var.get(), "exposure": self.exposure_var.get(), "gamma": self.gamma_var.get(), "contrast": self.contrast_var.get(), "saturation": self.saturation_var.get(), "tint": self.tint_var.get(), "temperature": self.temperature_var.get()}
                        c_img = video_engine.apply_color_correction_pil(img, settings); self.after(0, lambda ci=c_img, t=safe_t: self._sync_pb_v3(ci, t))
                finally: self.render_lock.release()
            time.sleep(max(0.001, (1/self.fps) - (time.time() - loop_start)))

    def _sync_pb_v3(self, corrected_img, t):
        if not self.is_playing: return
        self.timeline.play_head = max(0, min(1, t / self.duration)); self.timeline.draw(); self._render_to_canvas(corrected_img)

    def _on_fps_slider_move(self, val):
        self.fps_input_var.set(str(int(val))); self.fps = int(val)
        if self.clip and not self.is_playing: 
            self.on_timeline_change(self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.timeline.play_head * self.duration, fast=True)
        
    def _on_fps_entry_change(self, event):
        try:
            val = int(self.fps_input_var.get())
            if 1 <= val <= 60: self.fps_slider.set(val); self.fps = val; self.on_timeline_change(self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.timeline.play_head * self.duration)
        except: pass

    # Crop 관련 기능
    def reset_crop(self): self.crop_coords = [0.0, 0.0, 1.0, 1.0]; self.update_preview_frame(self.last_preview_time)
    
    def start_crop_drag(self, event):
        if not self.last_preview_img or not self.crop_enabled_var.get(): return
        cw, ch = self.preview_canvas.winfo_width(), self.preview_canvas.winfo_height(); iw, ih = self.last_preview_img_data.width, self.last_preview_img_data.height; ox, oy = (cw - iw) / 2, (ch - ih) / 2
        x1, y1, x2, y2 = self.crop_coords; px1, px2, py1, py2 = ox + x1*iw, ox + x2*iw, oy + y1*ih, oy + y2*ih; hz = 25; ex, ey = event.x, event.y
        if abs(ex - px1) < hz and abs(ey - py1) < hz: self.active_crop_handle = 'nw'
        elif abs(ex - px2) < hz and abs(ey - py1) < hz: self.active_crop_handle = 'ne'
        elif abs(ex - px1) < hz and abs(ey - py2) < hz: self.active_crop_handle = 'sw'
        elif abs(ex - px2) < hz and abs(ey - py2) < hz: self.active_crop_handle = 'se'
        elif min(px1, px2) < ex < max(px1, px2) and min(py1, py2) < ey < max(py1, py2): self.active_crop_handle = 'center'
        else: self.active_crop_handle = 'new'; sx, sy = max(0, min(1, (ex-ox)/iw)), max(0, min(1, (ey-oy)/ih)); self.crop_coords = [sx, sy, sx, sy]
        self.crop_start_pos, self.orig_crop_coords = (ex, ey), list(self.crop_coords)

    def update_crop_drag(self, event):
        if not self.crop_start_pos or not self.last_preview_img: return
        iw, ih = self.last_preview_img_data.width, self.last_preview_img_data.height; dx, dy = (event.x - self.crop_start_pos[0])/iw, (event.y - self.crop_start_pos[1])/ih
        nc = list(self.orig_crop_coords); ms = 0.02 
        if self.active_crop_handle == 'center':
            w, h = nc[2] - nc[0], nc[3] - nc[1]; nc[0] = max(0, min(1 - abs(w), nc[0] + dx)); nc[1] = max(0, min(1 - abs(h), nc[1] + dy)); nc[2], nc[3] = nc[0] + w, nc[1] + h
        elif self.active_crop_handle in ['nw', 'ne', 'sw', 'se', 'new']:
            if self.active_crop_handle == 'nw': nc[0] = max(0, min(nc[2] - ms, nc[0] + dx)); nc[1] = max(0, min(nc[3] - ms, nc[1] + dy))
            elif self.active_crop_handle == 'ne': nc[2] = min(1, max(nc[0] + ms, nc[2] + dx)); nc[1] = max(0, min(nc[3] - ms, nc[1] + dy))
            elif self.active_crop_handle == 'sw': nc[0] = max(0, min(nc[2] - ms, nc[0] + dx)); nc[3] = min(1, max(nc[1] + ms, nc[3] + dy))
            elif self.active_crop_handle == 'se': nc[2] = min(1, max(nc[0] + ms, nc[2] + dx)); nc[3] = min(1, max(nc[1] + ms, nc[3] + dy))
            elif self.active_crop_handle == 'new': nc[2], nc[3] = max(0, min(1, self.orig_crop_coords[2]+dx)), max(0, min(1, self.orig_crop_coords[3]+dy))
            if self.lock_aspect_ratio_var.get():
                td = abs(nc[2] - nc[0])
                if self.active_crop_handle in ['nw', 'ne', 'sw', 'se', 'new']:
                    if 'n' in self.active_crop_handle or self.active_crop_handle == 'new': (nc.__setitem__(3, nc[1] + td) if self.active_crop_handle == 'sw' else nc.__setitem__(1, nc[3] - td))
                    else: nc[3] = nc[1] + td
        self.crop_coords = nc; self.update_preview_frame(self.last_preview_time)

    def end_crop_drag(self, event):
        x1, y1, x2, y2 = self.crop_coords; nx1, ny1, nx2, ny2 = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        if (nx2 - nx1) < 0.01: nx2 = nx1 + 0.01
        if (ny2 - ny1) < 0.01: ny2 = ny1 + 0.01
        self.crop_coords, self.active_crop_handle, self.crop_start_pos = [max(0.0, nx1), max(0.0, ny1), min(1.0, nx2), min(1.0, ny2)], None, None