"""
Filtre ve Detay Scraping Test Dosyası
=====================================
Bu test:
1. validate_listing_against_filters fonksiyonunun doğru çalışıp çalışmadığını test eder
2. Valorant/LoL/Fortnite detay verisinden item_data oluşturma mantığını test eder
3. innerHTML fix'inin çalışıp çalışmadığını doğrular (botasaurus_bridge)
4. Gerçek bir Valorant detay sayfası scrape ederek tab verilerini kontrol eder

Kullanım:
  python test_filters.py          # Sadece filtre testleri (hızlı, tarayıcı açmaz)
  python test_filters.py --live   # Filtre + gerçek scrape testi (tarayıcı açar)
"""

import json
import sys
import os
import traceback

# =============================================================================
# TEST CONFIG
# =============================================================================
TEST_CONFIG_FILE = 'test_config.json'
REAL_CONFIG_FILE = 'config.json'

# Hangi config'i kullanalım
CONFIG_FILE_TO_USE = TEST_CONFIG_FILE if os.path.exists(TEST_CONFIG_FILE) else REAL_CONFIG_FILE

# =============================================================================
# MOCK: otomatize_scraper'dan bağımsız test için gerekli fonksiyonlar
# =============================================================================
test_logs = []

def add_log(message, level="info", link_id=None, extra_data=None, preset_id=None):
    """Test için log fonksiyonu"""
    test_logs.append({"level": level, "message": message, "preset_id": preset_id})

def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def _check_range(value, min_val, max_val, label, link_id, preset_id):
    """otomatize_scraper.py'deki _check_range kopyası"""
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

def validate_listing_against_filters(item_data, game, preset_id):
    """otomatize_scraper.py'deki validate_listing_against_filters kopyası"""
    config = load_json(CONFIG_FILE_TO_USE)
    preset = next((p for p in config.get('presets', []) if p['id'] == preset_id), None)
    if not preset:
        add_log(f"Filtre doğrulama: Preset bulunamadı ({preset_id})", "warning", preset_id=preset_id)
        return False

    ui_filters = preset.get('filters', {})
    if not ui_filters:
        return True

    link_id = item_data.get('id', '?')
    price_tl = float(item_data.get('price', 0))

    # FİYAT KONTROLÜ
    min_price = ui_filters.get('min_price')
    if min_price:
        try:
            if price_tl < float(min_price):
                add_log(f"Filtre uyumsuz - Fiyat düşük: {price_tl} < {min_price} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass

    max_price = ui_filters.get('max_price')
    if max_price:
        try:
            if price_tl > float(max_price):
                add_log(f"Filtre uyumsuz - Fiyat yüksek: {price_tl} > {max_price} ({link_id})", "warning", preset_id=preset_id)
                return False
        except (ValueError, TypeError):
            pass

    # VALORANT
    if game == 'valorant':
        filter_servers = ui_filters.get('servers', [])
        if filter_servers and item_data.get('region'):
            item_region = item_data['region'].strip().upper()
            normalized_servers = [s.strip().upper() for s in filter_servers]
            if item_region not in normalized_servers:
                add_log(f"Filtre uyumsuz - Server: {item_region} not in {normalized_servers} ({link_id})", "warning", preset_id=preset_id)
                return False

        filter_divisions = ui_filters.get('divisions', [])
        if filter_divisions and item_data.get('rank'):
            item_rank = item_data['rank'].strip()
            item_rank_base = item_rank.split()[0] if item_rank else ''
            valorant_rank_map = {
                'unranked': 'Unranked', 'iron': 'Iron', 'bronze': 'Bronze',
                'silver': 'Silver', 'gold': 'Gold', 'platinum': 'Platinum',
                'diamond': 'Diamond', 'ascendant': 'Ascendant',
                'immortal': 'Immortal', 'radiant': 'Radiant',
                'demir': 'Iron', 'bronz': 'Bronze', 'gümüş': 'Silver',
                'altın': 'Gold', 'platin': 'Platinum', 'elmas': 'Diamond',
                'yücelik': 'Ascendant', 'ölümsüzlük': 'Immortal', 'radyant': 'Radiant'
            }
            item_rank_normalized = valorant_rank_map.get(item_rank_base.lower(), item_rank_base)
            matched = False
            for div in filter_divisions:
                div_normalized = valorant_rank_map.get(div.strip().lower(), div.strip())
                if div_normalized.lower() == item_rank_normalized.lower():
                    matched = True
                    break
            if not matched:
                add_log(f"Filtre uyumsuz - Rank: {item_rank} not in {filter_divisions} ({link_id})", "warning", preset_id=preset_id)
                return False

        if not _check_range(item_data.get('agents', 0), ui_filters.get('min_agent'), ui_filters.get('max_agent'),
                            'Agent', link_id, preset_id):
            return False
        if not _check_range(item_data.get('skins', 0), ui_filters.get('min_skin'), ui_filters.get('max_skin'),
                            'Skin', link_id, preset_id):
            return False

    # LOL
    elif game == 'lol':
        filter_servers = ui_filters.get('servers', [])
        if filter_servers and item_data.get('region'):
            item_region = item_data['region'].strip().upper()
            lol_server_aliases = {'EUNE': 'EUN', 'EUN': 'EUN', 'OCE': 'OC', 'OC': 'OC'}
            item_region_normalized = lol_server_aliases.get(item_region, item_region)
            normalized_servers = [lol_server_aliases.get(s.strip().upper(), s.strip().upper()) for s in filter_servers]
            if item_region_normalized not in normalized_servers:
                add_log(f"Filtre uyumsuz - Server: {item_region} not in {filter_servers} ({link_id})", "warning", preset_id=preset_id)
                return False

        filter_divisions = ui_filters.get('divisions', [])
        if filter_divisions and item_data.get('rank'):
            item_rank = item_data['rank'].strip()
            item_rank_base = item_rank.split()[0] if item_rank else ''
            lol_rank_map = {
                'unranked': 'Unranked', 'iron': 'Iron', 'bronze': 'Bronze',
                'silver': 'Silver', 'gold': 'Gold', 'platinum': 'Platinum',
                'emerald': 'Emerald', 'diamond': 'Diamond', 'master': 'Master',
                'grandmaster': 'Grandmaster', 'challenger': 'Challenger',
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

        if not _check_range(item_data.get('champions', 0), ui_filters.get('min_champs'), ui_filters.get('max_champs'),
                            'Champion', link_id, preset_id):
            return False
        if not _check_range(item_data.get('skins', 0), ui_filters.get('min_skins'), ui_filters.get('max_skins'),
                            'Skin', link_id, preset_id):
            return False

    return True

def build_item_data_from_details(link_id, game, details, price_tl):
    """otomatize_scraper.py'deki item_data oluşturma mantığının kopyası"""
    item_data = {
        'id': link_id,
        'title': 'Test Account',
        'price': str(price_tl),
        'game': game,
        'category': game.title() if game != 'cs2' else 'CS2',
        'region': 'TR'
    }

    if game == 'valorant' and 'valorant_account_details' in details:
        item_data['region'] = details['valorant_account_details'].get('Region', 'TR')
        item_data['rank'] = details['valorant_account_details'].get('Rank', 'Unranked')
        raw_agents = details.get('agents', details.get('agent_names', 0))
        raw_skins = details.get('skins', details.get('skin_details', 0))
        item_data['agents'] = len(raw_agents) if isinstance(raw_agents, list) else int(raw_agents or 0)
        item_data['skins'] = len(raw_skins) if isinstance(raw_skins, list) else int(raw_skins or 0)

    elif game == 'lol' and 'lol_account_details' in details:
        item_data['region'] = details['lol_account_details'].get('Server', 'TR')
        item_data['rank'] = details['lol_account_details'].get('Rank (Solo/Duo)', 'Unranked')
        raw_champs = details.get('champions', [])
        raw_skins = details.get('skins', [])
        item_data['champions'] = len(raw_champs) if isinstance(raw_champs, list) else int(raw_champs or 0)
        item_data['skins'] = len(raw_skins) if isinstance(raw_skins, list) else int(raw_skins or 0)

    elif game == 'fortnite' and 'fortnite_account_details' in details:
        item_data['outfits'] = len(details.get('outfits', []))
        item_data['pickaxes'] = len(details.get('pickaxes', []))

    return item_data


# =============================================================================
# TEST FONKSİYONLARI
# =============================================================================
passed = 0
failed = 0

def test(name, expected, actual):
    global passed, failed
    if expected == actual:
        print(f"  [PASSED] {name}")
        passed += 1
    else:
        print(f"  [FAILED] {name}")
        print(f"           Beklenen: {expected}")
        print(f"           Gercek:   {actual}")
        failed += 1


def test_valorant_filters():
    """Valorant filtre testleri"""
    print("\n" + "="*60)
    print("TEST 1: VALORANT FİLTRE TESTLERİ")
    print("="*60)

    # --- 10-49 skin preset ---
    preset_id = "test-valo-10-49"

    # Skin 0 ile (ESKİ BUG - innerHTML None döndüğünde olan)
    item_skins_0 = {'id': 'VALO_001', 'price': '2000', 'region': 'EU', 'rank': 'Gold 2', 'skins': 0, 'agents': 0}
    test("Skin=0, min_skin=10 -> RED (eski bug senaryosu)",
         False, validate_listing_against_filters(item_skins_0, 'valorant', preset_id))

    # Skin 15 ile (doğru çekildiğinde)
    item_skins_15 = {'id': 'VALO_002', 'price': '2000', 'region': 'EU', 'rank': 'Gold 2', 'skins': 15, 'agents': 8}
    test("Skin=15, min_skin=10, max_skin=49 -> KABUL",
         True, validate_listing_against_filters(item_skins_15, 'valorant', preset_id))

    # Skin 50 ile (max aşımı)
    item_skins_50 = {'id': 'VALO_003', 'price': '2000', 'region': 'EU', 'rank': 'Gold 2', 'skins': 50, 'agents': 12}
    test("Skin=50, max_skin=49 -> RED",
         False, validate_listing_against_filters(item_skins_50, 'valorant', preset_id))

    # Skin 10 (tam sınır)
    item_skins_10 = {'id': 'VALO_004', 'price': '2000', 'region': 'EU', 'rank': 'Silver 3', 'skins': 10, 'agents': 5}
    test("Skin=10, min_skin=10 -> KABUL (sınır değer)",
         True, validate_listing_against_filters(item_skins_10, 'valorant', preset_id))

    # Skin 49 (tam sınır)
    item_skins_49 = {'id': 'VALO_005', 'price': '2000', 'region': 'EU', 'rank': 'Silver 3', 'skins': 49, 'agents': 5}
    test("Skin=49, max_skin=49 -> KABUL (sınır değer)",
         True, validate_listing_against_filters(item_skins_49, 'valorant', preset_id))

    # Fiyat yüksek
    item_expensive = {'id': 'VALO_006', 'price': '6000', 'region': 'EU', 'rank': 'Gold', 'skins': 30, 'agents': 10}
    test("Fiyat=6000, max_price=5000 -> RED",
         False, validate_listing_against_filters(item_expensive, 'valorant', preset_id))

    # Fiyat uygun
    item_cheap = {'id': 'VALO_007', 'price': '4999', 'region': 'EU', 'rank': 'Gold', 'skins': 30, 'agents': 10}
    test("Fiyat=4999, max_price=5000 -> KABUL",
         True, validate_listing_against_filters(item_cheap, 'valorant', preset_id))

    # Yanlış server
    item_na = {'id': 'VALO_008', 'price': '2000', 'region': 'NA', 'rank': 'Gold', 'skins': 30, 'agents': 10}
    test("Server=NA, filtre=EU -> RED",
         False, validate_listing_against_filters(item_na, 'valorant', preset_id))

    # Rank kontrolü - Gold filtre listesinde var
    item_gold = {'id': 'VALO_009', 'price': '2000', 'region': 'EU', 'rank': 'Gold 3', 'skins': 20, 'agents': 8}
    test("Rank=Gold 3, divisions=[Iron..Radiant] -> KABUL",
         True, validate_listing_against_filters(item_gold, 'valorant', preset_id))

    # --- Unranked preset ---
    preset_unranked = "test-valo-unranked"

    # Unranked hesap -> Unranked preset'e uyar
    item_unranked = {'id': 'VALO_010', 'price': '1500', 'region': 'EU', 'rank': 'Unranked', 'skins': 25, 'agents': 6}
    test("Rank=Unranked, divisions=[Unranked] -> KABUL",
         True, validate_listing_against_filters(item_unranked, 'valorant', preset_unranked))

    # Gold hesap -> Unranked preset'e uymaz
    item_gold_unranked = {'id': 'VALO_011', 'price': '1500', 'region': 'EU', 'rank': 'Gold 2', 'skins': 25, 'agents': 6}
    test("Rank=Gold 2, divisions=[Unranked] -> RED",
         False, validate_listing_against_filters(item_gold_unranked, 'valorant', preset_unranked))

    # --- Division boş preset (150-299 vlr) ---
    preset_no_div = "test-valo-no-division"

    # Division boş = rank filtresi yok, sadece skin kontrolü
    item_any_rank = {'id': 'VALO_012', 'price': '5000', 'region': 'EU', 'rank': 'Radiant', 'skins': 200, 'agents': 20}
    test("Division=[], skin=200, min=150, max=299 -> KABUL",
         True, validate_listing_against_filters(item_any_rank, 'valorant', preset_no_div))

    # Skin yetersiz
    item_low_skin = {'id': 'VALO_013', 'price': '5000', 'region': 'EU', 'rank': 'Radiant', 'skins': 100, 'agents': 20}
    test("Division=[], skin=100, min=150 -> RED",
         False, validate_listing_against_filters(item_low_skin, 'valorant', preset_no_div))

    # Türkçe rank testi
    item_turkish_rank = {'id': 'VALO_014', 'price': '2000', 'region': 'EU', 'rank': 'Altın 2', 'skins': 20, 'agents': 8}
    test("Rank=Altın 2 (Türkçe), divisions=[..Gold..] -> KABUL",
         True, validate_listing_against_filters(item_turkish_rank, 'valorant', preset_id))


def test_lol_filters():
    """LoL filtre testleri"""
    print("\n" + "="*60)
    print("TEST 2: LOL FİLTRE TESTLERİ")
    print("="*60)

    preset_id = "test-lol-10-49"

    # Skin 0 (eski bug)
    item_0 = {'id': 'LOL_001', 'price': '1000', 'region': 'EUW', 'rank': 'Gold IV', 'skins': 0, 'champions': 50}
    test("LoL Skin=0, min_skins=10 -> RED (eski bug)",
         False, validate_listing_against_filters(item_0, 'lol', preset_id))

    # Skin 25
    item_25 = {'id': 'LOL_002', 'price': '1000', 'region': 'EUW', 'rank': 'Gold IV', 'skins': 25, 'champions': 80}
    test("LoL Skin=25, min_skins=10, max_skins=49 -> KABUL",
         True, validate_listing_against_filters(item_25, 'lol', preset_id))

    # Skin 50 (max aşımı)
    item_50 = {'id': 'LOL_003', 'price': '1000', 'region': 'EUW', 'rank': 'Gold IV', 'skins': 50, 'champions': 80}
    test("LoL Skin=50, max_skins=49 -> RED",
         False, validate_listing_against_filters(item_50, 'lol', preset_id))

    # Yanlış server
    item_tr = {'id': 'LOL_004', 'price': '1000', 'region': 'TR', 'rank': 'Gold IV', 'skins': 30, 'champions': 80}
    test("LoL Server=TR, filtre=EUW -> RED",
         False, validate_listing_against_filters(item_tr, 'lol', preset_id))

    # EUNE server (alias testi)
    item_eune = {'id': 'LOL_005', 'price': '1000', 'region': 'EUNE', 'rank': 'Gold IV', 'skins': 30, 'champions': 80}
    test("LoL Server=EUNE, filtre=EUW -> RED",
         False, validate_listing_against_filters(item_eune, 'lol', preset_id))

    # Diamond rank
    item_dia = {'id': 'LOL_006', 'price': '1500', 'region': 'EUW', 'rank': 'Diamond I', 'skins': 20, 'champions': 100}
    test("LoL Rank=Diamond I, divisions=tümü -> KABUL",
         True, validate_listing_against_filters(item_dia, 'lol', preset_id))

    # Unranked preset ile ranked hesap
    preset_unranked = "test-lol-unranked"
    item_ranked = {'id': 'LOL_007', 'price': '1000', 'region': 'EUW', 'rank': 'Silver II', 'skins': 30, 'champions': 60}
    test("LoL Rank=Silver, divisions=[Unranked] -> RED",
         False, validate_listing_against_filters(item_ranked, 'lol', preset_unranked))

    # Unranked hesap + unranked preset
    item_unranked = {'id': 'LOL_008', 'price': '1000', 'region': 'EUW', 'rank': 'Unranked', 'skins': 30, 'champions': 60}
    test("LoL Rank=Unranked, divisions=[Unranked] -> KABUL",
         True, validate_listing_against_filters(item_unranked, 'lol', preset_unranked))

    # Division boş preset (300-499)
    preset_no_div = "test-lol-no-division"
    item_any = {'id': 'LOL_009', 'price': '3000', 'region': 'EUW', 'rank': 'Challenger', 'skins': 350, 'champions': 150}
    test("LoL Division=[], skin=350, min=300, max=499 -> KABUL",
         True, validate_listing_against_filters(item_any, 'lol', preset_no_div))

    # Türkçe rank testi
    item_turk = {'id': 'LOL_010', 'price': '1000', 'region': 'EUW', 'rank': 'Elmas III', 'skins': 30, 'champions': 80}
    test("LoL Rank=Elmas III (Türkçe=Diamond), divisions=tümü -> KABUL",
         True, validate_listing_against_filters(item_turk, 'lol', preset_id))


def test_fortnite_filters():
    """Fortnite filtre testleri"""
    print("\n" + "="*60)
    print("TEST 3: FORTNİTE FİLTRE TESTLERİ")
    print("="*60)

    preset_id = "test-fortnite"

    # Fortnite'da sadece fiyat filtresi var, min/max yok -> her şey geçer
    item1 = {'id': 'FN_001', 'price': '500', 'game': 'fortnite'}
    test("Fortnite filtre yok -> KABUL",
         True, validate_listing_against_filters(item1, 'fortnite', preset_id))


def test_item_data_building():
    """Detay verisinden item_data oluşturma testleri"""
    print("\n" + "="*60)
    print("TEST 4: DETAY -> ITEM_DATA DÖNÜŞÜM TESTLERİ")
    print("="*60)

    # --- Valorant: Skin listesi varken (fix sonrası beklenen durum) ---
    valo_details_good = {
        'valorant_account_details': {
            'Region': 'EU',
            'Rank': 'Diamond 2',
            'Level': '150',
            'Account Creation Country': 'Turkey'
        },
        'agent_names': ['Jett', 'Reyna', 'Omen', 'Sage', 'Phoenix', 'Sova', 'Brimstone', 'Cypher', 'Breach', 'Raze', 'Killjoy', 'Viper'],
        'skin_details': ['Elderflame Vandal', 'Reaver Vandal', 'Prime Phantom', 'Oni Phantom', 'Glitchpop Vandal',
                         'RGX 11z Pro Vandal', 'Spectrum Phantom', 'Champions Vandal', 'Magepunk Operator',
                         'Sovereign Ghost', 'Ion Phantom', 'Araxys Vandal', 'Ruination Phantom',
                         'Sentinels of Light Vandal', 'Gaia\'s Vengeance Vandal', 'Protocol 781-A Phantom',
                         'Prelude to Chaos Vandal', 'Crimsonbeast Vandal', 'Chronovoid Vandal', 'Neo Frontier Phantom',
                         'Evori Dreamwings Vandal', 'Mystbloom Vandal', 'Kuronami Vandal', 'Altitude Phantom',
                         'Radiant Crisis Phantom', 'Endeavour Phantom', 'Kohaku Operator', 'Tigris Phantom'],
        'agents': 12,
        'skins': 28
    }
    item = build_item_data_from_details('VALO_GOOD', 'valorant', valo_details_good, 3000)
    test("Valorant skin listesi -> skins=28",
         28, item['skins'])
    test("Valorant agent listesi -> agents=12",
         12, item['agents'])
    test("Valorant region -> EU",
         'EU', item['region'])
    test("Valorant rank -> Diamond 2",
         'Diamond 2', item['rank'])

    # --- Valorant: Skin listesi BOŞ (eski bug durumu) ---
    valo_details_bug = {
        'valorant_account_details': {
            'Region': 'EU',
            'Rank': 'Gold 1',
        },
        'agent_names': [],
        'skin_details': [],
        'agents': 0,
        'skins': 0
    }
    item_bug = build_item_data_from_details('VALO_BUG', 'valorant', valo_details_bug, 2000)
    test("Valorant BUG durumu (boş listeler) -> skins=0",
         0, item_bug['skins'])
    test("Valorant BUG durumu -> agents=0",
         0, item_bug['agents'])

    # --- Valorant: agents/skins sayı olarak gelirse ---
    valo_details_num = {
        'valorant_account_details': {'Region': 'EU', 'Rank': 'Silver'},
        'agents': 15,
        'skins': 42
    }
    item_num = build_item_data_from_details('VALO_NUM', 'valorant', valo_details_num, 2500)
    test("Valorant sayı olarak agents=15 -> 15",
         15, item_num['agents'])
    test("Valorant sayı olarak skins=42 -> 42",
         42, item_num['skins'])

    # --- LoL ---
    lol_details = {
        'lol_account_details': {
            'Server': 'EUW',
            'Rank (Solo/Duo)': 'Gold IV',
        },
        'champions': ['Ahri', 'Yasuo', 'Zed', 'Lee Sin', 'Jinx'] * 20,  # 100 champ
        'skins': ['Spirit Blossom Ahri', 'PROJECT Yasuo', 'Championship Zed'] * 10  # 30 skin
    }
    item_lol = build_item_data_from_details('LOL_001', 'lol', lol_details, 1500)
    test("LoL champions listesi -> 100",
         100, item_lol['champions'])
    test("LoL skins listesi -> 30",
         30, item_lol['skins'])
    test("LoL region -> EUW",
         'EUW', item_lol['region'])
    test("LoL rank -> Gold IV",
         'Gold IV', item_lol['rank'])

    # --- Fortnite ---
    fn_details = {
        'fortnite_account_details': {'Level': '300'},
        'outfits': ['Renegade Raider', 'Black Knight', 'Skull Trooper'] * 5,
        'pickaxes': ['Reaper', 'AC/DC'] * 3
    }
    item_fn = build_item_data_from_details('FN_001', 'fortnite', fn_details, 800)
    test("Fortnite outfits -> 15",
         15, item_fn['outfits'])
    test("Fortnite pickaxes -> 6",
         6, item_fn['pickaxes'])


def test_end_to_end_filter():
    """Detaydan item_data oluştur -> filtre uygula (uçtan uca)"""
    print("\n" + "="*60)
    print("TEST 5: UÇTAN UCA TEST (detay -> item_data -> filtre)")
    print("="*60)

    # Senaryo 1: Valorant 28 skin, Gold rank, EU -> 10-49 preset'e uymalı
    details = {
        'valorant_account_details': {'Region': 'EU', 'Rank': 'Gold 2', 'Account Creation Country': 'Turkey'},
        'agent_names': ['Jett', 'Reyna', 'Omen', 'Sage', 'Phoenix', 'Sova', 'Brimstone', 'Cypher'],
        'skin_details': ['Elderflame Vandal', 'Reaver Vandal', 'Prime Phantom'] * 9 + ['Oni Phantom'],
        'agents': 8, 'skins': 28
    }
    item = build_item_data_from_details('E2E_001', 'valorant', details, 3000)
    result = validate_listing_against_filters(item, 'valorant', 'test-valo-10-49')
    test("E2E: 28 skin, Gold, EU, 3000TL -> 10-49 preset KABUL",
         True, result)

    # Senaryo 2: Aynı ilan, 50-99 preset'e uymaz (28 < 50)
    result2 = validate_listing_against_filters(item, 'valorant', 'test-valo-50-99')
    test("E2E: 28 skin -> 50-99 preset RED (skin yetersiz)",
         False, result2)

    # Senaryo 3: innerHTML None bug - skin 0 olarak hesaplandığında
    details_bug = {
        'valorant_account_details': {'Region': 'EU', 'Rank': 'Gold 2', 'Account Creation Country': 'Turkey'},
        'agent_names': [],
        'skin_details': [],
        'agents': 0, 'skins': 0
    }
    item_bug = build_item_data_from_details('E2E_BUG', 'valorant', details_bug, 3000)
    result_bug = validate_listing_against_filters(item_bug, 'valorant', 'test-valo-10-49')
    test("E2E BUG: skin=0, agents=0 -> 10-49 preset RED (eski bug kanıtı)",
         False, result_bug)

    # Senaryo 4: LoL 30 skin, EUW, Gold IV -> 10-49 lol preset'e uymalı
    lol_details = {
        'lol_account_details': {'Server': 'EUW', 'Rank (Solo/Duo)': 'Gold IV'},
        'champions': ['Ahri'] * 80,
        'skins': ['Skin'] * 30
    }
    item_lol = build_item_data_from_details('E2E_LOL', 'lol', lol_details, 1500)
    result_lol = validate_listing_against_filters(item_lol, 'lol', 'test-lol-10-49')
    test("E2E LoL: 30 skin, EUW, Gold IV -> 10-49 KABUL",
         True, result_lol)

    # Senaryo 5: LoL Unranked hesap, ranked preset'e uymaz
    lol_unranked = {
        'lol_account_details': {'Server': 'EUW', 'Rank (Solo/Duo)': 'Unranked'},
        'champions': ['Ahri'] * 50,
        'skins': ['Skin'] * 30
    }
    item_lol_ur = build_item_data_from_details('E2E_LOL_UR', 'lol', lol_unranked, 1000)
    result_lol_ur = validate_listing_against_filters(item_lol_ur, 'lol', 'test-lol-10-49')
    test("E2E LoL: Unranked hesap -> ranked preset RED",
         False, result_lol_ur)

    # Senaryo 6: LoL Unranked hesap -> unranked preset KABUL
    result_lol_ur2 = validate_listing_against_filters(item_lol_ur, 'lol', 'test-lol-unranked')
    test("E2E LoL: Unranked hesap -> unranked preset KABUL",
         True, result_lol_ur2)


def test_innerHTML_fix():
    """botasaurus_bridge get_attribute fix testi"""
    print("\n" + "="*60)
    print("TEST 6: BOTASAURUS BRIDGE innerHTML FIX TESTİ")
    print("="*60)

    try:
        from botasaurus_bridge import BotasaurusBridge
        # get_attribute metodunun fallback mantığını kontrol et
        import inspect
        source = inspect.getsource(BotasaurusBridge.ElementWrapper.get_attribute)

        has_property_fallback = "element['" in source or 'element["' in source
        test("get_attribute: element['name'] property fallback var mı",
             True, has_property_fallback)

        has_getAttribute = "getAttribute" in source
        test("get_attribute: getAttribute HTML attribute fallback var mı",
             True, has_getAttribute)

        # None kontrolü
        has_none_check = "is not None" in source or "result is not None" in source
        test("get_attribute: None kontrolü var mı",
             True, has_none_check)

        print("\n  [INFO] get_attribute kaynak kodu:")
        for line in source.strip().split('\n'):
            print(f"    {line}")

    except Exception as e:
        print(f"  [SKIP] BotasaurusBridge import edilemedi: {e}")
        print(f"  [INFO] Bu test sadece bilgi amaçlıdır, ana testler etkilenmez")


def test_ultra_detail_scraper_none_safety():
    """ultra_detail_scraper.py'de innerHTML None güvenliği"""
    print("\n" + "="*60)
    print("TEST 7: ULTRA_DETAIL_SCRAPER innerHTML None GÜVENLİĞİ")
    print("="*60)

    try:
        with open('ultra_detail_scraper.py', 'r', encoding='utf-8') as f:
            code = f.read()

        # innerHTML kullanılan yerlerde None kontrolü var mı?
        lines = code.split('\n')
        innerHTML_lines = []
        for i, line in enumerate(lines):
            if "get_attribute('innerHTML')" in line:
                innerHTML_lines.append(i + 1)

        print(f"  [INFO] innerHTML kullanılan satırlar: {innerHTML_lines}")

        # Her innerHTML kullanımından sonra None kontrolü var mı kontrol et
        safe_count = 0
        for line_num in innerHTML_lines:
            # Sonraki 5 satıra bak
            context = '\n'.join(lines[line_num:line_num + 5])
            if 'not html' in context or 'html and' in context or 'html is None' in context or 'if html' in context:
                safe_count += 1

        test(f"innerHTML kullanımlarında None kontrolü ({safe_count}/{len(innerHTML_lines)})",
             len(innerHTML_lines), safe_count)

    except Exception as e:
        print(f"  [ERROR] ultra_detail_scraper.py okunamadı: {e}")


def test_live_scrape():
    """Gerçek bir Valorant detay sayfasını scrape et ve tab verilerini kontrol et"""
    print("\n" + "="*60)
    print("TEST 8: CANLI SCRAPE TESTİ (Valorant Detay Sayfası)")
    print("="*60)

    try:
        from botasaurus_bridge import BotasaurusBridge
        from ultra_detail_scraper import scrape_valorant_details
    except ImportError as e:
        print(f"  [SKIP] Import hatası: {e}")
        return

    test_url = "https://www.gamermarkt.com/tr/ilanlar/valorant-hesap"
    driver = None

    try:
        print("  [INFO] Tarayıcı başlatılıyor...")
        driver = BotasaurusBridge(lang="en", profile="test_filter")
        driver.maximize_window()

        # Önce listing sayfasına git, ilk ilanı bul
        print(f"  [INFO] Sayfa açılıyor: {test_url}")
        driver.get(test_url)
        import time
        time.sleep(5)

        # İlk ilan linkini bul
        from botasaurus_bridge import By
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/listing/valorant-account/']")
        if not links:
            print("  [SKIP] Hiç ilan bulunamadı, site erişilemez olabilir")
            return

        first_link = links[0].get_attribute('href')
        print(f"  [INFO] İlk ilan: {first_link}")

        # Detay sayfasına git
        driver.get(first_link)
        time.sleep(5)

        # Sayfanın yüklendiğini kontrol et
        page_html = driver.page_source
        test("Sayfa yüklendi (>5000 byte)",
             True, len(page_html) > 5000)

        # Detay scrape et
        print("  [INFO] Detaylar çekiliyor...")
        dummy_listing = {'id': 'TEST_LIVE', 'url': first_link, 'category': 'Valorant'}
        details = scrape_valorant_details(driver, dummy_listing)

        # Kontroller
        test("valorant_account_details dolu mu",
             True, len(details.get('valorant_account_details', {})) > 0)

        agent_count = len(details.get('agent_names', []))
        skin_count = len(details.get('skin_details', []))
        agents_num = details.get('agents', 0)
        skins_num = details.get('skins', 0)

        print(f"\n  [INFO] Sonuçlar:")
        print(f"    Account Details: {json.dumps(details.get('valorant_account_details', {}), indent=4, ensure_ascii=False)}")
        print(f"    Agent Names ({agent_count}): {details.get('agent_names', [])[:5]}...")
        print(f"    Skin Details ({skin_count}): {details.get('skin_details', [])[:5]}...")
        print(f"    agents (sayı): {agents_num}")
        print(f"    skins (sayı): {skins_num}")
        print(f"    Sprays: {len(details.get('spray_names', []))}")
        print(f"    Cards: {len(details.get('card_names', []))}")
        print(f"    Titles: {len(details.get('title_names', []))}")

        test("agent_names > 0 (innerHTML fix çalıştı mı)",
             True, agent_count > 0)
        test("skin_details > 0 (innerHTML fix çalıştı mı)",
             True, skin_count > 0)
        test("agents sayı == agent_names uzunluğu",
             agent_count, agents_num)
        test("skins sayı == skin_details uzunluğu",
             skin_count, skins_num)

        # Şimdi filtre testi yap
        if skin_count > 0:
            item = build_item_data_from_details('LIVE_TEST', 'valorant', details, 2000)
            print(f"\n  [INFO] Item Data: skins={item['skins']}, agents={item['agents']}, rank={item.get('rank')}, region={item.get('region')}")

            # Uygun preset'i bul
            if 10 <= skin_count <= 49:
                result = validate_listing_against_filters(item, 'valorant', 'test-valo-10-49')
                test(f"Canlı ilan ({skin_count} skin) -> 10-49 preset",
                     True, result)
            elif 50 <= skin_count <= 99:
                result = validate_listing_against_filters(item, 'valorant', 'test-valo-50-99')
                test(f"Canlı ilan ({skin_count} skin) -> 50-99 preset",
                     True, result)
            else:
                print(f"  [INFO] Skin sayısı ({skin_count}) test preset'lerinin dışında, filtre testi atlandı")

    except Exception as e:
        print(f"  [ERROR] Canlı test hatası: {e}")
        traceback.print_exc()
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass


# =============================================================================
# MAIN
# =============================================================================
if __name__ == '__main__':
    print("="*60)
    print("  OTOMATIZE SCRAPER - FİLTRE & DETAY TEST SÜİTİ")
    print("="*60)
    print(f"  Config: {CONFIG_FILE_TO_USE}")
    print(f"  Mod: {'CANLI (--live)' if '--live' in sys.argv else 'OFFLINE (sadece filtre testleri)'}")

    # Offline testler (her zaman çalışır)
    test_valorant_filters()
    test_lol_filters()
    test_fortnite_filters()
    test_item_data_building()
    test_end_to_end_filter()
    test_innerHTML_fix()
    test_ultra_detail_scraper_none_safety()

    # Canlı test (sadece --live ile)
    if '--live' in sys.argv:
        test_live_scrape()
    else:
        print("\n" + "="*60)
        print("  [INFO] Canlı scrape testi atlandı.")
        print("  [INFO] Gerçek tarayıcı ile test için: python test_filters.py --live")
        print("="*60)

    # Özet
    print("\n" + "="*60)
    print(f"  SONUÇ: {passed} PASSED / {failed} FAILED / {passed + failed} TOPLAM")
    print("="*60)

    if failed > 0:
        print("\n  BAŞARISIZ TESTLER İÇİN LOGLARI KONTROL ET:")
        for log in test_logs:
            if log['level'] == 'warning':
                print(f"    [{log['level'].upper()}] {log['message']}")
        sys.exit(1)
    else:
        print("\n  TÜM TESTLER BAŞARILI!")
        sys.exit(0)
