import os
import sys
import threading
import time
import tempfile
import atexit
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from PIL import Image

# 로컬 모듈
import constants as const
import utils
import updater
from ui_widgets import TimelineSlider, QueueWindow
from logic_media import MediaMixin
from logic_player import PlayerMixin
from logic_converter import ConverterMixin

# MoviePy (지연 로딩 또는 안전한 로딩)
try:
    from moviepy import VideoFileClip
except ImportError:
    try:
        from moviepy.editor import VideoFileClip
    except ImportError:
        pass

# Drag & Drop
if utils.HAS_DND:
    from tkinterdnd2 import DND_FILES, TkinterDnD

class VideoToGifApp(ctk.CTk, 
                    TkinterDnD.DnDWrapper if utils.HAS_DND else object,
                    MediaMixin, PlayerMixin, ConverterMixin):
    
    def __init__(self):
        ctk.CTk.__init__(self)
        ctk.set_appearance_mode("Dark")
        if utils.HAS_DND:
            TkinterDnD.DnDWrapper.__init__(self)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_available = True
            except:
                self.dnd_available = False
        else:
            self.dnd_available = False

        self.title(f"{const.APP_TITLE} v{const.APP_VERSION}")
        self.geometry("1100x950")

        self._init_vars()
        self.setup_ui()
        
        if self.dnd_available:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.handle_drop)
        
        self.after(1000, lambda: threading.Thread(target=updater.check_for_updates, args=(self,), daemon=True).start())
        atexit.register(self._cleanup_temp_files)

    def _init_vars(self):
        # 상태 변수 초기화
        self.video_path = None
        self.clip = None
        self.duration = 1.0
        self.fps = const.DEFAULT_FPS
        self.source_clip = None 
        self.proxy_clip = None 
        self.is_proxy_ready = False 
        self.is_proxy_active = False 
        self.is_proxy_generating = False 
        self.stop_proxy_request = False 
        self.frame_cache = {} 
        self.proxy_files = [] 
        self.proxy_thread = None
        
        self.sequence_paths = [] 
        self.is_playing = False
        self.editing_index = -1
        self.queue = []
        self.queue_window = None
        
        self.crop_coords = [0.0, 0.0, 1.0, 1.0]
        self.last_preview_time = -1.0
        self.preview_update_timer = None 
        self.active_crop_handle = None
        self.crop_start_pos = None
        self.last_preview_img_data = None
        self.last_preview_img = None
        self.orig_crop_coords = None
        self.latest_update_data = None
        
        self.render_lock = threading.Lock() 
        self.clip_access_lock = threading.Lock() 
        
        self.current_load_id = 0
        self.last_save_dir = None
        self.video_aspect_ratio = 1.0
        
        self.cancel_requested = False
        self.batch_paused = False
        self.is_batch_converting = False
        self.is_loading = False 
        self.job_widgets = {}

        # UI 연동 변수
        self.loop_count_var = ctk.StringVar(value="0")
        self.keep_transparency_var = ctk.BooleanVar(value=True)
        self.lock_aspect_ratio_var = ctk.BooleanVar(value=True)
        self.crop_enabled_var = ctk.BooleanVar(value=False) 
        self.proxy_enabled_var = ctk.BooleanVar(value=False) 
        self.color_correction_var = ctk.BooleanVar(value=False)
        self.export_format_var = ctk.StringVar(value=const.DEFAULT_EXPORT_FORMAT)
        self.seq_format_var = ctk.StringVar(value=const.DEFAULT_SEQ_FORMAT)
        self.webm_bitrate_var = ctk.StringVar(value="2") 
        
        self.exposure_var = ctk.DoubleVar(value=0.0)
        self.gamma_var = ctk.DoubleVar(value=1.0)
        self.contrast_var = ctk.DoubleVar(value=0.0)
        self.saturation_var = ctk.DoubleVar(value=1.0)
        self.tint_var = ctk.DoubleVar(value=0.0)
        self.temperature_var = ctk.DoubleVar(value=0.0)
        self.fps_input_var = ctk.StringVar(value=str(self.fps))

    def _cleanup_temp_files(self):
        for f in self.proxy_files:
            try:
                if os.path.exists(f): os.remove(f)
            except: pass

    # UI Setup
    def setup_ui(self):
        self.main_container = ctk.CTkFrame(self, corner_radius=15)
        self.main_container.pack(padx=20, pady=20, fill="both", expand=True)
        self.main_container.grid_rowconfigure(2, weight=1)
        self.main_container.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(self.main_container, text=f"{const.APP_TITLE} v{const.APP_VERSION}", font=ctk.CTkFont(size=24, weight="bold")).grid(row=0, column=0, pady=(15, 5))
        
        file_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        file_frame.grid(row=1, column=0, padx=20, pady=5, sticky="ew")
        
        self.btn_load_single = ctk.CTkButton(file_frame, text="단일 파일 불러오기", height=45, fg_color="#3b8ed0", command=self.select_file)
        self.btn_load_single.pack(side="left", expand=True, fill="x", padx=(0,5))
        self.btn_load_seq = ctk.CTkButton(file_frame, text="시퀀스 파일 불러오기", height=45, fg_color="#a040a0", command=self.select_sequence_files)
        self.btn_load_seq.pack(side="left", expand=True, fill="x", padx=5)
        self.btn_load_folder = ctk.CTkButton(file_frame, text="폴더 일괄 불러오기", height=45, fg_color="#2d9d78", command=self.select_folder)
        self.btn_load_folder.pack(side="left", expand=True, fill="x", padx=(5,0))
        
        self.preview_container = ctk.CTkFrame(self.main_container, fg_color="black", corner_radius=10)
        self.preview_container.grid(row=2, column=0, padx=20, pady=10, sticky="nsew")
        
        self.preview_canvas = tk.Canvas(self.preview_container, bg="black", highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True)
        
        self.proxy_progress_bar = ctk.CTkProgressBar(self.preview_container, height=4, fg_color="#111111", progress_color="#3b8ed0", corner_radius=0)
        self.proxy_progress_bar.set(0)
        
        self.preview_canvas.bind("<Configure>", lambda e: self.update_preview_frame(self.last_preview_time, force_resize=True))
        self.preview_canvas.bind("<Button-1>", self.start_crop_drag)
        self.preview_canvas.bind("<B1-Motion>", self.update_crop_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self.end_crop_drag)
        
        control_panel = ctk.CTkFrame(self.main_container, fg_color="transparent")
        control_panel.grid(row=3, column=0, pady=5, sticky="ew", padx=20)
        self.btn_play = ctk.CTkButton(control_panel, text="▶ 재생", width=80, command=self.toggle_playback)
        self.btn_play.pack(side="left", padx=5)
        self.label_playback_info = ctk.CTkLabel(control_panel, text="00:00:00:00/0F", font=("Courier", 12), text_color="gray")
        self.label_playback_info.pack(side="left", padx=15)
        
        tool_set = ctk.CTkFrame(control_panel, fg_color="transparent")
        tool_set.pack(side="right")
        
        ctk.CTkSwitch(tool_set, text="비율 고정", variable=self.lock_aspect_ratio_var).pack(side="left", padx=5)
        self.switch_crop = ctk.CTkSwitch(tool_set, text="Crop 모드", variable=self.crop_enabled_var, command=self.on_crop_switch_toggle)
        self.switch_crop.pack(side="left", padx=5)
        self.switch_proxy = ctk.CTkSwitch(tool_set, text="Proxy 모드", variable=self.proxy_enabled_var, command=self.on_proxy_switch_toggle)
        self.switch_proxy.pack(side="left", padx=5)
        
        self.timeline_frame = ctk.CTkFrame(self.main_container, corner_radius=10, fg_color="#222222")
        self.timeline_frame.grid(row=4, column=0, padx=20, pady=5, sticky="ew")
        self.timeline = TimelineSlider(self.timeline_frame)
        self.timeline.pack(padx=20, pady=(15, 0), fill="x")
        self.timeline.set_callback(self.on_timeline_change)
        
        # [추가] 타임라인 조작 콜백 연결
        self.timeline.set_interaction_callbacks(self.on_timeline_press, self.on_timeline_release)
        
        timecode_row = ctk.CTkFrame(self.timeline_frame, fg_color="transparent")
        timecode_row.pack(fill="x", padx=30, pady=(5, 5))
        self.label_tc_in = ctk.CTkLabel(timecode_row, text="00:00:00:00/0F", font=("Courier", 12, "bold"), text_color="#3b8ed0")
        self.label_tc_in.pack(side="left")
        ctk.CTkButton(timecode_row, text="영역 초기화 ↺", width=90, height=24, fg_color="#444444", font=("Arial", 11), command=self.timeline.reset_selection).pack(side="left", padx=20)
        self.label_tc_out = ctk.CTkLabel(timecode_row, text="00:00:00:00/0F", font=("Courier", 12, "bold"), text_color="#e67e22")
        self.label_tc_out.pack(side="right")
        
        self.bottom_options = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.bottom_options.grid(row=5, column=0, sticky="ew", padx=20, pady=5)
        
        quality_frame = ctk.CTkFrame(self.bottom_options, fg_color="#2b2b2b", corner_radius=8)
        quality_frame.pack(side="left", fill="both", expand=True, padx=5)
        self.combo_width = ctk.CTkComboBox(quality_frame, values=const.RESOLUTIONS, width=95)
        self.combo_width.set(const.DEFAULT_WIDTH)
        self.combo_width.pack(side="left", padx=10, pady=10)
        self.fps_slider = ctk.CTkSlider(quality_frame, from_=const.FPS_OPTIONS[0], to=const.FPS_OPTIONS[1], command=self._on_fps_slider_move)
        self.fps_slider.set(self.fps)
        self.fps_slider.pack(side="left", padx=5)
        self.entry_fps = ctk.CTkEntry(quality_frame, width=50, textvariable=self.fps_input_var)
        self.entry_fps.pack(side="left", padx=5)
        self.entry_fps.bind("<KeyRelease>", self._on_fps_entry_change)
        self.label_fps = ctk.CTkLabel(quality_frame, text="FPS", font=("Arial", 11))
        self.label_fps.pack(side="left", padx=(0, 10))
        
        self.export_frame_content = ctk.CTkFrame(self.bottom_options, fg_color="#2b2b2b", corner_radius=8)
        self.export_frame_content.pack(side="left", fill="both", expand=True, padx=5)
        ctk.CTkLabel(self.export_frame_content, text="Export Format:", font=("Arial", 11)).pack(side="left", padx=(10, 2))
        self.combo_format = ctk.CTkComboBox(self.export_frame_content, values=const.EXPORT_FORMATS, width=110, variable=self.export_format_var, command=self._update_export_ui, state="readonly")
        self.combo_format.pack(side="left", padx=5, pady=10)
        self.dynamic_opt_frame = ctk.CTkFrame(self.export_frame_content, fg_color="transparent")
        self.dynamic_opt_frame.pack(side="left", fill="both", expand=True)
        self.check_alpha = ctk.CTkCheckBox(self.dynamic_opt_frame, text="Alpha", variable=self.keep_transparency_var)
        self.combo_seq_format = ctk.CTkComboBox(self.dynamic_opt_frame, values=const.SEQUENCE_FORMATS, width=85, variable=self.seq_format_var, state="readonly")
        self.bitrate_container = ctk.CTkFrame(self.dynamic_opt_frame, fg_color="transparent")
        ctk.CTkLabel(self.bitrate_container, text="Bitrate:", font=("Arial", 11)).pack(side="left", padx=(5, 2))
        self.entry_bitrate = ctk.CTkEntry(self.bitrate_container, width=40, textvariable=self.webm_bitrate_var)
        self.entry_bitrate.pack(side="left", padx=2)
        ctk.CTkLabel(self.bitrate_container, text="Mbps", font=("Arial", 10), text_color="gray").pack(side="left")
        self.loop_container = ctk.CTkFrame(self.dynamic_opt_frame, fg_color="transparent")
        ctk.CTkLabel(self.loop_container, text="반복:", font=("Arial", 11)).pack(side="left", padx=(5, 2))
        self.entry_loop_count = ctk.CTkEntry(self.loop_container, width=40, textvariable=self.loop_count_var)
        self.entry_loop_count.pack(side="left", padx=5)
        self._update_export_ui(self.export_format_var.get())
        
        etc_frame = ctk.CTkFrame(self.bottom_options, fg_color="#2b2b2b", corner_radius=8)
        etc_frame.pack(side="left", fill="y", padx=5)
        self.check_color = ctk.CTkSwitch(etc_frame, text="색보정", variable=self.color_correction_var, command=self.toggle_color_panel)
        self.check_color.pack(side="right", padx=15, pady=10)
        
        self.color_panel = ctk.CTkFrame(self.main_container, fg_color="#222222", corner_radius=10)
        self.color_panel.grid(row=6, column=0, padx=20, pady=5, sticky="ew")
        self.color_panel.grid_remove() 
        self.setup_color_ui()
        
        self.action_frame = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.action_frame.grid(row=7, column=0, sticky="ew", padx=20, pady=10)
        
        self.btn_add_queue = ctk.CTkButton(self.action_frame, text="대기열에 추가", height=50, fg_color="#764ba2", command=self.add_to_queue)
        self.btn_add_queue.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        self.btn_cancel_edit = ctk.CTkButton(self.action_frame, text="항목 수정 취소", height=50, fg_color="#555555", command=self.cancel_edit)
        
        ctk.CTkButton(self.action_frame, text="대기열 창 열기", height=50, fg_color="#555555", command=self.open_queue_window).pack(side="left", padx=5)
        
        self.conv_btn_container = ctk.CTkFrame(self.action_frame, fg_color="transparent")
        self.conv_btn_container.pack(side="left", fill="x", expand=True, padx=(5, 0))
        
        self.btn_convert_now = ctk.CTkButton(self.conv_btn_container, text="즉시 변환 시작", height=50, fg_color="#2d9d78", command=self.start_conversion_thread)
        self.btn_convert_now.pack(side="left", fill="x", expand=True)
        
        self.btn_cancel_immediate = ctk.CTkButton(self.conv_btn_container, text="변환 중단", height=50, fg_color="#a04040", command=self.cancel_conversion)
        self.btn_cancel_immediate.pack_forget() 

        self.progress_bar = ctk.CTkProgressBar(self.main_container)
        self.progress_label = ctk.CTkLabel(self.main_container, text="")

    def setup_color_ui(self):
        for widget in self.color_panel.winfo_children(): widget.destroy()
        inner = ctk.CTkFrame(self.color_panel, fg_color="transparent")
        inner.pack(padx=20, pady=10, fill="x")
        
        for i, (name, v_min, v_max, v_def) in enumerate(const.COLOR_CONFIGS):
            var = [self.exposure_var, self.gamma_var, self.contrast_var, self.saturation_var, self.tint_var, self.temperature_var][i]
            row, col = i // 2, i % 2
            frame = ctk.CTkFrame(inner, fg_color="transparent")
            frame.grid(row=row, column=col, padx=10, pady=5, sticky="ew")
            inner.grid_columnconfigure(col, weight=1)
            ctk.CTkLabel(frame, text=name, font=("Arial", 11), width=45, anchor="w").pack(side="left")
            btn_reset = ctk.CTkButton(frame, text="↺", width=24, height=24, fg_color="#444444", hover_color="#555555", command=lambda v=var, d=v_def: v.set(d))
            btn_reset.pack(side="right", padx=(5, 0))
            entry = ctk.CTkEntry(frame, width=50, height=24, font=("Arial", 10))
            entry.pack(side="right", padx=5)
            entry.insert(0, str(round(var.get(), 2)))
            slider = ctk.CTkSlider(frame, from_=v_min, to=v_max, variable=var, height=16)
            slider.pack(side="left", fill="x", expand=True, padx=5)
            
            def update_entry(*args, e=entry, v=var):
                try:
                    current_val = float(e.get())
                    if abs(current_val - v.get()) > 0.01:
                        e.delete(0, tk.END)
                        e.insert(0, str(round(v.get(), 2)))
                except: pass
            def on_entry_change(event, e=entry, v=var, mi=v_min, ma=v_max):
                try:
                    val = float(e.get())
                    clamped = max(mi, min(ma, val))
                    v.set(clamped)
                    self.update_preview_frame(self.last_preview_time)
                except ValueError: pass
            var.trace_add("write", update_entry)
            var.trace_add("write", lambda *args: self.update_preview_frame(self.last_preview_time))
            entry.bind("<Return>", on_entry_change)
            entry.bind("<FocusOut>", on_entry_change)

        btn_row = ctk.CTkFrame(self.color_panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 10))
        ctk.CTkButton(btn_row, text="전체 초기화 ↺", width=100, height=28, fg_color="#444444", command=self.reset_color_vars).pack(side="right")

    def reset_color_vars(self):
        self.exposure_var.set(0.0); self.gamma_var.set(1.0); self.contrast_var.set(0.0); self.saturation_var.set(1.0); self.tint_var.set(0.0); self.temperature_var.set(0.0)

    def _update_export_ui(self, choice):
        self.check_alpha.pack_forget(); self.combo_seq_format.pack_forget(); self.bitrate_container.pack_forget(); self.loop_container.pack_forget()

        fps_state = "disabled" if choice == "Thumbnail" else "normal"
        self.fps_slider.configure(state=fps_state)
        self.entry_fps.configure(state=fps_state)
        self.label_fps.configure(text_color="gray" if fps_state == "disabled" else "white")
        
        if choice == "GIF":
            self.check_alpha.pack(side="left", padx=10); self.loop_container.pack(side="left", padx=5)
        elif choice == "WebM":
            self.check_alpha.pack(side="left", padx=10); self.bitrate_container.pack(side="left", padx=5)
        elif choice == "WebP":
            self.check_alpha.pack(side="left", padx=10); self.loop_container.pack(side="left", padx=5)
        elif choice == "MP4":
            self.bitrate_container.pack(side="left", padx=10)
        elif choice == "Sequence":
            self.combo_seq_format.pack(side="left", padx=5); self.check_alpha.pack(side="left", padx=10)
        elif choice == "Thumbnail":
            self.combo_seq_format.pack(side="left", padx=5)
            self.seq_format_var.set("JPG")

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

    def toggle_color_panel(self):
        if self.color_correction_var.get(): 
            self.color_panel.grid()
        else: 
            self.color_panel.grid_remove()
        if self.clip: self.update_preview_frame(self.last_preview_time)

    def on_crop_switch_toggle(self):
        if not self.crop_enabled_var.get():
            self.reset_crop()
        self.update_preview_frame(self.last_preview_time)

    def on_proxy_switch_toggle(self):
        if self.proxy_enabled_var.get():
            self.stop_proxy_request = False
            if self.is_proxy_ready and self.proxy_clip:
                self._apply_swap_logic(self.proxy_clip, is_proxy=True)
            elif not self.is_proxy_generating and self.source_clip:
                if self.source_clip.h >= 720:
                    temp_proxy = os.path.join(tempfile.gettempdir(), f"proxy_{self.current_load_id}.mp4")
                    self.is_proxy_generating = True
                    self.proxy_thread = threading.Thread(
                        target=self._create_proxy_background, 
                        args=(self.video_path, temp_proxy, self.current_load_id),
                        daemon=True
                    )
                    self.proxy_thread.start()
        else:
            self.stop_proxy_request = True
            if self.source_clip:
                self._apply_swap_logic(self.source_clip, is_proxy=False)
        self.update_preview_frame(self.last_preview_time)

    def _apply_swap_logic(self, target_clip, is_proxy=False):
        with self.render_lock:
            with self.clip_access_lock:
                if self.is_playing: self.toggle_playback()
                self.clip = target_clip
                self.is_proxy_active = is_proxy
                self.frame_cache = {}
        self.after(0, lambda: self.on_timeline_change(self.timeline.in_point * self.duration, self.timeline.out_point * self.duration, self.timeline.play_head * self.duration))

    def _create_proxy_background(self, original_path, proxy_path, load_id):
        try:
            self.after(0, lambda: self.proxy_progress_bar.pack(side="bottom", fill="x"))
            self.after(0, lambda: self.label_playback_info.configure(text_color="#3b8ed0"))
            p_orig_clip = VideoFileClip(original_path)
            h = p_orig_clip.h
            if h >= 4320: scale_h = h // 8
            elif h >= 2160: scale_h = h // 4
            else: scale_h = h // 2
            scale_h = int((max(scale_h, 360) // 2) * 2)
            p_clip = p_orig_clip.resized(height=scale_h) if hasattr(p_orig_clip, 'resized') else p_orig_clip.resize(height=scale_h)
            
            from proglog import ProgressBarLogger
            class ProxyLogger(ProgressBarLogger):
                def __init__(self, app): super().__init__(); self.app = app
                def callback(self, **changes):
                    if self.app.stop_proxy_request: raise RuntimeError("PROXY_STOPPED")
                    for message in self.state['bars'].values():
                        if message['total'] > 0: p = message['index'] / message['total']; self.app.after(0, lambda val=p: self.app._update_proxy_progress(val))
            
            p_clip.write_videofile(proxy_path, fps=p_orig_clip.fps, codec='libx264', audio=False, bitrate="8M", preset="faster", logger=ProxyLogger(self))
            p_clip.close(); p_orig_clip.close()
            if load_id == self.current_load_id:
                self.proxy_files.append(proxy_path); new_proxy_clip = VideoFileClip(proxy_path); self.proxy_clip = new_proxy_clip; self.is_proxy_ready = True; self.is_proxy_generating = False; self.after(0, self._auto_enable_proxy)
        except RuntimeError as e:
            self.is_proxy_generating = False
            if str(e) == "PROXY_STOPPED": self.after(0, lambda: (self.proxy_progress_bar.pack_forget(), self.label_playback_info.configure(text_color="gray")))
        except Exception as e: 
            self.is_proxy_generating = False
            print(f"Proxy creation failed: {e}")

    def _auto_enable_proxy(self):
        self.proxy_enabled_var.set(True)
        if self.proxy_clip: self._apply_swap_logic(self.proxy_clip, is_proxy=True)
        self.proxy_progress_bar.pack_forget()

    def _update_proxy_progress(self, value):
        if self.proxy_progress_bar.winfo_exists(): self.proxy_progress_bar.set(value)