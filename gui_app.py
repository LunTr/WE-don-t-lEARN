import sys
import re
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse
from bs4 import BeautifulSoup
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QTabWidget, QGroupBox, QFormLayout, QListWidget, QListWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

# Reuse logic from main.py and report.py
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
}

def parse_cookie_header(cookie_header: str) -> Dict[str, str]:
    cookies: Dict[str, str] = {}
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        try:
            name, value = part.split("=", 1)
            cookies[name.strip()] = value.strip()
        except ValueError:
            continue
    return cookies

def extract_js_var(html: str, name: str) -> Optional[str]:
    quoted_match = re.search(rf"var\s+{re.escape(name)}\s*=\s*['\"](.*?)['\"]\s*;", html)
    if quoted_match: return quoted_match.group(1)
    raw_match = re.search(rf"var\s+{re.escape(name)}\s*=\s*([^;]+);", html)
    if raw_match: return raw_match.group(1).strip()
    return None

def extract_initial_scoid(html: str, page_url: str) -> Optional[str]:
    init_match = re.search(r"InitSco\(\s*['\"]([^'\"]+)['\"]", html)
    if init_match: return init_match.group(1)
    query = parse_qs(urlparse(page_url).query)
    sco_values = query.get("sco")
    if sco_values: return sco_values[0]
    return None

class WorkerThread(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, action, url, cookie_str):
        super().__init__()
        self.action = action
        self.url = url
        self.cookie_str = cookie_str

    def run(self):
        try:
            cookies = parse_cookie_header(self.cookie_str)
            session = requests.Session()
            session.headers.update(DEFAULT_HEADERS)
            session.cookies.update(cookies)

            if self.action == "extract":
                self.extract_logic(session)
            elif self.action == "report":
                self.report_logic(session)
        except Exception as e:
            self.error.emit(str(e))

    def extract_logic(self, session):
        resp = session.get(self.url, timeout=20)
        resp.raise_for_status()
        html = resp.content.decode(resp.apparent_encoding or "utf-8", errors="replace")
        
        userid = extract_js_var(html, "userid")
        courseid = extract_js_var(html, "courseid")
        scoid = extract_initial_scoid(html, self.url)

        if not (userid and courseid and scoid):
            raise ValueError("无法从页面提取必要参数(userid/courseid/scoid)，请检查是否登录或URL是否正确。")

        ajax_url = urljoin(self.url, f"../Ajax/SCO.aspx?uid={userid}")
        payload = {"action": "scoAddr", "cid": courseid, "scoid": scoid, "nocache": "0.1"}
        sco_resp = session.post(ajax_url, data=payload, headers={"Referer": self.url}, timeout=20)
        sco_resp.raise_for_status()
        sco_data = sco_resp.json()

        addr = str(sco_data.get("addr", "")).split("|", 1)[0].strip()
        iframe_url = urljoin(self.url, addr)
        iframe_resp = session.get(iframe_url, headers={"Referer": self.url}, timeout=20)
        iframe_resp.raise_for_status()
        iframe_html = iframe_resp.content.decode(iframe_resp.apparent_encoding or "utf-8", errors="replace")

        soup = BeautifulSoup(iframe_html, "lxml")
        results = []
        pure_answers = []
        
        # Filling and cfilling
        for node in soup.select("input[data-solution]"):
            solution = node.get('data-solution')
            filling_parent = node.find_parent(attrs={"data-controltype": "filling"})
            cfilling_parent = node.find_parent(attrs={"data-controltype": "cfilling"})
            
            if filling_parent or cfilling_parent:
                pure_answers.append(solution)
                ctype_name = "完形填空" if cfilling_parent else "填空位"
                results.append(f"[{ctype_name}] {solution}")
            else:
                results.append(f"[未知填空] {solution}")
        
        # Choice
        for choice in soup.select('div[data-controltype="choice"]'):
            sols = [opt.get_text(strip=True) for opt in choice.select('li[data-solution]')]
            if sols:
                results.append(f"[选择项] {' / '.join(sols)}")

        output = f"用户ID: {userid}\n课程ID: {courseid}\nSCO ID: {scoid}\n\n提取到以下答案:\n" + "\n".join(results)
        
        sep = "====PURE_ANSWERS_SEP===="
        self.finished.emit(output + sep + "\n".join(pure_answers))

    def report_logic(self, session):
        resp = session.get(self.url, timeout=20)
        report = [
            f"目标URL: {self.url}",
            f"最终URL: {resp.url}",
            f"状态码: {resp.status_code}",
            f"重定向: {'是' if resp.history else '否'}",
            f"内容类型: {resp.headers.get('Content-Type')}",
            f"HTML长度: {len(resp.content)}",
            f"包含 'data-solution': {'是' if b'data-solution' in resp.content else '否'}"
        ]
        self.finished.emit("\n".join(report))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WE don't lEARN GUI - 智慧树/WElearn 增强版")
        self.resize(950, 750)
        self.setStyleSheet("""
            * {
                font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif;
                font-size: 14px;
                color: #2c3e50;
            }
            QMainWindow {
                background-color: #f0f2f5;
            }
            QGroupBox {
                font-size: 15px;
                font-weight: bold;
                border: 1px solid #dcdde1;
                border-radius: 8px;
                background-color: #ffffff;
                margin-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: #34495e;
            }
            QPushButton {
                background-color: #3498db;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
            QPushButton:pressed {
                background-color: #1c598a;
            }
            QPushButton:disabled {
                background-color: #bdc3c7;
                color: #ecf0f1;
            }
            QPushButton#SaveBtn {
                background-color: #2ecc71;
            }
            QPushButton#SaveBtn:hover {
                background-color: #27ae60;
            }
            QLineEdit, QTextEdit {
                border: 1px solid #dcdde1;
                border-radius: 6px;
                padding: 8px;
                background-color: #ffffff;
                selection-background-color: #3498db;
                color: #2c3e50;
            }
            QLineEdit:focus, QTextEdit:focus {
                border: 1px solid #3498db;
            }
            QTabWidget::pane {
                border: 1px solid #dcdde1;
                border-radius: 8px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #ecf0f1;
                border: 1px solid #dcdde1;
                border-bottom-color: #dcdde1;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 8px 18px;
                margin-right: 4px;
                color: #7f8c8d;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                border-bottom-color: #ffffff;
                color: #3498db;
            }
            QTabBar::tab:hover:!selected {
                background: #dcdde1;
            }
            /* Scrollbar Style */
            QScrollBar:vertical {
                border: none;
                background: #f0f2f5;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #bdc3c7;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #95a5a6;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        self.init_ui()
        self.load_default_cookie()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Config Area
        config_group = QGroupBox("✨ 核心配置")
        config_layout = QVBoxLayout()
        config_layout.setContentsMargins(15, 20, 15, 15)
        config_layout.setSpacing(12)
        
        # URL Line
        url_layout = QHBoxLayout()
        url_label = QLabel("学习页面 URL:")
        url_label.setStyleSheet("font-weight: bold;")
        url_layout.addWidget(url_label)
        self.url_input = QLineEdit("https://welearn.sflep.com/student/StudyCourse.aspx?cid=584&classid=730891&sco=m-2-4-9")
        self.url_input.textChanged.connect(self.on_url_changed)
        url_layout.addWidget(self.url_input)
        
        self.refresh_btn = QPushButton("🔄 刷新提取")
        self.refresh_btn.setFixedWidth(120)
        self.refresh_btn.clicked.connect(lambda: self.run_task("extract"))
        url_layout.addWidget(self.refresh_btn)
        config_layout.addLayout(url_layout)

        # Cookie Line
        cookie_label = QLabel("Cookie 字符串 (从浏览器 F12 获取):")
        cookie_label.setStyleSheet("font-weight: bold;")
        config_layout.addWidget(cookie_label)
        self.cookie_input = QTextEdit()
        self.cookie_input.setMaximumHeight(80)
        self.cookie_input.setPlaceholderText("在此粘贴您的 Cookies (建议不要包含敏感的密码字段)...")
        config_layout.addWidget(self.cookie_input)
        
        btn_layout = QHBoxLayout()
        self.save_cookie_btn = QPushButton("💾 保存到本地 (CookieValue.txt)")
        self.save_cookie_btn.setObjectName("SaveBtn")
        self.save_cookie_btn.clicked.connect(self.save_cookie)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_cookie_btn)
        config_layout.addLayout(btn_layout)
        
        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        # Tab Widget
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: Answer Extraction
        extract_tab = QWidget()
        extract_layout = QVBoxLayout(extract_tab)
        extract_layout.setContentsMargins(15, 15, 15, 15)
        self.extract_output = QTextEdit()
        self.extract_output.setReadOnly(True)
        self.extract_output.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; background-color: #fafbfc; border-radius: 8px; padding: 10px;")
        extract_layout.addWidget(self.extract_output)
        
        # Pure answers copy section
        self.pure_ans_group = QGroupBox("📋 独立填空答案 (直接点击单行内容即可复制)")
        pure_ans_layout = QVBoxLayout()
        self.pure_ans_list = QListWidget()
        self.pure_ans_list.setMaximumHeight(150)
        self.pure_ans_list.setStyleSheet("""
            QListWidget { font-size: 15px; border: 1px solid #dcdde1; border-radius: 6px; padding: 5px; }
            QListWidget::item { padding: 6px; border-bottom: 1px solid #f0f2f5; }
            QListWidget::item:hover { background-color: #f7f9fa; cursor: pointer; }
            QListWidget::item:selected { background-color: #e8f4fd; color: #2980b9; font-weight: bold; }
        """)
        self.pure_ans_list.itemClicked.connect(self.copy_single_item)
        
        self.copy_btn = QPushButton("📋 复制全部答案")
        self.copy_btn.clicked.connect(self.copy_pure_answers)
        
        pure_ans_layout.addWidget(self.pure_ans_list)
        pure_ans_layout.addWidget(self.copy_btn)
        self.pure_ans_group.setLayout(pure_ans_layout)
        self.pure_ans_group.hide() # Initially hidden
        extract_layout.addWidget(self.pure_ans_group)
        
        self.tabs.addTab(extract_tab, "🔍 答案解析")

        # Tab 2: Connectivity Report
        report_tab = QWidget()
        report_layout = QVBoxLayout(report_tab)
        report_layout.setContentsMargins(15, 15, 15, 15)
        self.report_btn = QPushButton("📡 检查当前页面的网络连通性")
        self.report_btn.setStyleSheet("margin-bottom: 10px;")
        self.report_btn.clicked.connect(lambda: self.run_task("report"))
        self.report_output = QTextEdit()
        self.report_output.setReadOnly(True)
        self.report_output.setStyleSheet("font-family: 'Consolas', monospace; font-size: 14px; background-color: #fafbfc; border-radius: 8px; padding: 10px;")
        report_layout.addWidget(self.report_btn)
        report_layout.addWidget(self.report_output)
        self.tabs.addTab(report_tab, "📊 运行报告")

    def on_url_changed(self):
        # Optional: visual feedback when URL changes
        self.url_input.setStyleSheet("border: 1px solid #0078d4;")

    def load_default_cookie(self):
        path = Path("CookieValue.txt")
        if path.exists():
            self.cookie_input.setPlainText(path.read_text(encoding="utf-8-sig").strip())

    def save_cookie(self):
        content = self.cookie_input.toPlainText().strip()
        if content:
            Path("CookieValue.txt").write_text(content, encoding="utf-8")
            QMessageBox.information(self, "成功", "Cookie 已保存")
        else:
            QMessageBox.warning(self, "警告", "请输入 Cookie")

    def run_task(self, action):
        url = self.url_input.text().strip()
        cookie = self.cookie_input.toPlainText().strip()
        if not url:
            QMessageBox.warning(self, "错误", "请输入学习页面 URL")
            return

        if action == "extract":
            btn = self.refresh_btn
            output_widget = self.extract_output
            self.tabs.setCurrentIndex(0)
        else:
            btn = self.report_btn
            output_widget = self.report_output
        
        btn.setEnabled(False)
        output_widget.setPlaceholderText("正在努力加载中...")
        output_widget.clear()

        self.worker = WorkerThread(action, url, cookie)
        self.worker.finished.connect(lambda text: self.on_finished(text, btn, output_widget))
        self.worker.error.connect(lambda err: self.on_error(err, btn, output_widget))
        self.worker.start()

    def on_finished(self, text, btn, widget):
        if "====PURE_ANSWERS_SEP====" in text:
            main_text, pure_text = text.split("====PURE_ANSWERS_SEP====")
            widget.setText(main_text)
            if pure_text.strip():
                self.pure_ans_list.clear() # clear existing items
                for i, ans in enumerate(pure_text.strip().split('\n')):
                    if ans.strip():
                        self.pure_ans_list.addItem(f"{i+1}. {ans.strip()}")
                self.pure_ans_group.show()
            else:
                self.pure_ans_group.hide()
        else:
            widget.setText(text)
            
        btn.setEnabled(True)
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(True) # Ensure both are re-enabled
        if hasattr(self, 'report_btn'):
            self.report_btn.setEnabled(True)

    def copy_single_item(self, item):
        # 取出 "1. answer" 中的答案部分
        text_to_copy = item.text().split(". ", 1)[-1]
        QApplication.clipboard().setText(text_to_copy)
        self.statusBar().showMessage(f"成功复制第 {item.text().split('.')[0]} 题答案: {text_to_copy}", 3000)

    def copy_pure_answers(self):
        answers = [self.pure_ans_list.item(i).text().split(". ", 1)[-1] for i in range(self.pure_ans_list.count())]
        QApplication.clipboard().setText("\n".join(answers))
        QMessageBox.information(self, "成功", "所有填空答案已复制到剪贴板！")

    def on_error(self, err, btn, widget):
        widget.setText(f"发生错误:\n{err}")
        btn.setEnabled(True)
        if hasattr(self, 'refresh_btn'):
            self.refresh_btn.setEnabled(True)
        if hasattr(self, 'report_btn'):
            self.report_btn.setEnabled(True)
        QMessageBox.critical(self, "执行失败", f"请求过程中出错: {err}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
