"""
Otomatize Scraper System V4 - STABLE VERSION
Bu sürüm V3'ün güçlü scraper modüllerini (ultra_detail_scraper, gamermarkt_scraper)
V4'ün otomasyon mantığıyla birleştirir.

Düzeltmeler:
- create_g2g_offer fonksiyonu düzgün çağrılıyor
- AI içerik G2G'ye gönderiliyor
- Filtre değerleri scraper formatına çevriliyor
- Kayıp linkler tespit edilip G2G'den siliniyor
- last_seen timestamp ile 3 kez üst üste görünmeyenler siliniyor
"""

import json
import time
import os
import random
import threading
import hashlib
import functools
import requests
from datetime import datetime, timedelta
from threading import Lock
from queue import Queue
from collections import defaultdict


# =============================================================================
# RETRY DECORATOR
# =============================================================================

def retry_on_failure(max_retries=3, delay=2, backoff=2, exceptions=(Exception,)):
    """
    Retry decorator - başarısız işlemleri tekrar dener

    Args:
        max_retries: Maksimum deneme sayısı
        delay: İlk bekleme süresi (saniye)
        backoff: Her denemede bekleme çarpanı
        exceptions: Yakalanacak exception türleri
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            current_delay = delay

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        print(f"[RETRY] {func.__name__} deneme {attempt + 1}/{max_retries} başarısız: {e}")
                        print(f"[RETRY] {current_delay}s sonra tekrar denenecek...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        print(f"[RETRY] {func.__name__} tüm denemeler başarısız ({max_retries}x)")

            raise last_exception

        return wrapper
    return decorator

from flask import Flask, jsonify, request, make_response

from botasaurus_bridge import BotasaurusBridge, By, NoSuchElementException
from bs4 import BeautifulSoup

# --- V3 MODÜLLERİ ---
import g2g_api
import ultra_detail_scraper as uds
from gamermarkt_scraper import GamerMarktScraper
from update_delivery_settings import G2GDeliveryUpdater

# --- AI SETUP ---
try:
    from google import genai
    from dotenv import load_dotenv
    load_dotenv()
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', '')
    gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except:
    gemini_client = None
    print("[UYARI] AI modülü yüklenemedi (.env kontrol edin).")

# Dosya Yolları
CONFIG_FILE = "otomatize_config.json"
LINKS_FILE = "links.json"
ULTRA_DETAILS_FILE = "ultra_details.json"
KUR_FILE = "kur.json"
DELIVERY_QUEUE_FILE = "delivery_queue.json"
ERRORS_FILE = "errors.json"  # Hata kayıtları için
PRESET_STATS_FILE = "preset_stats.json"  # Preset bazlı istatistikler
FAILED_QUEUE_FILE = "failed_queue.json"  # Başarısız ilanlar için retry kuyruğu
PROMPTS_FILE = "prompts.json"  # Prompt şablonları
CHROME_PROFILE_PATH = os.path.join(os.getcwd(), "chrome_profile_g2g")
VERIFY_PROFILE_PATH = os.path.join(os.getcwd(), "chrome_profile_verify")

# Kur güncelleme ayarları
KUR_UPDATE_INTERVAL = 60  # 60 saniyede bir kur güncelle
KUR_LOCK = Lock()

# Preset stats lock
PRESET_STATS_LOCK = Lock()

# Failed queue lock
FAILED_QUEUE_LOCK = Lock()

# Doğrulama thread'i için ayrı lock
verify_lock = Lock()

# Kaç döngü görünmezse silinsin (Kullanıcı tercihi: 1 döngü = hızlı senkronizasyon)
MISSING_THRESHOLD = 1  # Link 1 taramada bulunamazsa silinir

# Başarısız ilanlar için maksimum deneme sayısı
MAX_RETRY_ATTEMPTS = 3


# =============================================================================
# KUR GÜNCELLEME FONKSİYONLARI (Binance API)
# =============================================================================

def fetch_binance_kur():
    """Binance'den USDT/TRY kurunu çek"""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=USDTTRY"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            kur = float(data.get('price', 0))
            if kur > 0:
                return kur
    except Exception as e:
        print(f"[UYARI] Binance kur çekme hatası: {e}", flush=True)
    return None


def save_kur(kur_value):
    """Kuru kur.json'a kaydet"""
    with KUR_LOCK:
        try:
            # Mevcut dosyayı oku (profit_margin'i korumak için)
            existing_data = {}
            if os.path.exists(KUR_FILE):
                try:
                    with open(KUR_FILE, 'r', encoding='utf-8') as f:
                        existing_data = json.load(f)
                except:
                    pass

            data = {
                'usdt_try': round(kur_value, 2),
                'kur': round(kur_value, 2),  # Eski format uyumluluğu
                'profit_margin': existing_data.get('profit_margin', 1.45),
                'updated_at': datetime.now().isoformat()
            }
            with open(KUR_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[HATA] Kur kaydetme hatası: {e}", flush=True)
            return False


def load_kur():
    """kur.json'dan mevcut kuru yükle"""
    if os.path.exists(KUR_FILE):
        with KUR_LOCK:
            try:
                with open(KUR_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('usdt_try') or data.get('kur') or 35.0
            except:
                return 35.0
    return 35.0


def load_profit_margin():
    """kur.json'dan kar marjını yükle"""
    if os.path.exists(KUR_FILE):
        with KUR_LOCK:
            try:
                with open(KUR_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('profit_margin', 1.45)
            except:
                return 1.45
    return 1.45


def update_kur_periodically():
    """Arka planda periyodik kur güncellemesi"""
    while True:
        try:
            kur = fetch_binance_kur()
            if kur:
                save_kur(kur)
                print(f"[KUR] USDT/TRY güncellendi: {kur:.2f} ₺", flush=True)
        except Exception as e:
            print(f"[HATA] Kur güncelleme hatası: {e}", flush=True)
        time.sleep(KUR_UPDATE_INTERVAL)


def start_kur_updater():
    """Kur güncelleme thread'ini başlat"""
    kur_thread = threading.Thread(target=update_kur_periodically, daemon=True)
    kur_thread.start()
    print("[KUR] Kur güncelleme servisi başlatıldı", flush=True)


# İlk kur güncellemesi ve thread başlatma
def initialize_kur_system():
    """Kur sistemini başlat - uygulama başlangıcında çağrılmalı"""
    # İlk kur güncellemesini hemen yap
    initial_kur = fetch_binance_kur()
    if initial_kur:
        save_kur(initial_kur)
        print(f"[KUR] Başlangıç kuru: {initial_kur:.2f} ₺", flush=True)
    else:
        print(f"[KUR] Binance'e bağlanılamadı, mevcut kur kullanılıyor: {load_kur():.2f} ₺", flush=True)

    # Periyodik güncelleme thread'ini başlat
    start_kur_updater()

# Global Durum
scraper_state = {
    "running": False,
    "current_preset": None,
    "status": "Bekleniyor",
    "stats": {"created": 0, "deleted": 0, "errors": 0, "total_scanned": 0},
    "preset_session_stats": {},  # Her preset için ayrı session stats
    "log": []
}
state_lock = Lock()

def get_preset_session_stats(preset_id):
    """Preset için session stats al (yoksa oluştur)"""
    if preset_id not in scraper_state['preset_session_stats']:
        scraper_state['preset_session_stats'][preset_id] = {
            "created": 0,
            "deleted": 0,
            "errors": 0,
            "scanned": 0,
            "delivery_ok": 0
        }
    return scraper_state['preset_session_stats'][preset_id]

def update_preset_session_stat(preset_id, stat_type, increment=1):
    """Preset session stat güncelle (lock içinde çağrılmalı)"""
    stats = get_preset_session_stats(preset_id)
    if stat_type in stats:
        stats[stat_type] += increment

# Chrome lock'ları - AYRI PROFILE'LAR KULLANILDIĞI İÇİN AYRI LOCK'LAR
# Scraper: chrome_profile_g2g kullanır
# Delivery: chrome_profile_delivery kullanır (ayrı profile = paralel çalışabilir)
scraper_lock = Lock()   # Detay scraping için (GamerMarkt + G2G API)
delivery_lock = Lock()  # Delivery update için (G2G Edit sayfası)

# KRİTİK: Chrome BAŞLATMA için ortak lock (WinError 183 önleme)
# undetected_chromedriver aynı cache'i kullanıyor, iki Chrome aynı anda BAŞLATILAMAZ
# Ama başlatıldıktan sonra paralel çalışabilirler
chrome_init_lock = Lock()

# Aktif Chrome driver'ları — dönüşümlü öne getirme için
active_drivers = []
active_drivers_lock = Lock()


# Uyumluluk için eski isimler
chrome_driver_lock = scraper_lock  # Geriye uyumluluk
profile_lock = scraper_lock        # Geriye uyumluluk

# Thread referansları - durdur/başlat döngüsünde çift thread önleme
_verify_thread = None
_worker_thread = None

# Lock timeout sabiti (saniye)
LOCK_TIMEOUT = 120  # Delivery işlemi uzun sürebilir, 120 saniye
CHROME_INIT_TIMEOUT = 30  # Chrome başlatma için kısa timeout


def _find_chrome_hwnd(browser_pid):
    """PID'den Chrome penceresinin HWND'sini bulur."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _find_by_pid(h, lParam):
        if not user32.IsWindowVisible(h):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == browser_pid and user32.GetWindowTextLengthW(h) > 0:
            ctypes.cast(lParam, ctypes.POINTER(ctypes.c_void_p)).contents.value = h
            return False
        return True

    found = ctypes.c_void_p(0)
    user32.EnumWindows(WNDENUMPROC(_find_by_pid), ctypes.byref(found))
    return found.value


def _bring_hwnd_to_front(hwnd):
    """Verilen HWND'yi öne getirir (minimize'daysa restore, değilse sadece öne)."""
    import ctypes
    user32 = ctypes.windll.user32
    # Sadece minimize durumundaysa restore yap (küçülüp büyüme önlenir)
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)   # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)


def register_active_driver(driver, label="chrome"):
    """Driver'ı aktif driver listesine ekle (dönüşümlü öne getirme için)."""
    with active_drivers_lock:
        # Aynı driver tekrar eklenmesine engel
        for d, _ in active_drivers:
            if d is driver:
                return
        active_drivers.append((driver, label))
        add_log(f"🪟 Chrome kaydedildi: {label} (toplam: {len(active_drivers)})", "info")


def unregister_active_driver(driver):
    """Driver'ı aktif driver listesinden çıkar."""
    with active_drivers_lock:
        active_drivers[:] = [(d, l) for d, l in active_drivers if d is not driver]


def start_chrome_rotation():
    """
    Aktif Chrome pencerelerini sırayla 3 saniye öne getirir.
    Arka planda sürekli çalışır, bot durdurulunca durur.
    """
    import threading

    def _rotate():
        idx = 0
        while True:
            with state_lock:
                if not scraper_state['running']:
                    break

            with active_drivers_lock:
                drivers = list(active_drivers)

            if not drivers:
                time.sleep(1)
                continue

            idx = idx % len(drivers)
            driver, label = drivers[idx]

            try:
                # Sadece gamermarkt ilan sayfalarında öne getir
                current_url = driver.current_url.lower()
                if ('gamermarkt.com/tr/ilan/' not in current_url and
                        'gamermarkt.com/listing/' not in current_url):
                    idx += 1
                    time.sleep(1)
                    continue

                browser_pid = getattr(driver, 'browser_pid', None)
                if browser_pid:
                    hwnd = _find_chrome_hwnd(browser_pid)
                    if hwnd:
                        _bring_hwnd_to_front(hwnd)
            except Exception:
                pass

            idx += 1
            time.sleep(3)

    t = threading.Thread(target=_rotate, daemon=True)
    t.start()
    add_log("🔄 Chrome dönüşümlü öne getirme başlatıldı", "info")


def bring_chrome_to_front(driver):
    """
    Chrome penceresini öne getirir (Win32 API).
    Sadece gamermarkt ilan/listing sayfalarında çalışır.
    """
    try:
        current_url = driver.current_url.lower()
        if ('gamermarkt.com/tr/ilan/' not in current_url and
                'gamermarkt.com/listing/' not in current_url):
            return

        browser_pid = getattr(driver, 'browser_pid', None)
        if not browser_pid:
            return

        hwnd = _find_chrome_hwnd(browser_pid)
        if not hwnd:
            return

        _bring_hwnd_to_front(hwnd)
        add_log(f"🪟 Chrome öne getirildi (PID: {browser_pid})", "info")
    except Exception:
        pass


def maximize_chrome(driver):
    """
    Chrome penceresini tam ekran yapar.
    Chrome tam açılsın diye bekler, ardından maximize_window() ile garantiler.
    """
    time.sleep(1.5)  # Chrome tam açılsın
    try:
        driver.maximize_window()
    except Exception:
        pass
    time.sleep(0.5)
    try:
        driver.maximize_window()
    except Exception:
        pass


def force_cleanup_chrome():
    """
    Tüm artık Chrome ve ChromeDriver proseslerini öldür.
    Bot durdurulduğunda Ctrl+C gibi temiz bir kapanış sağlar.
    """
    import subprocess
    killed_chrome = 0
    killed_driver = 0
    
    try:
        # ChromeDriver proseslerini öldür
        result = subprocess.run(
            ['taskkill', '/F', '/IM', 'chromedriver.exe'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            killed_driver += 1
            add_log("🧹 ChromeDriver prosesleri sonlandırıldı", "info")
    except Exception as e:
        pass  # Proses yoksa hata verir, sorun değil
    
    try:
        # undetected_chromedriver proseslerini öldür
        result = subprocess.run(
            ['taskkill', '/F', '/IM', 'undetected_chromedriver.exe'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            killed_driver += 1
            add_log("🧹 Undetected ChromeDriver prosesleri sonlandırıldı", "info")
    except Exception:
        pass
    
    try:
        # Bot'un açtığı Chrome proseslerini bul ve öldür
        # Sadece --user-data-dir ile açılmış olanları hedefle (normal Chrome'a dokunma)
        # Hem eski chrome_profile hem de botasaurus_profiles klasörlerini ara
        for profile_pattern in ['%chrome_profile%', '%botasaurus_profiles%', '%botasaurus%']:
            try:
                result = subprocess.run(
                    ['wmic', 'process', 'where',
                     f"name='chrome.exe' AND commandline LIKE '{profile_pattern}'",
                     'get', 'processid'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split('\n'):
                        line = line.strip()
                        if line.isdigit():
                            try:
                                subprocess.run(['taskkill', '/F', '/PID', line],
                                             capture_output=True, timeout=5)
                                killed_chrome += 1
                            except:
                                pass
            except Exception:
                pass
        if killed_chrome > 0:
            add_log(f"🧹 {killed_chrome} bot Chrome prosesi sonlandırıldı", "info")
    except Exception:
        pass
    
    # ChromeDriver cache'ini temizle
    cleanup_chromedriver_cache()
    
    if killed_chrome > 0 or killed_driver > 0:
        add_log(f"🧹 Chrome temizliği tamamlandı (chrome: {killed_chrome}, driver: {killed_driver})", "success")



def interruptible_sleep(seconds):
    """
    Bölünebilir sleep - scraper_state['running'] her 0.5 saniyede kontrol edilir.
    Bot durdurulduğunda uzun sleep'ler hemen kesilir.
    True dönerse: sleep tamamlandı (bot hala çalışıyor)
    False dönerse: bot durduruldu, işlem iptal edilmeli
    """
    elapsed = 0
    interval = 0.5
    while elapsed < seconds:
        time.sleep(min(interval, seconds - elapsed))
        elapsed += interval
        with state_lock:
            if not scraper_state['running']:
                return False
    return True


class TimeoutLock:
    """Timeout mekanizmalı lock context manager"""

    def __init__(self, lock, timeout=LOCK_TIMEOUT, name="unnamed"):
        self.lock = lock
        self.timeout = timeout
        self.name = name
        self.acquired = False

    def __enter__(self):
        start_time = time.time()
        while True:
            self.acquired = self.lock.acquire(blocking=False)
            if self.acquired:
                return self

            elapsed = time.time() - start_time
            if elapsed >= self.timeout:
                add_log(f"Lock timeout ({self.name}): {self.timeout}s aşıldı - deadlock riski!", "error")
                raise TimeoutError(f"Lock '{self.name}' {self.timeout}s içinde alınamadı")

            # Kısa bekle ve tekrar dene
            time.sleep(0.1)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            self.lock.release()
        return False

# Delivery update kuyruğu (persistent + in-memory)
delivery_queue = Queue()
delivery_queue_lock = Lock()


def load_delivery_queue():
    """Persistent delivery queue'yu dosyadan yükle"""
    if os.path.exists(DELIVERY_QUEUE_FILE):
        try:
            with open(DELIVERY_QUEUE_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    return []
                data = json.loads(content)
                return data.get('pending', [])
        except Exception as e:
            print(f"[UYARI] Delivery queue yükleme hatası: {e}")
    return []


def save_delivery_queue(pending_items):
    """Delivery queue'yu dosyaya kaydet"""
    try:
        data = {
            'pending': pending_items,
            'updated_at': datetime.now().isoformat()
        }
        temp = DELIVERY_QUEUE_FILE + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(DELIVERY_QUEUE_FILE):
            os.remove(DELIVERY_QUEUE_FILE)
        os.rename(temp, DELIVERY_QUEUE_FILE)
        return True
    except Exception as e:
        print(f"[HATA] Delivery queue kaydetme hatası: {e}")
        return False


def get_pending_delivery_items():
    """Şu anda bekleyen tüm öğeleri listele"""
    with delivery_queue_lock:
        return load_delivery_queue()


# =============================================================================
# FİLTRE DÖNÜŞÜM FONKSİYONLARI
# UI'dan gelen değerleri GamerMarktScraper'ın beklediği formata çevirir
# =============================================================================

def convert_filters_for_scraper(game, ui_filters):
    """
    UI'dan gelen filtre değerlerini scraper'ın beklediği formata çevirir.

    UI'da: servers=['EU', 'TR'], divisions=['Immortal', 'Diamond']
    Scraper'da: servers=['EU'], divisions=['24', '18'] (numeric codes)
    """
    scraper_filters = {}

    # Fiyat filtreleri direkt geçer
    if ui_filters.get('min_price'):
        scraper_filters['min_price'] = ui_filters['min_price']
    if ui_filters.get('max_price'):
        scraper_filters['max_price'] = ui_filters['max_price']

    # Server mapping - GamerMarkt'ın gerçekten desteklediği sunucular
    server_mappings = {
        'valorant': {
            'EU': 'EU', 'NA': 'NA'  # GamerMarkt Valorant sadece EU/NA destekliyor
        },
        'lol': {
            'TR': 'TR', 'EUW': 'EUW', 'EUNE': 'EUN', 'NA': 'NA',
            'BR': 'BR', 'JP': 'JP', 'RU': 'RU', 'LAN': 'LAN', 'LAS': 'LAS', 'OCE': 'OC'
        },
        'cs2': {},  # CS2'de sunucu filtresi yok
        'fortnite': {}  # Fortnite'da sunucu filtresi yok
    }

    # Division mapping - UI isimleri -> GamerMarkt numeric codes
    division_mappings = {
        'valorant': {
            'Unranked': '0', 'Iron': '3', 'Bronze': '6', 'Silver': '9',
            'Gold': '12', 'Platinum': '15', 'Diamond': '18', 'Ascendant': '21',
            'Immortal': '24', 'Radiant': '27'
        },
        'lol': {
            'Unranked': '0', 'Iron': '10', 'Bronze': '20', 'Silver': '30',
            'Gold': '40', 'Platinum': '50', 'Emerald': '60', 'Diamond': '70',
            'Master': '80', 'Grandmaster': '90', 'Challenger': '100'
        },
        'cs2': {
            'Unranked': '0', 'Silver': '1', 'Gold Nova': '2',
            'Master Guardian': '3', 'Legendary Eagle': '4',
            'Supreme': '5', 'Global Elite': '6'
        },
        'fortnite': {
            'Unranked': '0', 'Bronze': '1', 'Silver': '2', 'Gold': '3',
            'Platinum': '4', 'Diamond': '5', 'Elite': '6',
            'Champion': '7', 'Unreal': '8'
        }
    }

    # Sunucuları dönüştür
    if ui_filters.get('servers') and game in server_mappings:
        converted_servers = []
        for server in ui_filters['servers']:
            if server in server_mappings[game]:
                converted_servers.append(server_mappings[game][server])
        if converted_servers:
            scraper_filters['servers'] = converted_servers

    # Rankları dönüştür
    if ui_filters.get('divisions') and game in division_mappings:
        converted_divisions = []
        for div in ui_filters['divisions']:
            if div in division_mappings[game]:
                converted_divisions.append(division_mappings[game][div])
        if converted_divisions:
            scraper_filters['divisions'] = converted_divisions

    # Valorant özel: agent ve skin sayıları
    if game == 'valorant':
        if ui_filters.get('min_agent'):
            scraper_filters['min_agent'] = ui_filters['min_agent']
        if ui_filters.get('max_agent'):
            scraper_filters['max_agent'] = ui_filters['max_agent']
        if ui_filters.get('min_skin'):
            scraper_filters['min_skin'] = ui_filters['min_skin']
        if ui_filters.get('max_skin'):
            scraper_filters['max_skin'] = ui_filters['max_skin']

    # LoL özel: champion ve skin sayıları
    if game == 'lol':
        if ui_filters.get('min_champs'):
            scraper_filters['min_champs'] = ui_filters['min_champs']
        if ui_filters.get('max_champs'):
            scraper_filters['max_champs'] = ui_filters['max_champs']
        if ui_filters.get('min_skins'):
            scraper_filters['min_skins'] = ui_filters['min_skins']
        if ui_filters.get('max_skins'):
            scraper_filters['max_skins'] = ui_filters['max_skins']

    # CS2 özel: prime status ve rank filtreleri
    if game == 'cs2':
        if ui_filters.get('prime') is not None:
            scraper_filters['prime'] = ui_filters['prime']
        if ui_filters.get('faceit_levels'):
            scraper_filters['faceit_levels'] = ui_filters['faceit_levels']

    # Fortnite: Şu an için sadece fiyat filtreleri destekleniyor
    # GamerMarkt Fortnite için rank/skin filtreleri sunmuyor

    return scraper_filters


def validate_listing_against_filters(item_data, game, preset_id):
    """
    G2G ilanı oluşturmadan önce, ilanın preset filtrelerine uygunluğunu kontrol eder.
    Uygun değilse False döner ve log yazar.

    Her oyun için GamerMarkt filtreleme sistemi:
    - Valorant: fiyat, server(EU/NA), kademe, agent sayısı, skin sayısı
    - LoL: fiyat, server(TR/EUW/EUN/NA/...), lig, champion sayısı, skin sayısı
    - CS2: fiyat (server/rank yok - attr bazlı filtreler detay sayfasından doğrulanamaz)
    - Fortnite: fiyat (server/rank yok)
    """
    config = load_json(CONFIG_FILE)
    preset = next((p for p in config.get('presets', []) if p['id'] == preset_id), None)
    if not preset:
        add_log(f"Filtre doğrulama: Preset bulunamadı ({preset_id}), atlanıyor", "warning", preset_id=preset_id)
        return False

    ui_filters = preset.get('filters', {})
    if not ui_filters:
        return True  # Filtre yoksa her ilan geçerli

    link_id = item_data.get('id', '?')
    price_tl = float(item_data.get('price', 0))

    # =========================================================================
    # 1. FİYAT KONTROLÜ (tüm oyunlar)
    # =========================================================================
    min_price = ui_filters.get('min_price')
    if min_price:
        try:
            if price_tl < float(min_price):
                add_log(f"Filtre uyumsuz - Fiyat çok düşük: {price_tl} < {min_price} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass

    max_price = ui_filters.get('max_price')
    if max_price:
        try:
            if price_tl > float(max_price):
                add_log(f"Filtre uyumsuz - Fiyat çok yüksek: {price_tl} > {max_price} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass

    # =========================================================================
    # 2. VALORANT KONTROLLER
    # =========================================================================
    if game == 'valorant':
        # Server kontrolü (EU, NA)
        filter_servers = ui_filters.get('servers', [])
        if filter_servers and item_data.get('region'):
            item_region = item_data['region'].strip().upper()
            normalized_servers = [s.strip().upper() for s in filter_servers]
            if item_region not in normalized_servers:
                add_log(f"Filtre uyumsuz - Server: {item_region} not in {normalized_servers} ({link_id})", "warning", preset_id=preset_id)
                return False

        # Kademe/Division kontrolü
        # UI'da divisions listesi İngilizce isimlerle saklanıyor: ['Unranked', 'Diamond', 'Immortal']
        # Detay sayfasından gelen rank İngilizce: "Immortal 2", "Diamond 1", "Unranked"
        # GamerMarkt kademe isimleri (Türkçe site): Unranked, Demir, Bronz, Gümüş, Altın, Platin, Elmas, Yücelik, Ölümsüzlük, Radyant
        filter_divisions = ui_filters.get('divisions', [])
        if filter_divisions and item_data.get('rank'):
            item_rank = item_data['rank'].strip()
            # Rank'ın ana kısmını al: "Immortal 2" -> "Immortal", "Diamond 1" -> "Diamond"
            item_rank_base = item_rank.split()[0] if item_rank else ''

            # Çift yönlü mapping: İngilizce <-> Türkçe
            valorant_rank_map = {
                'unranked': 'Unranked', 'iron': 'Iron', 'bronze': 'Bronze',
                'silver': 'Silver', 'gold': 'Gold', 'platinum': 'Platinum',
                'diamond': 'Diamond', 'ascendant': 'Ascendant',
                'immortal': 'Immortal', 'radiant': 'Radiant',
                # Türkçe karşılıklar (detay sayfası Türkçe dönerse)
                'demir': 'Iron', 'bronz': 'Bronze', 'gümüş': 'Silver',
                'altın': 'Gold', 'platin': 'Platinum', 'elmas': 'Diamond',
                'yücelik': 'Ascendant', 'ölümsüzlük': 'Immortal', 'radyant': 'Radiant'
            }

            # Item rank'ı normalize et
            item_rank_normalized = valorant_rank_map.get(item_rank_base.lower(), item_rank_base)

            # Filtre division isimlerini normalize et
            matched = False
            for div in filter_divisions:
                div_normalized = valorant_rank_map.get(div.strip().lower(), div.strip())
                if div_normalized.lower() == item_rank_normalized.lower():
                    matched = True
                    break
            if not matched:
                add_log(f"Filtre uyumsuz - Rank: {item_rank} not in {filter_divisions} ({link_id})", "warning", preset_id=preset_id)
                return False

        # Agent sayısı kontrolü
        if not _check_range(item_data.get('agents', 0), ui_filters.get('min_agent'), ui_filters.get('max_agent'),
                            'Agent', link_id, preset_id):
            return False

        # Skin sayısı kontrolü
        if not _check_range(item_data.get('skins', 0), ui_filters.get('min_skin'), ui_filters.get('max_skin'),
                            'Skin', link_id, preset_id):
            return False

    # =========================================================================
    # 3. LOL KONTROLLER
    # =========================================================================
    elif game == 'lol':
        # Server kontrolü (TR, EUW, EUN, NA, RU, BR, JP, LAN, LAS, OC, TH, PH, SG, ME)
        filter_servers = ui_filters.get('servers', [])
        if filter_servers and item_data.get('region'):
            item_region = item_data['region'].strip().upper()
            # GamerMarkt value'ları: EUN, OC vs. Detaydan gelen: EUNE, OCE olabilir
            # Her iki yönde normalize et
            lol_server_aliases = {
                'EUNE': 'EUN', 'EUN': 'EUN',
                'OCE': 'OC', 'OC': 'OC',
            }
            item_region_normalized = lol_server_aliases.get(item_region, item_region)
            normalized_servers = []
            for s in filter_servers:
                s_upper = s.strip().upper()
                normalized_servers.append(lol_server_aliases.get(s_upper, s_upper))

            if item_region_normalized not in normalized_servers:
                add_log(f"Filtre uyumsuz - Server: {item_region} not in {filter_servers} ({link_id})", "warning", preset_id=preset_id)
                return False

        # Lig/Division kontrolü (Solo/Duo)
        # UI'da divisions listesi İngilizce: ['Unranked', 'Iron', 'Gold', 'Diamond']
        # Detaydan gelen rank İngilizce: "Gold IV", "Diamond I", "Unranked"
        # GamerMarkt Türkçe: Unranked, Demir, Bronz, Gümüş, Altın, Platin, Zümrüt, Elmas, Ustalık, Üstatlık, Şampiyonluk
        filter_divisions = ui_filters.get('divisions', [])
        if filter_divisions and item_data.get('rank'):
            item_rank = item_data['rank'].strip()
            # "Gold IV" -> "Gold", "Master" -> "Master"
            item_rank_base = item_rank.split()[0] if item_rank else ''

            lol_rank_map = {
                'unranked': 'Unranked', 'iron': 'Iron', 'bronze': 'Bronze',
                'silver': 'Silver', 'gold': 'Gold', 'platinum': 'Platinum',
                'emerald': 'Emerald', 'diamond': 'Diamond', 'master': 'Master',
                'grandmaster': 'Grandmaster', 'challenger': 'Challenger',
                # Türkçe karşılıklar
                'demir': 'Iron', 'bronz': 'Bronze', 'gümüş': 'Silver',
                'altın': 'Gold', 'platin': 'Platinum', 'zümrüt': 'Emerald',
                'elmas': 'Diamond', 'ustalık': 'Master', 'üstatlık': 'Grandmaster',
                'şampiyonluk': 'Challenger'
            }

            item_rank_normalized = lol_rank_map.get(item_rank_base.lower(), item_rank_base)

            matched = False
            for div in filter_divisions:
                div_normalized = lol_rank_map.get(div.strip().lower(), div.strip())
                if div_normalized.lower() == item_rank_normalized.lower():
                    matched = True
                    break
            if not matched:
                add_log(f"Filtre uyumsuz - Rank: {item_rank} not in {filter_divisions} ({link_id})", "warning", preset_id=preset_id)
                return False

        # Champion sayısı kontrolü
        if not _check_range(item_data.get('champions', 0), ui_filters.get('min_champs'), ui_filters.get('max_champs'),
                            'Champion', link_id, preset_id):
            return False

        # Skin sayısı kontrolü
        if not _check_range(item_data.get('skins', 0), ui_filters.get('min_skins'), ui_filters.get('max_skins'),
                            'Skin', link_id, preset_id):
            return False

    # =========================================================================
    # 4. CS2 KONTROLLER
    # CS2'de server/division checkbox yok. Filtreler attr bazlı (attr_1031, attr_1035 vs.)
    # Bu attr değerleri detay sayfasından doğrudan doğrulanamaz,
    # sadece fiyat kontrolü yapılabilir (yukarıda yapıldı).
    # =========================================================================

    # =========================================================================
    # 5. FORTNITE KONTROLLER
    # Fortnite'da sadece fiyat filtresi var (server/rank/division yok).
    # Fiyat kontrolü yukarıda yapıldı.
    # =========================================================================

    return True


def _check_range(value, min_val, max_val, label, link_id, preset_id):
    """Min/max aralık kontrolü yardımcı fonksiyonu."""
    if min_val:
        try:
            if int(value) < int(min_val):
                add_log(f"Filtre uyumsuz - {label} az: {value} < {min_val} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass
    if max_val:
        try:
            if int(value) > int(max_val):
                add_log(f"Filtre uyumsuz - {label} fazla: {value} > {max_val} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass
    return True


# =============================================================================
# YARDIMCI FONKSİYONLAR
# =============================================================================

def add_log(message, level="info", link_id=None, extra_data=None, preset_id=None):
    timestamp = datetime.now().strftime("%H:%M:%S")
    full_timestamp = datetime.now().isoformat()

    with state_lock:
        scraper_state["log"].append({"time": timestamp, "level": level, "message": message})
        if len(scraper_state["log"]) > 100:
            scraper_state["log"].pop(0)

    # 🔥 Renkli ve görünür log çıktısı
    icons = {'info': '📌', 'success': '✅', 'warning': '⚠️', 'error': '❌'}
    icon = icons.get(level, '📌')
    print(f"{icon} [{timestamp}] [{level.upper()}] {message}", flush=True)

    # Hataları kalıcı dosyaya kaydet
    if level == "error" or level == "warning":
        save_error_log(message, level, link_id, extra_data, full_timestamp, preset_id)


def save_error_log(message, level, link_id=None, extra_data=None, timestamp=None, preset_id=None):
    """Hataları kalıcı dosyaya kaydet"""
    try:
        errors = load_json(ERRORS_FILE, default=[])
        if not isinstance(errors, list):
            errors = []

        error_entry = {
            "timestamp": timestamp or datetime.now().isoformat(),
            "level": level,
            "message": message,
            "link_id": link_id,
            "preset_id": preset_id,
            "extra_data": extra_data
        }

        errors.append(error_entry)

        # Son 500 hatayı tut
        if len(errors) > 500:
            errors = errors[-500:]

        save_json(ERRORS_FILE, errors)
    except Exception as e:
        print(f"Hata kaydedilemedi: {e}")


def load_json(path, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default


def save_json(path, data):
    try:
        temp = path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(path):
            os.remove(path)
        os.rename(temp, path)
        return True
    except Exception as e:
        add_log(f"Dosya kaydetme hatası ({path}): {e}", "error")
        return False


# =============================================================================
# PRESET BAZLI İSTATİSTİKLER
# =============================================================================

def load_preset_stats():
    """Preset istatistiklerini yükle"""
    with PRESET_STATS_LOCK:
        return load_json(PRESET_STATS_FILE, default={})


def save_preset_stats(stats):
    """Preset istatistiklerini kaydet"""
    with PRESET_STATS_LOCK:
        return save_json(PRESET_STATS_FILE, stats)


def get_preset_stats(preset_id):
    """Belirli bir preset'in istatistiklerini getir"""
    stats = load_preset_stats()
    return stats.get(preset_id, {
        'created': 0,
        'deleted': 0,
        'errors': 0,
        'active': 0,
        'last_scan': None,
        'last_created': None
    })


def update_preset_stat(preset_id, stat_type, increment=1):
    """
    Preset istatistiğini güncelle
    
    Args:
        preset_id: Preset ID
        stat_type: 'created', 'deleted', 'errors', 'scanned'
        increment: Artış miktarı (varsayılan: 1)
    """
    with PRESET_STATS_LOCK:
        stats = load_json(PRESET_STATS_FILE, default={})
        
        if preset_id not in stats:
            stats[preset_id] = {
                'created': 0,
                'deleted': 0,
                'errors': 0,
                'active': 0,
                'scanned': 0,
                'last_scan': None,
                'last_created': None
            }
        
        if stat_type in stats[preset_id]:
            stats[preset_id][stat_type] += increment
        
        # Timestamp güncelle
        if stat_type == 'created':
            stats[preset_id]['last_created'] = datetime.now().isoformat()
        
        stats[preset_id]['last_updated'] = datetime.now().isoformat()
        
        save_json(PRESET_STATS_FILE, stats)


def update_preset_scan_time(preset_id):
    """Preset'in son tarama zamanını güncelle"""
    with PRESET_STATS_LOCK:
        stats = load_json(PRESET_STATS_FILE, default={})
        
        if preset_id not in stats:
            stats[preset_id] = {
                'created': 0,
                'deleted': 0,
                'errors': 0,
                'active': 0,
                'scanned': 0,
                'last_scan': None,
                'last_created': None
            }
        
        stats[preset_id]['last_scan'] = datetime.now().isoformat()
        save_json(PRESET_STATS_FILE, stats)


def recalculate_preset_active_counts():
    """
    links.json'dan tüm preset'lerin aktif ilan sayısını yeniden hesapla
    Başlangıçta veya tutarsızlık durumunda çağrılır
    """
    links = load_json(LINKS_FILE)
    stats = load_preset_stats()
    
    # Tüm preset'lerin active count'unu sıfırla
    for preset_id in stats:
        stats[preset_id]['active'] = 0
    
    # links.json'dan aktif ilanları say
    for game, game_data in links.items():
        if not isinstance(game_data, dict):
            continue
        for link_id, link_data in game_data.get('links', {}).items():
            if link_data.get('status') == 'active':
                preset_id = link_data.get('preset_id')
                if preset_id:
                    if preset_id not in stats:
                        stats[preset_id] = {
                            'created': 0,
                            'deleted': 0,
                            'errors': 0,
                            'active': 0,
                            'scanned': 0,
                            'last_scan': None,
                            'last_created': None
                        }
                    stats[preset_id]['active'] += 1
    
    save_preset_stats(stats)
    return stats


def get_all_preset_stats_with_names():
    """
    Tüm preset istatistiklerini preset isimleriyle birlikte getir
    UI için kullanışlı format
    """
    stats = load_preset_stats()
    config = load_json(CONFIG_FILE)
    
    # Preset isimlerini eşle
    preset_names = {p['id']: p['name'] for p in config.get('presets', [])}
    
    result = []
    for preset_id, preset_stats in stats.items():
        result.append({
            'id': preset_id,
            'name': preset_names.get(preset_id, 'Bilinmeyen Preset'),
            'stats': preset_stats
        })
    
    # Config'de olup stats'ta olmayan preset'leri de ekle
    for preset in config.get('presets', []):
        if preset['id'] not in stats:
            result.append({
                'id': preset['id'],
                'name': preset['name'],
                'stats': {
                    'created': 0,
                    'deleted': 0,
                    'errors': 0,
                    'active': 0,
                    'scanned': 0,
                    'last_scan': None,
                    'last_created': None
                }
            })
    
    return result


# =============================================================================
# BAŞARISIZ İLAN RETRY KUYRUĞU
# =============================================================================

def load_failed_queue():
    """Başarısız ilanlar kuyruğunu yükle"""
    with FAILED_QUEUE_LOCK:
        data = load_json(FAILED_QUEUE_FILE, default={'items': [], 'updated_at': None})
        if not isinstance(data, dict) or 'items' not in data:
            data = {'items': data if isinstance(data, list) else [], 'updated_at': None}
        if not isinstance(data['items'], list):
            data['items'] = []
        return data


def save_failed_queue(queue_data):
    """Başarısız ilanlar kuyruğunu kaydet"""
    with FAILED_QUEUE_LOCK:
        queue_data['updated_at'] = datetime.now().isoformat()
        return save_json(FAILED_QUEUE_FILE, queue_data)


def add_to_failed_queue(link_id, url, game, preset_id, preset_name, error_message=None):
    """
    Başarısız ilanı retry kuyruğuna ekle
    
    Args:
        link_id: İlan ID
        url: GamerMarkt URL
        game: Oyun adı
        preset_id: Preset ID
        preset_name: Preset adı
        error_message: Hata mesajı (opsiyonel)
    """
    with FAILED_QUEUE_LOCK:
        queue = load_json(FAILED_QUEUE_FILE, default={'items': [], 'updated_at': None})
        if not isinstance(queue, dict) or 'items' not in queue:
            queue = {'items': queue if isinstance(queue, list) else [], 'updated_at': None}
        if not isinstance(queue['items'], list):
            queue['items'] = []

        # Zaten kuyrukta mı kontrol et
        existing = None
        for item in queue['items']:
            if item['link_id'] == link_id:
                existing = item
                break
        
        if existing:
            # Deneme sayısını artır
            existing['retry_count'] = existing.get('retry_count', 0) + 1
            existing['last_error'] = error_message
            existing['last_attempt'] = datetime.now().isoformat()
        else:
            # Yeni kayıt ekle
            queue['items'].append({
                'link_id': link_id,
                'url': url,
                'game': game,
                'preset_id': preset_id,
                'preset_name': preset_name,
                'retry_count': 1,
                'first_error': error_message,
                'last_error': error_message,
                'added_at': datetime.now().isoformat(),
                'last_attempt': datetime.now().isoformat()
            })
        
        queue['updated_at'] = datetime.now().isoformat()
        save_json(FAILED_QUEUE_FILE, queue)
        add_log(f"Retry kuyruğuna eklendi: {link_id} (deneme: {existing['retry_count'] if existing else 1})", "info")


def remove_from_failed_queue(link_id):
    """Başarılı olan ilanı kuyruktan kaldır"""
    with FAILED_QUEUE_LOCK:
        queue = load_json(FAILED_QUEUE_FILE, default={'items': [], 'updated_at': None})
        if not isinstance(queue, dict) or 'items' not in queue:
            queue = {'items': queue if isinstance(queue, list) else [], 'updated_at': None}
        if not isinstance(queue['items'], list):
            queue['items'] = []

        original_count = len(queue['items'])
        queue['items'] = [item for item in queue['items'] if item['link_id'] != link_id]
        
        if len(queue['items']) < original_count:
            queue['updated_at'] = datetime.now().isoformat()
            save_json(FAILED_QUEUE_FILE, queue)
            add_log(f"Retry kuyruğundan kaldırıldı (başarılı): {link_id}", "success")
            return True
        return False


def get_retry_items(preset_id=None, max_items=10):
    """
    Retry edilecek ilanları getir
    
    Args:
        preset_id: Sadece belirli preset için (opsiyonel)
        max_items: Maksimum kaç ilan döndürülsün
    
    Returns:
        Retry edilecek ilanlar listesi
    """
    queue = load_failed_queue()
    items = queue.get('items', [])
    
    # Maksimum deneme sayısını aşmamış olanları filtrele
    eligible = [item for item in items if item.get('retry_count', 0) < MAX_RETRY_ATTEMPTS]
    
    # Preset filtresi
    if preset_id:
        eligible = [item for item in eligible if item.get('preset_id') == preset_id]
    
    # En eski denemeden başla (FIFO)
    eligible.sort(key=lambda x: x.get('last_attempt', ''))
    
    return eligible[:max_items]


def mark_as_permanently_failed(link_id, reason=None):
    """
    İlanı kalıcı olarak başarısız işaretle (MAX_RETRY_ATTEMPTS aşıldı)
    """
    with FAILED_QUEUE_LOCK:
        queue = load_json(FAILED_QUEUE_FILE, default={'items': [], 'updated_at': None})
        if not isinstance(queue, dict) or 'items' not in queue:
            queue = {'items': queue if isinstance(queue, list) else [], 'updated_at': None}
        if not isinstance(queue['items'], list):
            queue['items'] = []

        for item in queue['items']:
            if item['link_id'] == link_id:
                item['permanently_failed'] = True
                item['failed_reason'] = reason or f"Maksimum deneme sayısı aşıldı ({MAX_RETRY_ATTEMPTS})"
                item['failed_at'] = datetime.now().isoformat()
                break
        
        queue['updated_at'] = datetime.now().isoformat()
        save_json(FAILED_QUEUE_FILE, queue)
        add_log(f"Kalıcı başarısız: {link_id} - {reason}", "warning")


def get_failed_queue_stats():
    """Retry kuyruğu istatistikleri"""
    queue = load_failed_queue()
    items = queue.get('items', [])
    
    pending = [i for i in items if not i.get('permanently_failed') and i.get('retry_count', 0) < MAX_RETRY_ATTEMPTS]
    failed = [i for i in items if i.get('permanently_failed') or i.get('retry_count', 0) >= MAX_RETRY_ATTEMPTS]
    
    return {
        'total': len(items),
        'pending_retry': len(pending),
        'permanently_failed': len(failed),
        'by_preset': {}
    }


def get_chrome_version():
    """Sistemdeki Chrome sürümünü tespit et"""
    try:
        import subprocess
        # Windows
        result = subprocess.run(
            ['reg', 'query', 'HKEY_CURRENT_USER\\Software\\Google\\Chrome\\BLBeacon', '/v', 'version'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            version = result.stdout.strip().split()[-1]
            return int(version.split('.')[0])
    except:
        pass

    # Fallback
    return None  # Auto-detect


# =============================================================================
# DELIVERY UPDATE WORKER
# =============================================================================

def delivery_worker():
    """Tek bir thread'de delivery güncellemelerini işler"""
    # Başlangıçta persistent queue'dan yükle
    with delivery_queue_lock:
        pending = load_delivery_queue()
        for offer_id in pending:
            # Zaten güncellendiyse atla
            if not is_delivery_already_updated(offer_id):
                delivery_queue.put(offer_id)
            else:
                add_log(f"Delivery zaten tamamlanmış, kuyruktan çıkarıldı: {offer_id}", "info")
        if pending:
            add_log(f"Restart sonrası {len(pending)} delivery işlemi kontrol edildi", "info")

    while True:
        try:
            offer_id = delivery_queue.get()
            if offer_id is None:  # Shutdown signal
                break

            # Tekrar kontrol et - başka bir işlem güncellemiş olabilir
            if is_delivery_already_updated(offer_id):
                add_log(f"Delivery zaten güncellendi, atlanıyor: {offer_id}", "info")
                # Persistent queue'dan kaldır
                with delivery_queue_lock:
                    pending = load_delivery_queue()
                    if offer_id in pending:
                        pending.remove(offer_id)
                        save_delivery_queue(pending)
                delivery_queue.task_done()
                continue

            try:
                with TimeoutLock(delivery_lock, timeout=LOCK_TIMEOUT, name="delivery_lock"):
                    add_log(f"Delivery güncelleme: {offer_id}", "info")
                    try:
                        time.sleep(3)  # İlan sistemde otursun
                        # chrome_init_lock'u geçir (WinError 183 önleme)
                        updater = G2GDeliveryUpdater(chrome_init_lock=chrome_init_lock)
                        result = updater.auto_update_after_creation(offer_id)
                        if result.get('success'):
                            add_log(f"Delivery OK: {offer_id}", "success")
                            # Başarılı güncellemeyi işaretle
                            mark_delivery_updated(offer_id)
                            # SADECE başarılı olursa kuyruktan kaldır
                            with delivery_queue_lock:
                                pending = load_delivery_queue()
                                if offer_id in pending:
                                    pending.remove(offer_id)
                                    save_delivery_queue(pending)
                        else:
                            add_log(f"Delivery FAIL: {offer_id} - 60 saniye sonra tekrar denenecek", "warning")
                            # Başarısız - 60 saniye sonra tekrar kuyruğa ekle
                            def retry_delivery(oid):
                                time.sleep(60)
                                if not is_delivery_already_updated(oid):
                                    delivery_queue.put(oid)
                                    add_log(f"Delivery retry kuyruğa eklendi: {oid}", "info")
                            retry_thread = threading.Thread(target=retry_delivery, args=(offer_id,), daemon=True)
                            retry_thread.start()

                    except Exception as e:
                        add_log(f"Delivery hata: {e}", "error")
                        # Hata durumunda queue'da kalacak, restart sonrası tekrar denenir
            except TimeoutError as te:
                add_log(f"Delivery lock timeout: {te}", "error")

            delivery_queue.task_done()
        except Exception as e:
            add_log(f"Delivery worker hatası: {e}", "error")


def is_delivery_already_updated(offer_id):
    """Bu offer için delivery zaten güncellendi mi kontrol et"""
    offers = g2g_api.load_g2g_offers()
    offer_data = offers.get(offer_id, {})
    return offer_data.get('delivery_updated', False)


def mark_delivery_updated(offer_id):
    """Offer'ın delivery güncellemesini tamamlandı olarak işaretle"""
    offers = g2g_api.load_g2g_offers()
    if offer_id in offers:
        offers[offer_id]['delivery_updated'] = True
        offers[offer_id]['delivery_updated_at'] = datetime.now().isoformat()
        g2g_api.save_g2g_offers(offers)


def update_delivery_safe(offer_id):
    """Delivery güncelleme kuyruğuna ekle (persistent) - duplicate kontrolü ile"""
    # Zaten güncellendi mi kontrol et
    if is_delivery_already_updated(offer_id):
        add_log(f"Delivery zaten güncellendi, atlanıyor: {offer_id}", "info")
        return

    # Önce persistent storage'a kaydet
    with delivery_queue_lock:
        pending = load_delivery_queue()
        if offer_id not in pending:
            pending.append(offer_id)
            save_delivery_queue(pending)

    # Sonra in-memory queue'ya ekle
    delivery_queue.put(offer_id)



# =============================================================================
# DETAY ÇEKME
# =============================================================================

def get_listing_details_via_selenium(driver, url, game):
    """V3'teki ultra_detail_scraper mantığını kullanarak detay çeker"""
    try:
        en_url = uds.convert_to_english_url(url)
        add_log(f"Detay sayfasına gidiliyor: {en_url}", "info")

        # Doğru pencereye geç - scraper penceresini öne getir
        try:
            current_handle = driver.current_window_handle
            driver.switch_to.window(current_handle)
            # Pencereyi öne getir
            driver.execute_script("window.focus();")
        except Exception as focus_err:
            add_log(f"⚠️ Pencere odaklama hatası (devam ediliyor): {focus_err}", "warning")

        # Cloudflare bypass ile sayfayı aç (her Chrome yeni açıldığı için bypass şart)
        # Retry mekanizması: timeout veya "Response not received" gelirse tekrar dene
        for _nav_attempt in range(3):
            try:
                driver.google_get(en_url, bypass_cloudflare=True)
                break  # Başarılı
            except Exception as nav_err:
                err_msg = str(nav_err).lower()
                if ('response not received' in err_msg or 'timeout' in err_msg) and _nav_attempt < 2:
                    add_log(f"⚠️ Navigasyon timeout (deneme {_nav_attempt+1}/3), tekrar deneniyor...", "warning")
                    time.sleep(3)
                    continue
                raise  # Son denemede veya farklı hatada yukarı fırlat

        bring_chrome_to_front(driver)

        # Sayfa yüklenmesi için 5 saniye bekle
        add_log("⏳ Sayfa yükleniyor (5 saniye)...", "info")
        time.sleep(5)

        # Sayfanın doğru gamermarkt detay sayfası olduğunu doğrula
        current_url = driver.current_url
        if 'gamermarkt' not in current_url.lower():
            add_log(f"❌ Yanlış sayfa açık! Beklenen: gamermarkt, Mevcut: {current_url}", "error")
            # Tekrar CF bypass ile git
            driver.google_get(en_url, bypass_cloudflare=True)
            time.sleep(5)
            current_url = driver.current_url
            if 'gamermarkt' not in current_url.lower():
                add_log(f"❌ Gamermarkt sayfası açılamadı: {current_url}", "error")
                return {}

        add_log(f"✅ Gamermarkt detay sayfası doğrulandı: {current_url}", "info")

        # Cloudflare kontrolü - hala CF sayfasındaysa bypass ile tekrar dene
        page_html = driver.page_source
        page_title_lower = driver.title.lower()
        if ('just a moment' in page_title_lower or 'attention required' in page_title_lower
                or 'checking your browser' in page_html.lower()):
            add_log("⏳ Cloudflare challenge tespit edildi, bypass ile tekrar deneniyor...", "warning")
            driver.google_get(en_url, bypass_cloudflare=True)
            time.sleep(8)
            page_html = driver.page_source  # Tekrar al

        if len(page_html) < 5000:
            add_log(f"❌ Sayfa yüklenemedi ({len(page_html)} byte)", "error")
            return {}

        dummy_listing = {'id': 'temp', 'url': url, 'category': game.title() if game != 'cs2' else 'CS2'}

        add_log(f"📊 Oyun detayları çekiliyor: {game}", "info")
        if game == 'cs2':
            return uds.scrape_cs2_details(driver, dummy_listing)
        elif game == 'fortnite':
            return uds.scrape_fortnite_details(driver, dummy_listing)
        elif game == 'lol':
            return uds.scrape_lol_details(driver, dummy_listing)
        elif game == 'valorant':
            return uds.scrape_valorant_details(driver, dummy_listing)

        return {}
    except Exception as e:
        add_log(f"❌ Detay çekme hatası: {e}", "error")
        import traceback
        traceback.print_exc()
        return {}


# =============================================================================
# AI İÇERİK OLUŞTURMA
# =============================================================================

# Rate limiting için
ai_request_times = []
AI_RATE_LIMIT = 10  # Dakikada maksimum istek
AI_TIMEOUT = 30     # API timeout (saniye)


def check_ai_rate_limit():
    """Rate limit kontrolü - dakikada max AI_RATE_LIMIT istek"""
    global ai_request_times
    current_time = time.time()

    # 1 dakikadan eski istekleri temizle
    ai_request_times = [t for t in ai_request_times if current_time - t < 60]

    if len(ai_request_times) >= AI_RATE_LIMIT:
        wait_time = 60 - (current_time - ai_request_times[0])
        add_log(f"AI rate limit - {wait_time:.1f}s bekleniyor", "warning")
        return False, wait_time

    return True, 0


def extract_json_fields(text):
    """
    Bozuk JSON'dan title ve description çıkarmaya çalış.
    AI bazen yarım JSON döndürüyor (token limiti aşılınca).
    """
    import re
    
    result = {}
    
    # Title'ı regex ile bul
    title_match = re.search(r'"title"\s*:\s*"([^"]*)"', text)
    if title_match:
        result['title'] = title_match.group(1)
    
    # Description'ı regex ile bul (daha esnek - tamamlanmamış olabilir)
    desc_match = re.search(r'"description"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    if desc_match:
        desc = desc_match.group(1)
        # Escape karakterleri düzelt
        desc = desc.replace('\\n', '\n').replace('\\"', '"')
        # Çok kısa ise fallback
        if len(desc) > 50:
            result['description'] = desc
    
    return result if result.get('title') else None


# G2G Karakter Limitleri
G2G_TITLE_MAX = 128
G2G_DESCRIPTION_MAX = 5000

def truncate_ai_content(result):
    """
    AI yanıtını G2G karakter limitlerine göre kes.
    Title: max 128 karakter
    Description: max 5000 karakter
    """
    if not result:
        return result
    
    # Title truncate (128 karakter)
    if result.get('title'):
        title = result['title']
        if len(title) > G2G_TITLE_MAX:
            # Son kelimeyi kesmemek için son boşluğu bul
            truncated = title[:G2G_TITLE_MAX - 3]
            last_space = truncated.rfind(' ')
            if last_space > G2G_TITLE_MAX - 30:  # Çok fazla kesmemek için
                truncated = truncated[:last_space]
            result['title'] = truncated + '...'
    
    # Description truncate (5000 karakter)
    if result.get('description'):
        desc = result['description']
        if len(desc) > G2G_DESCRIPTION_MAX:
            # Son paragrafı kesmemek için son satır sonunu bul
            truncated = desc[:G2G_DESCRIPTION_MAX - 50]
            last_newline = truncated.rfind('\n')
            if last_newline > G2G_DESCRIPTION_MAX - 200:
                truncated = truncated[:last_newline]
            result['description'] = truncated + '\n\n...'
    
    return result


def get_turkish_fallback_content(title, price, details, game):
    """AI başarısız olduğunda Türkçe fallback içerik oluştur"""
    game_names = {
        'valorant': 'Valorant',
        'lol': 'League of Legends',
        'cs2': 'CS2',
        'fortnite': 'Fortnite'
    }
    game_name = game_names.get(game, game.title())

    # Detaylardan rank ve region çıkar
    rank = 'Unranked'
    region = ''

    if game == 'valorant' and 'valorant_account_details' in details:
        rank = details['valorant_account_details'].get('Rank', 'Unranked')
        region = details['valorant_account_details'].get('Region', '')
    elif game == 'lol' and 'lol_account_details' in details:
        rank = details['lol_account_details'].get('Rank (Solo/Duo)', 'Unranked')
        region = details['lol_account_details'].get('Server', '')
    elif game == 'cs2' and 'cs2_account_details' in details:
        rank = details['cs2_account_details'].get('Rank', 'Unranked')

    # Başlık oluştur (max 128 karakter)
    title_parts = [f"[{game_name}]"]
    if region:
        title_parts.append(f"[{region}]")
    if rank and rank.lower() != 'unranked':
        title_parts.append(rank)
    title_parts.append("Account - Instant Delivery")

    generated_title = " ".join(title_parts)[:G2G_TITLE_MAX]

    # Açıklama oluştur
    description = f"""
{game_name} Account For Sale

Account Details:
- Region/Server: {region or 'Check screenshots'}
- Rank: {rank}

What You Get:
- Full account access (email + password)
- All account credentials
- Instant delivery after payment

Important Notes:
- Change all credentials immediately after purchase
- Original email access included
- Safe and secure transaction

Contact me for any questions before purchase!
    """.strip()

    return {
        'title': generated_title,
        'description': description
    }


def load_prompts():
    """prompts.json'dan prompt şablonlarını yükler"""
    try:
        return load_json(PROMPTS_FILE)
    except Exception:
        return {}


def get_game_prompt(game):
    """prompts.json'dan oyuna ait varsayılan promptu döndürür"""
    prompts = load_prompts()
    return prompts.get(game) or prompts.get('default') or None


def generate_ai_listing(title, price, details, game, custom_prompt=None):
    """
    Gemini ile ilan metni oluşturur - timeout ve rate limit ile

    Args:
        title: Orijinal ilan başlığı
        price: Fiyat (TL)
        details: Detay bilgileri (dict)
        game: Oyun adı (valorant, lol, cs2, fortnite)
        custom_prompt: Kullanıcı tanımlı prompt şablonu (opsiyonel)
    """
    if not gemini_client:
        add_log("AI client yok - Türkçe fallback kullanılıyor", "info")
        return get_turkish_fallback_content(title, price, details, game)

    # Rate limit kontrolü
    can_proceed, wait_time = check_ai_rate_limit()
    if not can_proceed:
        add_log(f"AI rate limit aşıldı - fallback kullanılıyor", "warning")
        return get_turkish_fallback_content(title, price, details, game)

    details_str = json.dumps(details, ensure_ascii=False)

    # Custom prompt varsa onu kullan, yoksa prompts.json'dan oyun promptunu al
    if custom_prompt:
        prompt = replace_prompt_variables(custom_prompt, title, price, details, game)
    else:
        game_prompt = get_game_prompt(game)
        if game_prompt:
            prompt = replace_prompt_variables(game_prompt, title, price, details, game)
        else:
            # prompts.json'da da yoksa son çare basit prompt
            prompt = f"""
You are a professional G2G seller. Write a listing for:
Game: {game}
Original Title: {title}
Price (TL): {price}
Details: {details_str[:2500]}

STRICT CHARACTER LIMITS:
- title: MAXIMUM 128 characters. USE the full 128 characters to make the title as detailed and descriptive as possible. Do NOT cut short - include rank, region, skins, key features until you reach close to 128 chars.
- description: MAXIMUM 5000 characters. Write a comprehensive, detailed description.

Task:
1. Create a catchy English Title (use full 128 chars). Include Rank/Server/Key features. Do NOT end the title early - fill it with relevant details.
2. Create a detailed English Description (up to 5000 chars). Use emojis sparingly.

Output JSON ONLY: {{"title": "...", "description": "..."}}
"""

    try:
        import signal

        def timeout_handler(signum, frame):
            raise TimeoutError("AI API timeout")

        ai_request_times.append(time.time())

        try:
            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(AI_TIMEOUT)
        except (AttributeError, ValueError):
            pass

        try:
            resp = gemini_client.models.generate_content(model="gemini-3-flash-preview", contents=prompt)
            text = resp.text.replace('```json', '').replace('```', '').strip()
            
            # İlk olarak direkt parse dene
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                # JSON bozuksa regex ile title ve description çıkar
                result = extract_json_fields(text)
            
            if result and result.get('title'):
                # G2G karakter limitlerine göre kes
                result = truncate_ai_content(result)
                add_log(f"AI başlık: {result.get('title', '')[:50]}...", "info")
                return result
            else:
                add_log("AI geçerli içerik üretemedi - fallback kullanılıyor", "warning")
                return get_turkish_fallback_content(title, price, details, game)
        finally:
            try:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            except (AttributeError, ValueError, NameError):
                pass

    except TimeoutError:
        add_log(f"AI API timeout ({AI_TIMEOUT}s) - fallback kullanılıyor", "warning")
        return get_turkish_fallback_content(title, price, details, game)
    except json.JSONDecodeError as e:
        add_log(f"AI JSON parse hatası: {e} - fallback kullanılıyor", "warning")
        return get_turkish_fallback_content(title, price, details, game)
    except Exception as e:
        add_log(f"AI Hatası: {e} - fallback kullanılıyor", "warning")
        return get_turkish_fallback_content(title, price, details, game)


def replace_prompt_variables(prompt_template, title, price, details, game):
    """
    Prompt şablonundaki {değişken} placeholder'larını gerçek verilerle değiştirir.
    v3.xml prompt sistemi entegrasyonu.
    """
    import re

    prompt = prompt_template

    # Temel değişkenler
    prompt = prompt.replace('{title}', str(title or ''))
    prompt = prompt.replace('{price}', str(price or ''))
    prompt = prompt.replace('{game}', str(game or ''))
    prompt = prompt.replace('{category}', str(game or '').title())
    prompt = prompt.replace('{account_type}', 'Ranked Accounts')
    prompt = prompt.replace('{item_details}', json.dumps(details, ensure_ascii=False, indent=2)[:3000])

    # Valorant değişkenleri
    valorant_details = details.get('valorant_account_details', {})
    prompt = prompt.replace('{region}', str(valorant_details.get('Region', details.get('region', 'TR'))))
    prompt = prompt.replace('{rank}', str(valorant_details.get('Rank', details.get('rank', '-'))))
    prompt = prompt.replace('{act_rank}', str(valorant_details.get('Act Rank', '-')))
    prompt = prompt.replace('{level}', str(valorant_details.get('Level', details.get('level', '-'))))
    prompt = prompt.replace('{agents}', str(details.get('agents', valorant_details.get('Agents', '0'))))
    prompt = prompt.replace('{skins}', str(details.get('skins', valorant_details.get('Skins', '0'))))
    prompt = prompt.replace('{valorant_vp}', str(valorant_details.get('Valorant Points', '0')))
    prompt = prompt.replace('{valorant_rp}', str(valorant_details.get('Radianite Points', '0')))
    prompt = prompt.replace('{valorant_kc}', str(valorant_details.get('Kingdom Credits', '0')))
    prompt = prompt.replace('{valorant_country}', str(valorant_details.get('Account Creation Country', '-')))
    prompt = prompt.replace('{valorant_created_at}', str(valorant_details.get('Account Created At', '-')))

    # LoL değişkenleri
    lol_details = details.get('lol_account_details', {})
    prompt = prompt.replace('{lol_server}', str(lol_details.get('Server', details.get('region', 'TR'))))
    prompt = prompt.replace('{lol_level}', str(lol_details.get('Level', '-')))
    prompt = prompt.replace('{lol_honor}', str(lol_details.get('Honor', '-')))
    prompt = prompt.replace('{lol_solo_rank}', str(lol_details.get('Rank (Solo/Duo)', '-')))
    prompt = prompt.replace('{lol_flex_rank}', str(lol_details.get('Rank (Flex 5v5)', '-')))
    prompt = prompt.replace('{lol_season_reward}', str(lol_details.get('Season Reward (Solo/Duo)', '-')))
    prompt = prompt.replace('{lol_prev_season}', str(lol_details.get('Prev. Season (Solo/Duo)', '-')))
    prompt = prompt.replace('{lol_profile_banner}', str(lol_details.get('Profile Banner', '-')))
    prompt = prompt.replace('{lol_rp}', str(lol_details.get('Riot Points', '0')))
    prompt = prompt.replace('{lol_be}', str(lol_details.get('Blue Essence', '0')))
    prompt = prompt.replace('{lol_creation_country}', str(lol_details.get('Creation Country', '-')))
    prompt = prompt.replace('{lol_created_at}', str(lol_details.get('Created At', '-')))
    prompt = prompt.replace('{champions}', str(details.get('champions', lol_details.get('Champions', '0'))))

    # Fortnite değişkenleri
    fortnite_details = details.get('fortnite_account_details', {})

    # Parse "Account": "Level 1723" -> "1723"
    account_level = fortnite_details.get('Account', '')
    if 'Level' in str(account_level):
        level_match = re.search(r'Level\s*(\d+)', str(account_level))
        account_level = level_match.group(1) if level_match else '-'
    prompt = prompt.replace('{level}', str(account_level) if account_level else str(details.get('level', '-')))

    # Parse "First": "Played Season Season 3" -> "3"
    first_season = fortnite_details.get('First', '')
    if 'Season' in str(first_season):
        season_match = re.search(r'Season\s*(\d+)', str(first_season))
        first_season = season_match.group(1) if season_match else '-'
    prompt = prompt.replace('{first_season}', str(first_season))

    # Parse "Current": "V-Buck Amount 50" -> "50"
    vbucks = fortnite_details.get('Current', '')
    if 'V-Buck' in str(vbucks):
        vbucks_match = re.search(r'(\d+)', str(vbucks))
        vbucks = vbucks_match.group(1) if vbucks_match else '0'
    prompt = prompt.replace('{vbucks}', str(vbucks))

    # Parse "Total": "Item Number 16" -> "16"
    total_items = fortnite_details.get('Total', '')
    if 'Item' in str(total_items):
        total_match = re.search(r'(\d+)', str(total_items))
        total_items = total_match.group(1) if total_match else '0'
    prompt = prompt.replace('{total_items}', str(total_items))

    # Parse "Not": "Connected Platforms Xbox, PSN, Nintendo" -> "Xbox, PSN, Nintendo"
    platforms = fortnite_details.get('Not', '')
    if 'Connected Platforms' in str(platforms):
        platforms = str(platforms).replace('Connected Platforms', '').strip()
    prompt = prompt.replace('{connected_platforms}', str(platforms))

    # Outfit count
    outfits = details.get('outfits', [])
    prompt = prompt.replace('{outfits_count}', str(len(outfits) if isinstance(outfits, list) else 0))

    # CS2 değişkenleri
    cs2_details = details.get('cs2_account_details', {})
    prompt = prompt.replace('{prime}', str(cs2_details.get('Is CS2 Prime?', '-')))
    prompt = prompt.replace('{cs2_level}', str(cs2_details.get('CS2 Level', '-')))
    prompt = prompt.replace('{faceit_connection}', str(cs2_details.get('Faceit Connection', '-')))
    prompt = prompt.replace('{faceit_level}', str(cs2_details.get('Faceit Level', '-')))
    prompt = prompt.replace('{vac_ban}', str(cs2_details.get('Vac/Overwatch Ban', '-')))
    prompt = prompt.replace('{community_ban}', str(cs2_details.get('Community Ban', '-')))
    prompt = prompt.replace('{trade_ban}', str(cs2_details.get('Trade Ban', '-')))

    # CS2 Item değişkenleri
    prompt = prompt.replace('{float}', str(details.get('float_value', details.get('float', '-'))))
    stickers = details.get('stickers', [])
    prompt = prompt.replace('{stickers}', ', '.join(stickers) if isinstance(stickers, list) else str(stickers))
    prompt = prompt.replace('{seller_reliability}', str(details.get('seller_reliability', '-')))

    return prompt


# =============================================================================
# YENİ İLAN İŞLEME
# =============================================================================

def cleanup_chromedriver_cache():
    """
    ChromeDriver cache dosyalarını temizle - WinError 183 çözümü

    undetected_chromedriver şu işlemi yapar:
    chromedriver-win32/chromedriver.exe -> undetected_chromedriver.exe (rename)

    İki Chrome aynı anda başlarsa bu rename işlemi çakışır.
    Bu fonksiyon hedef dosyayı silerek çakışmayı önler.
    """
    try:
        import shutil
        cache_dir = os.path.join(os.environ.get('APPDATA', ''), 'undetected_chromedriver')
        if os.path.exists(cache_dir):
            undetected_dir = os.path.join(cache_dir, 'undetected')
            if os.path.exists(undetected_dir):
                # 1. Kaynak klasörü sil (chromedriver-win32)
                win32_dir = os.path.join(undetected_dir, 'chromedriver-win32')
                if os.path.exists(win32_dir):
                    try:
                        shutil.rmtree(win32_dir)
                    except:
                        pass

                # 2. Hedef dosyayı sil (undetected_chromedriver.exe) - ÖNEMLİ!
                target_exe = os.path.join(undetected_dir, 'undetected_chromedriver.exe')
                if os.path.exists(target_exe):
                    try:
                        os.remove(target_exe)
                    except:
                        pass
    except:
        pass


def process_new_listing(link_id, url, game, preset_id, preset_name, custom_prompt=None, profit_margin=None):
    """Yeni ilanı işle: Detay -> AI -> G2G -> Kaydet

    Args:
        custom_prompt: Kullanıcı tanımlı AI prompt şablonu (opsiyonel)
        profit_margin: Kar marjı çarpanı (opsiyonel, varsayılan 1.45)
    """
    # Varsayılan kar marjı
    if profit_margin is None:
        profit_margin = 1.45

    # Durdurulmuşsa hiç başlama
    with state_lock:
        if not scraper_state['running']:
            return False

    title = "Game Account"
    price_tl = 0.0
    details = {}

    # PROFİL KİLİDİ: Detay çekme sırasında başka kimse tarayıcıyı kullanamaz
    # Timeout mekanizması ile deadlock önleme
    try:
        with TimeoutLock(scraper_lock, timeout=LOCK_TIMEOUT, name="scraper_lock"):
            driver = None

            try:
                # KRİTİK: Chrome başlatma için kısa süreli ortak lock (WinError 183 önleme)
                with TimeoutLock(chrome_init_lock, timeout=CHROME_INIT_TIMEOUT, name="chrome_init_lock"):
                    # Botasaurus Bridge ile Cloudflare bypass destekli tarayıcı başlat
                    driver = BotasaurusBridge(lang="en", profile="detay")
                    driver.maximize_window()
                # chrome_init_lock burada serbest bırakıldı, Chrome çalışmaya devam ediyor
                register_active_driver(driver, "detay")

                # Detayları çek
                details = get_listing_details_via_selenium(driver, url, game)

                # get_listing_details_via_selenium {} döndürdüyse sayfa sorunu var
                if not details:
                    add_log("❌ Detay çekme başarısız, işlem iptal ediliyor", "error", preset_id=preset_id)
                    return False

                # Sayfa içeriğini al
                add_log(f"Detaylar çekildi, sayfa içeriği alınıyor...", "info")
                time.sleep(1)

                page_html = driver.page_source
                if len(page_html) < 5000:
                    add_log(f"❌ Sayfa yüklenemedi ({len(page_html)} byte), işlem iptal ediliyor", "error", preset_id=preset_id)
                    return False

                # Fiyat ve Başlık al
                soup = BeautifulSoup(page_html, 'html.parser')
                title_el = soup.find('h1')
                title = title_el.get_text(strip=True) if title_el else "Game Account"

                # Güçlendirilmiş fiyat çıkarma (v3 uyumlu) - GELİŞTİRİLMİŞ
                price_tl = 0.0
                import re

                # Yöntem 1: CSS Selector ile (v3'teki gibi virgülle ayrılmış - OR mantığı)
                price_selectors = [
                    '.fw-600', '.price', '.text-primary', '.text-danger', '.product-price',
                    '.listing-price', '.item-price', '[class*="price"]', '.fw-bold',
                    'span.text-dark.fw-500', 'div.text-dark.fw-500'
                ]
                for selector in price_selectors:
                    if price_tl >= 10:
                        break
                    try:
                        price_els = soup.select(selector)
                        for price_el in price_els:
                            price_text = price_el.get_text(strip=True)
                            # ₺ sembolü içeriyorsa fiyat elementi
                            if '₺' in price_text or 'TL' in price_text:
                                # TR formatı: "₺ 1.234,56" veya "1.234,56 ₺"
                                price_text = price_text.replace('₺', '').replace('TL', '').strip()
                                if ',' in price_text:
                                    # TR format: nokta binlik, virgül ondalık
                                    price_text = price_text.replace('.', '').replace(',', '.')
                                try:
                                    candidate = float(price_text)
                                    if 10 <= candidate <= 100000:
                                        price_tl = candidate
                                        add_log(f"Fiyat bulundu (selector {selector}): {price_tl} TL", "info")
                                        break
                                except:
                                    pass
                    except:
                        continue

                # Yöntem 2: Regex ile tüm sayfadan çek - GELİŞTİRİLMİŞ
                if price_tl < 10:
                    page_text = driver.page_source
                    # GamerMarkt fiyat formatları:
                    # - "₺ 234,00" veya "234,00 ₺"
                    # - "₺234" veya "234₺"
                    # - "₺ 1.234,56" (binlik ayracı ile)
                    price_patterns = [
                        r'₺\s*([\d.]+[,]\d{2})',           # ₺ 234,00 veya ₺ 1.234,56
                        r'([\d.]+[,]\d{2})\s*₺',           # 234,00 ₺
                        r'₺\s*(\d+)',                       # ₺234 (ondalıksız)
                        r'(\d+)\s*₺',                       # 234₺ (ondalıksız)
                        r'(\d{2,})[,.](\d{2})\s*(?:TL|₺)',  # 234,00 TL veya 234.00 ₺
                        r'(?:TL|₺)\s*(\d{2,})[,.](\d{2})',  # TL 234,00
                        r'"price"[:\s]*["\']?(\d+(?:[.,]\d+)?)',  # JSON formatı "price": 234.00
                    ]

                    for pattern in price_patterns:
                        if price_tl >= 10:
                            break
                        matches = re.findall(pattern, page_text, re.IGNORECASE)
                        for match in matches:
                            try:
                                if isinstance(match, tuple):
                                    # İki gruplu pattern (tamsayı, ondalık)
                                    if len(match) == 2 and match[1]:
                                        price_str = f"{match[0]}.{match[1]}"
                                    else:
                                        price_str = match[0] if match[0] else match[1]
                                else:
                                    price_str = match

                                if price_str:
                                    # TR formatını çevir
                                    price_str = str(price_str).replace('.', '').replace(',', '.')
                                    # Çift nokta düzeltme
                                    if price_str.count('.') > 1:
                                        parts = price_str.rsplit('.', 1)
                                        price_str = parts[0].replace('.', '') + '.' + parts[1]

                                    candidate = float(price_str)
                                    # Minimum 10 TL, maksimum 100000 TL (mantıklı aralık)
                                    if 10 <= candidate <= 100000:
                                        price_tl = candidate
                                        add_log(f"Fiyat bulundu (regex): {price_tl} TL", "info")
                                        break
                            except:
                                continue

                # Yöntem 3: data-price attribute
                if price_tl < 10:
                    data_price_el = soup.select_one('[data-price]')
                    if data_price_el:
                        try:
                            price_tl = float(data_price_el.get('data-price', 0))
                            if price_tl >= 10:
                                add_log(f"Fiyat bulundu (data-price): {price_tl} TL", "info")
                        except:
                            pass

                # Yöntem 4: Meta tag veya script içinden
                if price_tl < 10:
                    # Schema.org price
                    meta_price = soup.find('meta', {'property': 'product:price:amount'})
                    if meta_price:
                        try:
                            price_tl = float(meta_price.get('content', 0))
                            if price_tl >= 10:
                                add_log(f"Fiyat bulundu (meta): {price_tl} TL", "info")
                        except:
                            pass

                if price_tl < 10:
                    add_log(f"Fiyat bulunamadı veya çok düşük ({link_id})", "warning", preset_id=preset_id)
                    # Debug: Sayfanın tam yüklenmesi için bekle, sonra HTML kaydet
                    add_log(f"⏳ Debug HTML için sayfa bekleniyor (10 saniye)...", "info")
                    time.sleep(10)
                    try:
                        debug_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_html")
                        os.makedirs(debug_dir, exist_ok=True)
                        debug_file = os.path.join(debug_dir, f"debug_price_{link_id}.html")
                        with open(debug_file, 'w', encoding='utf-8') as f:
                            f.write(driver.page_source)
                        add_log(f"Debug HTML kaydedildi: {debug_file}", "info")
                    except:
                        pass

            except Exception as e:
                add_log(f"Detay çekme hatası ({link_id}): {e}", "error", preset_id=preset_id)
                return False
            finally:
                if driver:
                    unregister_active_driver(driver)
                    try:
                        driver.quit()
                    except:
                        pass

    except TimeoutError as te:
        add_log(f"Scraper lock timeout ({link_id}): {te}", "error", preset_id=preset_id)
        return False
    except Exception as e:
        add_log(f"İşleme hatası ({link_id}): {e}", "error", preset_id=preset_id)
        return False

    # --- Tarayıcı kapandı, kilit serbest ---

    if price_tl <= 0:
        add_log(f"Geçersiz fiyat ({link_id}): {price_tl}", "warning", preset_id=preset_id)
        return False

    # Item Data hazırla
    item_data = {
        'id': link_id,
        'title': title,
        'price': str(price_tl),
        'game': game,
        'category': game.title() if game != 'cs2' else 'CS2',
        'region': 'TR'
    }

    # Detaylardan verileri işle
    if game == 'valorant' and 'valorant_account_details' in details:
        item_data['region'] = details['valorant_account_details'].get('Region', 'TR')
        item_data['rank'] = details['valorant_account_details'].get('Rank', 'Unranked')
        raw_agents = details.get('agents', details.get('agent_names', 0))
        raw_skins = details.get('skins', details.get('skin_details', 0))
        item_data['agents'] = len(raw_agents) if isinstance(raw_agents, list) else int(raw_agents or 0)
        item_data['skins'] = len(raw_skins) if isinstance(raw_skins, list) else int(raw_skins or 0)
        add_log(f"Valorant skin/agent sayısı - skins: {item_data['skins']}, agents: {item_data['agents']}", "info")

        # Valorant: Türkiye dışı hesapları atla
        country = details['valorant_account_details'].get('Account Creation Country', '').strip()
        if country and country.lower() not in ('turkey', 'türkiye', 'tr', 'turkiye'):
            add_log(f"Valorant hesap ülkesi Türkiye değil ({country}), atlanıyor: {link_id}", "warning", preset_id=preset_id)
            return False

    elif game == 'lol' and 'lol_account_details' in details:
        item_data['region'] = details['lol_account_details'].get('Server', 'TR')
        item_data['rank'] = details['lol_account_details'].get('Rank (Solo/Duo)', 'Unranked')
        raw_champs = details.get('champions', [])
        raw_skins = details.get('skins', [])
        item_data['champions'] = len(raw_champs) if isinstance(raw_champs, list) else int(raw_champs or 0)
        item_data['skins'] = len(raw_skins) if isinstance(raw_skins, list) else int(raw_skins or 0)
        add_log(f"LoL skin/champion sayısı - skins: {item_data['skins']}, champions: {item_data['champions']}", "info")

    elif game == 'cs2' and 'cs2_account_details' in details:
        item_data['rank'] = details['cs2_account_details'].get('Rank', 'Unranked')

    elif game == 'fortnite' and 'fortnite_account_details' in details:
        item_data['outfits'] = len(details.get('outfits', []))
        item_data['pickaxes'] = len(details.get('pickaxes', []))

    # Preset filtre doğrulaması - uyumsuz ilanları oluşturma
    if not validate_listing_against_filters(item_data, game, preset_id):
        add_log(f"İlan preset filtrelerine uymuyor, atlanıyor: {link_id}", "warning", preset_id=preset_id)
        return False

    # AI İçerik oluştur (hata durumunda None döner, fallback kullanılır)
    ai_content = None
    try:
        ai_content = generate_ai_listing(title, price_tl, details, game, custom_prompt)
    except Exception as e:
        add_log(f"AI içerik oluşturma hatası: {e}", "warning", preset_id=preset_id)

    # G2G'ye yükle (AI içerik ile birlikte) - retry mekanizması ile
    offer_id = None
    for attempt in range(3):
        try:
            offer_id = g2g_api.create_g2g_offer(link_id, item_data, details, game, ai_content, profit_margin)
            if offer_id:
                break
        except Exception as e:
            add_log(f"G2G oluşturma hatası (deneme {attempt + 1}/3): {e}", "error", preset_id=preset_id)
            if attempt < 2:
                time.sleep(5 * (attempt + 1))  # Backoff: 5s, 10s

    if offer_id:
        # Delivery Update kuyruğuna ekle (sadece yeni offer için, quantity artırıldıysa atla)
        # Quantity artırıldıysa delivery zaten yapılmış demektir
        if not is_delivery_already_updated(offer_id):
            update_delivery_safe(offer_id)
        else:
            add_log(f"Mevcut offer'a stok eklendi, delivery atlandı: {offer_id}", "info")

        # links.json'a kaydet
        links = load_json(LINKS_FILE)
        if game not in links:
            links[game] = {"links": {}}

        links[game]['links'][link_id] = {
            'url': url,
            'g2g_offer_id': offer_id,
            'preset_id': preset_id,
            'preset_name': preset_name,
            'status': 'active',
            'created_at': time.time(),
            'last_seen': time.time(),
            'missing_count': 0
        }
        save_json(LINKS_FILE, links)

        # ultra_details.json'a kaydet
        ultra_db = load_json(ULTRA_DETAILS_FILE)
        ultra_db[link_id] = {**details, 'basic_info': item_data}
        save_json(ULTRA_DETAILS_FILE, ultra_db)

        # Preset istatistiklerini güncelle
        update_preset_stat(preset_id, 'created', 1)
        update_preset_stat(preset_id, 'active', 1)
        
        # Başarılı oldu - retry kuyruğundan kaldır (eğer varsa)
        remove_from_failed_queue(link_id)

        add_log(f"Oluşturuldu: {link_id} -> {offer_id}", "success")
        return True

    # Hata durumunda preset stats güncelle ve retry kuyruğuna ekle
    update_preset_stat(preset_id, 'errors', 1)
    add_to_failed_queue(link_id, url, game, preset_id, preset_name, "G2G oluşturma başarısız")
    add_log(f"G2G oluşturma başarısız: {link_id}", "error", preset_id=preset_id)
    return False


# =============================================================================
# SİLME MEKANİZMASI
# =============================================================================

def check_and_delete_missing_links(game, found_link_ids, preset_id):
    """
    DEPRECATED: Bu fonksiyon artık kullanılmıyor.
    Silme işlemi verify_links_loop() tarafından yapılıyor.
    Geriye dönük uyumluluk için bırakıldı.
    """
    return 0


def _check_and_delete_missing_links_original(game, found_link_ids, preset_id):
    """
    Bulunamayan linkleri tespit et ve gerekirse G2G'den sil.
    Varsayılan: 1 döngü sonra silinir (yapılandırılabilir).

    Silinen veriler:
    - G2G API'den ilan
    - g2g_offers.json'dan offer kaydı
    - links.json'dan link (status: deleted)
    - ultra_details.json'dan detaylar
    """
    links = load_json(LINKS_FILE)
    config = load_json(CONFIG_FILE)

    # Yapılandırılabilir threshold (varsayılan: MISSING_THRESHOLD sabiti)
    threshold = config.get('global_settings', {}).get('missing_threshold', MISSING_THRESHOLD)

    if game not in links:
        return 0

    deleted_count = 0
    current_time = time.time()
    deleted_link_ids = []  # Silinen link ID'lerini takip et

    # Bu preset'e ait tüm aktif linkleri kontrol et
    for link_id, link_data in list(links[game].get('links', {}).items()):
        # Sadece bu preset'e ait olanları kontrol et
        if link_data.get('preset_id') != preset_id:
            continue

        if link_data.get('status') != 'active':
            continue

        # Bu link bu taramada bulundu mu?
        if link_id in found_link_ids:
            # Bulundu - last_seen güncelle, missing_count sıfırla
            links[game]['links'][link_id]['last_seen'] = current_time
            links[game]['links'][link_id]['missing_count'] = 0
        else:
            # Bulunamadı - missing_count artır
            current_missing = link_data.get('missing_count', 0) + 1
            links[game]['links'][link_id]['missing_count'] = current_missing

            add_log(f"Link bulunamadı ({current_missing}/{threshold}): {link_id}", "warning", preset_id=preset_id)

            # Eşik aşıldıysa sil
            if current_missing >= threshold:
                offer_id = link_data.get('g2g_offer_id')

                if offer_id:
                    add_log(f"G2G'den siliniyor: {offer_id}", "info")

                    # Silme işlemi için retry mekanizması
                    delete_success = False
                    for attempt in range(3):
                        try:
                            result = g2g_api.delete_offer(offer_id)
                            if result.get('success'):
                                delete_success = True
                                break
                            else:
                                add_log(f"Silme hatası (deneme {attempt + 1}/3): {result.get('error')}", "warning", preset_id=preset_id)
                        except Exception as e:
                            add_log(f"Silme exception (deneme {attempt + 1}/3): {e}", "error", preset_id=preset_id)

                        if attempt < 2:
                            time.sleep(2)

                    if delete_success:
                        links[game]['links'][link_id]['status'] = 'deleted'
                        links[game]['links'][link_id]['deleted_at'] = current_time
                        deleted_count += 1
                        deleted_link_ids.append(link_id)
                        add_log(f"Silindi: {link_id}", "success")
                        
                        # Preset istatistiklerini güncelle
                        link_preset_id = link_data.get('preset_id')
                        if link_preset_id:
                            update_preset_stat(link_preset_id, 'deleted', 1)
                            update_preset_stat(link_preset_id, 'active', -1)
                        
                        # g2g_offers.json'dan da sil
                        try:
                            offers = g2g_api.load_g2g_offers()
                            if offer_id in offers:
                                del offers[offer_id]
                                g2g_api.save_g2g_offers(offers)
                        except Exception as e:
                            add_log(f"g2g_offers.json temizleme hatası: {e}", "warning", preset_id=preset_id)
                    else:
                        add_log(f"Silme başarısız (tüm denemeler): {link_id}", "error", preset_id=preset_id)
                else:
                    # G2G offer ID yoksa sadece durumu güncelle
                    links[game]['links'][link_id]['status'] = 'deleted'
                    links[game]['links'][link_id]['deleted_at'] = current_time
                    deleted_link_ids.append(link_id)
                    
                    # Preset istatistiklerini güncelle
                    link_preset_id = link_data.get('preset_id')
                    if link_preset_id:
                        update_preset_stat(link_preset_id, 'deleted', 1)
                        update_preset_stat(link_preset_id, 'active', -1)
                    
                    add_log(f"Link silindi (G2G ID yok): {link_id}", "info")

    save_json(LINKS_FILE, links)
    
    # ultra_details.json'dan silinen linklerin detaylarını temizle
    if deleted_link_ids:
        try:
            ultra_details = load_json(ULTRA_DETAILS_FILE)
            details_deleted = 0
            for link_id in deleted_link_ids:
                if link_id in ultra_details:
                    del ultra_details[link_id]
                    details_deleted += 1
            if details_deleted > 0:
                save_json(ULTRA_DETAILS_FILE, ultra_details)
                add_log(f"ultra_details.json'dan {details_deleted} kayıt silindi", "info")
        except Exception as e:
            add_log(f"ultra_details.json temizleme hatası: {e}", "warning")
    
    return deleted_count


# =============================================================================
# TEMİZ SİLME FONKSİYONU
# =============================================================================

def _delete_link_completely(link_id, game, offer_id, preset_id):
    """
    Bir linki tüm JSON dosyalarından ve G2G API'den tamamen siler.

    Adımlar:
    1. G2G API'den ilan sil
    2. g2g_offers.json'dan offer kaydını sil
    3. links.json'dan linki tamamen sil (status değil, DEL)
    4. ultra_details.json'dan detayları sil
    5. failed_queue.json'dan filtrele
    6. errors.json'dan filtrele
    7. delivery_queue.json'dan filtrele
    8. Preset istatistiklerini güncelle
    """
    try:
        # 1. G2G API'den sil
        if offer_id:
            try:
                result = g2g_api.delete_offer(offer_id)
                if result.get('success'):
                    add_log(f"[VERIFY] G2G'den silindi: {offer_id}", "success")
                else:
                    add_log(f"[VERIFY] G2G silme uyarısı ({offer_id}): {result.get('error')}", "warning")
            except Exception as e:
                add_log(f"[VERIFY] G2G silme hatası ({offer_id}): {e}", "warning")

        # 2. g2g_offers.json'dan sil
        if offer_id:
            try:
                offers = g2g_api.load_g2g_offers()
                if offer_id in offers:
                    del offers[offer_id]
                    g2g_api.save_g2g_offers(offers)
            except Exception as e:
                add_log(f"[VERIFY] g2g_offers.json temizleme hatası: {e}", "warning")

        # 3. links.json'dan linki tamamen sil
        try:
            links = load_json(LINKS_FILE)
            if game in links and 'links' in links[game] and link_id in links[game]['links']:
                del links[game]['links'][link_id]
                save_json(LINKS_FILE, links)
        except Exception as e:
            add_log(f"[VERIFY] links.json temizleme hatası: {e}", "warning")

        # 4. ultra_details.json'dan sil
        try:
            ultra_details = load_json(ULTRA_DETAILS_FILE)
            if link_id in ultra_details:
                del ultra_details[link_id]
                save_json(ULTRA_DETAILS_FILE, ultra_details)
        except Exception as e:
            add_log(f"[VERIFY] ultra_details.json temizleme hatası: {e}", "warning")

        # 5. failed_queue.json'dan filtrele
        try:
            failed_queue = load_json(FAILED_QUEUE_FILE)
            if isinstance(failed_queue, dict) and 'items' in failed_queue:
                original = len(failed_queue['items'])
                failed_queue['items'] = [
                    item for item in failed_queue['items']
                    if item.get('link_id') != link_id
                ]
                if len(failed_queue['items']) < original:
                    failed_queue['updated_at'] = datetime.now().isoformat()
                    save_json(FAILED_QUEUE_FILE, failed_queue)
        except Exception as e:
            add_log(f"[VERIFY] failed_queue.json temizleme hatası: {e}", "warning")

        # 6. errors.json'dan filtrele
        try:
            errors_data = load_json(ERRORS_FILE, default=[])
            if isinstance(errors_data, list):
                original = len(errors_data)
                errors_data = [
                    e for e in errors_data
                    if not (isinstance(e, dict) and e.get('link_id') == link_id)
                ]
                if len(errors_data) < original:
                    save_json(ERRORS_FILE, errors_data)
        except Exception as e:
            add_log(f"[VERIFY] errors.json temizleme hatası: {e}", "warning")

        # 7. delivery_queue.json'dan filtrele (offer_id bazlı)
        if offer_id:
            try:
                with delivery_queue_lock:
                    pending = load_delivery_queue()
                    if offer_id in pending:
                        pending.remove(offer_id)
                        save_delivery_queue(pending)
            except Exception as e:
                add_log(f"[VERIFY] delivery_queue.json temizleme hatası: {e}", "warning")

        # 8. Preset istatistiklerini güncelle
        if preset_id:
            try:
                update_preset_stat(preset_id, 'deleted', 1)
                update_preset_stat(preset_id, 'active', -1)
            except Exception as e:
                add_log(f"[VERIFY] Preset stat güncelleme hatası: {e}", "warning")

        add_log(f"[VERIFY] Temiz silme tamamlandı: {link_id}", "success")
        return True

    except Exception as e:
        add_log(f"[VERIFY] _delete_link_completely hatası ({link_id}): {e}", "error")
        return False


# =============================================================================
# LİNK DOĞRULAMA DÖNGÜSÜ (BACKGROUND THREAD)
# =============================================================================

def verify_links_loop():
    """
    Tüm aktif linkleri doğrulayan sonsuz arka plan döngüsü.
    - Her link için Chrome açılır, CF bypass yapılır, kontrol edilir, Chrome kapatılır
    - Detay scraper ile birebir aynı yaklaşım (her link = yeni Chrome)
    - ultra_details.json'daki sold_or_removed=True olanlar da silinir
    - Tüm linkler bittikten sonra bekleme yok, döngü başa döner
    """
    add_log("[VERIFY] Doğrulama thread'i başlatıldı", "info")

    while True:
        # Bot durdurulduysa thread'den çık
        with state_lock:
            running = scraper_state['running']
        if not running:
            add_log("[VERIFY] Bot durduruldu, doğrulama thread'i kapanıyor", "info")
            return

        try:
            # --- ultra_details.json'daki sold_or_removed=True olanları sil ---
            try:
                ultra_details = load_json(ULTRA_DETAILS_FILE)
                links_data = load_json(LINKS_FILE)

                for ud_link_id, detail in list(ultra_details.items()):
                    if not detail.get('sold_or_removed'):
                        continue

                    # links.json'dan game ve preset_id bul
                    found_game = None
                    found_offer_id = None
                    found_preset_id = None
                    for g, gd in links_data.items():
                        if not isinstance(gd, dict):
                            continue
                        link_entry = gd.get('links', {}).get(ud_link_id)
                        if link_entry:
                            found_game = g
                            found_offer_id = link_entry.get('g2g_offer_id')
                            found_preset_id = link_entry.get('preset_id')
                            break

                    if found_game:
                        add_log(f"[VERIFY] sold_or_removed=True, siliniyor: {ud_link_id}", "info")
                        _delete_link_completely(ud_link_id, found_game, found_offer_id, found_preset_id)
                    else:
                        # links.json'da yok ama ultra_details'da var → sadece ultra_details'dan sil
                        try:
                            ud = load_json(ULTRA_DETAILS_FILE)
                            if ud_link_id in ud:
                                del ud[ud_link_id]
                                save_json(ULTRA_DETAILS_FILE, ud)
                        except Exception:
                            pass
            except Exception as e:
                add_log(f"[VERIFY] sold_or_removed tarama hatası: {e}", "warning")

            # --- Aktif linkleri topla ---
            links_data = load_json(LINKS_FILE)
            active_links = []
            for g, gd in links_data.items():
                if not isinstance(gd, dict):
                    continue
                for lid, ldata in gd.get('links', {}).items():
                    if ldata.get('status') == 'active':
                        active_links.append({
                            'link_id': lid,
                            'game': g,
                            'url': ldata.get('url', ''),
                            'offer_id': ldata.get('g2g_offer_id'),
                            'preset_id': ldata.get('preset_id'),
                        })

            if not active_links:
                time.sleep(5)
                continue

            verify_total = len(active_links)
            verify_ok = 0
            verify_deleted = 0
            verify_failed = 0
            add_log(f"[VERIFY] ========== Doğrulama turu başlıyor: {verify_total} link ==========", "info")

            for link_idx, link_info in enumerate(active_links, 1):
                # Her link öncesi running kontrolü - bot durdurulduysa hemen çık
                with state_lock:
                    if not scraper_state['running']:
                        add_log("[VERIFY] Bot durduruldu, link kontrolü kesiliyor", "info")
                        break

                link_id = link_info['link_id']
                game = link_info['game']
                url = link_info['url']
                offer_id = link_info['offer_id']
                preset_id = link_info['preset_id']

                if not url:
                    continue

                add_log(f"[VERIFY] [{link_idx}/{verify_total}] Kontrol ediliyor: {link_id}", "info")

                # --- Her link için yeni Chrome aç (detay scraper ile aynı) ---
                driver = None
                try:
                    # chrome_init_lock: sadece Chrome başlatma anında çakışma önleme
                    # Farklı profiller (verify vs detay) kullanıldığı için aynı anda çalışabilirler
                    with TimeoutLock(chrome_init_lock, timeout=60, name="verify_chrome_init"):
                        driver = BotasaurusBridge(lang="en", profile="verify")
                        driver.maximize_window()
                    register_active_driver(driver, "verify")

                    # Cloudflare bypass ile sayfayı aç (her Chrome yeni açıldığı için bypass şart)
                    en_url = uds.convert_to_english_url(url)
                    # Retry mekanizması: timeout veya "Response not received" gelirse tekrar dene
                    nav_success = False
                    for _nav_attempt in range(3):
                        try:
                            driver.google_get(en_url, bypass_cloudflare=True)
                            nav_success = True
                            break
                        except Exception as nav_err:
                            err_msg = str(nav_err).lower()
                            if ('response not received' in err_msg or 'timeout' in err_msg) and _nav_attempt < 2:
                                add_log(f"[VERIFY] Navigasyon timeout (deneme {_nav_attempt+1}/3), tekrar deneniyor: {url}", "warning")
                                time.sleep(3)
                                continue
                            raise
                    if not nav_success:
                        add_log(f"[VERIFY] [{link_idx}/{verify_total}] ⛔ TIMEOUT: {link_id} - 3 denemede sayfa açılamadı", "warning")
                        verify_failed += 1
                        continue
                    time.sleep(5)

                    bring_chrome_to_front(driver)

                    page_html  = driver.page_source
                    page_lower = page_html.lower()
                    page_title = driver.title.lower()

                    # Cloudflare kontrolü
                    is_cloudflare = (
                        'just a moment' in page_title
                        or 'attention required' in page_title
                        or 'checking your browser' in page_lower
                        or ('cloudflare' in page_lower and 'challenge' in page_lower)
                    )
                    if is_cloudflare:
                        add_log(f"[VERIFY] CF challenge tespit edildi, bypass ile tekrar deneniyor: {url}", "warning")
                        driver.google_get(en_url, bypass_cloudflare=True)
                        time.sleep(8)
                        page_html = driver.page_source
                        page_lower = page_html.lower()
                        page_title = driver.title.lower()

                        still_cf = 'just a moment' in page_title or 'attention required' in page_title
                        if still_cf:
                            add_log(f"[VERIFY] [{link_idx}/{verify_total}] ⛔ CF GEÇİLEMEDİ: {link_id} - Cloudflare aşılamadı", "warning")
                            verify_failed += 1
                            continue

                    # Sayfa çok küçükse - atla
                    if len(page_html) < 5000:
                        add_log(f"[VERIFY] Sayfa çok küçük ({len(page_html)} byte), atlanıyor: {url}", "warning")
                        continue

                    # İlan sayfası doğrulama
                    has_price = '₺' in page_html or 'TL' in page_html
                    has_title = '<h1' in page_lower
                    has_gamermarkt = 'gamermarkt' in page_lower

                    if not has_gamermarkt:
                        add_log(f"[VERIFY] GamerMarkt sayfası değil, atlanıyor: {url}", "warning")
                        continue

                    # Kesin satılmış/kaldırılmış metin kontrolü
                    is_invalid = (
                        'sold out' in page_lower
                        or 'no longer available' in page_lower
                        or 'bu ilan mevcut değil' in page_lower
                        or page_title in ('404', '404 not found', 'sayfa bulunamadı', 'page not found')
                        or 'sayfa bulunamadı' in page_lower
                        or 'page not found' in page_lower
                        or 'ilan bulunamadı' in page_lower
                    )

                    if is_invalid:
                        add_log(f"[VERIFY] [{link_idx}/{verify_total}] ❌ SİLİNDİ: {link_id} - İlan geçersiz/satılmış ({url})", "warning")
                        _delete_link_completely(link_id, game, offer_id, preset_id)
                        verify_deleted += 1
                    elif has_price and has_title:
                        add_log(f"[VERIFY] [{link_idx}/{verify_total}] ✅ AKTİF: {link_id} - Hala duruyor ({url})", "info")
                        verify_ok += 1
                    else:
                        add_log(f"[VERIFY] [{link_idx}/{verify_total}] ⚠️ BELİRSİZ: {link_id} (fiyat:{has_price}, başlık:{has_title})", "warning")
                        verify_failed += 1

                except Exception as e:
                    add_log(f"[VERIFY] [{link_idx}/{verify_total}] ⛔ HATA: {link_id} - {e}", "warning")
                    verify_failed += 1
                    continue
                finally:
                    # Her link sonrası Chrome'u kapat (detay scraper ile aynı)
                    if driver:
                        unregister_active_driver(driver)
                        try:
                            driver.quit()
                        except Exception:
                            pass
                    # Linkler arası bekleme - sistem kaynaklarını rahatlatmak için
                    time.sleep(3)

            # Tur sonu özeti
            add_log(f"[VERIFY] ========== Tur tamamlandı: ✅ {verify_ok} aktif | ❌ {verify_deleted} silindi | ⚠️ {verify_failed} hata/belirsiz | Toplam: {verify_total} ==========", "info")

        except Exception as outer_e:
            add_log(f"[VERIFY] Döngü hatası: {outer_e}", "error")
            time.sleep(5)


# =============================================================================
# ANA WORKER DÖNGÜSÜ
# =============================================================================

def preset_worker():
    print("🚀 preset_worker BAŞLADI!", flush=True)
    try:
        add_log("Otomasyon servisi başlatıldı", "success")

        while True:
            with state_lock:
                if not scraper_state['running']:
                    print("⛔ running=False, döngüden çıkılıyor", flush=True)
                    break

            config = load_json(CONFIG_FILE)
            active_presets = [p for p in config.get('presets', []) if p.get('active')]
            print(f"📋 Aktif preset sayısı: {len(active_presets)}", flush=True)

            if not active_presets:
                with state_lock:
                    scraper_state['status'] = "Aktif preset yok"
                print("⚠️ Aktif preset yok, 5s bekleniyor...", flush=True)
                if not interruptible_sleep(5):
                    break
                continue

            # =================================================================
            # FAZ 1: TÜM PRESETLERİ TARA, SONUÇLARI TOPLA
            # =================================================================
            # Her preset için ayrı Chrome açılır/kapatılır.
            # GamerMarkt listeleme sayfaları auth gerektirmediği için
            # profil kullanılmaz, çakışma olmaz.

            # Silme kontrolünde yanlış silme olmaması için önce TÜM presetler
            # taranır, sonra silme ve oluşturma işlemleri yapılır.
            scan_results = []  # [(preset, found_link_ids, new_links, scan_success)]
            game_all_found_ids = {}  # {game: set()} - oyun bazlı birleşik bulunan ID'ler

            for preset in active_presets:
                print(f"🎮 [FAZ 1] Taranıyor: {preset['name']} ({preset['game']})", flush=True)
                with state_lock:
                    if not scraper_state['running']:
                        break
                    scraper_state['current_preset'] = preset['name']
                    scraper_state['status'] = "Taranıyor..."

                game = preset['game']

                try:
                    # Filtreleri scraper formatına çevir
                    scraper_filters = convert_filters_for_scraper(game, preset.get('filters', {}))
                    add_log(f"Filtreler: {scraper_filters}", "info")

                    # Her preset için temiz Chrome aç (profil yok, çakışma yok)
                    print(f"🔍 GamerMarktScraper başlatılıyor: {game}", flush=True)
                    gm_scraper = GamerMarktScraper(game, scraper_filters, chrome_init_lock=chrome_init_lock)

                    scraper_success = False
                    try:
                        scraper_success = gm_scraper.start()
                    except Exception as start_err:
                        add_log(f"Scraper start hatası: {start_err}", "error", preset_id=preset['id'])
                        scraper_success = False

                    if scraper_success:
                        found_links = list(gm_scraper.scraped_links)
                        gm_scraper.stop()  # Chrome'u kapat

                        # Başarılı oldu, hata sayacını sıfırla
                        if '_filter_fail_counts' in scraper_state:
                            scraper_state['_filter_fail_counts'][preset['id']] = 0

                        add_log(f"{preset['name']}: {len(found_links)} ilan bulundu", "info")

                        # Preset istatistiklerini güncelle
                        update_preset_scan_time(preset['id'])
                        update_preset_stat(preset['id'], 'scanned', len(found_links))

                        with state_lock:
                            scraper_state['stats']['total_scanned'] += len(found_links)
                            update_preset_session_stat(preset['id'], 'scanned', len(found_links))

                        # Link ID'lerini oluştur
                        links_db = load_json(LINKS_FILE)
                        if game not in links_db:
                            links_db[game] = {"links": {}}

                        new_links = []
                        found_link_ids = set()

                        existing_count = len(links_db.get(game, {}).get('links', {}))
                        add_log(f"links_db'de {existing_count} mevcut link var", "info")

                        for link in found_links:
                            # URL'den ID çıkar
                            link_id = link.split('-')[-1]
                            if not link_id.isdigit():
                                link_id = f"{game.upper()}_{hashlib.md5(link.encode()).hexdigest()[:12]}"
                            else:
                                link_id = f"{game.upper()}_{link_id}"

                            found_link_ids.add(link_id)

                            # Yeni mi kontrol et
                            existing = links_db[game]['links'].get(link_id)
                            if not existing or existing.get('status') == 'deleted':
                                new_links.append((link_id, link))
                            else:
                                add_log(f"Zaten mevcut: {link_id} (status: {existing.get('status')})", "info")

                        add_log(f"Sonuç: {len(found_links)} toplam, {len(new_links)} yeni, {len(found_links) - len(new_links)} zaten mevcut", "info")

                        # Bulunan ID'leri oyun bazlı birleştir
                        if game not in game_all_found_ids:
                            game_all_found_ids[game] = set()
                        game_all_found_ids[game].update(found_link_ids)

                        scan_results.append((preset, found_link_ids, new_links, True))
                    else:
                        # Başarısız - Chrome'u kapat
                        try:
                            gm_scraper.stop()
                        except:
                            pass

                        if '_filter_fail_counts' not in scraper_state:
                            scraper_state['_filter_fail_counts'] = {}
                        fail_key = preset['id']
                        scraper_state['_filter_fail_counts'][fail_key] = scraper_state['_filter_fail_counts'].get(fail_key, 0) + 1
                        fail_count = scraper_state['_filter_fail_counts'][fail_key]

                        add_log(f"Scraper başlatılamadı: {preset['name']} (üst üste {fail_count}. başarısız deneme)", "error", preset_id=preset['id'])
                        with state_lock:
                            scraper_state['stats']['errors'] += 1
                            update_preset_session_stat(preset['id'], 'errors', 1)

                        # Üst üste çok başarısız olduysa preseti bu turda atla
                        if fail_count >= 10:
                            add_log(f"{preset['name']} preseti {fail_count} kez üst üste başarısız oldu, bu turda atlanıyor", "warning", preset_id=preset['id'])
                            scan_results.append((preset, set(), [], False))
                            continue
                        elif fail_count >= 3:
                            extra_wait = min(fail_count * 30, 300)  # Max 5 dakika
                            add_log(f"Filtreler {fail_count} kez başarısız oldu, {extra_wait}s ekstra bekleme...", "warning", preset_id=preset['id'])
                            if not interruptible_sleep(extra_wait):
                                break

                        scan_results.append((preset, set(), [], False))

                except Exception as e:
                    add_log(f"Preset hatası ({preset['name']}): {e}", "error", preset_id=preset['id'])
                    import traceback
                    traceback.print_exc()
                    with state_lock:
                        scraper_state['stats']['errors'] += 1
                    scan_results.append((preset, set(), [], False))

                if not interruptible_sleep(5):
                    break

            # =================================================================
            # FAZ 2: SİLME KONTROLÜ + YENİ İLANLARI OLUŞTUR
            # =================================================================
            # Silme kontrolünde aynı oyundaki TÜM presetlerin birleşik
            # found_link_ids'i kullanılır. Böylece Preset A'nın oluşturduğu
            # bir link Preset B'nin taramasında bulunduysa silinmez.
            for preset, found_link_ids, new_links, scan_success in scan_results:
                with state_lock:
                    if not scraper_state['running']:
                        break
                    scraper_state['current_preset'] = preset['name']

                if not scan_success:
                    continue

                game = preset['game']

                # Silme kontrolü - birleşik found_link_ids kullan
                combined_found_ids = game_all_found_ids.get(game, set())
                min_results_for_delete = 5
                if len(combined_found_ids) >= min_results_for_delete:
                    with state_lock:
                        scraper_state['status'] = f"Silme kontrolü: {preset['name']}"
                    deleted = check_and_delete_missing_links(game, combined_found_ids, preset['id'])
                    if deleted > 0:
                        with state_lock:
                            scraper_state['stats']['deleted'] += deleted
                            update_preset_session_stat(preset['id'], 'deleted', deleted)
                elif len(combined_found_ids) == 0:
                    add_log(f"⚠️ Tarama 0 sonuç döndü, silme atlandı (site hatası olabilir)", "warning", preset_id=preset['id'])
                else:
                    add_log(f"⚠️ Tarama az sonuç döndü ({len(combined_found_ids)}), silme atlandı", "warning", preset_id=preset['id'])

                # Yeni ilanları işle
                for link_id, url in new_links:
                    with state_lock:
                        if not scraper_state['running']:
                            break
                        scraper_state['status'] = f"İşleniyor: {link_id}"

                    add_log(f"Yeni ilan: {link_id}", "info")

                    # Preset'teki custom_prompt ve profit_margin'i GÜNCEL config'den al
                    fresh_config = load_json(CONFIG_FILE)
                    fresh_preset = next((p for p in fresh_config.get('presets', []) if p['id'] == preset['id']), preset)
                    custom_prompt = fresh_preset.get('custom_prompt')
                    profit_margin = fresh_preset.get('profit_margin', 1.45)
                    if process_new_listing(link_id, url, game, preset['id'], preset['name'], custom_prompt, profit_margin):
                        with state_lock:
                            scraper_state['stats']['created'] += 1
                            update_preset_session_stat(preset['id'], 'created', 1)
                    else:
                        with state_lock:
                            scraper_state['stats']['errors'] += 1
                            update_preset_session_stat(preset['id'], 'errors', 1)

                    # İlanlar arası rastgele bekleme (Cloudflare için biraz daha uzun)
                    config = load_json(CONFIG_FILE)
                    min_delay = config.get('global_settings', {}).get('listing_delay_min', 8)
                    max_delay = config.get('global_settings', {}).get('listing_delay_max', 15)
                    if not interruptible_sleep(random.uniform(min_delay, max_delay)):
                        break

            # =================================================================
            # BAŞARISIZ İLANLARI TEKRAR DENE (RETRY QUEUE)
            # =================================================================
            retry_items = get_retry_items(max_items=5)  # Her döngüde max 5 retry
            if retry_items:
                add_log(f"🔄 Retry kuyruğundan {len(retry_items)} ilan tekrar deneniyor...", "info")
                with state_lock:
                    scraper_state['status'] = "Retry işlemi..."
                
                for item in retry_items:
                    with state_lock:
                        if not scraper_state['running']:
                            break
                    
                    link_id = item['link_id']
                    retry_count = item.get('retry_count', 0)
                    
                    # Maksimum deneme kontrolü
                    if retry_count >= MAX_RETRY_ATTEMPTS:
                        mark_as_permanently_failed(link_id, f"Maksimum deneme sayısı aşıldı ({MAX_RETRY_ATTEMPTS})")
                        continue
                    
                    add_log(f"🔄 Retry ({retry_count + 1}/{MAX_RETRY_ATTEMPTS}): {link_id}", "info")
                    
                    # İlanı tekrar işle - GÜNCEL config'den oku
                    custom_prompt = None
                    profit_margin = 1.45
                    retry_config = load_json(CONFIG_FILE)
                    for p in retry_config.get('presets', []):
                        if p['id'] == item.get('preset_id'):
                            custom_prompt = p.get('custom_prompt')
                            profit_margin = p.get('profit_margin', 1.45)
                            break

                    preset_id = item.get('preset_id')
                    if process_new_listing(
                        link_id,
                        item['url'],
                        item['game'],
                        preset_id,
                        item['preset_name'],
                        custom_prompt,
                        profit_margin
                    ):
                        with state_lock:
                            scraper_state['stats']['created'] += 1
                            if preset_id:
                                update_preset_session_stat(preset_id, 'created', 1)
                        # Başarılı - kuyruktan kaldırıldı (process_new_listing içinde)
                    else:
                        # Hata - retry count artırıldı (add_to_failed_queue içinde)
                        with state_lock:
                            if preset_id:
                                update_preset_session_stat(preset_id, 'errors', 1)
                    
                    # Retry'lar arası bekleme
                    if not interruptible_sleep(random.uniform(10, 15)):
                        break

            # Döngü sonu bekleme
            cycle_delay = config.get('global_settings', {}).get('cycle_delay', 60)
            with state_lock:
                scraper_state['status'] = f"Döngü beklemesi ({cycle_delay}s)"
            if not interruptible_sleep(cycle_delay):
                break

        with state_lock:
            scraper_state['status'] = "Durduruldu"
        add_log("Otomasyon servisi durduruldu", "warning")
    except Exception as e:
        print(f"❌ preset_worker HATA: {e}", flush=True)
        import traceback
        traceback.print_exc()
        with state_lock:
            scraper_state['running'] = False
            scraper_state['status'] = "Durduruldu"


# =============================================================================
# FLASK API
# =============================================================================

app = Flask(__name__)


# Manuel CORS desteği - tüm response'lara CORS header'ları ekle
@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


# OPTIONS istekleri için handler (preflight requests)
@app.route('/api/<path:path>', methods=['OPTIONS'])
def handle_options(path):
    response = make_response()
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/')
def index():
    try:
        return open('otomatize.html', 'r', encoding='utf-8').read()
    except:
        return "otomatize.html bulunamadı", 404


# Stats cache (her istekte dosya okumamak için)
_stats_cache = {"data": {}, "last_update": 0}

@app.route('/api/status')
def status():
    global _stats_cache
    # Binance'den güncellenen kuru kullan
    kur = load_kur()

    # Gerçek istatistikleri hesapla (10 saniyede bir güncelle)
    current_time = time.time()
    if current_time - _stats_cache["last_update"] > 10:
        try:
            # G2G offers'dan istatistikler
            offers = g2g_api.load_g2g_offers()
            total_offers = len(offers) if offers else 0
            delivery_completed = sum(1 for offer_data in offers.values()
                                    if isinstance(offer_data, dict) and offer_data.get('delivery_updated', False)) if offers else 0
            
            # Links'den istatistikler
            links = load_json(LINKS_FILE)
            total_active = 0
            total_deleted = 0
            for game_data in links.values():
                if isinstance(game_data, dict):
                    for link_data in game_data.get('links', {}).values():
                        if link_data.get('status') == 'active':
                            total_active += 1
                        elif link_data.get('status') == 'deleted':
                            total_deleted += 1
            
            _stats_cache["data"] = {
                "total_offers": total_offers,
                "delivery_completed": delivery_completed,
                "total_active_links": total_active,
                "total_deleted_links": total_deleted
            }
            _stats_cache["last_update"] = current_time
        except Exception as e:
            print(f"Stats hesaplama hatası: {e}")

    # Session stats + Gerçek stats birleştir
    real_stats = _stats_cache.get("data", {})
    
    # Session'dan gelen stats'ı gerçek değerlerle güncelle
    combined_stats = {
        "created": real_stats.get("total_offers", scraper_state['stats']['created']),
        "deleted": real_stats.get("total_deleted_links", scraper_state['stats']['deleted']),
        "errors": scraper_state['stats']['errors'],
        "total_scanned": scraper_state['stats']['total_scanned']
    }

    # Kar marjını al
    profit_margin = load_profit_margin()
    profit_percent = round((profit_margin - 1) * 100, 1)

    return jsonify({
        **scraper_state,
        "stats": combined_stats,
        "kur": kur,
        "profit_margin": profit_margin,
        "profit_percent": profit_percent,
        "delivery_completed": real_stats.get("delivery_completed", 0),
        "real_stats": real_stats  # Ekstra: Gerçek istatistikler
    })


@app.route('/api/presets', methods=['GET', 'POST'])
def presets_api():
    if request.method == 'GET':
        return jsonify(load_json(CONFIG_FILE))

    data = request.json

    # Validate and fix preset IDs
    import uuid
    presets = data.get('presets', [])
    for preset in presets:
        if not preset.get('id') or preset['id'] == '':
            preset['id'] = str(uuid.uuid4())
            add_log(f"Generated new ID for preset: {preset.get('name', 'unnamed')}", "info")

    data['presets'] = presets
    save_json(CONFIG_FILE, data)
    return jsonify({"success": True})


@app.route('/api/prompts', methods=['GET', 'POST'])
def prompts_api():
    """prompts.json okuma/yazma endpoint'i"""
    if request.method == 'GET':
        return jsonify(load_json(PROMPTS_FILE))

    data = request.json
    if not data or not isinstance(data, dict):
        return jsonify({"error": "Geçersiz veri"}), 400
    save_json(PROMPTS_FILE, data)
    return jsonify({"success": True})


@app.route('/api/presets/delete', methods=['POST'])
def delete_preset_with_data():
    """
    Preset silindiğinde ilgili tüm verileri temizle:
    - links.json'dan preset'e ait linkler
    - G2G API'den ilanları sil
    - g2g_offers.json'dan offer'lar
    - ultra_details.json'dan detaylar
    - preset_stats.json'dan istatistikler
    - failed_queue.json'dan başarısız ilanlar
    - errors.json'dan hata kayıtları
    - delivery_queue.json'dan teslimat kuyruğu
    """
    data = request.json
    preset_id = data.get('preset_id')

    if not preset_id:
        return jsonify({"success": False, "error": "preset_id gerekli"})

    add_log(f"Preset siliniyor ve veriler temizleniyor: {preset_id}", "info")

    deleted_links = 0
    errors = []

    try:
        # 1. Preset'e ait linkleri topla
        links = load_json(LINKS_FILE)
        links_to_delete = []
        g2g_offer_ids_to_delete = []

        for game, game_data in links.items():
            if not isinstance(game_data, dict):
                continue
            for link_id, link_data in list(game_data.get('links', {}).items()):
                if link_data.get('preset_id') == preset_id:
                    offer_id = link_data.get('g2g_offer_id')
                    links_to_delete.append((game, link_id, offer_id))
                    if offer_id:
                        g2g_offer_ids_to_delete.append(offer_id)

        add_log(f"Silinecek link sayısı: {len(links_to_delete)}", "info")

        # 2. Her linki merkezi silme fonksiyonu ile temizle
        #    preset_id=None geçiyoruz: stats tüm preset silineceği için güncellemeye gerek yok
        for game, link_id, offer_id in links_to_delete:
            ok = _delete_link_completely(link_id, game, offer_id, preset_id=None)
            if ok:
                deleted_links += 1

        # 3. preset_stats.json'dan istatistikleri tamamen sil
        try:
            preset_stats = load_json(PRESET_STATS_FILE)
            if preset_id in preset_stats:
                del preset_stats[preset_id]
                save_json(PRESET_STATS_FILE, preset_stats)
                add_log(f"Preset istatistikleri silindi: {preset_id}", "info")
        except Exception as e:
            errors.append(f"preset_stats.json temizleme hatası: {str(e)}")

        # 4. errors.json'dan preset_id bazlı kalan hataları temizle
        #    (_delete_link_completely link_id bazlı temizler; preset_id bazlı olanlar burada)
        try:
            errors_data = load_json(ERRORS_FILE, default=[])
            if isinstance(errors_data, list):
                original_count = len(errors_data)
                errors_data = [
                    e for e in errors_data
                    if not (isinstance(e, dict) and e.get('preset_id') == preset_id)
                ]
                if len(errors_data) < original_count:
                    save_json(ERRORS_FILE, errors_data)
        except Exception as e:
            errors.append(f"errors.json temizleme hatası: {str(e)}")

        # 5. In-memory delivery queue'yu temizle
        if g2g_offer_ids_to_delete:
            offer_ids_set = set(g2g_offer_ids_to_delete)
            cleaned_items = []
            try:
                while not delivery_queue.empty():
                    item = delivery_queue.get_nowait()
                    if item not in offer_ids_set:
                        cleaned_items.append(item)
                    delivery_queue.task_done()
            except Exception:
                pass
            for item in cleaned_items:
                delivery_queue.put(item)

        # 6. Config'den preset'i sil
        config = load_json(CONFIG_FILE)
        config['presets'] = [p for p in config.get('presets', []) if p.get('id') != preset_id]
        save_json(CONFIG_FILE, config)

        add_log(f"Preset silme tamamlandı - {deleted_links} link temizlendi", "success")

        return jsonify({
            "success": True,
            "deleted_links": deleted_links,
            "total_deleted": deleted_links,
            "errors": errors
        })

    except Exception as e:
        add_log(f"Preset silme hatası: {e}", "error")
        return jsonify({"success": False, "error": str(e)})


@app.route('/api/retry-queue')
def get_retry_queue():
    """
    Retry kuyruğundaki ilanları listele
    """
    queue = load_failed_queue()
    stats = get_failed_queue_stats()
    
    return jsonify({
        'success': True,
        'items': queue.get('items', []),
        'stats': stats,
        'max_retry_attempts': MAX_RETRY_ATTEMPTS
    })


@app.route('/api/retry-queue/retry/<link_id>', methods=['POST'])
def manual_retry(link_id):
    """
    Belirli bir ilanı manuel olarak tekrar dene
    """
    queue = load_failed_queue()
    
    target_item = None
    for item in queue.get('items', []):
        if item['link_id'] == link_id:
            target_item = item
            break
    
    if not target_item:
        return jsonify({'success': False, 'error': 'İlan bulunamadı'}), 404
    
    # Custom prompt ve profit_margin'ı bul
    config = load_json(CONFIG_FILE)
    custom_prompt = None
    profit_margin = 1.45
    for preset in config.get('presets', []):
        if preset['id'] == target_item.get('preset_id'):
            custom_prompt = preset.get('custom_prompt')
            profit_margin = preset.get('profit_margin', 1.45)
            break

    # İlanı işle
    success = process_new_listing(
        target_item['link_id'],
        target_item['url'],
        target_item['game'],
        target_item['preset_id'],
        target_item['preset_name'],
        custom_prompt,
        profit_margin
    )
    
    return jsonify({
        'success': success,
        'message': 'İlan başarıyla oluşturuldu' if success else 'İlan oluşturulamadı'
    })


@app.route('/api/retry-queue/remove/<link_id>', methods=['DELETE'])
def remove_retry_item(link_id):
    """
    İlanı retry kuyruğundan kaldır (tekrar deneme)
    """
    success = remove_from_failed_queue(link_id)
    return jsonify({
        'success': success,
        'message': 'Kuyruktan kaldırıldı' if success else 'İlan bulunamadı'
    })


@app.route('/api/retry-queue/clear', methods=['DELETE'])
def clear_retry_queue():
    """
    Tüm retry kuyruğunu temizle
    """
    try:
        save_failed_queue({'items': [], 'updated_at': None})
        add_log("Retry kuyruğu temizlendi", "info")
        return jsonify({'success': True, 'message': 'Kuyruk temizlendi'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/profit-margin', methods=['GET', 'POST'])
def profit_margin_api():
    """
    Kar marjı okuma ve kaydetme API'si
    GET: Mevcut kar marjını döndür
    POST: Yeni kar marjını kaydet
    """
    if request.method == 'GET':
        try:
            if os.path.exists(KUR_FILE):
                with open(KUR_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    margin = data.get('profit_margin', 1.45)
                    return jsonify({
                        'success': True,
                        'profit_margin': margin,
                        'profit_percent': round((margin - 1) * 100, 1)
                    })
            return jsonify({
                'success': True,
                'profit_margin': 1.45,
                'profit_percent': 45.0
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    # POST - Kar marjını kaydet
    try:
        data = request.json
        new_margin = data.get('profit_margin')

        if new_margin is None:
            return jsonify({'success': False, 'error': 'profit_margin gerekli'})

        new_margin = float(new_margin)

        # Geçerlilik kontrolü (1.0 - 3.0 arası, yani %0 - %200 kar)
        if new_margin < 1.0 or new_margin > 3.0:
            return jsonify({
                'success': False,
                'error': 'Kar marjı 1.0 (0%) ile 3.0 (200%) arasında olmalı'
            })

        # Mevcut kur.json'u oku ve güncelle
        kur_data = load_json(KUR_FILE, default={})

        kur_data['profit_margin'] = round(new_margin, 2)
        kur_data['margin_updated_at'] = datetime.now().isoformat()

        with open(KUR_FILE, 'w', encoding='utf-8') as f:
            json.dump(kur_data, f, indent=2)

        profit_percent = round((new_margin - 1) * 100, 1)
        add_log(f"Kar marjı güncellendi: %{profit_percent} ({new_margin}x)", "info")

        return jsonify({
            'success': True,
            'profit_margin': new_margin,
            'profit_percent': profit_percent,
            'message': f'Kar marjı %{profit_percent} olarak ayarlandı'
        })

    except ValueError:
        return jsonify({'success': False, 'error': 'Geçersiz sayı formatı'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/control', methods=['POST', 'OPTIONS'])
def control():
    print(f"🔥 /api/control çağrıldı - Method: {request.method}", flush=True)

    if request.method == 'OPTIONS':
        return jsonify({"success": True})

    action = request.json.get('action')
    print(f"🔥 Action: {action}, Current running: {scraper_state['running']}", flush=True)

    should_start = False
    should_stop = False

    with state_lock:
        if action == 'start' and not scraper_state['running']:
            scraper_state['running'] = True
            scraper_state['status'] = "Başlatılıyor..."
            scraper_state['stats'] = {"created": 0, "deleted": 0, "errors": 0, "total_scanned": 0}
            scraper_state['preset_session_stats'] = {}
            should_start = True

        elif action == 'stop' and scraper_state['running']:
            scraper_state['running'] = False
            scraper_state['status'] = "Durduruluyor..."
            should_stop = True

        elif action == 'kill':
            scraper_state['running'] = False
            scraper_state['status'] = "Sistem kapatılıyor..."

    if action == 'kill':
        add_log("⚠️ Sistem tamamen kapatılıyor (Ctrl+C)...", "warning")
        force_cleanup_chrome()
        add_log("🔴 Sistem kapatıldı", "error")
        # Ctrl+C sinyali gönder - tüm process'i öldür
        import signal
        os.kill(os.getpid(), signal.SIGTERM)
        return jsonify({"success": True})

    global _verify_thread, _worker_thread

    if should_stop:
        add_log("Bot durduruluyor...", "warning")

        # Thread'lerin running=False'u görmesini bekle (max 5sn)
        for old_thread, name in [(_verify_thread, "verify"), (_worker_thread, "worker")]:
            if old_thread and old_thread.is_alive():
                old_thread.join(timeout=5)

        # Thread'ler kapandıktan sonra artık Chrome'ları temizle
        force_cleanup_chrome()
        with state_lock:
            scraper_state['status'] = "Durduruldu"
        add_log("✅ Bot durduruldu, Chrome temizlendi", "success")

    if should_start:

        # Eski thread'lerin bitmesini bekle (max 10sn)
        for old_thread, name in [(_worker_thread, "worker"), (_verify_thread, "verify")]:
            if old_thread and old_thread.is_alive():
                print(f"⏳ Eski {name} thread bitmesi bekleniyor...", flush=True)
                old_thread.join(timeout=10)
                if old_thread.is_alive():
                    print(f"⚠️ Eski {name} thread hâlâ çalışıyor, zorla devam ediliyor", flush=True)

        # Başlatmadan önce eski Chrome artıklarını temizle
        force_cleanup_chrome()
        cleanup_chromedriver_cache()
        print("🔥 preset_worker thread başlatılıyor...", flush=True)
        _worker_thread = threading.Thread(target=preset_worker, daemon=True)
        _worker_thread.start()
        # Temizlik bittikten sonra verify thread'i başlat
        _verify_thread = threading.Thread(target=verify_links_loop, daemon=True)
        _verify_thread.start()
        start_chrome_rotation()
        add_log("Bot başlatıldı", "success")

    return jsonify({"success": True})



@app.route('/api/links')
def get_links():
    """Tüm linkleri döndür"""
    return jsonify(load_json(LINKS_FILE))


@app.route('/api/stats')
def get_stats():
    """Detaylı istatistikler"""
    links = load_json(LINKS_FILE)

    stats = {
        'by_game': {},
        'total_active': 0,
        'total_deleted': 0
    }

    for game, data in links.items():
        game_links = data.get('links', {})
        active = sum(1 for l in game_links.values() if l.get('status') == 'active')
        deleted = sum(1 for l in game_links.values() if l.get('status') == 'deleted')

        stats['by_game'][game] = {'active': active, 'deleted': deleted}
        stats['total_active'] += active
        stats['total_deleted'] += deleted

    return jsonify(stats)


@app.route('/api/preset-stats')
def get_preset_stats_api():
    """
    Preset bazlı istatistikler
    Her preset için: created, deleted, errors, active, scanned, last_scan
    """
    return jsonify({
        'success': True,
        'presets': get_all_preset_stats_with_names()
    })


@app.route('/api/preset-stats/<preset_id>')
def get_single_preset_stats(preset_id):
    """Tek bir preset'in istatistikleri"""
    stats = get_preset_stats(preset_id)
    config = load_json(CONFIG_FILE)
    
    # Preset ismini bul
    preset_name = None
    for p in config.get('presets', []):
        if p['id'] == preset_id:
            preset_name = p['name']
            break
    
    # Session stats'ı da ekle
    with state_lock:
        session_stats = scraper_state['preset_session_stats'].get(preset_id, {
            "created": 0,
            "deleted": 0,
            "errors": 0,
            "scanned": 0,
            "delivery_ok": 0
        })
    
    return jsonify({
        'success': True,
        'id': preset_id,
        'name': preset_name or 'Bilinmeyen Preset',
        'stats': stats,
        'session_stats': session_stats
    })


@app.route('/api/preset-session-stats')
def get_all_preset_session_stats():
    """Tüm presetlerin session istatistikleri"""
    config = load_json(CONFIG_FILE)
    
    result = []
    with state_lock:
        for preset in config.get('presets', []):
            preset_id = preset['id']
            session_stats = scraper_state['preset_session_stats'].get(preset_id, {
                "created": 0,
                "deleted": 0,
                "errors": 0,
                "scanned": 0,
                "delivery_ok": 0
            })
            result.append({
                'id': preset_id,
                'name': preset['name'],
                'game': preset.get('game'),
                'active': preset.get('active', False),
                'session_stats': session_stats
            })
    
    return jsonify({
        'success': True,
        'presets': result
    })


@app.route('/api/preset-stats/recalculate', methods=['POST'])
def recalculate_stats():
    """
    Tüm preset istatistiklerini links.json'dan yeniden hesapla
    Tutarsızlık durumunda kullanılır
    """
    try:
        stats = recalculate_preset_active_counts()
        return jsonify({
            'success': True,
            'message': 'İstatistikler yeniden hesaplandı',
            'stats': stats
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/cleanup', methods=['POST'])
def cleanup_orphan_data():
    """
    Tutarsız/yetim verileri temizle:
    - g2g_offers.json'da olup links.json'da olmayan offer'ları sil
    - ultra_details.json'da olup links.json'da olmayan detayları sil
    """
    try:
        links = load_json(LINKS_FILE)
        offers = g2g_api.load_g2g_offers()
        ultra_details = load_json(ULTRA_DETAILS_FILE)
        
        # Tüm aktif link ID'lerini topla
        active_link_ids = set()
        active_offer_ids = set()
        for game_data in links.values():
            if isinstance(game_data, dict):
                for link_id, link_data in game_data.get('links', {}).items():
                    if link_data.get('status') == 'active':
                        active_link_ids.add(link_id)
                        if link_data.get('g2g_offer_id'):
                            active_offer_ids.add(link_data.get('g2g_offer_id'))
        
        # Yetim offer'ları bul ve sil
        orphan_offers = []
        for offer_id, offer_data in list(offers.items()):
            source_link_id = offer_data.get('source_link_id')
            if source_link_id not in active_link_ids:
                orphan_offers.append(offer_id)
                del offers[offer_id]
        
        if orphan_offers:
            g2g_api.save_g2g_offers(offers)
            add_log(f"Temizlendi: {len(orphan_offers)} yetim offer (g2g_offers.json)", "info")
        
        # Yetim detayları bul ve sil
        orphan_details = []
        for link_id in list(ultra_details.keys()):
            if link_id not in active_link_ids:
                orphan_details.append(link_id)
                del ultra_details[link_id]
        
        if orphan_details:
            save_json(ULTRA_DETAILS_FILE, ultra_details)
            add_log(f"Temizlendi: {len(orphan_details)} yetim detay (ultra_details.json)", "info")
        
        return jsonify({
            "success": True,
            "cleaned": {
                "orphan_offers": len(orphan_offers),
                "orphan_details": len(orphan_details),
                "offer_ids": orphan_offers,
                "detail_ids": orphan_details
            }
        })
        
    except Exception as e:
        add_log(f"Cleanup hatası: {e}", "error")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/errors', methods=['GET', 'DELETE'])
def errors_api():
    """
    GET: Hata loglarını getir
    DELETE: Hata loglarını temizle
    
    Query params:
    - level: "error" veya "warning" (opsiyonel)
    - limit: Kaç hata döndürülsün (varsayılan: 50)
    """
    if request.method == 'GET':
        errors = load_json(ERRORS_FILE, default=[])
        
        # Filtreleme
        level_filter = request.args.get('level')
        if level_filter:
            errors = [e for e in errors if e.get('level') == level_filter]
        
        # Limit
        limit = int(request.args.get('limit', 50))
        
        # En son hatalar önce
        errors = list(reversed(errors))[:limit]
        
        # İstatistikler
        all_errors = load_json(ERRORS_FILE, default=[])
        stats = {
            "total": len(all_errors),
            "errors": sum(1 for e in all_errors if e.get('level') == 'error'),
            "warnings": sum(1 for e in all_errors if e.get('level') == 'warning')
        }
        
        return jsonify({
            "success": True,
            "errors": errors,
            "stats": stats
        })
    
    elif request.method == 'DELETE':
        # Hataları temizle
        save_json(ERRORS_FILE, [])
        add_log("Hata logları temizlendi", "info")
        return jsonify({"success": True, "message": "Hata logları temizlendi"})


@app.route('/api/errors/summary')
def errors_summary():
    """Hata özeti - bugün ve son 24 saat"""
    errors = load_json(ERRORS_FILE, default=[])
    
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday = now - timedelta(hours=24)
    
    # Bugünün hataları
    today_errors = []
    last_24h_errors = []
    
    for error in errors:
        try:
            error_time = datetime.fromisoformat(error.get('timestamp', ''))
            if error_time >= today_start:
                today_errors.append(error)
            if error_time >= yesterday:
                last_24h_errors.append(error)
        except:
            pass
    
    # En sık karşılaşılan hatalar
    from collections import Counter
    error_messages = [e.get('message', '')[:50] for e in errors if e.get('level') == 'error']
    common_errors = Counter(error_messages).most_common(5)
    
    return jsonify({
        "success": True,
        "summary": {
            "today": {
                "total": len(today_errors),
                "errors": sum(1 for e in today_errors if e.get('level') == 'error'),
                "warnings": sum(1 for e in today_errors if e.get('level') == 'warning')
            },
            "last_24h": {
                "total": len(last_24h_errors),
                "errors": sum(1 for e in last_24h_errors if e.get('level') == 'error'),
                "warnings": sum(1 for e in last_24h_errors if e.get('level') == 'warning')
            },
            "all_time": {
                "total": len(errors),
                "errors": sum(1 for e in errors if e.get('level') == 'error'),
                "warnings": sum(1 for e in errors if e.get('level') == 'warning')
            },
            "common_errors": common_errors
        }
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    import webbrowser

    # İlk çalıştırma kontrolleri - dosya yoksa VEYA boş/bozuksa varsayılan değer yaz
    json_defaults = {
        LINKS_FILE: {},
        ULTRA_DETAILS_FILE: {},
        CONFIG_FILE: {"presets": [], "global_settings": {"cycle_delay": 60}},
        KUR_FILE: {"kur": 35.0, "updated": datetime.now().isoformat()},
        ERRORS_FILE: [],
        PRESET_STATS_FILE: {},
        FAILED_QUEUE_FILE: {'items': [], 'updated_at': None},
    }
    for filepath, default_value in json_defaults.items():
        needs_init = False
        if not os.path.exists(filepath):
            needs_init = True
        else:
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        needs_init = True
                    else:
                        json.loads(content)  # geçerli JSON mi kontrol et
            except (json.JSONDecodeError, Exception):
                needs_init = True
        if needs_init:
            save_json(filepath, default_value)
            print(f"[INIT] {filepath} oluşturuldu/düzeltildi", flush=True)

    # Preset istatistiklerini mevcut verilerden hesapla (tutarlılık için)
    print("[STATS] Preset istatistikleri hesaplanıyor...", flush=True)
    recalculate_preset_active_counts()
    print("[STATS] Preset istatistikleri hazır", flush=True)
    
    # Retry kuyruğu durumu
    retry_stats = get_failed_queue_stats()
    if retry_stats['pending_retry'] > 0:
        print(f"[RETRY] Bekleyen {retry_stats['pending_retry']} ilan tekrar denenecek", flush=True)

    # Kur güncelleme sistemini başlat (Binance API)
    initialize_kur_system()

    # Delivery worker'ı başlat
    delivery_thread = threading.Thread(target=delivery_worker, daemon=True)
    delivery_thread.start()

    print("=" * 50)
    print("Oto-Bot V4 Otomatize Sistemi")
    print("Web arayüzü: http://127.0.0.1:5001")
    print("=" * 50)

    # Tarayıcıyı otomatik aç (1 saniye gecikme ile sunucunun başlamasını bekle)
    def open_browser():
        time.sleep(1)
        webbrowser.open('http://127.0.0.1:5001')

    threading.Thread(target=open_browser, daemon=True).start()

    app.run(host='0.0.0.0', port=5001, debug=False)
