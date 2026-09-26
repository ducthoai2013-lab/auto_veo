"""Màu và QSS theo ảnh chụp Veo3 Go (ước lượng bằng mắt; chỉnh lại bằng công cụ chấm màu nếu cần)."""

PRIMARY = "#6C63F5"       # nút BẮT ĐẦU TẠO VIDEO
PRIMARY_HOVER = "#5B52E6"
TEAL = "#1CB5D0"          # nút MUA GÓI CƯỚC
TEAL_HOVER = "#12A2BC"
GREEN = "#22C55E"
INK = "#1F2937"
MUTED = "#9CA3AF"
BORDER = "#D9DCE1"
BG = "#F0F1F3"
PANEL = "#FFFFFF"
FIELD = "#F3F4F6"

QSS = f"""
* {{ font-family: "Segoe UI", "Tahoma", sans-serif; font-size: 13px; color: {INK}; }}
QMainWindow, QDialog {{ background: {BG}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QStatusBar QLabel {{ padding: 0 6px; }}

/* tab bên trái */
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: #E9EAED; border: 1px solid {BORDER}; border-bottom: none; padding: 6px 12px;
    margin-right: 2px; border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: {PANEL}; font-weight: 600; }}

QPlainTextEdit, QLineEdit {{ background: {FIELD}; border: none; padding: 6px; selection-background-color: {PRIMARY}; }}
QPlainTextEdit {{ color: {INK}; }}
QListWidget {{ background: {FIELD}; border: none; }}

/* nút chính */
QPushButton#startBtn {{ background: {PRIMARY}; color: white; border: none; border-radius: 4px;
    font-weight: 700; font-size: 14px; padding: 12px 18px; }}
QPushButton#startBtn:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#startBtn:disabled {{ background: #B9B6F0; }}
QPushButton#buyBtn {{ background: {TEAL}; color: white; border: none; border-radius: 4px;
    font-weight: 700; font-size: 14px; padding: 12px 18px; }}
QPushButton#buyBtn:hover {{ background: {TEAL_HOVER}; }}
QToolButton#chip, QPushButton#chip {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 8px 10px; font-weight: 600; }}
QToolButton#chip::menu-indicator {{ image: none; }}

/* nhóm chọn tỷ lệ / thư mục */
QFrame#card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel#cardTitle {{ color: {INK}; font-size: 12px; }}
QComboBox {{ background: {FIELD}; border: 1px solid {BORDER}; border-radius: 12px; padding: 6px 12px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}

QFrame#charColumn {{ border: 1px dashed #C7CBD1; border-radius: 8px; background: {PANEL}; }}

/* thanh công cụ bên phải */
QPushButton[tb="true"] {{ border: none; border-radius: 6px; padding: 8px 12px; font-weight: 600; }}
QPushButton#tbMerge {{ background: #E0EDFF; color: #2563EB; }}
QPushButton#tbRetry {{ background: #D5F3F1; color: #0F8A85; }}
QPushButton#tbRetryErr {{ background: #E3E6FB; color: #4F46E5; }}
QPushButton#tbLast {{ background: #D5F3F1; color: #0F8A85; }}
QPushButton#tbClear {{ background: #FDE2E2; color: #DC2626; }}
QPushButton#tbHelp {{ background: #E0EDFF; color: #0068FF; }}
QPushButton[tb="true"]:hover {{ border: 1px solid rgba(0,0,0,0.15); }}
QPushButton[tb="true"]:disabled {{ opacity: 0.5; color: #9CA3AF; }}

/* khung kết quả / hướng dẫn */
QFrame#results {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#guide {{ background: {PANEL}; border: 1px dashed {BORDER}; border-radius: 8px; }}
QLabel#guideTitle {{ font-size: 15px; font-weight: 700; }}
QLabel#guideHead {{ font-weight: 700; background: {PANEL}; border: 1px solid {BORDER}; border-radius: 5px; padding: 3px 8px; }}
QLabel#guideRow {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 5px; padding: 3px 8px; }}
QLabel#emptyMsg {{ color: {MUTED}; }}
QFrame#jobCard {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QFrame#jobCard[state="failed"] {{ border-color: #F5B5B5; background: #FFF7F7; }}
QFrame#jobCard[state="completed"] {{ border-color: #B7E4C7; }}
QLabel#jobPrompt {{ color: #4B5563; }}
QLabel#jobStatus {{ font-weight: 600; }}
QProgressBar {{ border: none; border-radius: 5px; background: #E5E7EB; text-align: center; color: white; height: 14px; }}
QProgressBar::chunk {{ background: {GREEN}; border-radius: 5px; }}
QProgressBar#quotaBar {{ height: 18px; font-weight: 700; }}
QPushButton#linkBtn {{ background: transparent; border: none; color: #2563EB; padding: 2px 6px; }}
QPushButton#linkBtn:hover {{ text-decoration: underline; }}

QLabel#accTitle {{ color: #2563EB; font-size: 13px; }}
QFrame#account {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; }}
QLabel#accKey {{ font-weight: 700; }}
QLabel#accVal {{ color: #374151; }}
QLabel#offline {{ color: #B91C1C; font-weight: 600; }}
"""
