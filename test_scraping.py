import json
import time
from botasaurus_bridge import BotasaurusBridge
from ultra_detail_scraper import (
    scrape_valorant_details,
    scrape_lol_details,
    scrape_fortnite_details,
    scrape_cs2_details,
    convert_to_english_url
)

TEST_CASES = [
    {
        'name': 'LOL',
        'url': 'https://www.gamermarkt.com/tr/ilan/lol-hesap/tr-sunucusu-271-level-altin-172-sampiyon-463-kostum-487666-1070642',
        'category': 'LoL',
        'scraper': scrape_lol_details,
        'id': '1070642',
    },
    {
        'name': 'FORTNITE',
        'url': 'https://www.gamermarkt.com/tr/ilan/fortnite-hesap/529-level-611-item-c87dcc-1070744',
        'category': 'Fortnite',
        'scraper': scrape_fortnite_details,
        'id': '1070744',
    },
    {
        'name': 'VALORANT',
        'url': 'https://www.gamermarkt.com/tr/ilan/valorant-hesap/eu-sunucusu-platin-23-ajan-328-kaplama-ab7db0-1070714',
        'category': 'Valorant',
        'scraper': scrape_valorant_details,
        'id': '1070714',
    },
    {
        'name': 'CS2',
        'url': 'https://www.gamermarkt.com/tr/ilan/nadir-10-madalyali-2062-saat-tek-fiyat-kacmaz-c8b84b-1070659',
        'category': 'CS2',
        'scraper': scrape_cs2_details,
        'id': '1070659',
    },
]


def test_all_games():
    all_results = {}

    driver = BotasaurusBridge(lang="en", profile="test_profile_2")
    driver.maximize_window()

    try:
        for tc in TEST_CASES:
            print(f"\n{'='*60}")
            print(f"  {tc['name']} TESTİ")
            print(f"{'='*60}")

            english_url = convert_to_english_url(tc['url'])
            print(f"  URL: {english_url}")

            # İlk giriş - Cloudflare bypass ile
            print(f"  Sayfa açılıyor (CF bypass)...")
            driver.google_get(english_url, bypass_cloudflare=True)
            time.sleep(5)
            print(f"  Sayfa açıldı: {driver.current_url[:80]}")

            target_listing = {
                'id': tc['id'],
                'url': tc['url'],
                'category': tc['category']
            }

            print("  Veriler çekiliyor...")
            data = tc['scraper'](driver, target_listing)

            all_results[tc['name'].lower()] = data

            # Özet
            print(f"\n  --- {tc['name']} SONUÇ ---")
            for key, val in data.items():
                if isinstance(val, list):
                    print(f"  {key}: {len(val)} items")
                elif isinstance(val, dict):
                    print(f"  {key}: {len(val)} fields")
                else:
                    val_str = str(val)
                    print(f"  {key}: {val_str[:80]}")

    except Exception as e:
        print(f"\nHATA: {e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()

    # Kaydet
    with open("test_2.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=4)
    print(f"\n✅ test_2.json kaydedildi ({len(all_results)} oyun)")


if __name__ == "__main__":
    test_all_games()
