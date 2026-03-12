"""
GamerMarkt Otomatik Link Scraper
Botasaurus Driver ile Cloudflare bypass yaparak filtreleri uygular ve linkleri ceker
"""
import time
import json
import os
from botasaurus_driver import Driver
import threading

class GamerMarktScraper:
    def __init__(self, category, filters, chrome_init_lock=None):
        """
        Args:
            category: 'valorant', 'lol', 'cs2', 'fortnite'
            filters: Filtre ayarlari dict
            chrome_init_lock: Chrome başlatma için ortak lock (WinError 183 önleme)
        """
        self.category = category
        self.filters = filters
        self.chrome_init_lock = chrome_init_lock
        self.driver = None
        self.is_running = False
        self.scraped_links = set()
        self.stats = {
            'total_links': 0,
            'new_listings': 0,
            'deleted_listings': 0,
            'errors': 0
        }
        self.logs = []

        # Kategori URL mapping
        self.urls = {
            'valorant': 'https://www.gamermarkt.com/tr/ilanlar/valorant-hesap',
            'lol': 'https://www.gamermarkt.com/tr/ilanlar/lol-hesap',
            'cs2': 'https://www.gamermarkt.com/tr/ilanlar/cs2-hesap',
            'fortnite': 'https://www.gamermarkt.com/tr/ilanlar/fortnite-hesap'
        }

    def add_log(self, message, log_type='info'):
        """Log ekle - kategori prefix'li"""
        log_entry = {
            'message': message,
            'type': log_type,
            'timestamp': time.time()
        }
        self.logs.append(log_entry)
        # Kategori prefix ekle
        icon = {'info': '📌', 'success': '✅', 'warning': '⚠️', 'error': '❌'}.get(log_type, '📌')
        print(f"[{self.category.upper()}] {icon} {message}", flush=True)

    def init_driver(self):
        """Botasaurus Driver ile tarayıcıyı başlat (Cloudflare bypass destekli)"""
        try:
            # KRİTİK: Chrome başlatma için ortak lock kullan (çakışma önleme)
            if self.chrome_init_lock:
                with self.chrome_init_lock:
                    self.driver = Driver(headless=False, lang="tr")
            else:
                self.driver = Driver(headless=False, lang="tr")
            self.add_log('Botasaurus Driver baslatildi (Cloudflare bypass aktif)', 'info')
            return True
        except Exception as e:
            self.add_log(f'Driver baslatma hatasi: {e}', 'error')
            self.stats['errors'] += 1
            if self.driver:
                try:
                    self.driver.close()
                except:
                    pass
                self.driver = None
            return False

    def close_popups(self):
        """Cookie ve diger popup'lari kapat"""
        try:
            # JS ile cookie popup'ını bul ve kapat
            self._run_js("""
                var selectors = [
                    "button:contains('Kabul')", "#cookie-accept",
                    ".consent button", "button.cookie", "a.cookie"
                ];
                // XPath ile de dene
                var xpaths = [
                    "//button[contains(text(), 'Kabul')]",
                    "//button[contains(text(), 'Accept')]"
                ];
                for (var i = 0; i < xpaths.length; i++) {
                    try {
                        var result = document.evaluate(xpaths[i], document, null,
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null);
                        if (result.singleNodeValue) {
                            result.singleNodeValue.click();
                            return;
                        }
                    } catch(e) {}
                }
                // CSS ile dene
                var el = document.getElementById('cookie-accept');
                if (el) { el.click(); return; }
                var consent = document.querySelector('.consent button, button.cookie, a.cookie');
                if (consent) { consent.click(); }
            """)
            time.sleep(0.5)
        except Exception:
            pass

    def _run_js(self, script, args=None):
        """Botasaurus native run_js wrapper - args dict olarak geçilir"""
        if args:
            return self.driver.run_js(script, args)
        return self.driver.run_js(script)

    def scroll_to_element(self, element):
        """Elementi gorunur alana scroll et - native scroll_into_view kullan"""
        try:
            raw = element._el if hasattr(element, '_el') else element
            raw.scroll_into_view()
        except Exception:
            pass
        time.sleep(0.3)

    def safe_click(self, element):
        """Guvenli tikla - native click, başarısız olursa JS click"""
        try:
            element.click()
        except Exception:
            try:
                raw = element._el if hasattr(element, '_el') else element
                raw.run_js("(el) => el.click()")
            except Exception:
                pass

    def safe_set_input(self, element_id, value, label=""):
        """Input alanına güvenli değer yaz - botasaurus native API ile"""
        value_str = str(value)
        for attempt in range(3):
            try:
                # Element'i scroll et
                el = self.driver.select(f'#{element_id}')
                el.scroll_into_view()
                time.sleep(0.3)

                # JS ile değer ata (args dict olarak geç)
                self._run_js("""
                    var el = document.getElementById(args.id);
                    if(el) {
                        el.value = '';
                        el.value = args.value;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                """, {"id": element_id, "value": value_str})

                time.sleep(0.3)

                # Doğrula
                actual = self._run_js(
                    "var el = document.getElementById(args.id); return el ? el.value : '';",
                    {"id": element_id}
                )
                if actual == value_str:
                    self.add_log(f'{label or element_id} ayarlandı: {value_str}', 'info')
                    return True

                # JS başarısız olduysa fallback: type
                self.add_log(f'{label or element_id} JS ile ayarlanamadı (beklenen: {value_str}, gerçek: {actual}), type deneniyor...', 'warning')
                self._run_js("var el = document.getElementById(args.id); if(el) { el.value = ''; el.dispatchEvent(new Event('input', {bubbles: true})); }", {"id": element_id})
                time.sleep(0.2)
                el.type(value_str)
                time.sleep(0.3)

                actual = self._run_js(
                    "var el = document.getElementById(args.id); return el ? el.value : '';",
                    {"id": element_id}
                )
                if actual == value_str:
                    self.add_log(f'{label or element_id} ayarlandı: {value_str}', 'info')
                    return True

                self.add_log(f'{label or element_id} deneme {attempt+1}/3 başarısız (gerçek: {actual})', 'warning')

            except Exception as e:
                self.add_log(f'{label or element_id} hatası deneme {attempt+1}/3: {e}', 'warning')

        self.add_log(f'{label or element_id} 3 denemede ayarlanamadı!', 'error')
        return False

    def wait_for_element_clickable(self, element_id, timeout=10):
        """Element tıklanabilir olana kadar bekle"""
        try:
            end_time = time.time() + timeout
            while time.time() < end_time:
                try:
                    element = self.driver.select(f'#{element_id}')
                    if element:
                        return element
                except Exception:
                    pass
                time.sleep(0.5)
            return None
        except Exception:
            return None

    def is_checkbox_checked(self, checkbox_id):
        """Checkbox'ın seçili olup olmadığını JS ile kontrol et"""
        try:
            return self._run_js(
                "var el = document.getElementById(args.id); return el ? el.checked : false;",
                {"id": checkbox_id}
            )
        except:
            return False

    def verify_checkbox_selected(self, checkbox, checkbox_id, max_retries=3):
        """Checkbox'ın seçili olduğunu doğrula, değilse tekrar dene"""
        for attempt in range(max_retries):
            try:
                if self.is_checkbox_checked(checkbox_id):
                    return True

                self.add_log(f'Checkbox seçilmedi, deneme {attempt + 1}/{max_retries}: {checkbox_id}', 'warning')

                # Yöntem 1: Label'a tıkla (custom checkbox'larda daha güvenilir)
                try:
                    label = self.driver.select(f'label[for="{checkbox_id}"]')
                    label.scroll_into_view()
                    time.sleep(0.3)
                    label.click()
                    time.sleep(0.5)
                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'Checkbox seçildi (label click, deneme {attempt + 1}): {checkbox_id}', 'success')
                        return True
                except:
                    pass

                # Yöntem 2: JS ile checked = true yap
                try:
                    self._run_js("""
                        var el = document.getElementById(args.id);
                        if (el && !el.checked) {
                            el.checked = true;
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                            el.dispatchEvent(new Event('click', {bubbles: true}));
                        }
                    """, {"id": checkbox_id})
                    time.sleep(0.5)
                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'Checkbox seçildi (JS, deneme {attempt + 1}): {checkbox_id}', 'success')
                        return True
                except:
                    pass

                # Yöntem 3: Doğrudan element click
                try:
                    fresh_checkbox = self.driver.select(f'#{checkbox_id}')
                    fresh_checkbox.scroll_into_view()
                    time.sleep(0.3)
                    fresh_checkbox.click()
                    time.sleep(0.5)
                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'Checkbox seçildi (click, deneme {attempt + 1}): {checkbox_id}', 'success')
                        return True
                except:
                    pass

            except Exception as e:
                self.add_log(f'Checkbox doğrulama hatası {checkbox_id}: {e}', 'warning')

        self.add_log(f'Checkbox {max_retries} denemede seçilemedi: {checkbox_id}', 'error')
        return False

    def apply_filters(self):
        """Filtreleri uygula"""
        try:
            # Sayfa tam yuklensin
            time.sleep(3)

            # Popup'lari kapat
            self.close_popups()

            # Filtre bolumunu scroll ile gorunur yap
            try:
                filters_div = self.driver.select('#filters_div')
                filters_div.scroll_into_view()
                time.sleep(1)
            except:
                pass

            # Fiyat filtreleri
            if 'min_price' in self.filters:
                self.safe_set_input('min_price', self.filters['min_price'], 'Min Fiyat')

            if 'max_price' in self.filters:
                self.safe_set_input('max_price', self.filters['max_price'], 'Max Fiyat')

            # Kategori ozel filtreler - başarı durumunu takip et
            filter_success = True
            expected_checkbox_ids = []
            if self.category == 'valorant':
                filter_success, expected_checkbox_ids = self._apply_valorant_filters()
            elif self.category == 'lol':
                filter_success, expected_checkbox_ids = self._apply_lol_filters()
            elif self.category == 'cs2':
                filter_success, expected_checkbox_ids = self._apply_cs2_filters()
            elif self.category == 'fortnite':
                filter_success, expected_checkbox_ids = self._apply_fortnite_filters()

            if not filter_success:
                self.add_log('Bazı filtreler uygulanamadı, tekrar deneniyor...', 'warning')
                time.sleep(2)
                # Bir kez daha dene
                if self.category == 'valorant':
                    filter_success, expected_checkbox_ids = self._apply_valorant_filters()
                elif self.category == 'lol':
                    filter_success, expected_checkbox_ids = self._apply_lol_filters()
                elif self.category == 'cs2':
                    filter_success, expected_checkbox_ids = self._apply_cs2_filters()

            # Filtrelerin DOM'a yansıması için ekstra bekleme
            time.sleep(1.5)

            # Ara butonuna basmadan önce tüm checkbox'ları son kez doğrula
            if expected_checkbox_ids:
                unselected = []
                for cb_id in expected_checkbox_ids:
                    if not self.is_checkbox_checked(cb_id):
                        unselected.append(cb_id)

                if unselected:
                    self.add_log(f'Son kontrol: {len(unselected)} checkbox seçili değil, düzeltiliyor: {unselected}', 'warning')
                    for cb_id in unselected:
                        try:
                            cb = self.driver.select(f'#{cb_id}')
                            self.verify_checkbox_selected(cb, cb_id, max_retries=3)
                        except Exception as e:
                            self.add_log(f'Son kontrol düzeltme hatası {cb_id}: {e}', 'error')
                    time.sleep(1)

                    # Son son kontrol - hala seçili değilse aramayı durdur
                    still_unselected = []
                    for cb_id in unselected:
                        if not self.is_checkbox_checked(cb_id):
                            still_unselected.append(cb_id)
                    if still_unselected:
                        self.add_log(f'HATA: Filtreler uygulanamadı, arama iptal! Seçilemeyen: {still_unselected}', 'error')
                        return False
                else:
                    self.add_log(f'Son kontrol: Tüm {len(expected_checkbox_ids)} checkbox seçili', 'success')

            # Ara butonuna tikla
            try:
                search_btn = self.driver.select('#submitForm')
                search_btn.scroll_into_view()
                time.sleep(1)
                search_btn.click()
            except Exception as e:
                # Fallback: JS click
                try:
                    self._run_js("var btn = document.getElementById('submitForm'); if(btn) btn.click();")
                except:
                    self.add_log(f'Ara butonu hatasi: {e}', 'error')
                    return False

            # AJAX yuklenmesini bekle
            time.sleep(3)
            try:
                # Polling ile ilan kartlarının yüklenmesini bekle
                end_time = time.time() + 15
                found = False
                while time.time() < end_time:
                    try:
                        cards = self.driver.select_all('div.col-12.asLink')
                        if cards:
                            found = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                if found:
                    time.sleep(2)
                else:
                    self.add_log('Ilan kartlari bulunamadi, devam ediliyor...', 'warning')
            except Exception:
                self.add_log('Ilan kartlari bulunamadi, devam ediliyor...', 'warning')

            self.add_log('Filtreler uygulandi', 'info')
            return True

        except Exception as e:
            self.add_log(f'Filtre uygulama hatasi: {e}', 'error')
            self.stats['errors'] += 1
            return False

    def _apply_valorant_filters(self):
        """Valorant ozel filtreleri - (success, expected_checkbox_ids) döndürür"""
        SERVER_MAPPING = {
            'EU': 'server_0',
            'NA': 'server_1'
        }

        DIVISION_MAPPING = {
            '0': 'division_0',   # Unranked
            '3': 'division_1',   # Demir
            '6': 'division_2',   # Bronz
            '9': 'division_3',   # Gumus
            '12': 'division_4',  # Altin
            '15': 'division_5',  # Platin
            '18': 'division_6',  # Elmas
            '21': 'division_7',  # Yucelik
            '24': 'division_8',  # Olumsuz
            '27': 'division_9'   # Radyant
        }

        all_success = True
        failed_filters = []
        expected_checkbox_ids = []

        # Ajan sayisi
        if 'min_agent' in self.filters:
            self.safe_set_input('min_agent', self.filters['min_agent'], 'Min Ajan')

        if 'max_agent' in self.filters:
            self.safe_set_input('max_agent', self.filters['max_agent'], 'Max Ajan')

        # Kaplama sayisi
        if 'min_skin' in self.filters:
            self.safe_set_input('min_skin', self.filters['min_skin'], 'Min Skin')

        if 'max_skin' in self.filters:
            self.safe_set_input('max_skin', self.filters['max_skin'], 'Max Skin')

        # Sunucu secimi (EU, NA)
        if 'servers' in self.filters and self.filters['servers']:
            for server in self.filters['servers']:
                checkbox_id = SERVER_MAPPING.get(server.upper())
                if checkbox_id:
                    expected_checkbox_ids.append(checkbox_id)
                    try:
                        checkbox = self.driver.select(f'#{checkbox_id}')
                        checkbox.scroll_into_view()
                        time.sleep(0.5)

                        if self.is_checkbox_checked(checkbox_id):
                            self.add_log(f'Sunucu zaten secili: {server}', 'info')
                        else:
                            if self.verify_checkbox_selected(checkbox, checkbox_id):
                                self.add_log(f'Sunucu secildi: {server}', 'success')
                            else:
                                self.add_log(f'Sunucu secilemedi: {server}', 'error')
                                all_success = False
                                failed_filters.append(f'server:{server}')
                    except Exception:
                        self.add_log(f'Sunucu checkbox bulunamadi: {checkbox_id}', 'warning')
                        all_success = False
                        failed_filters.append(f'server:{server}')

        # Kademe secimi
        if 'divisions' in self.filters and self.filters['divisions']:
            for division_value in self.filters['divisions']:
                checkbox_id = DIVISION_MAPPING.get(str(division_value))
                if checkbox_id:
                    expected_checkbox_ids.append(checkbox_id)
                    try:
                        checkbox = self.driver.select(f'#{checkbox_id}')
                        checkbox.scroll_into_view()
                        time.sleep(0.5)

                        if self.is_checkbox_checked(checkbox_id):
                            self.add_log(f'Kademe zaten secili: {checkbox_id}', 'info')
                        else:
                            if self.verify_checkbox_selected(checkbox, checkbox_id):
                                self.add_log(f'Kademe secildi: {checkbox_id}', 'success')
                            else:
                                self.add_log(f'Kademe secilemedi: {checkbox_id}', 'error')
                                all_success = False
                                failed_filters.append(f'division:{checkbox_id}')
                    except Exception:
                        self.add_log(f'Kademe checkbox bulunamadi: {checkbox_id}', 'warning')
                        all_success = False
                        failed_filters.append(f'division:{checkbox_id}')

        if failed_filters:
            self.add_log(f'Başarısız filtreler: {", ".join(failed_filters)}', 'warning')

        return all_success, expected_checkbox_ids

    def _apply_lol_filters(self):
        """LoL ozel filtreleri - (success, expected_checkbox_ids) döndürür"""
        SERVER_MAPPING = {
            'TR': 'server_tr',
            'EUW': 'server_euw',
            'EUN': 'server_eun',
            'EUNE': 'server_eun',
            'NA': 'server_na',
            'RU': 'server_ru',
            'BR': 'server_br',
            'JP': 'server_jp',
            'LAN': 'server_lan',
            'LAS': 'server_las',
            'OC': 'server_oc'
        }

        DIVISION_MAPPING = {
            '0': 'division_0',    # Unranked
            '10': 'division_1',   # Demir
            '20': 'division_2',   # Bronz
            '30': 'division_3',   # Gumus
            '40': 'division_4',   # Altin
            '50': 'division_5',   # Platin
            '60': 'division_6',   # Zumrut
            '70': 'division_7',   # Elmas
            '80': 'division_8',   # Ustalik
            '90': 'division_9',   # Ustatlik
            '100': 'division_10'  # Sampiyonluk
        }

        all_success = True
        failed_filters = []
        expected_checkbox_ids = []

        # Sampiyon sayisi
        if 'min_champs' in self.filters:
            self.safe_set_input('min_champs', self.filters['min_champs'], 'Min Sampiyon')

        if 'max_champs' in self.filters:
            self.safe_set_input('max_champs', self.filters['max_champs'], 'Max Sampiyon')

        # Kostum sayisi
        if 'min_skins' in self.filters:
            self.safe_set_input('min_skins', self.filters['min_skins'], 'Min Kostum')

        if 'max_skins' in self.filters:
            self.safe_set_input('max_skins', self.filters['max_skins'], 'Max Kostum')

        # Sunucu secimi
        if 'servers' in self.filters and self.filters['servers']:
            for server in self.filters['servers']:
                checkbox_id = SERVER_MAPPING.get(server.upper())
                if checkbox_id:
                    expected_checkbox_ids.append(checkbox_id)
                    try:
                        checkbox = self.driver.select(f'#{checkbox_id}')
                        checkbox.scroll_into_view()
                        time.sleep(0.5)

                        if self.is_checkbox_checked(checkbox_id):
                            self.add_log(f'LoL Sunucu zaten secili: {server}', 'info')
                        else:
                            if self.verify_checkbox_selected(checkbox, checkbox_id):
                                self.add_log(f'LoL Sunucu secildi: {server}', 'success')
                            else:
                                self.add_log(f'LoL Sunucu secilemedi: {server}', 'error')
                                all_success = False
                                failed_filters.append(f'server:{server}')
                    except Exception:
                        self.add_log(f'LoL Sunucu checkbox bulunamadi: {checkbox_id}', 'warning')
                        all_success = False
                        failed_filters.append(f'server:{server}')

        # Lig secimi
        if 'divisions' in self.filters and self.filters['divisions']:
            for division_value in self.filters['divisions']:
                checkbox_id = DIVISION_MAPPING.get(str(division_value))
                if checkbox_id:
                    expected_checkbox_ids.append(checkbox_id)
                    try:
                        checkbox = self.driver.select(f'#{checkbox_id}')
                        checkbox.scroll_into_view()
                        time.sleep(0.5)

                        if self.is_checkbox_checked(checkbox_id):
                            self.add_log(f'LoL Lig zaten secili: {checkbox_id}', 'info')
                        else:
                            if self.verify_checkbox_selected(checkbox, checkbox_id):
                                self.add_log(f'LoL Lig secildi: {checkbox_id}', 'success')
                            else:
                                self.add_log(f'LoL Lig secilemedi: {checkbox_id}', 'error')
                                all_success = False
                                failed_filters.append(f'division:{checkbox_id}')
                    except Exception:
                        self.add_log(f'LoL Lig checkbox bulunamadi: {checkbox_id}', 'warning')
                        all_success = False
                        failed_filters.append(f'division:{checkbox_id}')

        if failed_filters:
            self.add_log(f'LoL Başarısız filtreler: {", ".join(failed_filters)}', 'warning')

        return all_success, expected_checkbox_ids

    def _apply_cs2_filters(self):
        """CS2 ozel filtreleri - (success, expected_checkbox_ids) döndürür"""
        all_success = True
        failed_filters = []
        expected_checkbox_ids = []

        # Arama
        if 'query' in self.filters and self.filters['query']:
            self.safe_set_input('query', self.filters['query'], 'CS2 Arama')

        # Prime durumu (Seckin mi)
        if 'prime' in self.filters and self.filters['prime']:
            for prime_value in self.filters['prime']:
                checkbox_id = f'av_{prime_value}'
                expected_checkbox_ids.append(checkbox_id)
                try:
                    checkbox = self.driver.select(f'#{checkbox_id}')
                    checkbox.scroll_into_view()
                    time.sleep(0.5)

                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'CS2 Prime zaten secili: {checkbox_id}', 'info')
                    else:
                        if self.verify_checkbox_selected(checkbox, checkbox_id):
                            self.add_log(f'CS2 Prime secildi: {checkbox_id}', 'success')
                        else:
                            self.add_log(f'CS2 Prime secilemedi: {checkbox_id}', 'error')
                            all_success = False
                            failed_filters.append(f'prime:{checkbox_id}')
                except Exception:
                    self.add_log(f'CS2 Prime checkbox bulunamadi: {checkbox_id}', 'warning')
                    all_success = False
                    failed_filters.append(f'prime:{checkbox_id}')

        # Rank
        if 'ranks' in self.filters and self.filters['ranks']:
            for rank_value in self.filters['ranks']:
                checkbox_id = f'av_{rank_value}'
                expected_checkbox_ids.append(checkbox_id)
                try:
                    checkbox = self.driver.select(f'#{checkbox_id}')
                    checkbox.scroll_into_view()
                    time.sleep(0.5)

                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'CS2 Rank zaten secili: {checkbox_id}', 'info')
                    else:
                        if self.verify_checkbox_selected(checkbox, checkbox_id):
                            self.add_log(f'CS2 Rank secildi: {checkbox_id}', 'success')
                        else:
                            self.add_log(f'CS2 Rank secilemedi: {checkbox_id}', 'error')
                            all_success = False
                            failed_filters.append(f'rank:{checkbox_id}')
                except Exception:
                    self.add_log(f'CS2 Rank checkbox bulunamadi: {checkbox_id}', 'warning')
                    all_success = False
                    failed_filters.append(f'rank:{checkbox_id}')

        # Faceit
        if 'faceit' in self.filters and self.filters['faceit']:
            for faceit_value in self.filters['faceit']:
                checkbox_id = f'av_{faceit_value}'
                expected_checkbox_ids.append(checkbox_id)
                try:
                    checkbox = self.driver.select(f'#{checkbox_id}')
                    checkbox.scroll_into_view()
                    time.sleep(0.5)

                    if self.is_checkbox_checked(checkbox_id):
                        self.add_log(f'CS2 Faceit zaten secili: {checkbox_id}', 'info')
                    else:
                        if self.verify_checkbox_selected(checkbox, checkbox_id):
                            self.add_log(f'CS2 Faceit secildi: {checkbox_id}', 'success')
                        else:
                            self.add_log(f'CS2 Faceit secilemedi: {checkbox_id}', 'error')
                            all_success = False
                            failed_filters.append(f'faceit:{checkbox_id}')
                except Exception:
                    self.add_log(f'CS2 Faceit checkbox bulunamadi: {checkbox_id}', 'warning')
                    all_success = False
                    failed_filters.append(f'faceit:{checkbox_id}')

        if failed_filters:
            self.add_log(f'CS2 Başarısız filtreler: {", ".join(failed_filters)}', 'warning')

        return all_success, expected_checkbox_ids

    def _apply_fortnite_filters(self):
        """Fortnite ozel filtreleri - (success, expected_checkbox_ids) döndürür"""
        self.add_log('Fortnite: Sadece fiyat filtreleri uygulandi', 'info')
        return True, []

    def scrape_page_links(self):
        """Mevcut sayfadaki tum ilan linklerini cek"""
        try:
            # Önce sayfanın yüklenmesini bekle
            time.sleep(2)
            
            # JS ile tüm ilan linklerini çek (en güvenilir yöntem)
            page_links_raw = self._run_js("""
                var links = [];
                // Yöntem 1: asLink kartları
                var cards = document.querySelectorAll('div.col-12.asLink');
                cards.forEach(function(card) {
                    var a = card.querySelector('a');
                    if (a && a.href && (a.href.includes('/ilan/') || a.href.includes('/listing/'))) {
                        links.push(a.href);
                    }
                });
                if (links.length > 0) return links;

                // Yöntem 2: Direkt ilan linkleri
                var allLinks = document.querySelectorAll('a[href*="/ilan/"]');
                allLinks.forEach(function(a) {
                    if (a.href) links.push(a.href);
                });
                return links;
            """) or []

            self.add_log(f'{len(page_links_raw)} ilan linki bulundu', 'info')

            if not page_links_raw:
                try:
                    page_source = self.driver.page_html
                    with open('debug_page_source.html', 'w', encoding='utf-8') as f:
                        f.write(page_source)
                    self.add_log('Hiç kart bulunamadı! Sayfa HTML\'i debug_page_source.html\'e kaydedildi', 'warning')
                    page_title = self._run_js("return document.title")
                    self.add_log(f'Sayfa başlığı: {page_title}', 'info')
                    current_url = self._run_js("return window.location.href")
                    self.add_log(f'Mevcut URL: {current_url}', 'info')
                except:
                    pass

            page_links = []
            for href in page_links_raw:
                if href and ('/ilan/' in href or '/listing/' in href):
                    if not href.startswith('http'):
                        href = 'https://www.gamermarkt.com' + href
                    page_links.append(href)

            self.add_log(f'Toplam {len(page_links)} geçerli link çekildi', 'info')
            return page_links
            
        except Exception as e:
            self.add_log(f'Link cekme hatasi: {e}', 'error')
            self.stats['errors'] += 1
            return []

    def _get_current_page_number(self):
        """Sayfalama barından aktif sayfa numarasını oku"""
        try:
            result = self._run_js("""
                var el = document.querySelector('li.page-item.active span, li.page-item.active a');
                return el ? el.textContent.trim() : null;
            """)
            if result and result.strip().isdigit():
                return int(result.strip())
        except:
            pass
        return None

    def _get_first_link_on_page(self):
        """Sayfadaki ilk ilan linkini döndür (sayfa değişim kontrolü için)"""
        try:
            result = self._run_js("""
                var card = document.querySelector('div.col-12.asLink a');
                if (card) return card.href;
                var link = document.querySelector('a[href*="/ilan/"]');
                if (link) return link.href;
                return null;
            """)
            return result
        except:
            return None

    def scrape_all_pages(self):
        """Tum sayfalari sira sira tara"""
        all_links = set()
        page = 1
        max_pages = 100

        self.add_log(f'Sayfa taraması başlıyor (max {max_pages} sayfa)', 'info')

        while page <= max_pages and self.is_running:
            try:
                # Sayfa yüklenmesi için bekle
                time.sleep(2)

                # Gerçek sayfa numarasını kontrol et
                real_page = self._get_current_page_number()
                if real_page and real_page != page:
                    self.add_log(f'Sayfa numarası uyumsuz! Beklenen: {page}, Gerçek: {real_page}', 'warning')
                    page = real_page  # Gerçek sayfaya senkronize ol

                # Sayfadaki ilk linki kaydet (değişim kontrolü için)
                first_link_before = self._get_first_link_on_page()

                # Link çek
                page_links = self.scrape_page_links()

                if not page_links:
                    self.add_log(f'Sayfa {page}: Boş sayfa, tarama tamamlandı', 'warning')
                    break

                # Yeni linkleri hesapla
                page_links_set = set(page_links)
                new_links_count = len(page_links_set - all_links)
                all_links.update(page_links_set)

                self.add_log(f'Sayfa {page}/{max_pages}: {len(page_links)} link, {new_links_count} yeni | Toplam: {len(all_links)}', 'info')

                # Yeni link gelmiyorsa sayfa değişmemiş demektir, dur
                if new_links_count == 0:
                    self.add_log(f'Sayfa {page}: Yeni link yok, tarama tamamlandı', 'info')
                    break

                # Sonraki sayfa butonunu bul (pure JS)
                next_btn = None
                is_last_page = False

                pagination_info = self._run_js("""
                    // next-page span'ını bul
                    var nextSpan = document.getElementById('next-page');
                    if (nextSpan) {
                        // Parent li'nin disabled olup olmadığını kontrol et
                        var parentLi = nextSpan.closest('li.page-item');
                        if (parentLi && parentLi.classList.contains('disabled')) {
                            return 'last_page';
                        }
                        return 'has_next';
                    }
                    // Alternatif: "Sonraki Sayfa" metni
                    var allSpans = document.querySelectorAll('span');
                    for (var i = 0; i < allSpans.length; i++) {
                        if (allSpans[i].textContent.indexOf('Sonraki Sayfa') !== -1) {
                            var pLi = allSpans[i].closest('li');
                            if (pLi && pLi.classList.contains('disabled')) {
                                return 'last_page';
                            }
                            return 'has_next_alt';
                        }
                    }
                    return 'no_pagination';
                """)

                if pagination_info == 'last_page' or pagination_info == 'no_pagination':
                    is_last_page = True
                elif pagination_info == 'has_next':
                    try:
                        next_btn = self.driver.select('#next-page')
                    except Exception:
                        is_last_page = True
                elif pagination_info == 'has_next_alt':
                    # Alternatif buton - JS ile tıklayacağız
                    try:
                        next_btn = self.driver.select('#next-page')
                    except Exception:
                        is_last_page = True

                if is_last_page:
                    self.add_log(f'Son sayfaya ulaşıldı (sayfa {page})', 'info')
                    break

                if not next_btn:
                    self.add_log(f'Sonraki sayfa butonu bulunamadı (sayfa {page})', 'warning')
                    break

                # Sonraki sayfaya geç
                self.scroll_to_element(next_btn)
                time.sleep(0.5)
                self.safe_click(next_btn)

                # Sayfa değişimini bekle - ilk link değişmeli
                page_changed = False
                for _ in range(20):  # Max 10 saniye (20 * 0.5)
                    time.sleep(0.5)
                    new_first_link = self._get_first_link_on_page()
                    if first_link_before and new_first_link and new_first_link != first_link_before:
                        page_changed = True
                        break

                if not page_changed:
                    # Sayfa numarasından kontrol et
                    new_real_page = self._get_current_page_number()
                    if new_real_page and new_real_page != page:
                        page_changed = True
                    else:
                        self.add_log(f'Sayfa {page}: Sonraki sayfaya geçilemedi, tarama durduruluyor', 'warning')
                        break

                page += 1

            except Exception as e:
                self.add_log(f'Sayfa {page} tarama hatası: {e}', 'error')
                self.stats['errors'] += 1
                break

        self.add_log(f'Tarama tamamlandı: {page} sayfa tarandı, {len(all_links)} toplam link', 'info')
        return all_links

    def _get_with_timeout(self, url, timeout=120):
        """Sayfa açmayı timeout ile yap - Cloudflare takılmasını önle"""
        result = {'success': False, 'error': None}

        def _load():
            try:
                self.driver.google_get(url, bypass_cloudflare=True)
                result['success'] = True
            except Exception as e:
                result['error'] = str(e)

        load_thread = threading.Thread(target=_load, daemon=True)
        load_thread.start()
        load_thread.join(timeout=timeout)

        if load_thread.is_alive():
            self.add_log(f'Sayfa yükleme {timeout}sn timeout! Cloudflare geçilememiş olabilir.', 'error')
            return False

        if not result['success']:
            self.add_log(f'Sayfa yükleme hatası: {result["error"]}', 'error')
            return False

        return True

    def _wait_for_page_ready(self, timeout=60):
        """Sayfanın yüklendiğini kontrol et. Cloudflare varsa geçmesini bekle, yoksa direkt devam et."""
        end_time = time.time() + timeout
        cloudflare_detected = False

        while time.time() < end_time:
            try:
                page_title = self._run_js("return document.title") or ''
                current_url = self._run_js("return window.location.href") or ''

                # 1) Önce sayfa hazır mı kontrol et (Cloudflare olmadan direkt açılmış olabilir)
                try:
                    if self._run_js("return document.getElementById('filters_div') !== null"):
                        self.add_log('Sayfa hazır - filtre bölümü bulundu', 'success')
                        return True
                except:
                    pass

                # gamermarkt sayfasındayız ve ilanlar yüklüyse hazır
                if 'gamermarkt.com' in current_url and 'ilanlar' in current_url:
                    try:
                        if self._run_js("return document.getElementById('submitForm') !== null"):
                            self.add_log(f'Sayfa hazır: {current_url}', 'success')
                            return True
                    except:
                        pass

                # 2) Cloudflare challenge sayfasında mıyız?
                is_cloudflare = any([
                    'just a moment' in page_title.lower(),
                    'attention required' in page_title.lower(),
                    'challenge' in current_url.lower(),
                    'cdn-cgi' in current_url.lower(),
                ])

                if is_cloudflare:
                    if not cloudflare_detected:
                        self.add_log('Cloudflare challenge tespit edildi, geçilmesi bekleniyor...', 'info')
                        cloudflare_detected = True
                    time.sleep(3)
                    continue

                # 3) Ne Cloudflare ne de hazır sayfa - henüz yükleniyor olabilir
                time.sleep(1)

            except Exception as e:
                self.add_log(f'Sayfa kontrol hatası: {e}', 'warning')
                time.sleep(2)

        self.add_log(f'Sayfa {timeout}sn içinde hazır olmadı!', 'error')
        return False

    def start(self):
        """Scraper'i baslat"""
        self.is_running = True
        self.add_log(f'{self.category.upper()} icin scraper baslatiliyor...', 'info')

        if not self.init_driver():
            return False

        try:
            url = self.urls.get(self.category)
            self.add_log(f'Sayfa açılıyor: {url}', 'info')

            if not self._get_with_timeout(url, timeout=120):
                self.add_log('Sayfa açılamadı (timeout veya hata)', 'error')
                return False

            self.add_log(f'Sayfa acildi: {url}', 'info')

            # Cloudflare geçildi mi ve sayfa hazır mı kontrol et
            if not self._wait_for_page_ready(timeout=60):
                self.add_log('Sayfa hazır değil - Cloudflare geçilememiş olabilir', 'error')
                return False

            # Sayfa yüklenmesi için ek bekleme
            time.sleep(3)

            if not self.apply_filters():
                self.add_log('Filtre uygulama basarisiz, tekrar deneniyor...', 'warning')
                time.sleep(3)
                if not self.apply_filters():
                    return False

            links = self.scrape_all_pages()
            self.scraped_links = links
            self.stats['total_links'] = len(links)

            self.add_log(f'Toplam {len(links)} link cekildi', 'info')
            return True

        except Exception as e:
            self.add_log(f'Scraper hatasi: {e}', 'error')
            self.stats['errors'] += 1
            return False
        finally:
            # Başarısız olsa bile driver'ı kapat (stop() ayrıca çağrılırsa zaten kontrol eder)
            if not self.scraped_links and self.driver:
                try:
                    self.driver.close()
                except:
                    pass
                self.driver = None

    def change_filters_and_scrape(self, new_filters):
        """Mevcut Chrome oturumunu kapatmadan filtreleri değiştirip tekrar tara.

        Aynı oyun için birden fazla preset varsa, ilk preset start() ile açılır,
        sonrakiler bu metod ile aynı Chrome üzerinde taranır.

        Args:
            new_filters: Yeni filtre ayarları dict (scraper formatında)

        Returns:
            bool: Başarılı mı
        """
        if not self.driver:
            self.add_log('Driver yok, change_filters_and_scrape çalıştırılamaz', 'error')
            return False

        self.is_running = True
        self.filters = new_filters
        self.scraped_links = set()  # Önceki sonuçları sıfırla

        self.add_log(f'{self.category.upper()} için filtreler değiştiriliyor...', 'info')

        try:
            # Sayfayı yeniden yükle (filtreleri sıfırlamak için)
            url = self.urls.get(self.category)
            self.add_log(f'Sayfa yeniden yükleniyor: {url}', 'info')

            if not self._get_with_timeout(url, timeout=120):
                self.add_log('Sayfa yeniden yüklenemedi (timeout)', 'error')
                return False

            self.add_log(f'Sayfa yeniden yüklendi: {url}', 'info')

            # Cloudflare geçildi mi kontrol et
            if not self._wait_for_page_ready(timeout=60):
                self.add_log('Sayfa hazır değil - Cloudflare geçilememiş olabilir', 'error')
                return False

            time.sleep(3)

            if not self.apply_filters():
                self.add_log('Filtre uygulama başarısız, tekrar deneniyor...', 'warning')
                time.sleep(3)
                if not self.apply_filters():
                    return False

            links = self.scrape_all_pages()
            self.scraped_links = links
            self.stats['total_links'] = len(links)

            self.add_log(f'Filtre değişikliği ile {len(links)} link çekildi', 'info')
            return True

        except Exception as e:
            self.add_log(f'change_filters_and_scrape hatası: {e}', 'error')
            self.stats['errors'] += 1
            return False

    def stop(self):
        """Scraper'i durdur"""
        self.is_running = False
        if self.driver:
            try:
                self.driver.close()
            except:
                pass
            self.driver = None

        self.add_log('Scraper durduruldu', 'warning')

    def get_status(self):
        """Durum bilgisi dondur"""
        return {
            'is_running': self.is_running,
            'stats': self.stats,
            'logs': self.logs[-10:],
            'total_links': self.stats['total_links'],
            'new_listings': self.stats['new_listings'],
            'deleted_listings': self.stats['deleted_listings'],
            'errors': self.stats['errors']
        }


# Test
if __name__ == '__main__':
    filters = {
        'min_price': 40,
        'max_price': 10000,
        'min_agent': 20,
        'max_agent': 23,
        'min_skin': 50,
        'max_skin': 727,
        'servers': ['EU'],
        'divisions': ['0']
    }

    scraper = GamerMarktScraper('valorant', filters)
    scraper.start()

    print(f"\nToplam link: {len(scraper.scraped_links)}")
    print("Ilk 5 link:")
    for link in list(scraper.scraped_links)[:5]:
        print(f"  - {link}")
