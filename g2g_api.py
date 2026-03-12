"""
G2G API Wrapper for Otomatize System
V3 mantığı ile uyumlu - Dinamik attribute yapısı

Ana özellikler:
- Attribute'lar G2G API'den dinamik olarak çekilir (cache'lenir)
- Her zaman "Ranked Accounts" seçilir
- Sub-attribute'lar (Rank, Agents, Skins) düzgün şekilde eklenir
- Her ilan benzersiz attribute kombinasyonuna sahip olur
"""

import json
import os
import time
import requests
import hmac
import hashlib
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime
from dotenv import load_dotenv

# Thread-safe file access lock
_offers_file_lock = threading.Lock()

# Load environment variables
load_dotenv()

# G2G API Configuration
G2G_API_BASE = "https://open-api.g2g.com"
G2G_API_KEY = os.getenv('G2G_API_KEY', '')
G2G_API_SECRET = os.getenv('G2G_API_SECRET', '')
G2G_USER_ID = os.getenv('G2G_USER_ID', '')

G2G_CACHE_FILE = "g2g_cache.json"
G2G_OFFERS_FILE = "g2g_offers.json"

# Product IDs
PRODUCT_IDS = {
    "Valorant": "d11e60b4-56a3-4543-a094-9278a26985e7",
    "LoL": "104042dd-17b0-4c1d-b6a3-216316485962",
    "CS2": "b2356678-bd5e-414c-b14b-f48966cc6102",
    "Fortnite": "ede464c8-4c67-4965-b3db-bcce96b42cbb"
}

# Service ID for Accounts
ACCOUNTS_SERVICE_ID = "f6a1aba5-473a-4044-836a-8968bbab16d7"


# =============================================================================
# CACHE FUNCTIONS
# =============================================================================

def load_g2g_cache() -> Dict:
    """Load G2G cache from file"""
    if os.path.exists(G2G_CACHE_FILE):
        try:
            with open(G2G_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[G2G] Error loading cache: {e}")
    return {}


def save_g2g_cache(cache: Dict) -> bool:
    """Save G2G cache to file"""
    try:
        with open(G2G_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[G2G] Error saving cache: {e}")
        return False


def load_g2g_offers() -> Dict:
    """Load G2G offers tracking file - thread-safe with lock"""
    with _offers_file_lock:
        needs_init = False
        
        if os.path.exists(G2G_OFFERS_FILE):
            try:
                with open(G2G_OFFERS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if not content:
                        # Dosya boşsa, flag'i set et
                        needs_init = True
                    else:
                        return json.loads(content)
            except json.JSONDecodeError as e:
                print(f"[G2G] Error loading offers (JSON invalid): {e}")
                # Bozuk dosyayı yedekle ve yeniden başlat
                backup_file = G2G_OFFERS_FILE + '.backup'
                try:
                    import shutil
                    shutil.copy(G2G_OFFERS_FILE, backup_file)
                    print(f"[G2G] Corrupted file backed up to: {backup_file}")
                except:
                    pass
                needs_init = True
            except Exception as e:
                print(f"[G2G] Error loading offers: {e}")
                return {}
        else:
            needs_init = True
        
        # Lock içinde dosyayı initialize et (recursive lock kullanmadığımız için doğrudan yazıyoruz)
        if needs_init:
            print(f"[G2G] Initializing g2g_offers.json...")
            try:
                with open(G2G_OFFERS_FILE, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[G2G] Error initializing offers file: {e}")
        
        return {}


def save_g2g_offers(offers: Dict) -> bool:
    """Save G2G offers tracking file - thread-safe with lock"""
    with _offers_file_lock:
        try:
            # Doğrudan dosyaya yaz (Windows'ta atomic rename sorunlu olabiliyor)
            with open(G2G_OFFERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(offers if offers else {}, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"[G2G] Error saving offers: {e}")
            return False


# =============================================================================
# API REQUEST FUNCTIONS
# =============================================================================

def generate_signature(api_path: str, api_key: str, user_id: str, timestamp: str) -> str:
    """Generate HMAC-SHA256 signature for G2G API"""
    from urllib.parse import urlparse

    # Extract only the path part (no query params)
    parsed_path = urlparse(api_path).path

    # Concatenate: api_path + api_key + user_id + timestamp
    message = f"{parsed_path}{api_key}{user_id}{timestamp}"

    # HMAC-SHA256 with API secret as key
    signature = hmac.new(
        G2G_API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature


def make_api_request(method: str, endpoint: str, data: Dict = None) -> Dict:
    """Make authenticated request to G2G API"""
    if not G2G_API_KEY or not G2G_API_SECRET or not G2G_USER_ID:
        return {"success": False, "error": "API credentials not configured"}

    url = f"{G2G_API_BASE}{endpoint}"
    timestamp = str(int(time.time() * 1000))
    signature = generate_signature(endpoint, G2G_API_KEY, G2G_USER_ID, timestamp)

    headers = {
        "Content-Type": "application/json",
        "g2g-api-key": G2G_API_KEY,
        "g2g-userid": G2G_USER_ID,
        "g2g-signature": signature,
        "g2g-timestamp": timestamp
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=30)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=data, timeout=30)
        elif method == "PATCH":
            response = requests.patch(url, headers=headers, json=data, timeout=30)
        elif method == "DELETE":
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            return {"success": False, "error": f"Unsupported method: {method}"}

        if response.status_code not in [200, 201]:
            print(f"[G2G DEBUG] Request failed:")
            print(f"  Method: {method}")
            print(f"  URL: {url}")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.text[:500]}")

        if response.status_code in [200, 201]:
            return {"success": True, "data": response.json()}
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}",
                "message": response.text
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =============================================================================
# ATTRIBUTE FUNCTIONS (V3 STYLE - DYNAMIC)
# =============================================================================

def get_product_attributes(product_id: str) -> Optional[Dict]:
    """
    G2G API'den ürün attribute'larını çek ve cache'le
    V3 mantığı: Dinamik attribute yapısı
    """
    cache = load_g2g_cache()

    # Cache'de varsa ve 24 saatten eski değilse kullan
    cached = cache.get('attributes', {}).get(product_id)
    if cached:
        cached_time = cached.get('cached_at', 0)
        if time.time() - cached_time < 86400:  # 24 saat
            return cached.get('data')

    # API'den çek
    print(f"[G2G] Fetching attributes for product: {product_id}")
    result = make_api_request('GET', f'/v2/products/{product_id}/attributes')

    if result.get('success'):
        attrs_data = result.get('data', {}).get('payload', {})

        # Cache'e kaydet
        if 'attributes' not in cache:
            cache['attributes'] = {}
        cache['attributes'][product_id] = {
            'data': attrs_data,
            'cached_at': time.time()
        }
        save_g2g_cache(cache)

        return attrs_data

    print(f"[G2G] Failed to fetch attributes: {result.get('error')}")
    return None


def build_offer_attributes(item: Dict, details: Dict = None) -> List[Dict]:
    """
    V3 mantığı ile offer attribute'larını oluştur

    Her zaman "Ranked Accounts" seçilir ve sub-attribute'lar eklenir:
    - Server/Region
    - Account Type = Ranked Accounts
      - Rank (UnRanked, Iron, Bronze, ..., Radiant)
      - Agents/Champions count
      - Skins count
    """
    category = item.get('category', 'Valorant')
    region = item.get('region', 'EU').upper()
    product_id = PRODUCT_IDS.get(category)

    if not product_id:
        print(f"[G2G] Unknown category: {category}")
        return []

    # Attribute verilerini çek
    attrs_data = get_product_attributes(product_id)
    if not attrs_data:
        print(f"[G2G] Could not get attributes for {category}, using fallback")
        return build_fallback_attributes(item, details)

    offer_attributes = []
    attribute_group_list = attrs_data.get('attribute_group_list', [])

    # Item verilerini hazırla
    item_rank = item.get('rank', '').lower()

    # Skins/agents/champions değeri liste olarak gelebilir, sayı olarak da gelebilir
    raw_agents = item.get('agents', 0)
    raw_champions = item.get('champions', 0)
    raw_skins = item.get('skins', 0)

    item_agents = len(raw_agents) if isinstance(raw_agents, list) else int(raw_agents or 0)
    item_champions = len(raw_champions) if isinstance(raw_champions, list) else int(raw_champions or 0)
    item_skins = len(raw_skins) if isinstance(raw_skins, list) else int(raw_skins or 0)

    print(f"[G2G] Attribute values - rank: {item_rank}, agents: {item_agents}, champions: {item_champions}, skins: {item_skins}")

    # LoL için region mapping
    lol_region_map = {
        'EU': 'EUW', 'TR': 'TR', 'NA': 'NA', 'KR': 'KR',
        'BR': 'BR', 'JP': 'JP', 'RU': 'RU', 'OCE': 'OCE',
        'LAN': 'LAN', 'LAS': 'LAS', 'EUNE': 'EUNE'
    }

    # Rank mapping'leri
    valorant_rank_map = {
        'radiant': 'Radiant', 'radyant': 'Radiant',
        'immortal': 'Immortal', 'ölümsüz': 'Immortal',
        'ascendant': 'Ascendant', 'yücelik': 'Ascendant',
        'diamond': 'Diamond', 'elmas': 'Diamond',
        'platinum': 'Platinum', 'platin': 'Platinum',
        'gold': 'Gold', 'altın': 'Gold',
        'silver': 'Silver', 'gümüş': 'Silver',
        'bronze': 'Bronze', 'bronz': 'Bronze',
        'iron': 'Iron', 'demir': 'Iron'
    }

    lol_rank_map = {
        'challenger': 'Challenger', 'grandmaster': 'Grandmaster',
        'master': 'Master', 'diamond': 'Diamond', 'elmas': 'Diamond',
        'emerald': 'Emerald', 'zümrüt': 'Emerald',
        'platinum': 'Platinum', 'platin': 'Platinum',
        'gold': 'Gold', 'altın': 'Gold',
        'silver': 'Silver', 'gümüş': 'Silver',
        'bronze': 'Bronze', 'bronz': 'Bronze',
        'iron': 'Iron', 'demir': 'Iron'
    }

    # CS2 için detayları al
    cs2_prime = 'No'
    cs2_rank = 'Unranked'
    if category == 'CS2' and details:
        cs2_details = details.get('cs2_account_details', {})
        cs2_prime = cs2_details.get('Is CS2 Prime?', 'No')
        cs2_rank = cs2_details.get('Rank', 'Unranked')

    # Fortnite için detayları al
    item_outfits = 0
    item_pickaxes = 0
    item_gliders = 0
    item_emotes = 0
    if category == 'Fortnite' and details:
        item_outfits = len(details.get('outfits', []))
        item_pickaxes = len(details.get('pickaxes', []))
        item_gliders = max(1, len(details.get('gliders', [])))
        item_emotes = max(1, len(details.get('emotes', [])))

    # Her attribute group için işle
    for group in attribute_group_list:
        group_id = group['attribute_group_id']
        group_name = group.get('attribute_group_name', '').lower()
        attr_list = group.get('attribute_list', [])

        # ==================== FORTNITE ====================
        if category == 'Fortnite':
            # Current Solo Rank
            if 'rank' in group_name:
                rank_map = {
                    'unreal': 'Unreal', 'champion': 'Champion', 'elite': 'Elite',
                    'diamond': 'Diamond', 'platinum': 'Platinum', 'gold': 'Gold',
                    'silver': 'Silver', 'bronze': 'Bronze'
                }
                matched_rank = 'UnRanked'
                if item_rank:
                    for key, val in rank_map.items():
                        if key in item_rank:
                            matched_rank = val
                            break
                for attr in attr_list:
                    if attr['attribute_name'] == matched_rank:
                        offer_attributes.append({
                            'attribute_group_id': group_id,
                            'attribute_id': attr['attribute_id']
                        })
                        break

            # Outfits
            elif 'outfits' in group_name:
                ranges = [('1000+', 1000), ('700+', 700), ('500+', 500), ('300+', 300),
                         ('100+', 100), ('50+', 50), ('30+', 30), ('10+', 10)]
                selected = '9 or below'
                for name, min_val in ranges:
                    if item_outfits >= min_val:
                        selected = name
                        break
                for attr in attr_list:
                    if attr['attribute_name'] == selected:
                        offer_attributes.append({
                            'attribute_group_id': group_id,
                            'attribute_id': attr['attribute_id']
                        })
                        break

            # Pickaxes
            elif 'pickaxes' in group_name:
                ranges = [('500+', 500), ('300+', 300), ('100+', 100), ('70+', 70),
                         ('50+', 50), ('30+', 30), ('10+', 10)]
                selected = '9 or below'
                for name, min_val in ranges:
                    if item_pickaxes >= min_val:
                        selected = name
                        break
                for attr in attr_list:
                    if attr['attribute_name'] == selected:
                        offer_attributes.append({
                            'attribute_group_id': group_id,
                            'attribute_id': attr['attribute_id']
                        })
                        break

            # Gliders (number input - attribute_list boş, value olarak gönderilir)
            elif 'gliders' in group_name:
                if item_gliders > 0:
                    offer_attributes.append({
                        'attribute_group_id': group_id,
                        'value': str(item_gliders)
                    })

            # Emotes (number input - attribute_list boş, value olarak gönderilir)
            elif 'emotes' in group_name:
                if item_emotes > 0:
                    offer_attributes.append({
                        'attribute_group_id': group_id,
                        'value': str(item_emotes)
                    })

            continue  # Fortnite için diğer işlemleri atla

        # ==================== CS2 ====================
        if category == 'CS2':
            # Prime Status (mandatory)
            if 'prime status' in group_name:
                target_prime = 'Prime' if cs2_prime.lower() == 'yes' else 'No Prime'
                for attr in attr_list:
                    if attr['attribute_name'] == target_prime:
                        offer_attributes.append({
                            'attribute_group_id': group_id,
                            'attribute_id': attr['attribute_id']
                        })
                        break

            # Account Type (mandatory) - Her zaman "Ranked Accounts"
            elif 'account type' in group_name:
                for attr in attr_list:
                    if attr['attribute_name'] == 'Ranked Accounts':
                        offer_attributes.append({
                            'attribute_group_id': group_id,
                            'attribute_id': attr['attribute_id']
                        })

                        # Ranked Accounts için sub-attribute'lar (mandatory)
                        sub_groups = attr.get('sub_attribute_group_list', [])
                        for sub_group in sub_groups:
                            sub_group_id = sub_group['attribute_group_id']
                            sub_group_name = sub_group.get('attribute_group_name', '').lower()
                            sub_attr_list = sub_group.get('attribute_list', [])

                            # Premier Rating (mandatory)
                            if 'premier rating' in sub_group_name:
                                selected = 'UnRated'
                                for sub_attr in sub_attr_list:
                                    if sub_attr['attribute_name'] == selected:
                                        offer_attributes.append({
                                            'attribute_group_id': sub_group_id,
                                            'attribute_id': sub_attr['attribute_id']
                                        })
                                        break

                            # Current Competitive Rank (mandatory)
                            elif 'current competitive rank' in sub_group_name:
                                rank_map = {
                                    'global elite': 'The Global Elite',
                                    'supreme': 'Supreme Master',
                                    'legendary eagle master': 'Legendary Eagle Master',
                                    'legendary eagle': 'Legendary Eagle',
                                    'distinguished': 'Distinguished MG',
                                    'master guardian elite': 'Master Guardian Elite',
                                    'master guardian': 'Master Guardian',
                                    'gold nova': 'Gold Nova',
                                    'silver': 'Silver'
                                }
                                matched_rank = 'UnRanked'
                                cs2_rank_lower = cs2_rank.lower()
                                for key, val in rank_map.items():
                                    if key in cs2_rank_lower:
                                        matched_rank = val
                                        break
                                for sub_attr in sub_attr_list:
                                    if sub_attr['attribute_name'] == matched_rank:
                                        offer_attributes.append({
                                            'attribute_group_id': sub_group_id,
                                            'attribute_id': sub_attr['attribute_id']
                                        })
                                        break

                            # Medals (mandatory)
                            elif 'medals' in sub_group_name:
                                selected = '5 or below'
                                for sub_attr in sub_attr_list:
                                    if sub_attr['attribute_name'] == selected:
                                        offer_attributes.append({
                                            'attribute_group_id': sub_group_id,
                                            'attribute_id': sub_attr['attribute_id']
                                        })
                                        break
                        break

            continue  # CS2 için diğer işlemleri atla

        # ==================== VALORANT & LOL ====================
        # Server/Region attribute'u
        if 'server' in group_name:
            if category == 'LoL':
                region_mapped = lol_region_map.get(region, region)
            else:
                region_mapped = region

            for attr in attr_list:
                if attr['attribute_name'].upper() == region_mapped.upper():
                    offer_attributes.append({
                        'attribute_group_id': group_id,
                        'attribute_id': attr['attribute_id']
                    })
                    break

        # Account Type attribute'u - HER ZAMAN "Ranked Accounts"
        elif 'account type' in group_name:
            for attr in attr_list:
                if attr['attribute_name'] == 'Ranked Accounts':
                    offer_attributes.append({
                        'attribute_group_id': group_id,
                        'attribute_id': attr['attribute_id']
                    })

                    # Sub attribute group'ları işle
                    sub_groups = attr.get('sub_attribute_group_list', [])
                    for sub_group in sub_groups:
                        sub_group_id = sub_group['attribute_group_id']
                        sub_group_name = sub_group.get('attribute_group_name', '').lower()
                        sub_attr_list = sub_group.get('attribute_list', [])

                        # Rank attribute'u
                        if 'rank' in sub_group_name and 'smurf' not in sub_group_name:
                            rank_map = lol_rank_map if category == 'LoL' else valorant_rank_map
                            matched_rank = None

                            if item_rank:
                                for key, val in rank_map.items():
                                    if key in item_rank:
                                        matched_rank = val
                                        break

                            # Rank bulunamadıysa UnRanked
                            target_rank = matched_rank if matched_rank else 'UnRanked'

                            for sub_attr in sub_attr_list:
                                if sub_attr['attribute_name'] == target_rank:
                                    offer_attributes.append({
                                        'attribute_group_id': sub_group_id,
                                        'attribute_id': sub_attr['attribute_id']
                                    })
                                    break

                        # Agents/Champions attribute'u
                        elif 'agents' in sub_group_name or 'champions' in sub_group_name:
                            count = item_champions if category == 'LoL' else item_agents

                            if category == 'LoL':
                                ranges = [('160+', 160), ('130+', 130), ('100+', 100),
                                         ('50+', 50), ('30+', 30), ('10+', 10)]
                                selected = '9 or below'
                            else:
                                ranges = [('20+', 20), ('15+', 15), ('10+', 10), ('5+', 5)]
                                selected = '5+'

                            for name, min_val in ranges:
                                if count >= min_val:
                                    selected = name
                                    break

                            for sub_attr in sub_attr_list:
                                if sub_attr['attribute_name'] == selected:
                                    offer_attributes.append({
                                        'attribute_group_id': sub_group_id,
                                        'attribute_id': sub_attr['attribute_id']
                                    })
                                    break

                        # Skins attribute'u
                        elif 'skins' in sub_group_name:
                            if category == 'LoL':
                                skin_ranges = [('1000+', 1000), ('500+', 500), ('300+', 300),
                                              ('100+', 100), ('50+', 50), ('10+', 10)]
                            else:
                                skin_ranges = [('500+', 500), ('300+', 300), ('150+', 150),
                                              ('100+', 100), ('50+', 50), ('10+', 10)]
                            selected = '9 or below'

                            for name, min_val in skin_ranges:
                                if item_skins >= min_val:
                                    selected = name
                                    break

                            for sub_attr in sub_attr_list:
                                if sub_attr['attribute_name'] == selected:
                                    offer_attributes.append({
                                        'attribute_group_id': sub_group_id,
                                        'attribute_id': sub_attr['attribute_id']
                                    })
                                    break
                    break

    print(f"[G2G] Built {len(offer_attributes)} attributes for {category}")
    return offer_attributes


def build_fallback_attributes(item: Dict, details: Dict = None) -> List[Dict]:
    """
    API'den attribute çekilemezse kullanılacak fallback
    Hardcoded ID'ler kullanır (son çare)
    """
    category = item.get('category', 'Valorant')
    region = item.get('region', 'EU').upper()

    attributes = []

    # Sadece temel attribute'ları ekle
    if category == 'Valorant':
        # Server
        server_ids = {'EU': 'b3a06cc8', 'NA': 'c9fda90e', 'TR': 'a5f690f8'}
        if region in server_ids:
            attributes.append({
                'attribute_group_id': '330ad3f1',
                'attribute_id': server_ids[region]
            })

        # Account Type = Ranked Accounts
        attributes.append({
            'attribute_group_id': '57031965',
            'attribute_id': '8f7f8436'  # Ranked Accounts
        })

    elif category == 'LoL':
        # Server (EU -> EUW mapping)
        server_ids = {'EUW': '304244a1', 'TR': '2247e703', 'NA': 'e2f2c55b', 'EU': '304244a1'}
        if region in server_ids:
            attributes.append({
                'attribute_group_id': 'e80c30d1',
                'attribute_id': server_ids[region]
            })

        # Account Type = Ranked Accounts
        attributes.append({
            'attribute_group_id': '319340f0',
            'attribute_id': '65ec9642'  # Ranked Accounts
        })

    print(f"[G2G] Using fallback attributes for {category}: {len(attributes)} items")
    return attributes


# =============================================================================
# OFFER CRUD FUNCTIONS
# =============================================================================

def create_offer(
    product_id: str,
    title: str,
    description: str,
    unit_price: float,
    offer_attributes: List[Dict],
    currency: str = "USD",
    min_qty: int = 1,
    api_qty: int = 1,
    available_qty: int = 1,
    low_stock_alert_qty: int = 0,
    delivery_method_ids: List[str] = None,
    custom_attributes: List[Dict] = None
) -> Dict:
    """
    G2G'de yeni ilan oluştur (v2 API)
    V3 ile uyumlu parametre yapısı
    """
    if not G2G_API_KEY or not G2G_API_SECRET or not G2G_USER_ID:
        # Simulation mode
        import random
        offer_id = f"G{int(time.time())}{random.randint(1000, 9999)}ZG"
        print(f"[G2G] 📝 Simulated offer created: {offer_id}")
        return {"success": True, "offer_id": offer_id, "simulated": True}

    # Offer data
    data = {
        'product_id': product_id,
        'service_id': ACCOUNTS_SERVICE_ID,
        'title': title[:128],  # Max 128 karakter
        'description': description,
        'status': 'live',
        'currency': currency,
        'unit_price': round(unit_price, 2),
        'min_qty': min_qty,
        'api_qty': api_qty,
        'available_qty': available_qty,
        'low_stock_alert_qty': low_stock_alert_qty,
        'offer_attributes': offer_attributes
    }

    # Delivery method (opsiyonel)
    if delivery_method_ids:
        data['delivery_method_ids'] = delivery_method_ids

    # Custom attributes (Fortnite Gliders/Emotes için)
    if custom_attributes:
        for custom_attr in custom_attributes:
            data['offer_attributes'].append(custom_attr)

    print(f"[G2G] Creating offer: {title[:50]}...")
    print(f"[G2G] Price: ${unit_price:.2f}, Attributes: {len(offer_attributes)}")

    result = make_api_request("POST", "/v2/offers", data)

    if result.get("success"):
        response_data = result.get("data", {})
        payload = response_data.get("payload", {})
        offer_id = payload.get("offer_id") or response_data.get("offer_id")

        if offer_id:
            print(f"[G2G] ✅ Offer created: {offer_id}")
            return {
                "success": True,
                "offer_id": offer_id,
                "data": response_data
            }
        else:
            return {"success": False, "error": "No offer_id in response"}
    else:
        return {
            "success": False,
            "error": result.get("error", "Unknown error"),
            "message": result.get("message", "")
        }


def update_offer(offer_id: str, title: str = None, description: str = None,
                price_usd: float = None, quantity: int = None) -> Dict:
    """Update an existing offer"""
    if not G2G_API_KEY or not G2G_API_SECRET or not G2G_USER_ID:
        return {"success": False, "error": "API credentials not configured"}

    offer_update = {"offer_id": str(offer_id)}

    if title is not None:
        offer_update["title"] = title
    if description is not None:
        offer_update["description"] = description
    if price_usd is not None:
        offer_update["unit_price"] = round(price_usd, 2)
    if quantity is not None:
        offer_update["available_qty"] = quantity
        offer_update["api_qty"] = quantity

    if len(offer_update) <= 1:
        return {"success": False, "error": "No fields to update"}

    batch_data = {"payload": [offer_update]}

    print(f"[G2G] Updating offer {offer_id}...")
    result = make_api_request("POST", "/v1/offers/update", batch_data)

    if result.get("success"):
        print(f"[G2G] ✅ Offer updated: {offer_id}")
        return {"success": True, "offer_id": offer_id}
    else:
        print(f"[G2G] ❌ Update failed: {result.get('error')}")
        return {"success": False, "error": result.get("error")}


def delete_offer(offer_id: str) -> Dict:
    """Delete an offer from G2G"""
    if not G2G_API_KEY or not G2G_API_SECRET:
        return {"success": False, "error": "API credentials not configured"}

    print(f"[G2G] Deleting offer: {offer_id}")
    result = make_api_request("DELETE", f"/v2/offers/{offer_id}")

    if result.get("success"):
        # Update local tracking
        offers = load_g2g_offers()
        if offer_id in offers:
            offers[offer_id]["status"] = "deleted"
            offers[offer_id]["deleted_at"] = datetime.now().isoformat()
            save_g2g_offers(offers)

        print(f"[G2G] ✅ Offer deleted: {offer_id}")
        return {"success": True, "offer_id": offer_id}
    else:
        print(f"[G2G] ❌ Delete failed: {result.get('error')}")
        return {"success": False, "error": result.get("error")}


# =============================================================================
# PRICE & KUR FUNCTIONS
# =============================================================================

def load_kur() -> float:
    """Load USD/TL exchange rate from kur.json"""
    kur_file = "kur.json"
    default_kur = 35.0

    if os.path.exists(kur_file):
        try:
            with open(kur_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                kur = data.get('usdt_try') or data.get('kur') or data.get('rate') or default_kur
                return float(kur)
        except:
            pass
    return default_kur


def load_profit_margin() -> float:
    """Load profit margin from kur.json"""
    kur_file = "kur.json"
    default_margin = 1.45

    if os.path.exists(kur_file):
        try:
            with open(kur_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return float(data.get('profit_margin', default_margin))
        except:
            pass
    return default_margin


# =============================================================================
# MAIN WRAPPER FUNCTION
# =============================================================================

def create_g2g_offer(
    link_id: str,
    item_data: Dict,
    details: Dict,
    game: str,
    ai_content: Dict = None,
    profit_margin: float = None
) -> Optional[str]:
    """
    Ana wrapper fonksiyon - otomatize_scraper tarafından çağrılır
    V3 mantığı ile ilan oluşturur

    Args:
        link_id: Benzersiz ilan ID'si (örn: VALORANT_12345)
        item_data: Temel ilan bilgileri
        details: ultra_detail_scraper'dan gelen detaylı bilgiler
        game: Oyun adı (valorant, lol, cs2, fortnite)
        ai_content: AI-generated başlık ve açıklama
        profit_margin: Kar marjı çarpanı (preset bazlı, varsayılan 1.45)

    Returns:
        offer_id if successful, None if failed
    """
    # 1. Oyun kategorisini belirle
    game_category_map = {
        'valorant': 'Valorant',
        'lol': 'LoL',
        'cs2': 'CS2',
        'fortnite': 'Fortnite'
    }
    category = game_category_map.get(game.lower(), game.title())
    product_id = PRODUCT_IDS.get(category)

    if not product_id:
        print(f"[G2G] Unknown game category: {game}")
        return None

    # 2. Fiyatı USD'ye çevir
    try:
        price_tl = float(str(item_data.get('price', '0')).replace(',', '.'))
    except:
        price_tl = 0.0

    if price_tl <= 0:
        print(f"[G2G] Invalid price: {item_data.get('price')}")
        return None

    kur = load_kur()
    # Preset bazlı kar marjı kullan, yoksa global varsayılana dön
    if profit_margin is None:
        profit_margin = load_profit_margin()
    price_usd = round((price_tl / kur) * profit_margin, 2)

    if price_usd < 1.0:
        price_usd = 1.0

    print(f"[G2G] Price conversion: {price_tl} TL -> ${price_usd} USD (kur: {kur}, margin: {profit_margin})")

    # 3. Başlık ve açıklama
    if ai_content and ai_content.get('title'):
        title = ai_content['title'][:128]
        description = ai_content.get('description', '')
    else:
        # Fallback
        rank = item_data.get('rank', 'Unranked')
        region = item_data.get('region', '')
        title = f"[{category}] [{region}] {rank} Account"[:128]
        description = f"{category} Account for Sale. Full access provided."

    # 4. Item'a category ekle (build_offer_attributes için)
    item_for_attrs = {**item_data, 'category': category}

    # 5. V3 mantığı ile attribute'ları oluştur
    offer_attributes = build_offer_attributes(item_for_attrs, details)

    if not offer_attributes:
        print(f"[G2G] ❌ No attributes generated for {link_id}")
        return None

    # 6. G2G'ye ilan oluştur
    result = create_offer(
        product_id=product_id,
        title=title,
        description=description,
        unit_price=price_usd,
        offer_attributes=offer_attributes,
        currency='USD',
        min_qty=1,
        api_qty=1,
        available_qty=1,
        low_stock_alert_qty=0
    )

    if result.get('success'):
        offer_id = result.get('offer_id')
        print(f"[G2G] ✅ Offer created: {offer_id} for {link_id}")

        # Local tracking'e kaydet
        offers = load_g2g_offers()
        offers[offer_id] = {
            'offer_id': offer_id,
            'source_link_id': link_id,
            'source_game': game,
            'price_tl': price_tl,
            'price_usd': price_usd,
            'title': title,
            'attributes_count': len(offer_attributes),
            'created_at': datetime.now().isoformat(),
            'status': 'live'
        }
        save_g2g_offers(offers)

        return offer_id
    else:
        print(f"[G2G] ❌ Failed to create offer: {result.get('error')}")
        return None


def check_api_connection() -> Dict:
    """Check if G2G API is accessible"""
    if not G2G_API_KEY or not G2G_API_SECRET or not G2G_USER_ID:
        return {
            "success": True,
            "connected": False,
            "mode": "simulation",
            "message": "Running in simulation mode - API credentials not configured"
        }

    return {
        "success": True,
        "connected": True,
        "mode": "api",
        "message": "G2G API credentials configured"
    }


def initialize_g2g_cache() -> Dict:
    """Initialize/refresh G2G cache"""
    cache = load_g2g_cache()
    cache['initialized'] = True
    save_g2g_cache(cache)
    return cache


# For backwards compatibility
def calculate_g2g_attributes(item: Dict, details: Dict = None) -> Dict:
    """Backwards compatible wrapper"""
    attrs = build_offer_attributes(item, details)
    return {"attribute_list": attrs}


# Export
__all__ = [
    'check_api_connection',
    'initialize_g2g_cache',
    'load_g2g_cache',
    'load_g2g_offers',
    'save_g2g_offers',
    'build_offer_attributes',
    'calculate_g2g_attributes',
    'create_offer',
    'create_g2g_offer',
    'update_offer',
    'delete_offer',
    'load_kur',
    'load_profit_margin',
    'PRODUCT_IDS'
]
