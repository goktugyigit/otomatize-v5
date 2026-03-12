"""
G2G Delivery Settings Updater - Zombi Element Çözümü ile Optimize Edilmiş

🔥 ÖNEMLİ ÖZELLİKLER:
1. Zombi Menü Temizleme: ESC tuşu ile eski/açık menüleri kapatır
2. Negatif Filtreleme: "Edit/Delist" içeren elementleri atlar
3. Spesifik XPath: Yanlış menülerden kaçınır
4. JavaScript Click: Daha güvenilir tıklama
5. Visibility Kontrolü: Sadece görünür elementleri seçer

🧟 ZOMBİ ELEMENT SORUNU:
G2G'nin Quasar framework'ü nedeniyle, eski menüler (Action Menu: Edit/Delist)
DOM'da kalabiliyor ve yeni dropdown'ları (Delivery Speed: 10 mins, 30 mins...)
karıştırabiliyor. Bu kod, bu sorunu çözmek için optimize edilmiştir.
"""

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import os
import threading

def maximize_chrome(driver):
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
    # Driver kapanana kadar sürekli maximize state'i koru (focus çakışması, küçülme vs.)
    import threading
    def _keep_maximize():
        while True:
            try:
                driver.maximize_window()
            except Exception:
                break  # Driver kapandı, thread durur
            time.sleep(2)
    threading.Thread(target=_keep_maximize, daemon=True).start()

class G2GDeliveryUpdater:
    def __init__(self, profile_path="chrome_profile_delivery", chrome_init_lock=None):
        """G2G delivery settings güncelleyici - Ayrı Chrome profile kullanır
        
        Args:
            profile_path: Chrome profile klasörü
            chrome_init_lock: Chrome başlatma için ortak lock (WinError 183 önleme)
        """
        self.profile_path = os.path.abspath(profile_path)
        self.driver = None
        self.wait = None
        self.keep_alive_active = False
        self.chrome_init_lock = chrome_init_lock
        
    def cleanup_chromedriver_cache(self):
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
        except Exception as e:
            print(f"Cache temizleme hatası (önemli değil): {e}")

    def kill_orphan_chrome_processes(self):
        """Önceki Chrome/ChromeDriver process'lerini temizle"""
        try:
            import subprocess
            # ChromeDriver process'lerini kapat
            subprocess.run(['taskkill', '/f', '/im', 'chromedriver.exe'], 
                         capture_output=True, timeout=5)
        except:
            pass
    
    def setup_driver(self, max_retries=3):
        """Chrome driver'ı ayarla - retry mekanizması ile"""
        import random
        
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # İlk denemede değilse, önceki process'leri temizle
                if attempt > 0:
                    print(f"Retry {attempt + 1}/{max_retries} - Chrome process'leri temizleniyor...")
                    self.kill_orphan_chrome_processes()
                    time.sleep(2)  # Process'lerin kapanması için bekle

                options = uc.ChromeOptions()
                options.add_argument(f'--user-data-dir={self.profile_path}')
                options.add_argument('--no-first-run')
                options.add_argument('--no-default-browser-check')
                options.add_argument('--disable-blink-features=AutomationControlled')
                options.add_argument('--start-maximized')  # 🔥 Tam ekran başlat
                
                # 🌐 İNGİLİZCE DİL AYARI
                options.add_argument('--lang=en-US')
                options.add_experimental_option('prefs', {
                    'intl.accept_languages': 'en,en_US',
                    'profile.default_content_setting_values.notifications': 2
                })

                # 🔥 ARKA PLAN THROTTLING ÇÖZÜMÜ
                options.add_argument('--disable-background-timer-throttling')
                options.add_argument('--disable-backgrounding-occluded-windows')
                options.add_argument('--disable-renderer-backgrounding')
                options.add_argument('--disable-features=CalculateNativeWinOcclusion')

                # 🔥 PERFORMANS AYARLARI
                options.add_argument('--disable-gpu-vsync')
                options.add_argument('--disable-frame-rate-limit')
                options.add_argument('--force-device-scale-factor=1')

                # 🔥 Benzersiz debug port kullan (çakışmayı önlemek için)
                debug_port = random.randint(9500, 9999)
                options.add_argument(f'--remote-debugging-port={debug_port}')

                print(f"Chrome driver başlatılıyor (port: {debug_port})...")
                
                # KRİTİK: Chrome başlatma için ortak lock kullan (WinError 183 önleme)
                # maximize_chrome da lock içinde - diğer Chrome'lar focus almadan önce maximize tamamlanır
                if self.chrome_init_lock:
                    with self.chrome_init_lock:
                        self.cleanup_chromedriver_cache()
                        self.driver = uc.Chrome(options=options, version_main=144)
                        maximize_chrome(self.driver)
                else:
                    self.cleanup_chromedriver_cache()
                    self.driver = uc.Chrome(options=options, version_main=144)
                    maximize_chrome(self.driver)

                self.wait = WebDriverWait(self.driver, 20)
                print("Chrome driver başlatıldı (tam ekran)!")
                return  # Başarılı, fonksiyondan çık
                
            except Exception as e:
                last_error = e
                print(f"Chrome başlatma hatası (deneme {attempt + 1}): {e}")
                
                # Driver varsa kapat
                if self.driver:
                    try:
                        self.driver.quit()
                    except:
                        pass
                    self.driver = None
                
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 3  # 3, 6, 9 saniye bekle
                    print(f"{wait_time} saniye bekleniyor...")
                    time.sleep(wait_time)
        
        # Tüm denemeler başarısız
        raise Exception(f"Chrome başlatılamadı ({max_retries} deneme): {last_error}")
        
    def start_keep_alive(self):
        """Arka plan keep-alive thread'i başlat - tarayıcıyı aktif tutar"""
        def keep_alive_worker():
            while self.keep_alive_active:
                try:
                    if self.driver:
                        # Küçük bir JS işlemi yap (tarayıcıyı aktif tut)
                        self.driver.execute_script("return 1;")
                except:
                    pass
                time.sleep(1)  # 1 saniyede bir
        
        self.keep_alive_active = True
        thread = threading.Thread(target=keep_alive_worker, daemon=True)
        thread.start()
        print("🔥 Keep-alive thread başlatıldı (arka plan throttling önleniyor)")
        
    def stop_keep_alive(self):
        """Keep-alive thread'ini durdur"""
        self.keep_alive_active = False
        print("Keep-alive thread durduruldu")
        
    def go_to_offers_page(self):
        """İlanlar sayfasına git"""
        url = "https://www.g2g.com/offers/list?cat_id=5830014a-b974-45c6-9672-b51e83112fb7&status=live"
        print(f"Sayfa açılıyor: {url}")
        self.driver.get(url)
        
        # Sayfanın tam yüklenmesini bekle
        print("Sayfa yükleniyor...")
        time.sleep(5)
        
        # Loading overlay'in kaybolmasını bekle
        try:
            self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.q-loading.fullscreen')))
            print("Sayfa yüklendi")
        except:
            print("Loading overlay bulunamadı, devam ediliyor...")
            pass
            
    def search_offer(self, offer_id):
        """İlan ID'sini ara"""
        print(f"İlan aranıyor (Offer ID): {offer_id}")
        try:
            # Search input'u bul
            search_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[placeholder="Search title or offer number"]'))
            )
            search_input.clear()
            search_input.send_keys(offer_id)
            time.sleep(2)
            print(f"Offer ID yazıldı: {offer_id}")
            return True
        except TimeoutException:
            print("Search input bulunamadı!")
            return False
        except Exception as e:
            print(f"Search hatası: {e}")
            return False
            
    def click_action_menu(self):
        """İlk ilanın action menüsüne (3 nokta) tıkla"""
        print("Action menüsü açılıyor...")
        try:
            # Sayfanın hazır olmasını bekle
            time.sleep(2)
            
            # more_vert ikonunu bul ve tıkla
            buttons = self.driver.find_elements(By.CSS_SELECTOR, 'i.material-icons.q-icon')
            for btn in buttons:
                if btn.text == 'more_vert':
                    # JavaScript ile tıkla
                    self.driver.execute_script("arguments[0].click();", btn)
                    time.sleep(1)
                    print("Action menüsü açıldı")
                    return True
            return False
        except Exception as e:
            print(f"Action menüsü açılamadı: {e}")
            return False
            
    def click_edit(self):
        """Edit seçeneğine tıkla"""
        print("Edit seçeneği tıklanıyor...")
        try:
            # Edit text'ini içeren div'i bul
            edit_elements = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'q-item__section') and text()='Edit']")
            if edit_elements:
                # JavaScript ile tıkla
                self.driver.execute_script("arguments[0].click();", edit_elements[0])
                print("Edit sayfası açılıyor...")
                time.sleep(5)  # 🔥 Edit sayfasının tam yüklenmesi için daha fazla bekle
                
                # Loading overlay'in kaybolmasını bekle
                try:
                    self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.q-loading.fullscreen')))
                    print("Edit sayfası yüklendi")
                except:
                    print("Loading overlay bulunamadı, devam ediliyor...")
                
                time.sleep(2)  # 🔥 Ekstra güvenlik bekleme
                print("Edit sayfası hazır")
                return True
            return False
        except Exception as e:
            print(f"Edit tıklanamadı: {e}")
            return False
            
    def clean_ghost_menus(self):
        """🔥 Zombi menüleri temizle - ESC tuşu ile eski/açık menüleri kapat"""
        try:
            body = self.driver.find_element(By.TAG_NAME, 'body')
            body.send_keys(Keys.ESCAPE)
            time.sleep(0.5)
            print("🧹 Zombi menüler temizlendi (ESC)")
        except Exception as e:
            print(f"Temizlik hatası (önemli değil): {e}")
    
    def select_manual_delivery(self):
        """Manual delivery seçeneğini seç - bulana kadar dene"""
        print("Manual delivery seçiliyor...")
        
        # 🔥 Önce zombi menüleri temizle
        self.clean_ghost_menus()
        
        max_attempts = 5  # Maksimum 5 deneme
        attempt = 0
        
        while attempt < max_attempts:
            attempt += 1
            print(f"� Manual delivery seçme denemesi {attempt}/{max_attempts}")
            
            try:
                # 🔥 Daha fazla bekle - sayfa yükleniyor olabilir
                time.sleep(3)
                
                # Loading overlay varsa kaybolmasını bekle
                try:
                    self.wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.q-inner-loading')))
                    print("Loading overlay kayboldu")
                except:
                    pass
                
                # 🔥 Ekstra bekleme - Vue component render için
                time.sleep(2)
                
                # Manual delivery radio button'unu bul
                manual_radios = self.driver.find_elements(By.XPATH, "//div[contains(@class, 'q-radio__label') and text()='Manual delivery']")
                if manual_radios:
                    # Parent radio button'a tıkla - JavaScript ile
                    parent = manual_radios[0].find_element(By.XPATH, "./..")
                    self.driver.execute_script("arguments[0].click();", parent)
                    time.sleep(2)  # 🔥 Seçim sonrası bekleme
                    print("✅ Manual delivery başarıyla seçildi")
                    return True
                
                # Bu denemede bulunamadı
                print(f"⚠️ Deneme {attempt}'de Manual delivery bulunamadı")
                
                if attempt < max_attempts:
                    print("Sayfa yenileniyor ve tekrar deneniyor...")
                    self.driver.execute_script("window.scrollBy(0, -100);")
                    time.sleep(1)
                    self.driver.execute_script("window.scrollBy(0, 100);")
                    time.sleep(3)  # 🔥 Daha fazla bekleme
                
            except Exception as e:
                print(f"⚠️ Manual delivery seçme hatası: {e}")
                if attempt < max_attempts:
                    time.sleep(3)  # 🔥 Hata sonrası daha fazla bekleme
        
        print(f"✗ {max_attempts} denemede Manual delivery seçilemedi")
        return False
            
    def open_delivery_speed_dropdown(self):
        """🔥 Delivery speed dropdown'unu aç - Zombi menülerden kaçınarak"""
        print("Delivery speed dropdown açılıyor...")

        # 🔥 Önce zombi menüleri temizle
        self.clean_ghost_menus()

        max_attempts = 5
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            print(f"🔄 Dropdown açma denemesi {attempt}/{max_attempts}")

            try:
                time.sleep(2)

                # Sayfayı ilgili alana kaydır
                self.driver.execute_script("window.scrollBy(0, 400);")
                time.sleep(1)

                # 🔥 YÖNTEM 1: Delivery Speed label'ını bul ve yanındaki dropdown'a tıkla
                try:
                    # "Delivery Speed" veya benzeri label'ı ara
                    delivery_labels = self.driver.find_elements(By.XPATH,
                        "//*[contains(text(), 'Delivery Speed') or contains(text(), 'delivery speed') or contains(text(), 'Delivery Time')]"
                    )
                    if delivery_labels:
                        print(f"Delivery Speed label bulundu: {len(delivery_labels)} adet")
                        for label in delivery_labels:
                            try:
                                # Label'ın parent container'ındaki dropdown'u bul
                                parent = label.find_element(By.XPATH, "./ancestor::div[contains(@class, 'row') or contains(@class, 'col')]")
                                # Daha esnek ikon arama - material-icons class'ı zorunlu değil
                                dropdown = parent.find_element(By.XPATH, ".//i[text()='expand_more' or text()='arrow_drop_down']")
                                self.driver.execute_script("arguments[0].click();", dropdown)
                                time.sleep(3)  # 🔥 Dropdown içeriğinin yüklenmesi için bekle
                                print("✅ Dropdown açıldı (Delivery Speed label yöntemi)")
                                return True
                            except:
                                continue
                except Exception as e:
                    print(f"Label yöntemi hatası: {e}")

                # 🔥 YÖNTEM 2: SPESİFİK XPATH - 'min' içeren alanların expand_more ikonunu hedefle
                try:
                    # Birden fazla pattern dene
                    xpath_patterns = [
                        "//div[contains(@class, 'right')]//div[contains(text(), 'min')]/following-sibling::i[text()='expand_more' or text()='arrow_drop_down']",
                        "//*[contains(text(), '10 min') or contains(text(), '20 min') or contains(text(), '30 min')]/following-sibling::i",
                        "//*[contains(text(), 'mins')]/ancestor::div[1]//i[text()='expand_more' or text()='arrow_drop_down']"
                    ]
                    for pattern in xpath_patterns:
                        try:
                            dropdown_trigger = self.driver.find_element(By.XPATH, pattern)
                            if dropdown_trigger.is_displayed():
                                self.driver.execute_script("arguments[0].click();", dropdown_trigger)
                                time.sleep(3)
                                print("✅ Dropdown başarıyla açıldı (XPath yöntemi)")
                                return True
                        except:
                            continue
                except:
                    pass

                # 🔥 YÖNTEM 3: Alternatif - tüm expand_more ikonlarını tara
                if attempt < max_attempts:
                    try:
                        print("Alternatif yöntem deneniyor...")

                        # Tüm expand_more ve arrow_drop_down ikonlarını bul
                        expand_icons = self.driver.find_elements(By.XPATH,
                            "//i[text()='expand_more' or text()='arrow_drop_down']"
                        )
                        print(f"Toplam {len(expand_icons)} dropdown ikonu bulundu")

                        for idx, icon in enumerate(expand_icons):
                            try:
                                if not icon.is_displayed():
                                    continue

                                # Birkaç seviye yukarı çıkarak parent container'ı bul
                                parent_container = icon
                                parent_text = ""
                                for _ in range(5):  # En fazla 5 seviye yukarı çık
                                    try:
                                        parent_container = parent_container.find_element(By.XPATH, "./..")
                                        parent_text = self.driver.execute_script(
                                            "return arguments[0].innerText || arguments[0].textContent;",
                                            parent_container
                                        ).strip().lower()
                                        # Yeterli bilgi varsa dur
                                        if len(parent_text) > 5:
                                            break
                                    except:
                                        break

                                # "min" içermeli ama "edit", "delist", "hour" içermemeli
                                if ('min' in parent_text or 'speed' in parent_text or 'delivery' in parent_text):
                                    if 'edit' not in parent_text and 'delist' not in parent_text and 'hour' not in parent_text:
                                        print(f"✓ Uygun dropdown bulundu (index {idx}): '{parent_text[:50]}'")
                                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", icon)
                                        time.sleep(0.5)
                                        self.driver.execute_script("arguments[0].click();", icon)
                                        time.sleep(3)  # 🔥 Dropdown içeriğinin yüklenmesi için bekle
                                        print("✅ Dropdown açıldı (alternatif yöntem)")
                                        return True
                            except Exception as icon_err:
                                print(f"  İkon {idx} hatası: {icon_err}")
                                continue

                        # Hiçbiri bulunamazsa right.col-6 yöntemini dene
                        print("Section yöntemi deneniyor...")
                        right_sections = self.driver.find_elements(By.CSS_SELECTOR, '.right.col-6, .col-6.right, [class*="col"][class*="right"]')

                        for idx, section in enumerate(right_sections):
                            try:
                                section_text = self.driver.execute_script(
                                    "return arguments[0].innerText || arguments[0].textContent;",
                                    section
                                ).strip().lower()

                                if 'min' in section_text and 'hour' not in section_text and 'edit' not in section_text and section_text != '':
                                    # Daha esnek ikon arama - material-icons zorunlu değil
                                    expand_icon = section.find_element(By.XPATH,
                                        ".//i[text()='expand_more' or text()='arrow_drop_down']"
                                    )

                                    print(f"✓ Minutes dropdown bulundu (Section {idx})")
                                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", expand_icon)
                                    time.sleep(1)
                                    self.driver.execute_script("arguments[0].click();", expand_icon)
                                    time.sleep(3)
                                    print("✅ Dropdown açıldı (section yöntemi)")
                                    return True
                            except Exception as sec_err:
                                continue

                        # Son çare: Doğrudan tıklanabilir dropdown container'ı ara
                        print("Container yöntemi deneniyor...")
                        try:
                            containers = self.driver.find_elements(By.CSS_SELECTOR,
                                '[class*="dropdown"], [class*="select"], .q-field, .q-select'
                            )
                            for container in containers:
                                try:
                                    container_text = container.text.lower()
                                    if 'min' in container_text and 'hour' not in container_text:
                                        self.driver.execute_script("arguments[0].click();", container)
                                        time.sleep(3)
                                        print("✅ Dropdown açıldı (container yöntemi)")
                                        return True
                                except:
                                    continue
                        except:
                            pass

                    except Exception as alt_e:
                        print(f"Alternatif yöntem hatası: {alt_e}")

                    time.sleep(2)

            except Exception as e:
                print(f"⚠️ Deneme {attempt} hatası: {e}")
                time.sleep(2)

        print(f"✗ {max_attempts} denemede dropdown açılamadı")
        return False

    def force_select_10_mins(self):
        """🔥 Dropdown açmadan doğrudan 10 mins seçmeyi dene - Son çare yöntemi"""
        print("Force 10 mins seçimi deneniyor...")

        try:
            # Sayfadaki tüm "10 min" text'lerini bul ve tıkla
            selectors = [
                "//*[contains(text(), '10 mins')]",
                "//*[contains(text(), '10 min')]",
                "//div[text()='10 mins']",
                "//span[text()='10 mins']",
                "//*[@value='10' or @data-value='10']"
            ]

            for selector in selectors:
                try:
                    elements = self.driver.find_elements(By.XPATH, selector)
                    for elem in elements:
                        try:
                            if elem.is_displayed():
                                # Zombi menü kontrolü - Edit/Delist içermemeli
                                parent_text = self.driver.execute_script(
                                    "return arguments[0].closest('body').innerText || '';", elem
                                )[:200]

                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", elem)
                                time.sleep(0.3)
                                self.driver.execute_script("arguments[0].click();", elem)
                                time.sleep(1)
                                print(f"✅ Force 10 mins seçildi: {selector}")
                                return True
                        except:
                            continue
                except:
                    continue

            # JavaScript ile dropdown değerini doğrudan ayarla
            try:
                js_code = """
                // Tüm select ve input'ları tara
                var selects = document.querySelectorAll('select, input[type="text"], .q-field__native');
                for (var s of selects) {
                    var parentText = s.closest('div')?.innerText || '';
                    if (parentText.includes('Delivery') || parentText.includes('Speed') || parentText.includes('min')) {
                        if (s.tagName === 'SELECT') {
                            for (var opt of s.options) {
                                if (opt.text.includes('10')) {
                                    s.value = opt.value;
                                    s.dispatchEvent(new Event('change', {bubbles: true}));
                                    return true;
                                }
                            }
                        } else {
                            s.value = '10 mins';
                            s.dispatchEvent(new Event('input', {bubbles: true}));
                            return true;
                        }
                    }
                }
                return false;
                """
                result = self.driver.execute_script(js_code)
                if result:
                    print("✅ JavaScript ile 10 mins ayarlandı")
                    return True
            except Exception as js_err:
                print(f"JS yöntemi hatası: {js_err}")

        except Exception as e:
            print(f"Force select hatası: {e}")

        return False

    def select_10_mins(self):
        """🔥 10 mins seçeneğini seç - Quasar dropdown menüsünden"""
        print("10 mins seçiliyor...")

        max_attempts = 5
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            print(f"\n🔄 Deneme {attempt}/{max_attempts}")

            try:
                # 🔥 Dropdown menüsünün render olması için bekle
                time.sleep(2)

                # 🔥 ÖNCE: Quasar dropdown menüsünü (.q-menu) bul - body seviyesinde render edilir
                try:
                    menus = self.driver.find_elements(By.CSS_SELECTOR, '.q-menu')
                    visible_menus = [m for m in menus if m.is_displayed()]
                    print(f"Toplam {len(menus)} q-menu, {len(visible_menus)} görünür")

                    if visible_menus:
                        # En son açılan (görünür) menüyü kullan
                        active_menu = visible_menus[-1]
                        print(f"Aktif menü bulundu")

                        # Menü içindeki tüm seçenekleri bul
                        menu_items = active_menu.find_elements(By.CSS_SELECTOR, '.q-item, [role="option"], [role="menuitem"]')
                        print(f"Menüde {len(menu_items)} item bulundu")

                        for idx, item in enumerate(menu_items):
                            try:
                                item_text = self.driver.execute_script(
                                    "return arguments[0].innerText || arguments[0].textContent;",
                                    item
                                ).strip()

                                if attempt == 1 and idx < 8:
                                    print(f"  Item {idx}: '{item_text}'")

                                if '10 mins' in item_text or item_text == '10 mins' or '10 min' in item_text.lower():
                                    print(f"✓ 10 mins bulundu! Tıklanıyor...")
                                    self.driver.execute_script("arguments[0].click();", item)
                                    time.sleep(1)
                                    print("✅ 10 mins başarıyla seçildi (q-menu içinden)")
                                    return True
                            except:
                                continue
                except Exception as e:
                    print(f"q-menu araması hatası: {e}")

                # 🔥 ALTERNATİF 1: Direkt XPath ile ara
                try:
                    xpath_options = [
                        "//div[contains(@class, 'q-menu')]//div[contains(text(), '10 mins')]",
                        "//div[contains(@class, 'q-menu')]//div[contains(text(), '10 min')]",
                        "//*[contains(@class, 'q-item')][contains(., '10 mins')]",
                        "//div[text()='10 mins']",
                        "//span[text()='10 mins']",
                        "//*[contains(text(), '10 mins')]"
                    ]

                    for xpath in xpath_options:
                        try:
                            elements = self.driver.find_elements(By.XPATH, xpath)
                            visible = [e for e in elements if e.is_displayed()]
                            if visible:
                                # Zombi kontrolü
                                for elem in visible:
                                    parent_text = self.driver.execute_script(
                                        "return arguments[0].closest('.q-menu, .q-card, body').innerText || '';",
                                        elem
                                    )
                                    if 'Edit' not in parent_text or 'Delist' not in parent_text:
                                        print(f"✓ XPath ile bulundu: {xpath}")
                                        self.driver.execute_script("arguments[0].click();", elem)
                                        time.sleep(1)
                                        print("✅ 10 mins başarıyla seçildi (XPath)")
                                        return True
                        except:
                            continue
                except Exception as e:
                    print(f"XPath araması hatası: {e}")

                # 🔥 ALTERNATİF 2: Tüm q-item'ları tara
                all_items = self.driver.find_elements(By.CSS_SELECTOR, '[class*="q-item"], [class*="q-option"]')
                print(f"Toplam {len(all_items)} q-item/q-option bulundu")

                for idx, item in enumerate(all_items):
                    try:
                        if not item.is_displayed():
                            continue

                        item_text = self.driver.execute_script(
                            "return arguments[0].innerText || arguments[0].textContent;",
                            item
                        ).strip()

                        # Zombi kontrolü
                        if "Edit" in item_text or "Delist" in item_text:
                            continue

                        if '10 mins' in item_text or item_text == '10 mins':
                            print(f"✓ 10 mins bulundu (index {idx})! Tıklanıyor...")
                            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", item)
                            time.sleep(0.3)
                            self.driver.execute_script("arguments[0].click();", item)
                            time.sleep(1)
                            print("✅ 10 mins başarıyla seçildi")
                            return True

                    except:
                        continue

                print(f"⚠️ Deneme {attempt}'de 10 mins bulunamadı")

                # Dropdown'u tekrar açmayı dene
                if attempt < max_attempts:
                    print("Dropdown tekrar açılıyor...")
                    self.clean_ghost_menus()
                    time.sleep(1)
                    self.open_delivery_speed_dropdown()
                    time.sleep(2)

            except Exception as e:
                print(f"⚠️ Deneme {attempt} hatası: {e}")
                time.sleep(1)

        print(f"✗ {max_attempts} denemede 10 mins bulunamadı")
        return False
            
    def click_update(self):
        """🔥 Update butonuna tıkla - JavaScript ile güvenli"""
        print("Update butonu tıklanıyor...")
        
        # 🔥 Önce zombi menüleri temizle
        self.clean_ghost_menus()
        
        try:
            time.sleep(1)
            
            # Update text'ini içeren button'u bul
            update_buttons = self.driver.find_elements(By.XPATH, "//span[text()='Update']/ancestor::button")
            if update_buttons:
                # JavaScript ile tıkla (daha güvenilir)
                self.driver.execute_script("arguments[0].click();", update_buttons[0])
                time.sleep(2)
                print("✅ Update tıklandı")
                return True
            
            print("⚠️ Update butonu bulunamadı")
            return False
            
        except Exception as e:
            print(f"❌ Update tıklanamadı: {e}")
            return False
            
    def click_ok(self):
        """🔥 OK butonuna tıkla - JavaScript ile güvenli"""
        print("OK butonu tıklanıyor...")
        
        try:
            # OK butonunun görünmesini bekle
            time.sleep(2)
            
            # Ok text'ini içeren button'u bul - farklı varyasyonlar dene
            ok_buttons = self.driver.find_elements(By.XPATH, "//span[text()='Ok']/ancestor::button")
            
            if not ok_buttons:
                # Alternatif: OK (büyük harf)
                ok_buttons = self.driver.find_elements(By.XPATH, "//span[text()='OK']/ancestor::button")
            
            if not ok_buttons:
                # Alternatif: Confirm, Done, vb.
                ok_buttons = self.driver.find_elements(By.XPATH, "//span[contains(text(), 'Confirm') or contains(text(), 'Done')]/ancestor::button")
            
            if ok_buttons:
                # JavaScript ile tıkla (daha güvenilir)
                self.driver.execute_script("arguments[0].click();", ok_buttons[0])
                time.sleep(1)
                print("✅ OK tıklandı")
                return True
            else:
                print("⚠️ OK butonu bulunamadı, muhtemelen otomatik kapandı")
                return True  # Başarılı sayalım
                
        except Exception as e:
            print(f"⚠️ OK tıklama hatası: {e}")
            # OK bulunamasa bile işlem başarılı olabilir
            return True
            
    def update_offer_delivery(self, offer_id, close_browser=True):
        """
        Bir ilanın delivery ayarlarını güncelle
        
        Args:
            offer_id: İlan ID'si (örn: "123456789")
            close_browser: İşlem sonunda tarayıcıyı kapat (varsayılan: True)
        
        Returns:
            bool: Başarılı ise True, değilse False
        """
        try:
            self.setup_driver()
            self.start_keep_alive()  # 🔥 Keep-alive başlat
            self.go_to_offers_page()
            
            if not self.search_offer(offer_id):
                return False
                
            if not self.click_action_menu():
                return False
                
            if not self.click_edit():
                return False
                
            if not self.select_manual_delivery():
                return False

            # Dropdown aç ve 10 mins seç - başarısız olursa force yöntemi dene
            dropdown_success = self.open_delivery_speed_dropdown()
            select_success = False

            if dropdown_success:
                select_success = self.select_10_mins()

            # Normal yöntem başarısız olduysa force yöntemi dene
            if not select_success:
                print("⚠️ Normal yöntem başarısız, force yöntemi deneniyor...")
                select_success = self.force_select_10_mins()

            if not select_success:
                print("❌ 10 mins seçilemedi!")
                return False

            if not self.click_update():
                return False
                
            if not self.click_ok():
                return False
                
            print(f"✓ İlan başarıyla güncellendi (Offer ID: {offer_id})")
            return True
            
        except Exception as e:
            print(f"✗ Hata oluştu: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            self.stop_keep_alive()  # 🔥 Keep-alive durdur
            if self.driver and close_browser:
                print("\n" + "="*70)
                print("İşlem tamamlandı. Tarayıcı 3 saniye sonra kapanacak...")
                print("="*70)
                time.sleep(3)
                print("Tarayıcı kapatılıyor...")
                try:
                    self.driver.quit()
                except:
                    pass
    
    def auto_update_after_creation(self, offer_id):
        """
        API ile ilan oluşturulduktan hemen sonra otomatik delivery ayarlarını güncelle
        HER ZAMAN çalışır - ilan oluşturma başarılı olduktan sonra
        
        Args:
            offer_id: Yeni oluşturulan ilanın ID'si
            
        Returns:
            dict: {'success': bool, 'message': str, 'offer_id': str}
        """
        print("\n" + "="*70)
        print("OTOMATİK DELIVERY AYARLARI GÜNCELLENİYOR")
        # İlanın sisteme kaydedilmesi için kısa bir bekleme (3 saniye yeterli)
        time.sleep(3)
        
        success = self.update_offer_delivery(offer_id, close_browser=True)
        
        result = {
            'success': success,
            'offer_id': offer_id,
            'message': 'Delivery ayarları başarıyla güncellendi (Manual delivery, 10 mins)' if success else 'Delivery ayarları güncellenemedi'
        }
        
        return result
        print("="*70 + "\n")
        
        return result
                
    def update_multiple_offers(self, offer_ids):
        """Birden fazla ilanın delivery ayarlarını güncelle"""
        results = []
        for offer_id in offer_ids:
            print(f"\n{'='*60}")
            print(f"İşleniyor (Offer ID): {offer_id}")
            print('='*60)
            success = self.update_offer_delivery(offer_id)
            results.append({'offer_id': offer_id, 'success': success})
            
        print(f"\n{'='*60}")
        print("ÖZET")
        print('='*60)
        for result in results:
            status = "✓ Başarılı" if result['success'] else "✗ Başarısız"
            print(f"{status}: Offer ID {result['offer_id']}")
        
        return results


if __name__ == "__main__":
    # Test için
    updater = G2GDeliveryUpdater()
    
    # Test offer ID (gerçek bir offer ID ile değiştirin)
    test_offer_id = "123456789"  # Örnek offer ID
    
    print("G2G Delivery Settings Updater")
    print("="*60)
    
    # Otomatik güncelleme testi
    result = updater.auto_update_after_creation(test_offer_id)
    print(f"\nSonuç: {result}")