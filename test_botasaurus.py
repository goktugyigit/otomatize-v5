"""
Botasaurus driver API test - hangi metodlar çalışıyor kontrol et
"""
from botasaurus_driver import Driver
import time

print("=" * 50)
print("Botasaurus Driver API Test")
print("=" * 50)

# Driver başlat
print("\n[1] Driver başlatılıyor...")
driver = Driver(headless=False, lang="tr")
print("    ✅ Driver başlatıldı")

# Sayfaya git
print("\n[2] Sayfaya gidiliyor...")
driver.google_get("https://www.gamermarkt.com/tr/ilanlar/valorant-hesap", bypass_cloudflare=True)
print("    ✅ Sayfa açıldı")

# Sayfa yüklenmesini bekle
print("\n[3] Sayfa yüklenmesi bekleniyor (5sn)...")
time.sleep(5)

# Sayfa title kontrol
print("\n[4] Sayfa bilgileri:")
try:
    title = driver.run_js("return document.title")
    print(f"    Title: {title}")
except Exception as e:
    print(f"    ❌ Title hatası: {e}")

try:
    url = driver.run_js("return window.location.href")
    print(f"    URL: {url}")
except Exception as e:
    print(f"    ❌ URL hatası: {e}")

# Element bulma testi
print("\n[5] Element bulma testleri:")

# select ile
try:
    el = driver.select('#max_price')
    print(f"    ✅ select('#max_price') bulundu: {el}")
except Exception as e:
    print(f"    ❌ select('#max_price') hatası: {e}")

# wait_for_element ile
try:
    el = driver.wait_for_element('#max_price', wait=8)
    print(f"    ✅ wait_for_element('#max_price') bulundu: {el}")
except Exception as e:
    print(f"    ❌ wait_for_element('#max_price') hatası: {e}")

# scroll_into_view testi
print("\n[6] scroll_into_view testi:")
try:
    el = driver.select('#max_price')
    el.scroll_into_view()
    print("    ✅ scroll_into_view çalıştı")
except Exception as e:
    print(f"    ❌ scroll_into_view hatası: {e}")

# type testi
print("\n[7] type testi (max_price'a 50 yazma):")
try:
    el = driver.select('#max_price')
    el.scroll_into_view()
    time.sleep(0.5)

    # Önce clear
    driver.run_js("document.getElementById('max_price').value = '';")
    time.sleep(0.3)

    el.type("50")
    time.sleep(0.5)

    val = driver.run_js("return document.getElementById('max_price').value")
    print(f"    Değer: {val}")
    if val == "50":
        print("    ✅ type çalıştı!")
    else:
        print(f"    ⚠️ type çalışmadı, değer: {val}")
except Exception as e:
    print(f"    ❌ type hatası: {e}")

# run_js ile değer atama testi
print("\n[8] run_js ile değer atama testi:")
try:
    driver.run_js("""
        var el = document.getElementById('max_price');
        if(el) {
            el.value = '';
            el.value = '100';
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }
    """)
    time.sleep(0.3)
    val = driver.run_js("return document.getElementById('max_price').value")
    print(f"    Değer: {val}")
    if val == "100":
        print("    ✅ run_js değer atama çalıştı!")
    else:
        print(f"    ⚠️ run_js değer atama çalışmadı, değer: {val}")
except Exception as e:
    print(f"    ❌ run_js değer atama hatası: {e}")

# run_js args dict testi
print("\n[9] run_js args dict testi:")
try:
    driver.run_js("""
        var el = document.getElementById(args.id);
        if(el) {
            el.value = '';
            el.value = args.value;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }
    """, {"id": "max_price", "value": "75"})
    time.sleep(0.3)
    val = driver.run_js("return document.getElementById('max_price').value")
    print(f"    Değer: {val}")
    if val == "75":
        print("    ✅ run_js args dict çalıştı!")
    else:
        print(f"    ⚠️ run_js args dict çalışmadı, değer: {val}")
except Exception as e:
    print(f"    ❌ run_js args dict hatası: {e}")

# click testi
print("\n[10] click testi (checkbox server_0):")
try:
    cb = driver.select('#server_0')
    cb.scroll_into_view()
    time.sleep(0.3)

    checked_before = driver.run_js("return document.getElementById('server_0').checked")
    print(f"    Önceki durum: {checked_before}")

    cb.click()
    time.sleep(0.5)

    checked_after = driver.run_js("return document.getElementById('server_0').checked")
    print(f"    Sonraki durum: {checked_after}")

    if checked_before != checked_after:
        print("    ✅ click çalıştı!")
    else:
        print("    ⚠️ click çalışmadı, label click deneniyor...")
        label = driver.select('label[for="server_0"]')
        label.click()
        time.sleep(0.5)
        checked_label = driver.run_js("return document.getElementById('server_0').checked")
        print(f"    Label click sonrası: {checked_label}")
except Exception as e:
    print(f"    ❌ click hatası: {e}")

# submitForm click testi
print("\n[11] submitForm butonu testi:")
try:
    btn = driver.select('#submitForm')
    btn.scroll_into_view()
    time.sleep(0.3)
    print(f"    ✅ submitForm bulundu")
    # Tıklamıyoruz sadece bulunduğunu kontrol ediyoruz
except Exception as e:
    print(f"    ❌ submitForm hatası: {e}")

print("\n" + "=" * 50)
print("Test tamamlandı! 10 saniye sonra kapatılacak...")
print("=" * 50)
time.sleep(10)

try:
    driver.close()
except:
    pass
