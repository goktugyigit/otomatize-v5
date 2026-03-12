import json
import time
import os
import random
from botasaurus_bridge import BotasaurusBridge, By, NoSuchElementException
from bs4 import BeautifulSoup

LISTINGS_FILE = 'listings.json'
ULTRA_DETAILS_FILE = 'ultra_details.json'

def load_listings():
    """listings.json'ı yükle"""
    if os.path.exists(LISTINGS_FILE):
        try:
            with open(LISTINGS_FILE, 'r', encoding='utf-8') as f:
                listings = json.load(f)
                if isinstance(listings, list):
                    return listings
        except Exception as e:
            print(f"Error loading listings.json: {e}")
    return []

def load_ultra_details():
    """Ultra details dosyasını yükle (id -> detail mapping)"""
    if os.path.exists(ULTRA_DETAILS_FILE):
        # Retry mekanizması - dosya kilitli olabilir
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(ULTRA_DETAILS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Dosya boş veya bozuksa
                    if not isinstance(data, dict):
                        print(f"[KRİTİK HATA] ultra_details.json geçersiz format!")
                        raise SystemExit(1)
                    print(f"[DEBUG] Loaded {len(data)} records from ultra_details.json")
                    return data
            except json.JSONDecodeError as e:
                print(f"[KRİTİK HATA] ultra_details.json bozuk! Scraping DURDURULUYOR!")
                print(f"   -> Hata: {e}")
                raise SystemExit(1)
            except PermissionError as e:
                print(f"[UYARI] Dosya kilitli, tekrar deneniyor... ({attempt+1}/{max_retries})")
                time.sleep(1)
                if attempt == max_retries - 1:
                    print(f"[KRİTİK HATA] Dosya açılamadı!")
                    raise SystemExit(1)
            except Exception as e:
                print(f"[KRİTİK HATA] ultra_details.json okunamadı! Scraping DURDURULUYOR!")
                print(f"   -> Hata: {e}")
                raise SystemExit(1)
    else:
        print(f"[INFO] ultra_details.json bulunamadı, yeni dosya oluşturulacak.")
    return {}

# Global değişken - en yüksek kayıt sayısını takip et
_max_records_seen = 0

def save_ultra_details(details):
    """Ultra details'i ayrı dosyaya kaydet"""
    global _max_records_seen
    
    new_count = len(details)
    
    # En yüksek kayıt sayısını güncelle
    if new_count > _max_records_seen:
        _max_records_seen = new_count
    
    # KORUMA 1: Eğer daha önce çok kayıt gördüysek ve şimdi çok azsa, DURDUR!
    if _max_records_seen > 50 and new_count < _max_records_seen * 0.5:
        print(f"[KRİTİK KORUMA] Hafızadaki veri kaybı tespit edildi!")
        print(f"   -> En yüksek görülen: {_max_records_seen}, Şimdi: {new_count}")
        print(f"   -> Kaydetme İPTAL EDİLDİ!")
        return False
    
    # KORUMA 2: Mevcut dosyayla karşılaştır
    if os.path.exists(ULTRA_DETAILS_FILE):
        try:
            with open(ULTRA_DETAILS_FILE, 'r', encoding='utf-8') as f:
                existing = json.load(f)
            existing_count = len(existing)
            
            # Eğer yeni veri mevcut veriden %50'den fazla azsa, KAYDETME!
            if existing_count > 20 and new_count < existing_count * 0.5:
                print(f"[KRİTİK KORUMA] Dosyadaki veri kaybı tespit edildi!")
                print(f"   -> Mevcut: {existing_count}, Yeni: {new_count}")
                print(f"   -> Kaydetme İPTAL EDİLDİ! Veriler korunuyor.")
                return False
                
            # En yüksek kayıt sayısını dosyadan da güncelle
            if existing_count > _max_records_seen:
                _max_records_seen = existing_count
                
        except Exception as e:
            print(f"[UYARI] Mevcut dosya okunamadı: {e}")
    
    temp_file = ULTRA_DETAILS_FILE + '.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(details, f, ensure_ascii=False, indent=4)
        
        # Windows'ta dosya kilidi sorununu önlemek için
        if os.path.exists(ULTRA_DETAILS_FILE):
            os.remove(ULTRA_DETAILS_FILE)
        os.rename(temp_file, ULTRA_DETAILS_FILE)
        
        print(f"Saved ultra details to file. ({new_count} records, max seen: {_max_records_seen})")
        return True
    except Exception as e:
        print(f"Error saving ultra details: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        return False

def trigger_details_ajax(driver):
    """Site'nin tab içeriklerini yükleyen olayları tetikle ve bekle.
    Doğrudan sitenin kendi click veya $.post mekanizmasını kullanır.
    """
    import time
    from botasaurus_bridge import By
    
    try:
        already_loaded = driver.execute_script("return typeof details_loaded !== 'undefined' && details_loaded === 1")
        if already_loaded:
            print("   -> [AJAX] Details zaten yüklenmiş (details_loaded=1)")
            return True
    except:
        pass

    try:
        # 1. Aşama: Sitenin kendi sekmesine tıklayarak AJAX'ı tetikle
        tab_links = driver.find_elements(By.CSS_SELECTOR, "a[data-bs-toggle='tab'], .nav-tabs a")
        if tab_links:
            driver.execute_script("arguments[0].click();", tab_links[0])
            
        # 2. Aşama: Fallback olarak doğrudan $.post at. Veriyi iki farkli formla besle garantile.
        driver.execute_script("""
            if (typeof $ !== 'undefined') {
                $.post("", { get_details: 1 }).done(function(data) {
                    if (data) {
                        var obj = typeof data === 'string' ? JSON.parse(data) : data;
                        for (var key in obj) {
                            if (obj.hasOwnProperty(key)) {
                                var div = document.getElementById(key + '_div');
                                if (div) { div.innerHTML = obj[key]; }
                            }
                        }
                    }
                    if (typeof details_loaded !== 'undefined') { details_loaded = 1; }
                });
                
                $.post("", { "get_details": "1" }).done(function(data) {
                    if (data) {
                        var obj = typeof data === 'string' ? JSON.parse(data) : data;
                        for (var key in obj) {
                            if (obj.hasOwnProperty(key)) {
                                var div = document.getElementById(key + '_div');
                                if (div && div.innerHTML.trim() === "") { div.innerHTML = obj[key]; }
                            }
                        }
                    }
                    if (typeof details_loaded !== 'undefined') { details_loaded = 1; }
                });
            }
        """)
    except Exception as e:
        print(f"   -> [AJAX] Tetikleme hatası: {e}")

    # DOM'un dolmasını doğrudan elemanların içinden test et (max 15s bekleme süresi var)
    for i in range(30):
        time.sleep(0.5)
        try:
            val = driver.execute_script("""
                var divs = ['agents_div', 'skins_div', 'outfits_div', 'champions_div'];
                for(var i=0; i<divs.length; i++){
                    var el = document.getElementById(divs[i]);
                    // Eğer div varsa ve içi trimlendikten sonra 50 karakterden büyükse veri gelmiş demektir!
                    if (el && el.innerHTML && el.innerHTML.trim().length > 50) return el.innerHTML.trim().length;
                }
                return 0;
            """)
            if val > 50:
                print(f"   -> [AJAX] Divler başarıyla doldu ({(i+1)*0.5:.1f}s)")
                return True
        except:
            pass

    print("   -> [AJAX] Timeout - İçerik DOM'a yüklenemedi")
    return False


def convert_to_english_url(url):
    """Türkçe URL'yi İngilizce versiyona çevir"""
    # Valorant
    url = url.replace('/tr/ilan/valorant-hesap/', '/listing/valorant-account/')
    url = url.replace('/tr/ilanlar/valorant-hesap/', '/listings/valorant-account/')
    # LoL
    url = url.replace('/tr/ilan/lol-hesap/', '/listing/lol-account/')
    url = url.replace('/tr/ilanlar/lol-hesap/', '/listings/lol-account/')
    # Fortnite
    url = url.replace('/tr/ilan/fortnite-hesap/', '/listing/fortnite-account/')
    url = url.replace('/tr/ilanlar/fortnite-hesap/', '/listings/fortnite-account/')
    # CS2
    url = url.replace('/tr/ilan/cs2-hesap/', '/listing/cs2-account/')
    url = url.replace('/tr/ilanlar/cs2-hesap/', '/listings/cs2-account/')
    # CS2 Item/Skin
    url = url.replace('/tr/ilanlar/cs2-item-skin/', '/listings/cs2-item-skin/')
    return url

def scrape_cs2_details(driver, target_listing):
    """CS2 hesap detaylarını çek"""
    data = {
        'ultra_detail_scraped': True,
        'cs2_account_details': {},
        'listing_description': ''
    }
    
    try:
        # 1. CS2 Account Details (Önizleme)
        print(f"   -> Extracting CS2 Account Details...")
        try:
            page_html = driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # CS2 için özel yapı: text-dark divleri
            text_dark_divs = soup.find_all('div', class_='text-dark')
            
            # İki'şerli grupla (label, value)
            i = 0
            while i < len(text_dark_divs) - 1:
                label_div = text_dark_divs[i]
                value_div = text_dark_divs[i + 1]
                
                label_classes = label_div.get('class', [])
                value_classes = value_div.get('class', [])
                
                # Value'da fw-500 varsa, bu bir label-value çifti
                if 'fw-500' in value_classes and 'fw-500' not in label_classes:
                    label = label_div.get_text(strip=True)
                    value = value_div.get_text(strip=True)
                    
                    if label and value:
                        data['cs2_account_details'][label] = value
                    i += 2
                else:
                    i += 1
            
            print(f"   -> CS2 Account Details: {len(data['cs2_account_details'])} fields")
        except Exception as e:
            print(f"   -> CS2 Account Details error: {e}")
        
        # 2. Listing Description (Tam Açıklama)
        print(f"   -> Extracting Listing Description...")
        try:
            page_html = driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # ck-content class'ından açıklamayı al
            ck_content = soup.find('div', class_='ck-content')
            
            if ck_content:
                data['listing_description'] = ck_content.get_text('\n', strip=True)
                print(f"   -> Listing Description: {len(data['listing_description'])} characters")
            else:
                print(f"   -> Listing Description: Not found")
                
        except Exception as e:
            print(f"   -> Listing Description error: {e}")
                
    except Exception as e:
        print(f"   -> CS2 details extraction error: {e}")
    
    return data

def scrape_cs2_item_details(driver, target_listing):
    """CS2 Item/Skin detaylarını çek"""
    data = {
        'ultra_detail_scraped': True,
        'product_title': '',
        'seller_name': '',
        'seller_id': '',
        'seller_reliability': '',
        'seller_status': '',
        'delivery_hours': '',
        'stickers': [],
        'float_value': '',
        'discount': '',
        'price': ''
    }
    
    try:
        page_html = driver.page_source
        soup = BeautifulSoup(page_html, 'html.parser')
        
        # Product title
        h1 = soup.find('h1')
        if h1:
            data['product_title'] = h1.get_text(strip=True)
        
        # Find table
        table = soup.find('table')
        if not table:
            print(f"   -> No table found")
            return data
        
        # Get the specific row for this listing (match by float/price from listings.json)
        target_float = target_listing.get('float', '')
        target_price = target_listing.get('price', '')
        
        tbody = table.find('tbody')
        rows = tbody.find_all('tr') if tbody else table.find_all('tr')[1:]
        
        print(f"   -> Found {len(rows)} items in table")
        
        for row in rows:
            cols = row.find_all('td')
            if len(cols) < 6:
                continue
            
            # Check if this is the right row (match float)
            float_col = cols[3]
            row_float = float_col.get('data-order', '') or float_col.get_text(strip=True)
            
            # If we have a target float, try to match
            if target_float and target_float not in row_float and row_float not in target_float:
                continue
            
            # Seller info
            seller_col = cols[0]
            seller_link = seller_col.find('a', href=True)
            if seller_link:
                data['seller_name'] = seller_link.get_text(strip=True)
                seller_href = seller_link.get('href', '')
                if 'seller-profile/' in seller_href:
                    data['seller_id'] = seller_href.split('seller-profile/')[-1]
            
            # Reliability
            progress_bar = seller_col.find('div', class_='progress-bar')
            if progress_bar:
                data['seller_reliability'] = progress_bar.get_text(strip=True)
            
            # Online status
            full_text = seller_col.get_text(' ', strip=True)
            if 'Offline' in full_text:
                import re
                offline_match = re.search(r'Offline\s*\([^)]+\)', full_text)
                data['seller_status'] = offline_match.group(0) if offline_match else 'Offline'
            elif 'Online' in full_text:
                data['seller_status'] = 'Online'
            
            # Delivery hours
            data['delivery_hours'] = cols[1].get_text(strip=True)
            
            # Stickers
            sticker_col = cols[2]
            sticker_imgs = sticker_col.find_all('img')
            stickers = []
            for img in sticker_imgs:
                sticker_name = img.get('alt', '') or img.get('title', '')
                if sticker_name:
                    stickers.append(sticker_name)
            data['stickers'] = stickers if stickers else [sticker_col.get_text(strip=True)]
            
            # Float (precise)
            data['float_value'] = row_float
            
            # Discount
            data['discount'] = cols[4].get_text(strip=True)
            
            # Price
            price_col = cols[5]
            price_text = price_col.get_text(strip=True)
            import re
            price_match = re.search(r'₺\s*[\d.,]+', price_text)
            data['price'] = price_match.group(0) if price_match else price_text
            
            print(f"   -> Seller: {data['seller_name']} ({data['seller_reliability']})")
            print(f"   -> Float: {data['float_value']}")
            print(f"   -> Price: {data['price']}")
            break  # Found the matching row
                
    except Exception as e:
        print(f"   -> CS2 Item details extraction error: {e}")
    
    return data


def scrape_fortnite_details(driver, target_listing):
    """Fortnite hesap detaylarını çek"""
    data = {
        'ultra_detail_scraped': True,
        'fortnite_account_details': {},
        'outfits': [],
        'gliders': [],
        'pickaxes': [],
        'back_blings': [],
        'item_wraps': [],
        'contrails': [],
        'emotes': [],
        'loading_screens': [],
        'music_packs': []
    }
    
    try:
        # 1. Fortnite Account Details tab'ına tıkla
        print(f"   -> Extracting Fortnite Account Details...")
        try:
            fortnite_nav = driver.find_element(By.XPATH, "//a[contains(text(), 'Fortnite Account Details')]")
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", fortnite_nav)
            time.sleep(random.uniform(0.3, 0.7))
            driver.execute_script("arguments[0].click();", fortnite_nav)
            time.sleep(2)
            
            page_html = driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # Detayları çek
            detail_items = soup.find_all('div', class_=lambda c: c and 'col-6' in c and 'col-md-4' in c)
            for item in detail_items:
                text = item.get_text(' ', strip=True)
                parts = text.split(' ', 1)
                if len(parts) == 2:
                    label = parts[0].strip()
                    value = parts[1].strip()
                    if label and value:
                        data['fortnite_account_details'][label] = value
            
            print(f"   -> Fortnite Account Details: {len(data['fortnite_account_details'])} fields")
        except Exception as e:
            print(f"   -> Fortnite Account Details error: {e}")
        
        # 2. AJAX ile tab içeriklerini yükle
        print(f"   -> Fortnite tab içerikleri yükleniyor (AJAX)...")
        ajax_ok = trigger_details_ajax(driver)

        if not ajax_ok:
            # Fallback: İlk tab'a tıklayarak AJAX'ı tetiklemeyi dene
            print(f"   -> [FALLBACK] Tab tıklama ile yükleme deneniyor...")
            try:
                tab_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='#tab1']")
                if tab_links:
                    driver.execute_script("arguments[0].click();", tab_links[0])
                    time.sleep(4)
            except:
                pass

        fortnite_tabs = [
            ("Outfits", "outfits_div", "outfits"),
            ("Gliders", "gliders_div", "gliders"),
            ("Pickaxes", "pickaxes_div", "pickaxes"),
            ("Back Blings", "backpacks_div", "back_blings"),
            ("Item Wraps", "itemwraps_div", "item_wraps"),
            ("Contrails", "contrails_div", "contrails"),
            ("Emotes", "dances_div", "emotes"),
            ("Loading Screens", "loadingscreens_div", "loading_screens"),
            ("Music Packs", "musicpacks_div", "music_packs")
        ]

        for tab_name, container_id, data_key in fortnite_tabs:
            try:
                html = driver.execute_script(f"return document.getElementById('{container_id}') ? document.getElementById('{container_id}').innerHTML : ''")
                if not html or len(html.strip()) <= 50:
                    try:
                        container = driver.find_element(By.ID, container_id)
                        html = container.get_attribute('innerHTML')
                        if not html:
                            html = container.get_attribute('outerHTML') or ''
                    except Exception:
                        pass

                if html and len(html.strip()) > 50:
                    soup = BeautifulSoup(html, 'html.parser')
                    items = []

                    # Fortnite yapısı: data-name attribute
                    elements = soup.find_all('div', attrs={'data-name': True})
                    if elements:
                        items = [elem['data-name'] for elem in elements]

                    # Fallback: data-filter-name
                    if not items:
                        elements = soup.find_all('div', attrs={'data-filter-name': True})
                        if elements:
                            items = [elem['data-filter-name'] for elem in elements]

                    # Fallback: img alt
                    if not items:
                        imgs = soup.find_all('img', alt=True)
                        items = [img['alt'] for img in imgs if img['alt'] and img['alt'] not in ['None', '']]

                    data[data_key] = items
                    print(f"   -> {tab_name}: {len(items)} items")
                else:
                    print(f"   -> {tab_name}: Container boş")

            except Exception as e:
                print(f"   -> Error extracting {tab_name}: {e}")
                
    except Exception as e:
        print(f"   -> Fortnite details extraction error: {e}")
    
    return data

def scrape_valorant_details(driver, target_listing):
    """Valorant hesap detaylarını çek - Bağımsız fonksiyon (otomatize_scraper tarafından çağrılabilir)"""
    data = {
        'ultra_detail_scraped': True,
        'valorant_account_details': {},
        'agent_names': [],
        'skin_details': [],
        'rank_history': [],
        'spray_names': [],
        'card_names': [],
        'title_names': [],
        'restrictions': []
    }

    try:
        # Sayfa tam yüklensin - önemli!
        time.sleep(2)

        # Sayfa durumunu kontrol et
        page_html = driver.page_source
        if len(page_html) < 5000:
            print(f"   -> [UYARI] Sayfa içeriği çok kısa ({len(page_html)} byte), Cloudflare olabilir")
            time.sleep(3)  # Ekstra bekleme
            page_html = driver.page_source

        # 1. Restrictions
        try:
            alert_div = driver.find_element(By.CSS_SELECTOR, "div.alert.alert-warning")
            data['restrictions'] = [line.strip() for line in alert_div.text.split('\n') if line.strip()]
            if data['restrictions']:
                print(f"   -> Restrictions found: {data['restrictions']}")
        except:
            pass

        # 2. Account Details
        print(f"   -> Extracting Valorant Account Details...")
        try:
            soup = BeautifulSoup(page_html, 'html.parser')

            known_labels = {
                'Region': 'Region',
                'Level': 'Level',
                'Rank': 'Rank',
                'Act Rank': 'Act Rank',
                'Valorant Points': 'Valorant Points',
                'Radianite Points': 'Radianite Points',
                'Kingdom Credits': 'Kingdom Credits',
                'Account Valorant Region-Affinity': 'Account Valorant Region',
                'Account Creation Country': 'Account Creation Country',
                'Account Created At': 'Account Created At'
            }

            text_dark_divs = soup.find_all('div', class_='text-dark')
            i = 0
            while i < len(text_dark_divs) - 1:
                label_div = text_dark_divs[i]
                value_div = text_dark_divs[i + 1]

                label_classes = label_div.get('class', [])
                value_classes = value_div.get('class', [])

                if 'fw-500' in value_classes and 'fw-500' not in label_classes:
                    label = label_div.get_text(strip=True).strip()
                    value = value_div.get_text(strip=True)

                    for known_label, english_key in known_labels.items():
                        if label == known_label or label.startswith(known_label):
                            if value and len(value) < 100 and english_key not in data['valorant_account_details']:
                                data['valorant_account_details'][english_key] = value
                            break
                    i += 2
                else:
                    i += 1

            print(f"   -> Valorant Account Details: {len(data['valorant_account_details'])} fields")
        except Exception as e:
            print(f"   -> Valorant Account Details error: {e}")

        # 3. Rank History
        try:
            rank_header = None
            for header_text in ['Rank History', 'Kademe (Rank) Geçmişi']:
                try:
                    rank_header = driver.find_element(By.XPATH, f"//h3[contains(text(), '{header_text}')]")
                    break
                except:
                    continue

            if rank_header:
                parent_html = driver.execute_script("return arguments[0].parentElement ? arguments[0].parentElement.outerHTML : null", rank_header)
                if parent_html:
                    soup = BeautifulSoup(parent_html, 'html.parser')
                    table = soup.find('table')
                    if table:
                        tbody = table.find('tbody')
                        if tbody:
                            rows = tbody.find_all('tr')
                            for row in rows:
                                cols = row.find_all('td')
                                if len(cols) >= 3:
                                    data['rank_history'].append({
                                        'season': cols[0].get_text(strip=True),
                                        'rank': cols[1].get_text(strip=True),
                                        'date': cols[2].get_text(strip=True)
                                    })
                    if data['rank_history']:
                        print(f"   -> Rank history extracted: {len(data['rank_history'])} entries")
                    else:
                        print(f"   -> Rank history: tablo bulunamadı")
        except Exception as e:
            print(f"   -> Rank history error: {e}")

        # 4. AJAX ile tab içeriklerini yükle (tab tıklamaya gerek yok)
        print(f"   -> Valorant tab içerikleri yükleniyor (AJAX)...")
        ajax_ok = trigger_details_ajax(driver)

        if not ajax_ok:
            # Fallback: İlk tab'a tıklayarak AJAX'ı tetiklemeyi dene
            print(f"   -> [FALLBACK] Tab tıklama ile yükleme deneniyor...")
            try:
                tab_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='#tab1']")
                if tab_links:
                    driver.execute_script("arguments[0].click();", tab_links[0])
                    time.sleep(4)  # AJAX'ın tamamlanması için daha uzun bekle
            except:
                pass

        tabs = [
            ('agents_div', 'agent_names'),
            ('skins_div', 'skin_details'),
            ('sprays_div', 'spray_names'),
            ('cards_div', 'card_names'),
            ('titles_div', 'title_names')
        ]

        for container_id, data_key in tabs:
            try:
                # Önce execute_script ile doğrudan DOM'dan oku (get_attribute güvenilmez)
                html = driver.execute_script(f"return document.getElementById('{container_id}') ? document.getElementById('{container_id}').innerHTML : ''")

                # Fallback: get_attribute dene
                if not html or len(html.strip()) <= 50:
                    try:
                        container = driver.find_element(By.ID, container_id)
                        html = container.get_attribute('innerHTML')
                    except Exception:
                        pass

                if html and len(html.strip()) > 50:
                    soup = BeautifulSoup(html, 'html.parser')
                    items = []
                    cols = soup.find_all('div', attrs={'data-filter-name': True})
                    if cols:
                        items = [col['data-filter-name'] for col in cols]
                    else:
                        spans = soup.select('p.size-6.fw-500 > span')
                        items = [s.get_text(strip=True) for s in spans]

                    data[data_key] = items
                    print(f"   -> {data_key}: {len(items)} items")
                else:
                    print(f"   -> {data_key}: Container boş")
            except Exception as e:
                print(f"   -> Error extracting {data_key}: {e}")

        # G2G için sayı özeti
        data['agents'] = len(data.get('agent_names', []))
        data['skins'] = len(data.get('skin_details', []))

    except Exception as e:
        print(f"   -> Valorant details extraction error: {e}")

    return data


def scrape_lol_details(driver, target_listing):
    """LoL hesap detaylarını çek - Tüm alanları kapsamlı şekilde"""
    data = {
        'ultra_detail_scraped': True,
        'lol_account_details': {},
        'champions': [],
        'skins': [],
        'chromas': [],
        'summoner_icons': [],
        'wards': [],
        'emotes': []
    }
    
    try:
        # Önce sayfanın düzgün yüklendiğini kontrol et
        try:
            # Satılmış/kaldırılmış ilan kontrolü
            page_text = driver.page_source.lower()
            if 'sold out' in page_text or 'no longer available' in page_text or 'bu ilan mevcut değil' in page_text:
                print(f"   -> ⚠️ İlan satılmış veya kaldırılmış, detay çekme atlanıyor")
                data['sold_or_removed'] = True
                return data
        except:
            pass
            
        # 1. LOL Account Details tab'ına tıkla
        print(f"   -> Extracting LoL Account Details...")
        try:
            # Alternatif selector'lar dene
            lol_nav = None
            selectors = [
                "//a[contains(text(), 'LOL Account Details')]",
                "//a[contains(text(), 'LoL Account Details')]",
                "//a[contains(text(), 'Account Details')]"
            ]
            for selector in selectors:
                try:
                    lol_nav = driver.find_element(By.XPATH, selector)
                    if lol_nav:
                        break
                except:
                    continue
            
            if not lol_nav:
                print(f"   -> LoL Account Details tab bulunamadı, sayfa yapısı farklı olabilir")
                return data
            
            lol_nav = lol_nav  # Bulunan elementi kullan
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", lol_nav)
            time.sleep(random.uniform(0.3, 0.7))
            driver.execute_script("arguments[0].click();", lol_nav)
            time.sleep(2)
            
            page_html = driver.page_source
            soup = BeautifulSoup(page_html, 'html.parser')
            
            # Yeni yöntem: Tüm label-value çiftlerini bul
            # Site yapısı: <div class="row"><div class="col-6">Label</div><div class="col-6">Value</div></div>
            
            # Bilinen alan etiketleri (İngilizce)
            known_labels = [
                'Server', 'Level', 'Honor', 
                'Rank (Solo/Duo)', 'Season Reward (Solo/Duo)', 'Prev. Season (Solo/Duo)',
                'Rank (Flex 5v5)', 'Season Reward (Flex 5v5)', 'Prev. Season (Flex 5v5)',
                'Profile Banner', 'Available Riot Points', 'Available Blue Essence',
                'Account Valorant Region-Affinity', 'Account Creation Country',
                'Account Created At', 'First LoL Server of Account', 'LoL Server History of Account'
            ]
            
            # Yöntem 1: Direkt metin arama ile değerleri bul
            for label in known_labels:
                try:
                    # Label'ı içeren elementi bul
                    label_elements = soup.find_all(string=lambda text: text and label in text if text else False)
                    for label_el in label_elements:
                        parent = label_el.parent
                        if parent:
                            # Kardeş elementi bul (değer)
                            next_sibling = parent.find_next_sibling()
                            if next_sibling:
                                value = next_sibling.get_text(strip=True)
                                if value and len(value) < 100:
                                    # Label'ı kısalt
                                    short_label = label.replace('Available ', '').replace('Account ', '').replace(' of Account', '')
                                    data['lol_account_details'][short_label] = value
                                    break
                except:
                    pass
            
            # Yöntem 2: col-6 yapısını tara
            rows = soup.find_all('div', class_='row')
            for row in rows:
                cols = row.find_all('div', class_=lambda c: c and 'col-' in c if c else False, recursive=False)
                if len(cols) >= 2:
                    label_text = cols[0].get_text(strip=True)
                    value_text = cols[1].get_text(strip=True)
                    
                    # Bilinen etiketlerden biri mi?
                    for known in known_labels:
                        if known in label_text or label_text in known:
                            if value_text and len(value_text) < 100 and value_text not in ['', 'None']:
                                short_label = label_text.replace('Available ', '').replace('Account ', '').replace(' of Account', '')
                                if short_label not in data['lol_account_details']:
                                    data['lol_account_details'][short_label] = value_text
                            break
            
            # Yöntem 3: Spesifik elementleri direkt bul (Riot Points ve Blue Essence için)
            try:
                # Riot Points
                rp_label = soup.find(string=lambda t: t and 'Riot Points' in t if t else False)
                if rp_label:
                    rp_parent = rp_label.find_parent('div')
                    if rp_parent:
                        rp_row = rp_parent.find_parent('div', class_='row')
                        if rp_row:
                            rp_value = rp_row.find_all('div')[-1].get_text(strip=True)
                            if rp_value.isdigit() or rp_value == '0':
                                data['lol_account_details']['Riot Points'] = rp_value
                
                # Blue Essence
                be_label = soup.find(string=lambda t: t and 'Blue Essence' in t if t else False)
                if be_label:
                    be_parent = be_label.find_parent('div')
                    if be_parent:
                        be_row = be_parent.find_parent('div', class_='row')
                        if be_row:
                            be_value = be_row.find_all('div')[-1].get_text(strip=True)
                            if be_value.isdigit():
                                data['lol_account_details']['Blue Essence'] = be_value
            except:
                pass
            
            print(f"   -> LoL Account Details: {len(data['lol_account_details'])} fields")
            if data['lol_account_details']:
                print(f"      Fields: {list(data['lol_account_details'].keys())}")
                
        except Exception as e:
            # Hata mesajını kısalt
            error_msg = str(e).split('\n')[0][:80]
            print(f"   -> LoL Account Details error: {error_msg}")
        
        # 2. AJAX ile tab içeriklerini yükle
        print(f"   -> LoL tab içerikleri yükleniyor (AJAX)...")
        ajax_ok = trigger_details_ajax(driver)

        if not ajax_ok:
            # Fallback: İlk tab'a tıklayarak AJAX'ı tetiklemeyi dene
            print(f"   -> [FALLBACK] Tab tıklama ile yükleme deneniyor...")
            try:
                tab_links = driver.find_elements(By.CSS_SELECTOR, "a[href*='#tab1']")
                if tab_links:
                    driver.execute_script("arguments[0].click();", tab_links[0])
                    time.sleep(4)
            except:
                pass

        lol_tabs = [
            ("Champions", "champions_div", "champions"),
            ("Skins", "skins_div", "skins"),
            ("Chromas", "chromas_div", "chromas"),
            ("Summoner Icons", "summoner_icons_div", "summoner_icons"),
            ("Wards", "ward_skins_div", "wards"),
            ("Emotes", "emotes_div", "emotes")
        ]

        for tab_name, container_id, data_key in lol_tabs:
            try:
                html = driver.execute_script(f"return document.getElementById('{container_id}') ? document.getElementById('{container_id}').innerHTML : ''")
                if not html or len(html.strip()) <= 50:
                    try:
                        container = driver.find_element(By.ID, container_id)
                        html = container.get_attribute('innerHTML')
                        if not html:
                            html = container.get_attribute('outerHTML') or ''
                    except Exception:
                        pass

                if html and len(html.strip()) > 50:
                    soup = BeautifulSoup(html, 'html.parser')
                    items = []

                    # LoL yapısı: data-name attribute
                    elements = soup.find_all('div', attrs={'data-name': True})
                    if elements:
                        items = [elem['data-name'] for elem in elements]

                    # Fallback: data-filter-name
                    if not items:
                        elements = soup.find_all('div', attrs={'data-filter-name': True})
                        if elements:
                            items = [elem['data-filter-name'] for elem in elements]

                    # Fallback: img alt
                    if not items:
                        imgs = soup.find_all('img', alt=True)
                        items = [img['alt'] for img in imgs if img['alt'] and img['alt'] not in ['None', 'Masteries', '']]

                    data[data_key] = items
                    print(f"   -> {tab_name}: {len(items)} items")
                else:
                    print(f"   -> {tab_name}: Container boş")

            except Exception as e:
                error_msg = str(e).split('\n')[0][:100]
                print(f"   -> {tab_name}: Bulunamadı ({error_msg[:50]})" if len(error_msg) > 50 else f"   -> {tab_name}: Bulunamadı")
                
    except Exception as e:
        error_msg = str(e).split('\n')[0][:100]
        print(f"   -> LoL details extraction error: {error_msg}")
    
    return data

def cleanup_error_records():
    """Başlamadan önce scrape_error olan kayıtları temizle (tekrar denensin)"""
    if not os.path.exists('ultra_details.json'):
        return 0
    
    with open('ultra_details.json', 'r', encoding='utf-8') as f:
        ultra_details = json.load(f)
    
    error_ids = [id for id, data in ultra_details.items() if 'scrape_error' in data]
    
    if not error_ids:
        return 0
    
    print(f"-> Found {len(error_ids)} failed records, removing for retry...")
    for id in error_ids:
        del ultra_details[id]
    
    # Güvenli dosya yazma
    temp_file = 'ultra_details.json.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(ultra_details, f, ensure_ascii=False, indent=4)
        
        # Windows'ta dosya kilidi sorununu önlemek için
        if os.path.exists('ultra_details.json'):
            os.remove('ultra_details.json')
        os.rename(temp_file, 'ultra_details.json')
    except Exception as e:
        print(f"-> [HATA] Dosya yazma hatası: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise
    
    return len(error_ids)


def cleanup_old_records():
    """listings.json'da olmayan eski kayıtları ultra_details.json'dan temizle"""
    if not os.path.exists('ultra_details.json') or not os.path.exists('listings.json'):
        return 0
    
    # Geçerli ID'leri al
    with open('listings.json', 'r', encoding='utf-8') as f:
        listings = json.load(f)
    valid_ids = set(item['id'] for item in listings)
    
    # Ultra details yükle
    with open('ultra_details.json', 'r', encoding='utf-8') as f:
        ultra_details = json.load(f)
    
    # Eski kayıtları bul
    old_ids = [id for id in ultra_details.keys() if id not in valid_ids]
    
    if not old_ids:
        return 0
    
    print(f"-> Found {len(old_ids)} old records (not in listings), removing...")
    for id in old_ids:
        del ultra_details[id]
    
    # Güvenli dosya yazma
    temp_file = 'ultra_details.json.tmp'
    try:
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(ultra_details, f, ensure_ascii=False, indent=4)
        
        # Windows'ta dosya kilidi sorununu önlemek için
        if os.path.exists('ultra_details.json'):
            os.remove('ultra_details.json')
        os.rename(temp_file, 'ultra_details.json')
    except Exception as e:
        print(f"-> [HATA] Dosya yazma hatası: {e}")
        if os.path.exists(temp_file):
            os.remove(temp_file)
        raise
    
    return len(old_ids)

def scrape_ultra_details():
    print("Starting Ultra Detail Scraper (English Mode)...")
    
    # Önce eski kayıtları temizle (listings'de olmayanlar)
    cleaned_old = cleanup_old_records()
    if cleaned_old > 0:
        print(f"-> Cleaned {cleaned_old} old records (deleted listings)")
    
    # Sonra hatalı kayıtları temizle (tekrar denensin)
    cleaned_errors = cleanup_error_records()
    if cleaned_errors > 0:
        print(f"-> Cleaned {cleaned_errors} error records, will retry them")
    
    driver = None
    consecutive_errors = 0
    max_consecutive_errors = 3

    try:
        # Botasaurus Bridge ile Cloudflare bypass destekli tarayıcı başlat
        driver = BotasaurusBridge(lang="en", profile="ultra_detail")
        driver.maximize_window()
        driver.start_keep_maximize()
        
        while True:
            listings = load_listings()
            ultra_details = load_ultra_details()

            target_listing = None

            # Find first Valorant, LoL, Fortnite, CS2 or CS2 Item listing that needs details
            for item in listings:
                category = item.get('category')
                item_id = item['id']

                if category in ['Valorant', 'LoL', 'Fortnite', 'CS2', 'CS2 Item'] and item_id not in ultra_details:
                    target_listing = item
                    break
            
            if not target_listing:
                # Beklerken eski kayıtları temizle
                cleaned = cleanup_old_records()
                if cleaned > 0:
                    print(f"-> Cleaned {cleaned} old records")
                
                print("No pending listings found. Waiting 60 seconds...")
                time.sleep(60)
                continue
            
            # URL'yi İngilizce versiyona çevir
            original_url = target_listing['url']
            english_url = convert_to_english_url(original_url)
            print(f"Processing: {target_listing['title']}")
            print(f"   -> URL (TR): {original_url}")
            print(f"   -> URL (EN): {english_url}")
            
            try:
                print(f"   -> Loading page...")
                start_time = time.time()
                
                # Random delay before loading (simulate thinking)
                time.sleep(random.uniform(0.5, 1.5))
                
                driver.get(english_url)
                
                # Wait for Cloudflare/Page Load
                try:
                    print(f"   -> Waiting for page elements...", end='', flush=True)
                    
                    # Custom wait with progress indicator
                    max_wait = 20
                    poll_interval = 0.5
                    elapsed = 0
                    last_dot = 0
                    
                    while elapsed < max_wait:
                        try:
                            # Try to find any of these elements
                            driver.find_element(By.CLASS_NAME, "breadCrumbDiv")
                            break
                        except:
                            try:
                                driver.find_element(By.TAG_NAME, "h1")
                                break
                            except:
                                pass
                        
                        time.sleep(poll_interval)
                        elapsed += poll_interval
                        
                        # Print dot every 2 seconds
                        if elapsed - last_dot >= 2:
                            print(".", end='', flush=True)
                            last_dot = elapsed
                    
                    print()  # New line
                    
                    if elapsed >= max_wait:
                        raise Exception("Timeout waiting for page elements")
                    
                    load_time = time.time() - start_time
                    print(f"   -> Page loaded in {load_time:.1f}s")
                    
                    # DEBUG: Sayfa dilini kontrol et
                    try:
                        html_lang = driver.find_element(By.TAG_NAME, "html").get_attribute("lang")
                        page_title = driver.title
                        current_url = driver.current_url
                        print(f"   -> [DEBUG] HTML lang: {html_lang}")
                        print(f"   -> [DEBUG] Page title: {page_title[:60] if page_title else 'N/A'}")
                        print(f"   -> [DEBUG] Current URL: {current_url}")
                        
                        # Türkçe içerik kontrolü
                        if '/tr/' in current_url or html_lang == 'tr':
                            print(f"   -> [WARNING] Page might be in Turkish! Attempting to switch...")
                            # İngilizce URL'ye yönlendir
                            if '/tr/' in current_url:
                                en_url = current_url.replace('/tr/ilan/', '/listing/').replace('/tr/ilanlar/', '/listings/')
                                en_url = en_url.replace('valorant-hesap', 'valorant-account')
                                driver.get(en_url)
                                time.sleep(2)
                                print(f"   -> [DEBUG] Redirected to: {driver.current_url}")
                    except Exception as debug_e:
                        print(f"   -> [DEBUG] Language check error: {debug_e}")
                        
                except Exception as e:
                    load_time = time.time() - start_time
                    print(f"   -> Page load timeout after {load_time:.1f}s")
                    print(f"   -> Error: {str(e)[:100]}")
                    print(f"   -> Current URL: {driver.current_url}")
                    print(f"   -> Page title: {driver.title[:50] if driver.title else 'No title'}")
                    
                    # Try to save screenshot for debugging
                    try:
                        screenshot_path = f"error_{target_listing['id']}.png"
                        driver.save_screenshot(screenshot_path)
                        print(f"   -> Screenshot saved: {screenshot_path}")
                    except:
                        pass
                    
                    # Mark as scraped to avoid infinite retry
                    error_data = {
                        'id': target_listing['id'],
                        'scrape_error': f'Page load timeout after {load_time:.1f}s',
                        'timestamp': time.time()
                    }
                    ultra_details = load_ultra_details()
                    ultra_details[target_listing['id']] = error_data
                    save_ultra_details(ultra_details)
                    continue
                
                # Scroll (random amount, multiple times like human)
                try:
                    # First scroll
                    scroll_amount = random.randint(300, 500)
                    driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                    time.sleep(random.uniform(0.3, 0.7))
                    
                    # Second scroll (sometimes)
                    if random.random() > 0.5:
                        scroll_amount = random.randint(200, 400)
                        driver.execute_script(f"window.scrollBy(0, {scroll_amount});")
                        time.sleep(random.uniform(0.5, 1.0))
                except Exception as e:
                    print(f"   -> Scroll error: {e}")
                
                # Kategoriye göre farklı scraping
                category = target_listing.get('category')
                
                if category == 'CS2':
                    # CS2 için özel scraping
                    data = scrape_cs2_details(driver, target_listing)
                
                elif category == 'CS2 Item':
                    # CS2 Item/Skin için özel scraping
                    data = scrape_cs2_item_details(driver, target_listing)
                    
                elif category == 'Fortnite':
                    # Fortnite için özel scraping
                    data = scrape_fortnite_details(driver, target_listing)
                    
                elif category == 'LoL':
                    # LoL için özel scraping
                    data = scrape_lol_details(driver, target_listing)
                    
                elif category == 'Valorant':
                    # Valorant için mevcut scraping
                    data = {
                        'ultra_detail_scraped': True,
                        'valorant_account_details': {},
                        'agent_names': [],
                        'skin_details': [],
                        'rank_history': [],
                        'spray_names': [],
                        'card_names': [],
                        'title_names': [],
                        'restrictions': []
                    }
                
                    # VALORANT SCRAPING
                    # 1. Restrictions
                    try:
                        # Random mouse movement (simulate reading)
                        driver.execute_script("window.scrollBy(0, 100);")
                        time.sleep(random.uniform(0.2, 0.5))
                        
                        alert_div = driver.find_element(By.CSS_SELECTOR, "div.alert.alert-warning")
                        data['restrictions'] = [line.strip() for line in alert_div.text.split('\n') if line.strip()]
                        if data['restrictions']:
                            print(f"   -> Restrictions found: {data['restrictions']}")
                    except:
                        pass

                    # 2. Valorant Account Details - Sayfanın üst kısmından çek (tab'a gerek yok)
                    # HTML yapısı: <div class="text-dark">Label</div><div class="text-dark fw-500">Value</div>
                    print(f"   -> Extracting Valorant Account Details...")
                    try:
                        page_html = driver.page_source
                        soup = BeautifulSoup(page_html, 'html.parser')
                        
                        # Bilinen alan etiketleri (İngilizce - site İngilizce modda açılıyor)
                        known_labels = {
                            'Region': 'Region',
                            'Level': 'Level',
                            'Rank': 'Rank',
                            'Act Rank': 'Act Rank',
                            'Valorant Points': 'Valorant Points',
                            'Radianite Points': 'Radianite Points',
                            'Kingdom Credits': 'Kingdom Credits',
                            'Account Valorant Region-Affinity': 'Account Valorant Region',
                            'Account Creation Country': 'Account Creation Country',
                            'Account Created At': 'Account Created At',
                            'First LoL Server of Account': 'First LoL Server',
                            'LoL Server History of Account': 'LoL Server History'
                        }
                        
                        # text-dark divleri çiftler halinde: label (text-dark) + value (text-dark fw-500)
                        text_dark_divs = soup.find_all('div', class_='text-dark')
                        i = 0
                        while i < len(text_dark_divs) - 1:
                            label_div = text_dark_divs[i]
                            value_div = text_dark_divs[i + 1]
                            
                            label_classes = label_div.get('class', [])
                            value_classes = value_div.get('class', [])
                            
                            # Label: text-dark (fw-500 yok), Value: text-dark fw-500
                            if 'fw-500' in value_classes and 'fw-500' not in label_classes:
                                label = label_div.get_text(strip=True)
                                value = value_div.get_text(strip=True)
                                
                                # Tooltip ikonunu temizle (label sonundaki soru işareti)
                                if label:
                                    # "Rank " gibi sonunda boşluk kalabilir
                                    label = label.strip()
                                
                                for known_label, english_key in known_labels.items():
                                    # Tam eşleşme veya başlangıç eşleşmesi (tooltip nedeniyle)
                                    if label == known_label or label.startswith(known_label):
                                        if value and len(value) < 100 and english_key not in data['valorant_account_details']:
                                            data['valorant_account_details'][english_key] = value
                                        break
                                i += 2
                            else:
                                i += 1
                        
                        print(f"   -> Valorant Account Details: {len(data['valorant_account_details'])} fields")
                        if data['valorant_account_details']:
                            print(f"      Fields: {list(data['valorant_account_details'].keys())}")
                    except Exception as e:
                        print(f"   -> Valorant Account Details error: {e}")

                    # 3. Rank History (English: "Rank History" or Turkish: "Kademe (Rank) Geçmişi")
                    try:
                        # Random delay before reading (simulate reading page)
                        time.sleep(random.uniform(0.3, 0.8))
                        
                        # Try English first, then Turkish as fallback
                        rank_header = None
                        for header_text in ['Rank History', 'Kademe (Rank) Geçmişi']:
                            try:
                                rank_header = driver.find_element(By.XPATH, f"//h3[contains(text(), '{header_text}')]")
                                break
                            except:
                                continue
                        
                        if rank_header:
                            parent_html = driver.execute_script("return arguments[0].parentElement ? arguments[0].parentElement.outerHTML : null", rank_header)
                            if parent_html:
                                soup = BeautifulSoup(parent_html, 'html.parser')
                                table = soup.find('table')
                                if table:
                                    tbody = table.find('tbody')
                                    if tbody:
                                        rows = tbody.find_all('tr')
                                        for row in rows:
                                            cols = row.find_all('td')
                                            if len(cols) >= 3:
                                                data['rank_history'].append({
                                                    'season': cols[0].get_text(strip=True),
                                                    'rank': cols[1].get_text(strip=True),
                                                    'date': cols[2].get_text(strip=True)
                                                })
                                print(f"   -> Rank history extracted: {len(data['rank_history'])} entries")
                    except Exception as e:
                        print(f"   -> Rank history error: {e}")

                    # Helper for Tabs
                    def extract_tab_data(tab_href, container_id, data_key):
                        try:
                            tab_links = driver.find_elements(By.CSS_SELECTOR, f"a[href*='{tab_href}']")
                            if not tab_links:
                                print(f"   -> {data_key}: Tab not found")
                                return
                            
                            tab_link = tab_links[0]
                            
                            # Scroll to tab first
                            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tab_link)
                            time.sleep(random.uniform(0.2, 0.5))
                            
                            # Click with JavaScript (more reliable)
                            driver.execute_script("arguments[0].click();", tab_link)
                            
                            time.sleep(random.uniform(1.5, 2.5)) # Wait for AJAX
                            
                            html = driver.execute_script(f"return document.getElementById('{container_id}') ? document.getElementById('{container_id}').innerHTML : ''")
                            if not html or len(html.strip()) <= 50:
                                try:
                                    container = driver.find_element(By.ID, container_id)
                                    html = container.get_attribute('innerHTML')
                                    if not html:
                                        html = container.get_attribute('outerHTML') or ''
                                except Exception:
                                    pass

                            if html and len(html) > 50:
                                soup = BeautifulSoup(html, 'html.parser')
                                items = []
                                cols = soup.find_all('div', attrs={'data-filter-name': True})
                                if cols:
                                    items = [col['data-filter-name'] for col in cols]
                                else:
                                    spans = soup.select('p.size-6.fw-500 > span')
                                    items = [s.get_text(strip=True) for s in spans]

                                data[data_key] = items
                                print(f"   -> {data_key}: {len(items)} items")
                            else:
                                print(f"   -> {data_key}: Empty container")
                        except Exception as e:
                            print(f"   -> Error extracting {data_key}: {e}")

                    # Extract Tabs (with random order sometimes)
                    try:
                        tabs = [
                            ('#tab1', 'agents_div', 'agent_names'),
                            ('#tab2', 'skins_div', 'skin_details'),
                            ('#tab5', 'sprays_div', 'spray_names'),
                            ('#tab6', 'cards_div', 'card_names'),
                            ('#tab7', 'titles_div', 'title_names')
                        ]
                        
                        # Sometimes shuffle tabs (10% chance)
                        if random.random() < 0.1:
                            random.shuffle(tabs)
                        
                        for tab_href, container_id, data_key in tabs:
                            extract_tab_data(tab_href, container_id, data_key)
                            # Random pause between tabs
                            time.sleep(random.uniform(0.3, 0.8))
                            
                    except Exception as e:
                        print(f"   -> Tab extraction error: {e}")
                        # Tab'lar çekilemese bile ultra_detail_scraped = True olsun
                else:
                    # Unknown category
                    data = {
                        'ultra_detail_scraped': True,
                        'scrape_error': f'Unknown category: {category}'
                    }
                
                # Save to ultra_details file
                data['id'] = target_listing['id']
                data['timestamp'] = time.time()

                ultra_details = load_ultra_details()
                ultra_details[target_listing['id']] = data
                save_ultra_details(ultra_details)
                print("   -> Saved details to ultra_details.json")
                consecutive_errors = 0  # Reset on success
                
            except Exception as e:
                error_msg = str(e)
                print(f"Error processing listing {target_listing['id']}: {error_msg[:100]}")
                
                consecutive_errors += 1
                
                # Check if it's a timeout error - might need to restart Chrome
                if 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                    print(f"   -> Timeout error detected ({consecutive_errors}/{max_consecutive_errors})")
                    
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"   -> Too many consecutive errors, restarting Chrome...")
                        try:
                            driver.quit()
                        except:
                            pass

                        time.sleep(5)
                        # Yeni Botasaurus Bridge başlat
                        driver = BotasaurusBridge(lang="en", profile="ultra_detail")
                        driver.maximize_window()
                        driver.start_keep_maximize()
                        consecutive_errors = 0
                        print(f"   -> Chrome restarted (English mode, Botasaurus Bridge)")
                else:
                    # Reset counter on non-timeout errors
                    consecutive_errors = 0
                
                # Mark as scraped to avoid infinite retry on broken listings
                try:
                    error_data = {
                        'id': target_listing['id'],
                        'scrape_error': error_msg[:200],
                        'timestamp': time.time()
                    }
                    ultra_details = load_ultra_details()
                    ultra_details[target_listing['id']] = error_data
                    save_ultra_details(ultra_details)
                    print(f"   -> Marked as scraped with error to avoid retry")
                except Exception as save_error:
                    print(f"   -> Could not save error state: {save_error}")
                time.sleep(random.uniform(2, 4))

            time.sleep(random.uniform(1.5, 3.0)) # Random pause between listings

    except Exception as e:
        print(f"Fatal Scraper Error: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    scrape_ultra_details()
