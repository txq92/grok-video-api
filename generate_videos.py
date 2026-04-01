#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chương trình tạo video học tiếng Anh cho trẻ em bằng Grok API.
Tích hợp Telegram Bot để quản lý và nhận video.

- Nếu có TELEGRAM_BOT_TOKEN: chạy Telegram Bot mode
- Nếu không có: chạy CLI mode như bình thường

Lệnh Telegram:
  /start  - Menu chính
  /run    - Bắt đầu tạo video
  /stop   - Dừng tạo video
  /pause  - Tạm dừng / tiếp tục
  /status - Xem trạng thái
  /list   - Xem danh sách từ
  /add    - Thêm từ mới
  /clear  - Xóa toàn bộ danh sách từ
  /videos - Liệt kê video đã tạo
  /config - Xem cấu hình
  /set    - Thay đổi cấu hình
"""

import os
import sys
import time
import random
import string
import requests
import re
import json
import threading
import base64
from datetime import datetime
from dotenv import load_dotenv

# Load .env file
load_dotenv()

#nohup uv run python -u generate_videos.py > generate_videos.log 2>&1 &
#pkill -f generate_videos.py
# ============================================================
# CẤU HÌNH
# ============================================================
API_KEY = os.environ.get("XAI_API_KEY", "")
BASE_URL = "https://api.x.ai/v1"
MODEL = "grok-imagine-video"
DURATION = 11          # Thời lượng video (giây)
RESOLUTION = "720p"    # Độ phân giải

INPUT_FILE = "input.txt"
OUTPUT_DIR = "OUTPUTVIDEO"
IMAGES_DIR = "IMAGES"    # Thư mục chứa ảnh để random

# Khoảng thời gian polling (giây)
POLL_INTERVAL = 7
# Timeout tối đa cho mỗi video (giây) - 10 phút
MAX_WAIT_TIME = 600

# ============================================================
# TELEGRAM CONFIG
# ============================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_API = "https://api.telegram.org"

# ============================================================
# PROMPT TEMPLATE (tham khảo từ video-generation1.sh)
# ============================================================
PROMPT_TEMPLATE = """
# KỊCH BẢN VIDEO HỌC TIẾNG ANH CHO TRẺ EM

## 1. YÊU CẦU CHUNG (VIDEO SPECIFICATIONS)
* **Phong cách:** Giáo dục trẻ em, đơn giản, trực quan.
* **Nhân vật:** Cô giáo (giọng nữ thân thiện, rõ ràng, hình ảnh không thay đổi).
* **Hình ảnh minh họa:** Hoạt hình dễ thương, đúng chủ đề, đặt ở **góc trên bên trái**.
* **Nhạc nền:** Nhạc thiếu nhi nhẹ nhàng hoặc không nhạc.
* **Yêu cầu Text:** * Font chữ lớn, dễ đọc, tuyệt đối không vỡ font tiếng Việt.
    * Màu sắc tươi sáng, hiển thị xuyên suốt video.
    * Bố cục: Nằm ở phía trên bên trái video.
---
## 2. CẤU TRÚC KỊCH BẢN (STORYBOARD)

| Bước | Hành động | Nội dung âm thanh | Hiển thị Text |
| :--- | :--- | :--- | :--- |
| **1** | Cô giáo xuất hiện | Đọc nghĩa tiếng Việt to, rõ. | `{TIENG_VIET}` |
| **2** | Cô giáo dẫn dắt | "Từ này trong tiếng Anh đọc là..." | `{TIENG_VIET}` (Không hiện text lời dẫn) |
| **3** | Cô giáo phát âm | Đọc từ tiếng Anh lần 1. | `{TIENG_VIET}` <br> `{TIENG_ANH}` |
| **4** | Im lặng để học sinh chuẩn bị | `{TIENG_VIET}` <br> `{TIENG_ANH}` |
| **5** | Học sinh đọc | Học sinh đọc tiếng Anh to, rõ. | `{TIENG_VIET}` <br> `{TIENG_ANH}` |
| **6** | Cô giáo nhắc lại tiếng Anh to, rõ  | `{TIENG_VIET}` <br> `{TIENG_ANH}` |
| **7** | Cô giáo nhắc lại tiếng Anh to, rõ | Đọc từ tiếng Anh lần nữa để chốt. | `{TIENG_VIET}` <br> `{TIENG_ANH}` |
---
## 3. NỘI DUNG CHI TIẾT (CONTENT DATA)

### Từ vựng 1:
* **Tiếng Việt:** {word}
* **Tiếng Anh:** tìm từ tương ứng
* **Minh họa:** hoạt hình dễ thương mô tả đúng chủ đề
---
## 4. LƯU Ý KỸ THUẬT
> [!IMPORTANT]
> * Đảm bảo text hiển thị xuyên suốt, chữ không bị vỡ font tiếng việt để trẻ ghi nhớ mặt chữ.
> * Sử dụng màu sắc tương phản tốt giữa chữ và nền để dễ đọc.
""".strip()


# ============================================================
# UTILITY FUNCTIONS
# ============================================================
def get_script_dir():
    return os.path.dirname(os.path.abspath(__file__))


def sanitize_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'[^\w\-]', '', name, flags=re.UNICODE)
    return name


def random_5_digits() -> str:
    return ''.join(random.choices(string.digits, k=5))


def get_random_image(images_dir: str) -> str:
    if not os.path.isdir(images_dir):
        return None
    valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
    images = [
        os.path.join(images_dir, f)
        for f in os.listdir(images_dir)
        if os.path.splitext(f)[1].lower() in valid_exts
    ]
    if not images:
        return None
    return random.choice(images)


def read_words(filepath: str) -> list:
    if not os.path.exists(filepath):
        return []
    with open(filepath, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


# ============================================================
# VIDEO GENERATOR CLASS
# ============================================================
class VideoGenerator:
    """Quản lý việc tạo video, hỗ trợ stop/pause từ bên ngoài."""

    def __init__(self):
        self.script_dir = get_script_dir()
        self.input_path = os.path.join(self.script_dir, INPUT_FILE)
        self.output_dir = os.path.join(self.script_dir, OUTPUT_DIR)
        self.images_dir = os.path.join(self.script_dir, IMAGES_DIR)

        # Shared state cho threading
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # Mặc định không pause
        self._running = False
        self._thread = None

        # Trạng thái tiến trình
        self.current_word = ""
        self.current_index = 0
        self.total_words = 0
        self.success_count = 0
        self.fail_count = 0
        self.start_time = None

        # Callback khi có sự kiện
        self.on_video_start = None      # (word, index, total)
        self.on_video_done = None       # (word, filepath)
        self.on_video_fail = None       # (word, reason)
        self.on_all_done = None         # (success, fail, total)
        self.on_log = None              # (message)

    @property
    def is_running(self):
        return self._running

    @property
    def is_paused(self):
        return not self._pause_event.is_set()

    def _log(self, msg):
        log(msg)
        if self.on_log:
            try:
                self.on_log(msg)
            except:
                pass

    def submit_video(self, word, image_path=None):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }
        prompt = PROMPT_TEMPLATE.replace("{word}", word)
        payload = {
            "model": MODEL,
            "prompt": prompt,
            "duration": DURATION,
            "resolution": RESOLUTION,
        }
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as img_file:
                img_data = base64.b64encode(img_file.read()).decode("utf-8")
            ext = os.path.splitext(image_path)[1].lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
            mime_type = mime_map.get(ext, "image/png")
            payload["image"] = {"url": f"data:{mime_type};base64,{img_data}"}

        response = requests.post(
            f"{BASE_URL}/videos/generations",
            headers=headers, json=payload, timeout=60
        )
        response.raise_for_status()
        return response.json().get("request_id")

    def poll_video(self, request_id):
        headers = {"Authorization": f"Bearer {API_KEY}"}
        start = time.time()
        attempt = 0
        while not self._stop_event.is_set():
            # Xử lý pause
            self._pause_event.wait()
            if self._stop_event.is_set():
                return None

            elapsed = time.time() - start
            if elapsed > MAX_WAIT_TIME:
                return None
            attempt += 1
            try:
                result = requests.get(
                    f"{BASE_URL}/videos/{request_id}",
                    headers=headers, timeout=30
                )
                result.raise_for_status()
                data = result.json()
                status = data.get("status", "unknown")
                if status == "done":
                    return {
                        "url": data.get("video", {}).get("url"),
                        "duration": data.get("video", {}).get("duration")
                    }
                elif status in ("expired", "failed"):
                    return None
                else:
                    self._log(f"  ⏳ Poll #{attempt}: {status} ({int(elapsed)}s)")
                    time.sleep(POLL_INTERVAL)
            except Exception as e:
                self._log(f"  ⚠️ Poll error: {e}")
                time.sleep(POLL_INTERVAL)
        return None

    def download_video(self, url, save_path):
        response = requests.get(url, stream=True, timeout=180)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return os.path.getsize(save_path)

    def run(self):
        """Chạy tạo video cho tất cả từ trong input.txt"""
        if self._running:
            self._log("⚠️ Đang chạy rồi!")
            return

        self._stop_event.clear()
        self._pause_event.set()
        self._running = True
        self.success_count = 0
        self.fail_count = 0
        self.start_time = time.time()

        words = read_words(self.input_path)
        if not words:
            self._log("❌ Không có từ nào trong input.txt!")
            self._running = False
            return

        self.total_words = len(words)
        os.makedirs(self.output_dir, exist_ok=True)
        self._log(f"🚀 Bắt đầu tạo {self.total_words} video...")

        for i, word in enumerate(words, 1):
            if self._stop_event.is_set():
                self._log("🛑 Đã dừng bởi người dùng.")
                break

            # Xử lý pause
            self._pause_event.wait()
            if self._stop_event.is_set():
                self._log("🛑 Đã dừng bởi người dùng.")
                break

            self.current_word = word
            self.current_index = i
            self._log(f"\n📹 [{i}/{self.total_words}] Từ: '{word}'")

            if self.on_video_start:
                try:
                    self.on_video_start(word, i, self.total_words)
                except:
                    pass

            # Lấy ảnh random
            random_image = get_random_image(self.images_dir)
            if random_image:
                self._log(f"  🖼️ Ảnh: {os.path.basename(random_image)}")

            # Submit
            try:
                request_id = self.submit_video(word, random_image)
                if not request_id:
                    raise Exception("Không nhận được request_id")
                self._log(f"  ✅ request_id: {request_id}")
            except Exception as e:
                self.fail_count += 1
                reason = str(e)
                self._log(f"  ❌ Submit lỗi: {reason}")
                if self.on_video_fail:
                    try:
                        self.on_video_fail(word, reason)
                    except:
                        pass
                continue

            # Poll
            result = self.poll_video(request_id)
            if not result or not result.get("url"):
                self.fail_count += 1
                reason = "Timeout hoặc failed"
                self._log(f"  ❌ {reason}")
                if self.on_video_fail:
                    try:
                        self.on_video_fail(word, reason)
                    except:
                        pass
                continue

            # Download
            safe_name = sanitize_filename(word)
            filename = f"{safe_name}_{random_5_digits()}.mp4"
            save_path = os.path.join(self.output_dir, filename)
            try:
                file_size = self.download_video(result["url"], save_path)
                self.success_count += 1
                self._log(f"  ✅ Đã lưu: {filename} ({file_size/1024/1024:.2f}MB)")
                if self.on_video_done:
                    try:
                        self.on_video_done(word, save_path)
                    except:
                        pass
            except Exception as e:
                self.fail_count += 1
                reason = f"Download lỗi: {e}"
                self._log(f"  ❌ {reason}")
                if self.on_video_fail:
                    try:
                        self.on_video_fail(word, reason)
                    except:
                        pass

        # Hoàn thành
        elapsed = time.time() - self.start_time
        self._log(f"\n🏁 HOÀN THÀNH: {self.success_count}✅ / {self.fail_count}❌ / {self.total_words} tổng ({int(elapsed)}s)")
        if self.on_all_done:
            try:
                self.on_all_done(self.success_count, self.fail_count, self.total_words)
            except:
                pass

        self._running = False
        self.current_word = ""

    def run_async(self):
        """Chạy trong background thread"""
        if self._running:
            return False
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        self._pause_event.set()  # Unblock nếu đang pause

    def pause(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._log("⏸️ Đã tạm dừng")
        else:
            self._pause_event.set()
            self._log("▶️ Đã tiếp tục")

    def get_status(self):
        if not self._running:
            return "⏹️ Chưa chạy"
        elapsed = int(time.time() - self.start_time) if self.start_time else 0
        status = "⏸️ Tạm dừng" if self.is_paused else "🔄 Đang chạy"
        return (
            f"{status}\n"
            f"📝 Từ hiện tại: {self.current_word}\n"
            f"📊 Tiến độ: {self.current_index}/{self.total_words}\n"
            f"✅ Thành công: {self.success_count}\n"
            f"❌ Thất bại: {self.fail_count}\n"
            f"⏱️ Thời gian: {elapsed}s"
        )


# ============================================================
# TELEGRAM BOT CLASS
# ============================================================
class TelegramBot:
    """Telegram Bot để quản lý VideoGenerator."""

    def __init__(self, token: str, generator: VideoGenerator):
        self.token = token
        self.gen = generator
        self.api = f"{TELEGRAM_API}/bot{token}"
        self.offset = 0
        self._running = False

        # Gắn callback
        self.gen.on_video_start = self._on_video_start
        self.gen.on_video_done = self._on_video_done
        self.gen.on_video_fail = self._on_video_fail
        self.gen.on_all_done = self._on_all_done

        # Lưu chat_ids đã tương tác để gửi thông báo
        self._chat_ids = set()

    def send_message(self, chat_id, text, parse_mode="Markdown"):
        try:
            requests.post(f"{self.api}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            }, timeout=10)
        except Exception as e:
            log(f"[TG] Lỗi gửi tin: {e}")

    def send_video(self, chat_id, video_path, caption=""):
        try:
            with open(video_path, 'rb') as f:
                file_size = os.path.getsize(video_path)
                # Telegram giới hạn 50MB cho bot
                if file_size > 50 * 1024 * 1024:
                    self.send_message(chat_id, f"⚠️ Video quá lớn ({file_size/1024/1024:.1f}MB), không gửi qua Telegram được.")
                    return
                requests.post(
                    f"{self.api}/sendVideo",
                    data={"chat_id": chat_id, "caption": caption},
                    files={"video": (os.path.basename(video_path), f, "video/mp4")},
                    timeout=120
                )
        except Exception as e:
            log(f"[TG] Lỗi gửi video: {e}")
            self.send_message(chat_id, f"⚠️ Không gửi được video: {e}")

    def broadcast(self, text, parse_mode="Markdown"):
        for chat_id in self._chat_ids:
            self.send_message(chat_id, text, parse_mode)

    def broadcast_video(self, video_path, caption=""):
        for chat_id in self._chat_ids:
            self.send_video(chat_id, video_path, caption)

    # ---- Callbacks từ VideoGenerator ----
    def _on_video_start(self, word, index, total):
        self.broadcast(f"📹 *[{index}/{total}]* Đang tạo video: `{word}`...")

    def _on_video_done(self, word, filepath):
        self.broadcast_video(filepath, caption=f"✅ Video hoàn thành: {word}")

    def _on_video_fail(self, word, reason):
        self.broadcast(f"❌ Thất bại: `{word}`\nLý do: {reason}")

    def _on_all_done(self, success, fail, total):
        self.broadcast(
            f"🏁 *HOÀN THÀNH*\n"
            f"✅ Thành công: {success}\n"
            f"❌ Thất bại: {fail}\n"
            f"📊 Tổng: {total}"
        )

    # ---- Command Handlers ----
    def handle_start(self, chat_id):
        self.send_message(chat_id,
            "🤖 *Video Generator Bot*\n\n"
            "📋 *Lệnh quản lý:*\n"
            "/run - Bắt đầu tạo video\n"
            "/stop - Dừng tạo video\n"
            "/pause - Tạm dừng / tiếp tục\n"
            "/status - Xem trạng thái\n\n"
            "📝 *Quản lý từ vựng:*\n"
            "/list - Xem danh sách từ\n"
            "/add `<từ>` - Thêm từ mới\n"
            "/clear - Xóa toàn bộ danh sách\n\n"
            "📁 *Video & Cấu hình:*\n"
            "/videos - Liệt kê video đã tạo\n"
            "/config - Xem cấu hình\n"
            "/set `<key>` `<value>` - Đổi cấu hình\n"
        )

    def handle_run(self, chat_id):
        if self.gen.is_running:
            self.send_message(chat_id, "⚠️ Đang chạy rồi! Dùng /stop để dừng trước.")
            return
        words = read_words(self.gen.input_path)
        if not words:
            self.send_message(chat_id, "❌ File input.txt trống! Dùng /add để thêm từ.")
            return
        self.send_message(chat_id, f"🚀 Bắt đầu tạo *{len(words)}* video...\nVideo hoàn thành sẽ được gửi trực tiếp vào đây.")
        self.gen.run_async()

    def handle_stop(self, chat_id):
        if not self.gen.is_running:
            self.send_message(chat_id, "ℹ️ Hiện không có tiến trình nào đang chạy.")
            return
        self.gen.stop()
        self.send_message(chat_id, "🛑 Đang dừng... (sẽ dừng sau khi hoàn thành video hiện tại)")

    def handle_pause(self, chat_id):
        if not self.gen.is_running:
            self.send_message(chat_id, "ℹ️ Hiện không có tiến trình nào đang chạy.")
            return
        self.gen.pause()
        status = "⏸️ Đã tạm dừng" if self.gen.is_paused else "▶️ Đã tiếp tục"
        self.send_message(chat_id, status)

    def handle_status(self, chat_id):
        self.send_message(chat_id, self.gen.get_status())

    def handle_list(self, chat_id):
        words = read_words(self.gen.input_path)
        if not words:
            self.send_message(chat_id, "📝 Danh sách trống.")
            return
        text = f"📝 *Danh sách từ ({len(words)}):*\n\n"
        for i, w in enumerate(words, 1):
            text += f"{i}. {w}\n"
            if i >= 80:  # Giới hạn hiển thị
                text += f"\n... và {len(words) - 80} từ nữa"
                break
        self.send_message(chat_id, text)

    def handle_add(self, chat_id, args):
        if not args:
            self.send_message(chat_id, "⚠️ Cú pháp: /add `<từ>`\nVí dụ: /add Con mèo")
            return
        word = args.strip()
        with open(self.gen.input_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{word}")
        words = read_words(self.gen.input_path)
        self.send_message(chat_id, f"✅ Đã thêm: `{word}`\nTổng: {len(words)} từ")

    def handle_clear(self, chat_id):
        with open(self.gen.input_path, 'w', encoding='utf-8') as f:
            f.write("")
        self.send_message(chat_id, "🗑️ Đã xóa toàn bộ danh sách từ.")

    def handle_videos(self, chat_id):
        output_dir = self.gen.output_dir
        if not os.path.isdir(output_dir):
            self.send_message(chat_id, "📁 Chưa có video nào.")
            return
        files = [f for f in os.listdir(output_dir) if f.endswith('.mp4')]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(output_dir, f)), reverse=True)
        if not files:
            self.send_message(chat_id, "📁 Chưa có video nào.")
            return
        total_size = sum(os.path.getsize(os.path.join(output_dir, f)) for f in files)
        text = f"📁 *Video đã tạo ({len(files)}):*\nTổng dung lượng: {total_size/1024/1024:.1f}MB\n\n"
        for i, f in enumerate(files[:30], 1):
            size = os.path.getsize(os.path.join(output_dir, f)) / 1024 / 1024
            text += f"{i}. `{f}` ({size:.1f}MB)\n"
        if len(files) > 30:
            text += f"\n... và {len(files) - 30} video nữa"
        self.send_message(chat_id, text)

    def handle_config(self, chat_id):
        global DURATION, RESOLUTION, MODEL, POLL_INTERVAL, MAX_WAIT_TIME
        self.send_message(chat_id,
            f"⚙️ *Cấu hình hiện tại:*\n\n"
            f"🎬 Model: `{MODEL}`\n"
            f"⏱️ Duration: `{DURATION}s`\n"
            f"📐 Resolution: `{RESOLUTION}`\n"
            f"🔄 Poll Interval: `{POLL_INTERVAL}s`\n"
            f"⏰ Max Wait: `{MAX_WAIT_TIME}s`\n"
            f"📂 Input: `{INPUT_FILE}`\n"
            f"📂 Output: `{OUTPUT_DIR}`\n"
            f"🖼️ Images: `{IMAGES_DIR}`\n\n"
            f"Dùng /set `<key>` `<value>` để thay đổi\n"
            f"Keys: duration, resolution, poll\\_interval, max\\_wait"
        )

    def handle_set(self, chat_id, args):
        global DURATION, RESOLUTION, POLL_INTERVAL, MAX_WAIT_TIME
        if not args or len(args.split()) < 2:
            self.send_message(chat_id, "⚠️ Cú pháp: /set `<key>` `<value>`\nVí dụ: /set duration 15")
            return
        parts = args.split(maxsplit=1)
        key = parts[0].lower()
        value = parts[1].strip()

        try:
            if key == "duration":
                DURATION = int(value)
                self.send_message(chat_id, f"✅ Duration = {DURATION}s")
            elif key == "resolution":
                RESOLUTION = value
                self.send_message(chat_id, f"✅ Resolution = {RESOLUTION}")
            elif key == "poll_interval":
                POLL_INTERVAL = int(value)
                self.send_message(chat_id, f"✅ Poll Interval = {POLL_INTERVAL}s")
            elif key == "max_wait":
                MAX_WAIT_TIME = int(value)
                self.send_message(chat_id, f"✅ Max Wait = {MAX_WAIT_TIME}s")
            else:
                self.send_message(chat_id, f"❌ Key không hợp lệ: `{key}`")
        except ValueError:
            self.send_message(chat_id, f"❌ Giá trị không hợp lệ: `{value}`")

    def process_update(self, update):
        message = update.get("message")
        if not message:
            return
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        # Lưu chat_id để broadcast
        self._chat_ids.add(chat_id)

        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]  # Bỏ @botname
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/start" or cmd == "/help":
            self.handle_start(chat_id)
        elif cmd == "/run":
            self.handle_run(chat_id)
        elif cmd == "/stop":
            self.handle_stop(chat_id)
        elif cmd == "/pause":
            self.handle_pause(chat_id)
        elif cmd == "/status":
            self.handle_status(chat_id)
        elif cmd == "/list":
            self.handle_list(chat_id)
        elif cmd == "/add":
            self.handle_add(chat_id, args)
        elif cmd == "/clear":
            self.handle_clear(chat_id)
        elif cmd == "/videos":
            self.handle_videos(chat_id)
        elif cmd == "/config":
            self.handle_config(chat_id)
        elif cmd == "/set":
            self.handle_set(chat_id, args)
        else:
            self.send_message(chat_id, f"❓ Lệnh không rõ: `{cmd}`\nDùng /start để xem danh sách lệnh.")

    def poll_updates(self):
        """Long polling lấy tin nhắn mới từ Telegram."""
        try:
            resp = requests.get(
                f"{self.api}/getUpdates",
                params={"offset": self.offset, "timeout": 30},
                timeout=40
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            if not data.get("ok"):
                return
            for update in data.get("result", []):
                self.offset = update["update_id"] + 1
                try:
                    self.process_update(update)
                except Exception as e:
                    log(f"[TG] Lỗi xử lý update: {e}")
        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            log(f"[TG] Lỗi poll: {e}")
            time.sleep(5)

    def start(self):
        """Bắt đầu bot loop."""
        self._running = True
        log("🤖 Telegram Bot đã khởi động! Gửi /start để bắt đầu.")

        # Test kết nối
        try:
            resp = requests.get(f"{self.api}/getMe", timeout=10)
            if resp.status_code == 200:
                bot_info = resp.json().get("result", {})
                log(f"🤖 Bot: @{bot_info.get('username', 'unknown')}")
            else:
                log(f"⚠️ Không kết nối được Telegram Bot! Status: {resp.status_code}")
                return
        except Exception as e:
            log(f"❌ Lỗi kết nối Telegram: {e}")
            return

        while self._running:
            self.poll_updates()

    def stop(self):
        self._running = False


# ============================================================
# CLI MODE (khi không có Telegram token)
# ============================================================
def run_cli_mode():
    """Chạy chế độ CLI như cũ"""
    gen = VideoGenerator()

    if not API_KEY:
        print("[LỖI] Chưa thiết lập API key!")
        sys.exit(1)

    words = read_words(gen.input_path)
    if not words:
        print("[LỖI] Không có từ nào trong input.txt!")
        sys.exit(1)

    os.makedirs(gen.output_dir, exist_ok=True)
    print(f"[INFO] Output: {gen.output_dir}")

    if os.path.isdir(gen.images_dir):
        valid_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        img_count = len([f for f in os.listdir(gen.images_dir) if os.path.splitext(f)[1].lower() in valid_exts])
        print(f"[INFO] Ảnh: {gen.images_dir} ({img_count} file)")

    print(f"\n{'='*60}")
    print(f"BẮT ĐẦU TẠO {len(words)} VIDEO (CLI MODE)")
    print(f"{'='*60}\n")

    gen.run()


# ============================================================
# MAIN
# ============================================================
def main():
    if TELEGRAM_BOT_TOKEN:
        # Telegram Bot mode
        log("=" * 50)
        log("🚀 TELEGRAM BOT MODE")
        log("=" * 50)

        gen = VideoGenerator()
        bot = TelegramBot(TELEGRAM_BOT_TOKEN, gen)
        try:
            bot.start()
        except KeyboardInterrupt:
            log("\n👋 Đang tắt...")
            gen.stop()
            bot.stop()
    else:
        # CLI mode
        log("=" * 50)
        log("📟 CLI MODE (không có Telegram token)")
        log("Để dùng Telegram, hãy thiết lập TELEGRAM_BOT_TOKEN")
        log("=" * 50)
        run_cli_mode()


if __name__ == "__main__":
    main()
