import sys
import time
import tkinter as tk
import customtkinter as ctk
from datetime import datetime
from PIL import Image, ImageTk
from utils import format_timecode, RESAMPLING_LANKZOS
import constants as const

# -------------------------------------------------------------------------
# 타임라인 슬라이더 UI (Timeline Slider)
# -------------------------------------------------------------------------
class TimelineSlider(ctk.CTkCanvas):
    def __init__(self, master, width=860, height=100, **kwargs):
        super().__init__(master, width=width, height=height, bg="#222222", highlightthickness=0, **kwargs)
        self.width, self.height, self.padding = width, height, 30 
        self.in_point, self.out_point, self.play_head, self.duration, self.fps = 0.0, 1.0, 0.0, 1.0, 24
        self.thumbnails, self.dim_layer_images, self.active_handle, self.on_change_callback = [], [], None, None
        
        # 사용자 조작 시작/종료 콜백 (충돌 방지용)
        self.on_press_callback = None
        self.on_release_callback = None
        
        # 이벤트 스로틀링을 위한 시간 변수
        self.last_update_time = 0
        self.update_interval = 0.05  # 50ms (초당 약 20회로 제한)

        self.bind("<Button-1>", self.on_click); self.bind("<B1-Motion>", self.on_drag); self.bind("<ButtonRelease-1>", self.on_release); self.bind("<Configure>", self.on_resize)
    
    def set_callback(self, callback): self.on_change_callback = callback
    
    # [복구] 인터랙션 콜백 설정 메서드
    def set_interaction_callbacks(self, on_press, on_release):
        self.on_press_callback = on_press
        self.on_release_callback = on_release

    def on_resize(self, event): self.width = event.width; self.draw()
    
    def set_thumbnails(self, thumbnail_images):
        self.thumbnails = []
        if not thumbnail_images: self.draw(); return
        track_w = max(1, self.width - (2 * self.padding))
        for i, img in enumerate(thumbnail_images):
            x_start = self.padding + (i * track_w / len(thumbnail_images))
            w = int(self.padding + ((i + 1) * track_w / len(thumbnail_images))) - int(x_start) + 1
            if w <= 0: continue
            try:
                photo = ImageTk.PhotoImage(img.resize((w, 60), RESAMPLING_LANKZOS))
                self.thumbnails.append((photo, int(x_start)))
            except: continue
        self.draw()
        
    def get_x_pos(self, ratio): return self.padding + (ratio * max(1, self.width - (2 * self.padding)))
    def get_ratio_from_x(self, x): return max(0.0, min(1.0, (x - self.padding) / max(1, self.width - (2 * self.padding))))
    
    def draw_dimmed_area(self, x_s, x_e):
        w = int(x_e) - int(x_s)
        if w <= 0: return
        photo = ImageTk.PhotoImage(Image.new('RGBA', (w, 60), (0, 0, 0, 180)))
        self.dim_layer_images.append(photo); self.create_image(x_s, 10, image=photo, anchor="nw")

    def draw(self):
        self.delete("all"); self.dim_layer_images = []
        self.create_rectangle(self.padding, 10, self.width - self.padding, 70, fill="#111111", outline="")
        if self.thumbnails:
            for p, x in self.thumbnails: self.create_image(x, 10, image=p, anchor="nw")
        x_i, x_o, x_p = self.get_x_pos(self.in_point), self.get_x_pos(self.out_point), self.get_x_pos(self.play_head)
        self.draw_dimmed_area(self.padding, x_i); self.draw_dimmed_area(x_o, self.width - self.padding)

        # 메인 선택 영역 박스
        self.create_rectangle(x_i, 10, x_o, 70, outline="#2a2a2a", width=1)
        
        # 선택 영역 모서리 강조
        cl, ct, color = 10, 3, "#2a2a2a"
        # 좌상
        self.create_line(x_i, 10, x_i+cl, 10, fill=color, width=ct)
        self.create_line(x_i, 10, x_i, 10+cl, fill=color, width=ct)
        # 우상
        self.create_line(x_o, 10, x_o-cl, 10, fill=color, width=ct)
        self.create_line(x_o, 10, x_o, 10+cl, fill=color, width=ct)
        # 좌하
        self.create_line(x_i, 70, x_i+cl, 70, fill=color, width=ct)
        self.create_line(x_i, 70, x_i, 70-cl, fill=color, width=ct)
        # 우하
        self.create_line(x_o, 70, x_o-cl, 70, fill=color, width=ct)
        self.create_line(x_o, 70, x_o, 70-cl, fill=color, width=ct)

        # 핸들 표시 [ ]
        self.create_rectangle(x_i, 10, x_i+14, 70, fill="#3b8ed0", outline=""); self.create_text(x_i+7, 40, text="[", fill="white", font=("Arial", 12, "bold"))
        self.create_rectangle(x_o-14, 10, x_o, 70, fill="#e67e22", outline=""); self.create_text(x_o-7, 40, text="]", fill="white", font=("Arial", 12, "bold"))
        self.create_line(x_p, 5, x_p, 75, fill="#ff4444", width=2); self.create_polygon(x_p-6, 5, x_p+6, 5, x_p, 15, fill="#ff4444")
        self.create_text(max(65, min(self.width-65, x_p)), 88, text=f"{format_timecode(self.play_head*self.duration, self.fps)}/{int(round(self.play_head*self.duration*self.fps))}F", fill="#ff4444", font=("Courier", 9, "bold"))

    def on_click(self, e):
        # [복구] 조작 시작 시 콜백 호출 (재생 중지 요청)
        if self.on_press_callback: self.on_press_callback()
        
        xi, xo, hz = self.get_x_pos(self.in_point), self.get_x_pos(self.out_point), 25
        if abs(e.x-xi) < hz and abs(e.x-xo) < hz: self.active_handle = 'in' if e.x < (xi+xo)/2 else 'out'
        elif abs(e.x-xi) < hz: self.active_handle = 'in'
        elif abs(e.x-xo) < hz: self.active_handle = 'out'
        else: self.active_handle = None

        # 핸들 클릭 시 프리뷰(재생 헤드) 이동 동기화
        if self.active_handle == 'in':
            self.play_head = self.in_point
        elif self.active_handle == 'out':
            self.play_head = self.out_point
        else:
            self.play_head = self.get_ratio_from_x(e.x)
        
        # [수정] 재생 중지 직후 즉시 락을 요청하면 충돌(멈춤)이 발생할 수 있으므로
        # 아주 짧은 지연(50ms)을 두고 프리뷰 업데이트를 요청합니다.
        # 이렇게 하면 재생 스레드가 락을 해제할 시간을 벌어줍니다.
        self.after(50, lambda: self.trigger_callback(False))
        self.draw()
    
    def on_drag(self, e):
        v, gap = self.get_ratio_from_x(e.x), 1.0/max(1, self.duration*self.fps)
        if self.active_handle == 'in': 
            if v <= self.out_point - gap: 
                self.in_point = v
                self.play_head = self.in_point # 드래그 중 프리뷰 동기화
        elif self.active_handle == 'out':
            if v >= self.in_point + gap: 
                self.out_point = v
                self.play_head = self.out_point # 드래그 중 프리뷰 동기화
        else: self.play_head = v
        self.draw(); self.trigger_callback(True)
    
    def on_release(self, e): 
        self.active_handle = None; self.trigger_callback(False); self.draw()
        # [복구] 조작 종료 시 콜백 호출
        if self.on_release_callback: self.on_release_callback()
    
    def trigger_callback(self, fast=False):
        # [수정] 스로틀링(Throttling) 로직 적용
        # 드래그(fast=True) 중일 때 너무 잦은 업데이트 방지 (시스템 다운 방지)
        if fast:
            current_time = time.time()
            if current_time - self.last_update_time < self.update_interval:
                return # 너무 빠르면 무시
            self.last_update_time = current_time

        if self.on_change_callback: 
            self.on_change_callback(self.in_point*self.duration, self.out_point*self.duration, self.play_head*self.duration, fast)

    def update_points(self, start, end, duration, play_head=None, fps=24):
        self.duration, self.fps = max(0.01, duration), fps
        self.in_point = max(0.0, min(1.0, start / self.duration))
        self.out_point = max(0.0, min(1.0, end / self.duration))
        if play_head is not None: 
            self.play_head = max(0.0, min(1.0, play_head / self.duration))
        self.draw()
    
    def reset_selection(self): self.in_point, self.out_point, self.play_head = 0.0, 1.0, 0.0; self.draw(); self.trigger_callback()

# -------------------------------------------------------------------------
# 일괄 수정 팝업 윈도우 UI (Bulk Edit Window)
# -------------------------------------------------------------------------
class BulkEditWindow(ctk.CTkToplevel):
    """메인 윈도우의 옵션 패널 디자인을 그대로 가져온 일괄 수정 팝업 창"""
    def __init__(self, master, indices, **kwargs):
        super().__init__(master, **kwargs)
        self.app = getattr(master, 'app', master)
        self.indices = indices
        self.title("대기열 일괄 옵션 수정"); 
        
        # 윈도우 크기 및 위치 계산 (부모 창 중앙 정렬)
        w, h = 1000, 300
        
        # 위치 계산 전 부모 윈도우 정보 갱신
        master.update_idletasks()
        
        try:
            # 부모 창(QueueWindow)의 위치와 크기 정보를 가져옴
            parent_x = master.winfo_rootx()
            parent_y = master.winfo_rooty()
            parent_w = master.winfo_width()
            parent_h = master.winfo_height()
            
            # 부모 창의 정중앙 좌표 계산
            x = parent_x + (parent_w - w) // 2
            y = parent_y + (parent_h - h) // 2
            
            # 화면 밖으로 나가지 않도록 보정 (선택 사항이나 안전을 위해)
            self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        except:
            # 실패 시 화면 중앙 배치
            try:
                screen_w = self.winfo_screenwidth()
                screen_h = self.winfo_screenheight()
                x = (screen_w - w) // 2
                y = (screen_h - h) // 2
                self.geometry(f"{w}x{h}+{x}+{y}")
            except:
                self.geometry(f"{w}x{h}")
            
        self.resizable(False, False)
        self.configure(fg_color="#2b2b2b")
        
        # 메인 컨테이너
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(padx=10, pady=30, fill="both", expand=True)
        
        # 상단 타이틀
        ctk.CTkLabel(container, text=f"선택된 총 {len(indices)}개 항목 일괄 수정", font=("Arial", 18, "bold")).pack(pady=(0, 20))
        
        # 옵션 패널 레이아웃
        options_row = ctk.CTkFrame(container, fg_color="transparent")
        options_row.pack(fill="x", pady=5)
        
        # 1. 품질 설정
        quality_frame = ctk.CTkFrame(options_row, fg_color="#2b2b2b", corner_radius=8)
        quality_frame.pack(side="left", fill="both", expand=True, padx=5)
        
        self.width_var = ctk.StringVar(value=const.DEFAULT_WIDTH)
        self.combo_width = ctk.CTkComboBox(quality_frame, values=const.RESOLUTIONS, width=95, variable=self.width_var)
        self.combo_width.pack(side="left", padx=10, pady=10)
        
        self.fps_val_var = ctk.DoubleVar(value=const.DEFAULT_FPS)
        self.fps_slider = ctk.CTkSlider(quality_frame, from_=const.FPS_OPTIONS[0], to=const.FPS_OPTIONS[1], width=140, variable=self.fps_val_var, command=self._sync_fps_entry)
        self.fps_slider.pack(side="left", padx=5)
        
        self.fps_str_var = ctk.StringVar(value=str(const.DEFAULT_FPS))
        self.entry_fps = ctk.CTkEntry(quality_frame, width=50, textvariable=self.fps_str_var)
        self.entry_fps.pack(side="left", padx=5)
        self.entry_fps.bind("<KeyRelease>", self._sync_fps_slider)
        self.label_fps_unit = ctk.CTkLabel(quality_frame, text="FPS", font=("Arial", 11))
        self.label_fps_unit.pack(side="left", padx=(0, 10))

        # 2. 내보내기 설정
        export_frame = ctk.CTkFrame(options_row, fg_color="#2b2b2b", corner_radius=8)
        export_frame.pack(side="left", fill="both", expand=True, padx=5)
        
        ctk.CTkLabel(export_frame, text="Export Format:", font=("Arial", 11)).pack(side="left", padx=(10, 2))
        self.format_var = ctk.StringVar(value=const.DEFAULT_EXPORT_FORMAT)
        self.combo_format = ctk.CTkComboBox(export_frame, values=const.EXPORT_FORMATS, width=110, variable=self.format_var, command=self._update_ui_visibility, state="readonly")
        self.combo_format.pack(side="left", padx=5, pady=10)
        
        self.dynamic_opt_frame = ctk.CTkFrame(export_frame, fg_color="transparent")
        self.dynamic_opt_frame.pack(side="left", fill="both", expand=True)
        
        # Alpha
        self.alpha_var = ctk.BooleanVar(value=True)
        self.check_alpha = ctk.CTkCheckBox(self.dynamic_opt_frame, text="Alpha", variable=self.alpha_var)
        
        # 확장자 포맷
        self.seq_format_var = ctk.StringVar(value=const.DEFAULT_SEQ_FORMAT)
        self.combo_seq_format = ctk.CTkComboBox(self.dynamic_opt_frame, values=const.SEQUENCE_FORMATS, width=85, variable=self.seq_format_var, state="readonly")
        
        # Bitrate
        self.bitrate_container = ctk.CTkFrame(self.dynamic_opt_frame, fg_color="transparent")
        ctk.CTkLabel(self.bitrate_container, text="Bitrate:", font=("Arial", 11)).pack(side="left", padx=(5, 2))
        self.bitrate_var = ctk.StringVar(value="2")
        self.entry_bitrate = ctk.CTkEntry(self.bitrate_container, width=40, textvariable=self.bitrate_var)
        self.entry_bitrate.pack(side="left", padx=2)
        ctk.CTkLabel(self.bitrate_container, text="Mbps", font=("Arial", 10), text_color="gray").pack(side="left")
        
        # Loop
        self.loop_container = ctk.CTkFrame(self.dynamic_opt_frame, fg_color="transparent")
        ctk.CTkLabel(self.loop_container, text="반복:", font=("Arial", 11)).pack(side="left", padx=(5, 2))
        self.loop_var = ctk.StringVar(value="0")
        self.entry_loop = ctk.CTkEntry(self.loop_container, width=40, textvariable=self.loop_var)
        self.entry_loop.pack(side="left", padx=5)

        # 3. 색보정 설정 (비활성화 고정)
        etc_frame = ctk.CTkFrame(options_row, fg_color="#2b2b2b", corner_radius=8)
        etc_frame.pack(side="left", fill="y", padx=5)
        self.dummy_color_var = ctk.BooleanVar(value=False)
        self.check_color = ctk.CTkSwitch(etc_frame, text="색보정", variable=self.dummy_color_var, state="disabled")
        self.check_color.pack(side="right", padx=15, pady=10)
        
        # 안내 라벨
        ctk.CTkLabel(container, text="※ 타임라인 인앤아웃, 크롭, 색보정 설정은 각 항목의 기존 값을 그대로 유지합니다.", text_color="#aa5a5a", font=("Arial", 12)).pack(pady=5)

        # 초기 가시성 업데이트
        self._update_ui_visibility(self.format_var.get())
        
        # 하단 실행 버튼
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(20, 0))
        
        # [수정] 취소 버튼 커맨드 변경 (로그 출력 후 닫기)
        ctk.CTkButton(btn_frame, text="취소", fg_color="#555555", height=45, width=120, command=self.cancel).pack(side="right", padx=5)
        ctk.CTkButton(btn_frame, text="설정 일괄 적용", fg_color="#db6600", height=45, width=180, font=("Arial", 13, "bold"), command=self.apply_settings).pack(side="right", padx=5)
        
        self._update_ui_visibility(self.format_var.get())
        self.grab_set()

    def _sync_fps_entry(self, val): self.fps_str_var.set(str(int(val)))
    def _sync_fps_slider(self, e):
        try:
            val = int(self.fps_str_var.get())
            if const.FPS_OPTIONS[0] <= val <= const.FPS_OPTIONS[1]: self.fps_slider.set(val)
        except: pass

    def _update_ui_visibility(self, choice):
        self.check_alpha.pack_forget(); self.combo_seq_format.pack_forget()
        self.bitrate_container.pack_forget(); self.loop_container.pack_forget()
        
        fps_state = "disabled" if choice == "Thumbnail" else "normal"
        self.fps_slider.configure(state=fps_state); self.entry_fps.configure(state=fps_state)
        self.label_fps_unit.configure(text_color="gray" if fps_state == "disabled" else "white")
        self.check_alpha.configure(state="normal")
        
        if choice == "GIF":
            self.check_alpha.pack(side="left", padx=10); self.loop_container.pack(side="left", padx=5)
        elif choice == "WebM":
            self.check_alpha.pack(side="left", padx=10); self.bitrate_container.pack(side="left", padx=5)
        elif choice == "WebP":
            self.check_alpha.pack(side="left", padx=10); self.loop_container.pack(side="left", padx=5)
        elif choice == "MP4":
            self.bitrate_container.pack(side="left", padx=10); self.check_alpha.deselect(); self.check_alpha.configure(state="disabled")
        elif choice == "Sequence":
            self.combo_seq_format.pack(side="left", padx=5); self.check_alpha.pack(side="left", padx=10)
        elif choice == "Thumbnail":
            self.combo_seq_format.pack(side="left", padx=5); self.seq_format_var.set("JPG")

    def cancel(self):
        """취소 버튼 동작: 로그 출력 후 창 닫기"""
        if self.app.queue_window and self.app.queue_window.winfo_exists():
            self.app.queue_window.append_log("일괄 수정 취소됨")
        self.destroy()

    def apply_settings(self):
        try:
            settings = {
                "fps": int(self.fps_str_var.get()),
                "width": int(self.width_var.get()),
                "export_format": self.format_var.get(),
                "transparent": self.alpha_var.get(),
                "loop": int(self.loop_var.get() or 0),
                "bitrate": self.bitrate_var.get(),
                "seq_format": self.seq_format_var.get()
            }
            self.app.bulk_update_selected_items(self.indices, settings)
            
            # [수정] 적용 성공 로그 출력
            if self.app.queue_window and self.app.queue_window.winfo_exists():
                self.app.queue_window.append_log(f"일괄 수정 적용 완료: 총 {len(self.indices)}개 항목")
            
            self.destroy()
        except ValueError:
            tk.messagebox.showerror("오류", "입력값이 올바르지 않습니다. 숫자 형식을 확인해주세요.")

# -------------------------------------------------------------------------
# 대기열 목록 UI (Queue Window)
# -------------------------------------------------------------------------
class QueueWindow(ctk.CTkToplevel):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.title("변환 대기열 목록"); self.geometry("1000x750"); self.configure(fg_color="#1a1a1a")
        self.app = master
        self.check_vars = {} 
        self.job_frames = [] 
        self.last_checked_index = None # Shift 다중 선택용 마지막 체크 인덱스
        
        # 대기열 목록 자동 로그를 위해 초기 항목 개수 저장
        # 창이 열리는 시점의 큐 개수를 저장해두고, 이후 추가되는 항목만 로그에 찍음
        self.last_queue_len = len(self.app.queue)
        
        self.setup_ui()
        self.update_list()

    def setup_ui(self):
        bg_dark = "#1a1a1a"
        self.main_frame = ctk.CTkFrame(self, corner_radius=10, fg_color="#1a1a1a")
        self.main_frame.pack(padx=20, pady=20, fill="both", expand=True)

        # 상단 툴바
        toolbar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=(10, 5))

        self.all_check_var = ctk.BooleanVar(value=True)
        self.btn_select_all = ctk.CTkCheckBox(toolbar, text="전체 선택", variable=self.all_check_var, command=self.toggle_all_selection, width=100)
        self.btn_select_all.pack(side="left")
        
        self.opt_btn = ctk.CTkButton(toolbar, text="옵션 ☰", width=80, fg_color="#333333", command=self.show_options_menu)
        self.opt_btn.pack(side="right")
        
        self.options_menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#ffffff", font=("Arial", 11), activebackground="#3b8ed0")
        self.options_menu.add_command(label="내보내기 (JSON)", command=self.app.export_queue_to_json)
        self.options_menu.add_command(label="가져오기 (JSON)", command=self.app.import_queue_from_json)

        # 스크롤 가능한 대기열 목록
        self.scroll_frame = ctk.CTkScrollableFrame(self.main_frame, fg_color="#1a1a1a")
        self.scroll_frame.pack(padx=0, pady=0, fill="both", expand=True)
        
        # [터치패드 스크롤 문제 해결] 마우스 휠 이벤트 바인딩
        # Canvas 객체에 직접 바인딩하여 모든 OS 및 터치패드 환경 지원
        # MouseEnter/Leave 이벤트를 통해 마우스가 윈도우 내부에 있을 때만 바인딩
        self.scroll_frame.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.scroll_frame.bind_all("<Button-4>", self._on_mouse_wheel)
        self.scroll_frame.bind_all("<Button-5>", self._on_mouse_wheel)

        # 창이 닫힐 때 언바인딩 처리 (메모리 누수 방지)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # 하단 컨트롤 버튼 프레임
        self.bottom_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.bottom_frame.pack(fill="x", padx=10, pady=(10, 5)) 
        
        self.left_btn_frame = ctk.CTkFrame(self.bottom_frame, fg_color="transparent")
        self.left_btn_frame.pack(side="left", fill="x", expand=True)
        
        self.control_btn_frame = ctk.CTkFrame(self.left_btn_frame, fg_color="transparent")

        self.btn_clear_queue = ctk.CTkButton(self.left_btn_frame, text="대기열 비우기", fg_color="#555555", width=100, command=self.app.clear_queue)
        self.btn_clear_queue.pack(side="left", padx=5)

        self.btn_remove = ctk.CTkButton(self.left_btn_frame, text="선택 삭제", fg_color="#aa5a5a", width=100, command=self.remove_selected)
        self.btn_remove.pack(side="left", padx=5)

        self.btn_edit_selected = ctk.CTkButton(self.left_btn_frame, text="선택 수정", fg_color="#3b8ed0", width=100, command=self.edit_selected)
        self.btn_edit_selected.pack(side="left", padx=5)
        
        self.btn_batch = ctk.CTkButton(self.left_btn_frame, text="일괄 변환 시작", fg_color="#2d9d78", command=self.handle_batch_btn_click)
        self.btn_batch.pack(side="left", fill="x", expand=True, padx=5)
        
        self.btn_batch_all = None

        self.btn_open_folder = ctk.CTkButton(self.bottom_frame, text="📁", width=40, fg_color="#555555", command=lambda: self.app.open_directory(self.app.last_save_dir))
        self.btn_open_folder.pack(side="right", padx=5)

        # -------------------------------------------------------------------------
        # 시스템 로그 창 (System Log)
        # -------------------------------------------------------------------------
        self.log_container = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.log_container.pack(fill="x", padx=10, pady=(5, 10))
        
        log_header = ctk.CTkFrame(self.log_container, fg_color="transparent")
        log_header.pack(fill="x")
        
        # 로그 접기/펼치기 버튼
        self.log_visible = True
        self.btn_toggle_log = ctk.CTkButton(log_header, text="▼", width=25, height=20, fg_color="transparent", text_color="#aaaaaa", hover_color="#333333", command=self.toggle_log_visibility)
        self.btn_toggle_log.pack(side="left")

        self.log_label = ctk.CTkLabel(log_header, text="System Log", font=("Arial", 11, "bold"), anchor="w", text_color="gray")
        self.log_label.pack(side="left", padx=(5, 0))
        
        self.btn_clear_log = ctk.CTkButton(log_header, text="지우기", width=50, height=20, fg_color="#333333", font=("Arial", 10), command=self.clear_log)
        self.btn_clear_log.pack(side="right")

        self.log_frame = ctk.CTkFrame(self.log_container, fg_color="transparent")
        self.log_frame.pack(fill="x", pady=(5, 0))

        self.log_textbox = ctk.CTkTextbox(self.log_frame, height=120, fg_color="#222222", text_color="#dddddd", font=("Courier", 11))
        self.log_textbox.pack(fill="x")
        self.log_textbox.configure(state="disabled")

    def toggle_log_visibility(self):
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_frame.pack(fill="x", pady=(5, 0))
            self.btn_toggle_log.configure(text="▼")
        else:
            self.log_frame.pack_forget()
            self.btn_toggle_log.configure(text="▶")

    def on_close(self):
        try:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")
        except: pass
        self.destroy()

    def _on_mouse_wheel(self, event):
        # [수정] 터치패드 스크롤 문제 해결 (소수점 delta 처리 및 범위 체크)
        try:
            # 윈도우 상태 확인 (최소화 여부 등)
            if self.state() != "normal": return
            
            # 마우스가 스크롤 프레임 영역 안에 있는지 확인
            x1 = self.scroll_frame.winfo_rootx()
            y1 = self.scroll_frame.winfo_rooty()
            x2 = x1 + self.scroll_frame.winfo_width()
            y2 = y1 + self.scroll_frame.winfo_height()
            
            if not (x1 <= event.x_root <= x2 and y1 <= event.y_root <= y2):
                return

            if sys.platform == "darwin":
                delta = event.delta
                if delta == 0: return
                
                # macOS 터치패드 스크롤 감도 개선
                # delta 값이 작아도 최소 1단위 스크롤 보장
                if abs(delta) < 1:
                     move = -1 if delta > 0 else 1 
                else:
                     move = int(-1 * delta)
                
                self.scroll_frame._parent_canvas.yview_scroll(move, "units")
            
            elif sys.platform == "win32":
                self.scroll_frame._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            
            else: # Linux
                if event.num == 4: self.scroll_frame._parent_canvas.yview_scroll(-1, "units")
                elif event.num == 5: self.scroll_frame._parent_canvas.yview_scroll(1, "units")
        except: pass

    def handle_batch_btn_click(self):
        if not self.app.is_batch_converting:
            self.append_log("일괄 변환 시작 요청됨.")
            self.app.start_batch_conversion()
        else:
            self.append_log("일괄 변환 중단 요청됨.")
            self.after(50, self._confirm_batch_cancel)

    def _confirm_batch_cancel(self):
        auto_paused = False
        if not self.app.batch_paused:
            self.app.toggle_batch_pause()
            auto_paused = True

        if tk.messagebox.askyesno("일괄 변환 중단", "진행 중인 모든 변환 작업을 중단하고 취소하시겠습니까?"):
            self.app.cancel_conversion(force=True)
        else:
            if auto_paused and self.app.batch_paused:
                self.app.toggle_batch_pause()

    def show_options_menu(self): self.options_menu.post(self.opt_btn.winfo_rootx(), self.opt_btn.winfo_rooty() + 35)

    def toggle_all_selection(self):
        state = self.all_check_var.get()
        for var in self.check_vars.values(): var.set(state)

    # 하나라도 체크가 해제되면 "전체 선택" 체크박스를 끄기 위한 동기화 로직
    def _sync_select_all_checkbox(self):
        if not self.check_vars:
            self.all_check_var.set(False)
            return
        # 모든 항목이 True인지 검사
        all_checked = all(var.get() for var in self.check_vars.values())
        self.all_check_var.set(all_checked)

    def on_checkbox_click(self, index):
        """체크박스 클릭 시 마지막 선택 인덱스 저장"""
        self.last_checked_index = index
        self._sync_select_all_checkbox()

    def on_shift_click_checkbox(self, index):
        """Shift+Click 시 범위 선택 처리"""
        if self.last_checked_index is not None:
            start = min(self.last_checked_index, index)
            end = max(self.last_checked_index, index)
            target_state = self.check_vars[self.last_checked_index].get() # 이전 상태를 따라감
            
            # 범위 내의 모든 체크박스 상태 변경
            for i in range(start, end + 1):
                if i in self.check_vars:
                    self.check_vars[i].set(target_state)
        
        self.last_checked_index = index
        self._sync_select_all_checkbox()

    def remove_selected(self):
        indices = [i for i, v in self.check_vars.items() if v.get()]
        if not indices: return
        if tk.messagebox.askyesno("삭제 확인", f"{len(indices)}개의 항목을 삭제하시겠습니까?"):
            removed_items = []
            for i in sorted(indices, reverse=True):
                if i < len(self.app.queue):
                    removed_items.append(self.app.queue[i]['filename'])
                    self.app.remove_from_queue(i)
            
            for name in removed_items:
                self.append_log(f"항목 삭제: {name}")
            self.append_log(f"선택된 {len(removed_items)}개 항목이 삭제되었습니다.")
            self.last_checked_index = None # 인덱스가 바뀌므로 초기화

    def edit_selected(self):
        indices = [i for i, v in self.check_vars.items() if v.get()]
        if not indices: return
        BulkEditWindow(self.app, indices)

    def update_list(self):
        try:
            if not self.winfo_exists(): return

            target_text = "일괄 변환 취소" if self.app.is_batch_converting else "일괄 변환 시작"
            target_color = "#764ba2" if self.app.is_batch_converting else "#4b6ca2"
            
            if self.btn_batch.cget("text") != target_text:
                self.btn_batch.configure(text=target_text, fg_color=target_color)
            
            state_mode = "disabled" if self.app.is_batch_converting else "normal"
            self.btn_select_all.configure(state=state_mode)
            self.btn_remove.configure(state=state_mode)
            self.btn_edit_selected.configure(state=state_mode)
            self.btn_clear_queue.configure(state=state_mode)

            if not self.app.queue:
                for widget in self.scroll_frame.winfo_children(): widget.destroy()
                self.job_frames = []
                self.check_vars = {}
                ctk.CTkLabel(self.scroll_frame, text="대기열이 비어 있습니다.", text_color="gray").pack(pady=50)
                return
            
            for child in self.scroll_frame.winfo_children():
                if isinstance(child, ctk.CTkLabel) and child.cget("text") == "대기열이 비어 있습니다.":
                    child.destroy()

            while len(self.job_frames) > len(self.app.queue):
                frame_data = self.job_frames.pop()
                if frame_data['frame'].winfo_exists():
                    frame_data['frame'].destroy()

            new_check_vars = {}
            self.app.job_widgets = {}

            # [로그 자동 출력] 큐 길이 변화 감지
            # 현재 큐 길이가 마지막으로 확인한 길이보다 크다면, 새로운 항목이 추가된 것임
            current_len = len(self.app.queue)
            if current_len > self.last_queue_len:
                new_items = self.app.queue[self.last_queue_len:current_len]
                for item in new_items:
                    self.append_log(f"항목 추가됨: {item['filename']} [{item.get('export_format', 'Unknown')}]")
            
            # 길이 동기화
            self.last_queue_len = current_len

            for i, job in enumerate(self.app.queue):
                if not self.winfo_exists(): break
                self._sync_job_item(i, job, new_check_vars)
            
            self.check_vars = new_check_vars
            self.scroll_frame.update_idletasks()
        except Exception as e:
            print(f"Error updating list: {e}")

    def _sync_job_item(self, i, job, new_vars_map):
        try:
            if not self.winfo_exists(): return

            is_edit = (self.app.editing_index == i)
            status_text = job.get('status', '대기')
            is_done = (status_text == "완료")
            border_color = "#db6600" if is_edit else "#444444"

            if i in self.check_vars:
                new_vars_map[i] = self.check_vars[i]
            else:
                new_vars_map[i] = ctk.BooleanVar(value=not is_done)

            if i < len(self.job_frames):
                data = self.job_frames[i]
                if not data['frame'].winfo_exists(): return

                data['frame'].configure(border_color=border_color)
                data['num_label'].configure(text=f"{i+1}")
                data['name_label'].configure(text=job['filename'])
                data['check_box'].configure(variable=new_vars_map[i])
                
                # 체크박스 이벤트 바인딩 갱신
                data['check_box'].configure(command=lambda idx=i: self.on_checkbox_click(idx))
                data['check_box'].bind("<Shift-Button-1>", lambda e, idx=i: self.on_shift_click_checkbox(idx), add="+")

                if job.get('thumb_img'):
                    img = ctk.CTkImage(light_image=job['thumb_img'], dark_image=job['thumb_img'], size=(80, 45))
                    data['thumb_label'].configure(image=img)
                    data['thumb_label']._image = img

                details = [f"{job.get('width', 1280)}px"]
                if not job.get('is_sequence'):
                    fps = job.get('fps', 24)
                    start_f = int(round(job.get('start', 0) * fps))
                    end_time = job.get('end', 0)
                    if isinstance(end_time, (int, float)) and end_time != -1:
                        end_f = int(round(end_time * fps))
                        details.append(f"{start_f}-{end_f}({end_f - start_f + 1})")
                    else: details.append(f"{start_f}-??")
                
                details.append(f"{job.get('fps', 24)} fps")
                export_fmt = job.get('export_format', 'GIF')
                
                if export_fmt == "Thumbnail":
                    details.append(f"{export_fmt} ({job.get('seq_format', 'JPG')})")
                else:
                    details.append(export_fmt)

                if export_fmt in ["GIF", "WebP"]:
                    l_cnt = job.get('loop', 0)
                    details.append(f"Loop{'' if l_cnt == 0 else '(%d)' % l_cnt}")

                # JPG, MP4는 UI 체크박스와 상관없이 Alpha 강제 OFF 처리
                seq_fmt_check = job.get('seq_format', 'JPG').upper()
                supports_alpha = True
                if export_fmt == "MP4" or (export_fmt in ["Sequence", "Thumbnail"] and seq_fmt_check in ["JPG", "JPEG"]):
                    supports_alpha = False

                if job.get('transparent') and supports_alpha: details.append("Alpha")
                if job.get('crop_enabled'): details.append("Crop")
                if job.get('color_settings', {}).get('color_correction', False): details.append(f"CC")
                
                data['detail_label'].configure(text=" / ".join(details))
                
                status_color = {"완료": "#3b8ed0", "진행중": "#96ff55", "파일없음": "#ff8644", "취소됨": "#ff4444"}.get(status_text, "#aaaaaa")
                if "실패" in status_text: status_color = "#e67e22"
                data['status_label'].configure(text=status_text, text_color=status_color)
                
                is_frozen = self.app.is_batch_converting
                data['check_box'].configure(state="disabled" if is_frozen else "normal")
                data['btn_del'].configure(state="disabled" if is_frozen else "normal")
                btn_edit_col = "#db6600" if is_edit else "#3b8ed0"
                data['btn_edit'].configure(
                    text="수정중" if is_edit else "수정", 
                    fg_color=btn_edit_col,
                    state="disabled" if is_edit or status_text == "파일없음" or is_frozen or self.app.is_loading else "normal"
                )
                
                data['p_bar'].configure(progress_color="#3b8ed0" if is_done else "#96ff55")
                data['p_bar'].set(1.0 if is_done else job.get('progress', 0))
                self.app.job_widgets[i] = {'status_label': data['status_label'], 'progress_bar': data['p_bar']}
                return
        
            item_frame = ctk.CTkFrame(self.scroll_frame, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color=border_color)
            item_frame.pack(fill="x", pady=5, padx=5)

            chk = ctk.CTkCheckBox(item_frame, text="", variable=new_vars_map[i] , width=20, state="disabled" if self.app.is_batch_converting else "normal")
            chk.pack(side="left", padx=(10, 0))
            chk.configure(command=lambda idx=i: self.on_checkbox_click(idx))
            chk.bind("<Shift-Button-1>", lambda e, idx=i: self.on_shift_click_checkbox(idx), add="+")

            num_lbl = ctk.CTkLabel(item_frame, text=f"{i+1}", font=("Arial", 12, "bold"), width=30, text_color="white")
            num_lbl.pack(side="left", padx=(10, 0))

            thumb_lbl = ctk.CTkLabel(item_frame, text="", width=80, height=45)
            thumb_lbl.pack(side="left", padx=10, pady=5)
            if job.get('thumb_img'):
                img = ctk.CTkImage(light_image=job['thumb_img'], dark_image=job['thumb_img'], size=(80, 45))
                thumb_lbl.configure(image=img)
                thumb_lbl._image = img
            
            content = ctk.CTkFrame(item_frame, fg_color="transparent")
            content.pack(side="left", padx=5, pady=(5, 5), fill="both", expand=True)
            info_row = ctk.CTkFrame(content, fg_color="transparent")
            info_row.pack(fill="x", padx=5, pady=(5, 5))
            
            name_lbl = ctk.CTkLabel(info_row, text=f"{job['filename']}", font=("Arial", 12, "bold"), text_color="white")
            name_lbl.pack(side="left")

            det_lbl = ctk.CTkLabel(info_row, text="", font=("Arial", 10), text_color="#aaaaaa")
            det_lbl.pack(side="left", padx=15)

            stat_lbl = ctk.CTkLabel(info_row, text=status_text, font=("Arial", 10))
            stat_lbl.pack(side="right", padx=5)

            btn_del = ctk.CTkButton(info_row, text="삭제", width=40, height=24, fg_color="#444444", command=lambda idx=i: self.app.remove_from_queue(idx))
            btn_del.pack(side="right", padx=2)
        
            btn_edit = ctk.CTkButton(info_row, text="수정", width=40, height=24, command=lambda idx=i: self.app.load_job_for_edit(idx))
            btn_edit.pack(side="right", padx=2)

            ctk.CTkButton(info_row, text="📁", width=30, height=24, fg_color="#555555", 
                    command=lambda p=job['path'], s=job.get('sequence_paths'): self.app.open_source_folder(p, s)).pack(side="right", padx=2)
            
            p_bar = ctk.CTkProgressBar(content, height=4, fg_color="#111111", progress_color="#3b8ed0" if is_done else "#96ff55")
            p_bar.pack(fill="x", padx=5, pady=(2, 4))
            
            self.job_frames.append({
                'frame': item_frame, 'check_box': chk, 'num_label': num_lbl, 'thumb_label': thumb_lbl,
                'name_label': name_lbl, 'detail_label': det_lbl, 'status_label': stat_lbl,
                'btn_del': btn_del, 'btn_edit': btn_edit, 'p_bar': p_bar
            })
            self.app.job_widgets[i] = {'status_label': stat_lbl, 'progress_bar': p_bar} 
            self._sync_job_item(i, job, new_vars_map)

        except Exception as e:
            print(f"Error drawing job item {i}: {e}")

    def fast_remove_item(self, index):
        self.update_list()

    def append_log(self, message):
        """로그 텍스트 박스에 메시지 (외부 호출용)"""
        if hasattr(self, 'log_textbox') and self.winfo_exists():
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log_textbox.configure(state="normal")
            self.log_textbox.insert("end", f"[{timestamp}] {message}\n")
            self.log_textbox.see("end")
            self.log_textbox.configure(state="disabled")

    def clear_log(self):
        """로그 창 비우기"""
        if hasattr(self, 'log_textbox') and self.winfo_exists():
            self.log_textbox.configure(state="normal")
            self.log_textbox.delete("1.0", "end")
            self.log_textbox.configure(state="disabled")