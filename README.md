<div align="center">

# OTOMATIZE

### Automated Game Account Marketplace Bot

*Scrape. Enrich. Price. Publish. Deliver. — All on autopilot.*

**[English](#english)** | **[Türkçe](#türkçe)**

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-REST_API-000000?style=for-the-badge&logo=flask&logoColor=white)
![Botasaurus](https://img.shields.io/badge/Botasaurus-CF_Bypass-FF6B35?style=for-the-badge&logo=googlechrome&logoColor=white)
![Selenium](https://img.shields.io/badge/Selenium-Automation-43B02A?style=for-the-badge&logo=selenium&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Gemini_AI-Content_Gen-4285F4?style=for-the-badge&logo=google&logoColor=white)
![BeautifulSoup](https://img.shields.io/badge/BeautifulSoup4-Parsing-8B0000?style=for-the-badge&logo=python&logoColor=white)
![Binance](https://img.shields.io/badge/Binance-FX_Rates-F0B90B?style=for-the-badge&logo=binance&logoColor=black)
![G2G API](https://img.shields.io/badge/G2G-HMAC_SHA256-00C853?style=for-the-badge&logo=shopify&logoColor=white)
![HTML/JS](https://img.shields.io/badge/HTML%2FJS-Dashboard-E34F26?style=for-the-badge&logo=html5&logoColor=white)

---

<table>
<tr>
<td><b>4</b> Games</td>
<td><b>20+</b> API Endpoints</td>
<td><b>50+</b> AI Variables</td>
<td><b>7</b> Modules</td>
</tr>
</table>

</div>

---

## ENGLISH

---

### Overview

Otomatize is a fully automated pipeline that discovers game account listings on [GamerMarkt](https://gamermarkt.com), extracts detailed account data (skins, ranks, inventory), generates AI-optimized marketplace descriptions via Google Gemini, calculates real-time pricing through Binance exchange rates, and publishes everything to [G2G](https://g2g.com) — with zero manual intervention.

---

### Supported Games

| Game | Filters | Extracted Data |
|:-----|:--------|:---------------|
| **Valorant** | Rank, Skins, Agents, Region, VP/RP | Skin inventory, rank history, agent contracts, sprays, cards, titles |
| **League of Legends** | Rank, Champions, Skins, Region, BE/RP | Champion pool, skin inventory, honor level, season rewards |
| **CS2** | Rank, Skins, Prime, Region | Skin inventory, Faceit level, medals, ban history (VAC/OW/Trade) |
| **Fortnite** | Skins, V-Bucks, Platform | Outfits, pickaxes, gliders, emotes, battle pass, OG status |

---

### Architecture

```
                          ┌──────────────────────────────────────┐
                          │          OTOMATIZE CORE              │
                          │         Flask Backend                │
                          │     20+ REST API Endpoints           │
                          │   Thread-safe Queue Architecture     │
                          └──────┬──────────┬──────────┬────────┘
                                 │          │          │
              ┌──────────────────┤          │          ├──────────────────┐
              │                  │          │          │                  │
   ┌──────────▼────────┐ ┌──────▼────┐ ┌───▼──────┐ ┌▼───────────┐ ┌───▼──────────┐
   │    GamerMarkt     │ │ Botasaurus│ │ Gemini AI│ │ Binance API│ │   G2G API    │
   │  Source Scraper   │ │ CF Bypass │ │  Content │ │  FX Rates  │ │  Marketplace │
   └───────────────────┘ └───────────┘ └──────────┘ └────────────┘ └──────────────┘
```

---

### Features

<table>
<tr><td width="50%">

**Core Automation**
- Multi-preset system with per-game filters
- Full scan → extract → generate → publish pipeline
- Auto-sync: removes G2G offers when source is deleted
- Failed listing retry queue (up to 5 attempts)
- Exponential backoff retry decorator

</td><td width="50%">

**AI & Pricing**
- Google Gemini generates titles & descriptions
- 50+ dynamic variables per game template
- Real-time USDT/TRY via Binance (60s refresh)
- Configurable profit margins per preset
- Structured JSON output enforcement

</td></tr>
<tr><td>

**Browser Automation**
- Botasaurus-based Cloudflare bypass
- Undetected ChromeDriver sets delivery config on G2G (Manual, 10 mins)
- Zombie element cleanup (Quasar framework)
- Multi-method element interaction fallbacks
- Timeout-protected navigation (no hangs)

</td><td>

**Infrastructure**
- Thread-safe concurrency (5+ locks)
- JSON corruption recovery with auto-backups
- Orphan Chrome process cleanup
- ChromeDriver cache race condition handling
- Per-preset persistent + session statistics

</td></tr>
</table>

---

### Web Dashboard

Real-time control panel at `localhost:5001`:

| Feature | Description |
|:--------|:------------|
| **Preset Manager** | Create, edit, clone, activate/deactivate presets per game |
| **Live Logs** | Real-time streaming of all bot activity |
| **Statistics** | Per-preset and global metrics — created, deleted, errors, scanned |
| **Bot Controls** | Start/stop automation, trigger manual scans, manage queues |
| **Exchange Rate** | Live USDT/TRY display with auto-refresh |
| **Error Tracker** | Centralized error log with categorization |
| **Retry Queue** | View and manage failed listings awaiting retry |

---

### Quick Start

#### Prerequisites

- Python 3.10+
- Google Chrome (latest)
- [Google Gemini API Key](https://aistudio.google.com/)
- [G2G API Credentials](https://www.g2g.com/)

#### Installation

```bash
git clone https://github.com/yourusername/otomatize.git
cd otomatize
pip install flask selenium undetected-chromedriver beautifulsoup4 requests python-dotenv google-generativeai botasaurus-driver
```

#### Environment Setup

Create `.env` in the project root:

```env
GEMINI_API_KEY=your_gemini_api_key
G2G_API_KEY=your_g2g_api_key
G2G_API_SECRET=your_g2g_api_secret
G2G_USER_ID=your_g2g_user_id
```

#### Configuration

```bash
cp otomatize_config.json.example otomatize_config.json
```

#### Run

```bash
python otomatize_scraper.py
```

Open **http://localhost:5001** to access the dashboard.

---

### How It Works

```
1. SCAN        GamerMarkt listings filtered by rank, price, region, skins...
       │
2. EXTRACT     Visit each detail page → collect skins, ranks, inventory, bans
       │
3. GENERATE    Send account data to Gemini AI → optimized title & description
       │
4. PRICE       (TRY price × margin) ÷ live USDT/TRY rate = USD price
       │
5. PUBLISH     Create G2G offer via API with attributes, images & pricing
       │
6. SYNC        Detect removed source listings → auto-delete from G2G
       │
7. CONFIGURE   Set "Manual delivery" & "10 mins" speed on G2G via browser automation
```

---

### Project Structure

```
otomatize/
├── otomatize_scraper.py           # Core — Flask server, automation loop, 20+ endpoints
├── otomatize.html                 # Dashboard — real-time control panel UI
├── g2g_api.py                     # G2G API — HMAC-SHA256 auth, offer CRUD, attribute cache
├── gamermarkt_scraper.py          # Scraper — listing discovery, filters, deduplication
├── ultra_detail_scraper.py        # Extractor — per-game account data (skins, ranks, etc.)
├── update_delivery_settings.py    # Delivery config — sets Manual/10mins on G2G via undetected Chrome
├── botasaurus_bridge.py           # Bridge — Selenium-compatible Botasaurus wrapper
├── prompts.json                   # AI — game-specific prompt templates (50+ variables)
├── otomatize_config.json.example  # Config — template with all available settings
├── llms.txt                       # Docs — G2G OpenAPI reference
└── rdp_disconnect.bat             # VDS — safe RDP disconnect without locking session
```

> **Remote Desktop Users:** If you're running this on a remote machine (VDS, VPS, dedicated server, etc.), do NOT close the RDP session with the X button — it locks the session and Chrome stops working in the background. Instead, run `rdp_disconnect.bat` as Administrator to safely disconnect while keeping the bot alive.

---

### Tech Stack

| Layer | Technology |
|:------|:-----------|
| **Backend** | Flask, Python 3.10+, Threading |
| **Browser** | Botasaurus, Undetected ChromeDriver, Selenium |
| **AI** | Google Gemini (generative content) |
| **Parsing** | BeautifulSoup4 |
| **APIs** | G2G REST API (HMAC-SHA256), Binance API |
| **Security** | python-dotenv, HMAC signatures, env-based secrets |

---

### API Endpoints

<details>
<summary><b>Click to expand — 20+ endpoints</b></summary>

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| GET | `/api/status` | Bot status, active preset, cycle info |
| GET | `/api/presets` | List all presets |
| POST | `/api/presets` | Create new preset |
| PUT | `/api/presets/<id>` | Update preset |
| DELETE | `/api/presets/<id>` | Delete preset |
| POST | `/api/control` | Start/stop bot |
| GET | `/api/stats` | Global statistics |
| GET | `/api/preset-stats` | Per-preset cumulative stats |
| GET | `/api/preset-session-stats` | Current session stats |
| GET | `/api/retry-queue` | View failed listing queue |
| GET | `/api/errors` | Error log |
| GET | `/api/logs` | Live log stream |
| POST | `/api/prompts` | Update AI prompt templates |
| GET | `/api/exchange-rate` | Current USDT/TRY rate |

</details>

---

<br>

## TÜRKÇE

---

### Genel Bakış

Otomatize, [GamerMarkt](https://gamermarkt.com) üzerindeki oyun hesabı ilanlarını otomatik olarak tarayıp, detaylı hesap verilerini (skinler, ranklar, envanter) çıkartan, Google Gemini ile yapay zeka destekli ilan açıklamaları oluşturan, Binance üzerinden anlık kur hesaplayarak fiyatlayan ve [G2G](https://g2g.com) pazaryerine yayınlayan tam otomatik bir pipeline sistemidir.

---

### Mimari

```
                          ┌──────────────────────────────────────┐
                          │          OTOMATIZE ÇEKİRDEK          │
                          │         Flask Backend                │
                          │     20+ REST API Endpoint            │
                          │   Thread-safe Kuyruk Mimarisi        │
                          └──────┬──────────┬──────────┬────────┘
                                 │          │          │
              ┌──────────────────┤          │          ├──────────────────┐
              │                  │          │          │                  │
   ┌──────────▼────────┐ ┌──────▼────┐ ┌───▼──────┐ ┌▼───────────┐ ┌───▼──────────┐
   │    GamerMarkt     │ │ Botasaurus│ │ Gemini AI│ │ Binance API│ │   G2G API    │
   │  Kaynak Tarayıcı  │ │ CF Bypass │ │  İçerik  │ │ Döviz Kuru │ │  Pazaryeri   │
   └───────────────────┘ └───────────┘ └──────────┘ └────────────┘ └──────────────┘
```

---

### Desteklenen Oyunlar

| Oyun | Filtreler | Çıkartılan Veriler |
|:-----|:----------|:-------------------|
| **Valorant** | Rank, Skinler, Ajanlar, Bölge, VP/RP | Skin envanteri, rank geçmişi, ajan sözleşmeleri, spreyler, kartlar |
| **League of Legends** | Rank, Şampiyonlar, Skinler, Bölge, BE/RP | Şampiyon havuzu, skin envanteri, onur seviyesi, sezon ödülleri |
| **CS2** | Rank, Skinler, Prime, Bölge | Skin envanteri, Faceit seviyesi, madalyalar, ban geçmişi |
| **Fortnite** | Skinler, V-Bucks, Platform | Kıyafetler, kazma, planör, emotlar, battle pass, OG durumu |

---

### Özellikler

<table>
<tr><td width="50%">

**Temel Otomasyon**
- Oyun bazlı filtrelerle çoklu preset sistemi
- Tara → Çıkar → Oluştur → Yayınla tam pipeline
- Otomatik senkronizasyon: kaynak silinince G2G'den de silinir
- Başarısız ilan yeniden deneme kuyruğu (5 denemeye kadar)
- Üstel geri çekilme (exponential backoff) mekanizması

</td><td width="50%">

**Yapay Zeka & Fiyatlama**
- Google Gemini ile başlık ve açıklama oluşturma
- Oyun başına 50+ dinamik değişken
- Binance üzerinden anlık USDT/TRY kuru (60sn yenileme)
- Preset bazlı yapılandırılabilir kâr marjı
- Yapılandırılmış JSON çıktı zorunluluğu

</td></tr>
<tr><td>

**Tarayıcı Otomasyonu**
- Botasaurus tabanlı Cloudflare bypass
- Undetected ChromeDriver ile G2G'de teslimat ayarı (Manual, 10 mins)
- Zombie element temizliği (Quasar framework)
- Çoklu element etkileşim yedekleri
- Zaman aşımı korumalı navigasyon

</td><td>

**Altyapı**
- Thread-safe eşzamanlılık (5+ kilit)
- JSON bozulma kurtarma ve otomatik yedekleme
- Sahipsiz Chrome süreç temizliği
- ChromeDriver önbellek yarışma durumu yönetimi
- Preset bazlı kalıcı + oturum istatistikleri

</td></tr>
</table>

---

### Web Kontrol Paneli

`localhost:5001` adresinde gerçek zamanlı kontrol paneli:

| Özellik | Açıklama |
|:--------|:---------|
| **Preset Yöneticisi** | Oyun bazlı preset oluşturma, düzenleme, klonlama, aktif/pasif geçiş |
| **Canlı Loglar** | Tüm bot aktivitesinin gerçek zamanlı akışı |
| **İstatistikler** | Preset ve genel metrikler — oluşturulan, silinen, hatalar, taranan |
| **Bot Kontrolleri** | Otomasyonu başlat/durdur, manuel tarama tetikle, kuyruk yönetimi |
| **Döviz Kuru** | Otomatik yenilenen canlı USDT/TRY gösterimi |
| **Hata Takibi** | Kategorize edilmiş merkezi hata logu |
| **Yeniden Deneme Kuyruğu** | Başarısız ilanları görüntüle ve yönet |

---

### Hızlı Başlangıç

#### Gereksinimler

- Python 3.10+
- Google Chrome (güncel)
- [Google Gemini API Anahtarı](https://aistudio.google.com/)
- [G2G API Kimlik Bilgileri](https://www.g2g.com/)

#### Kurulum

```bash
git clone https://github.com/yourusername/otomatize.git
cd otomatize
pip install flask selenium undetected-chromedriver beautifulsoup4 requests python-dotenv google-generativeai botasaurus-driver
```

#### Ortam Değişkenleri

Proje kökünde `.env` dosyası oluşturun:

```env
GEMINI_API_KEY=gemini_api_anahtariniz
G2G_API_KEY=g2g_api_anahtariniz
G2G_API_SECRET=g2g_api_sifresi
G2G_USER_ID=g2g_kullanici_id
```

#### Yapılandırma

```bash
cp otomatize_config.json.example otomatize_config.json
```

#### Çalıştırma

```bash
python otomatize_scraper.py
```

Kontrol paneline erişmek için **http://localhost:5001** adresini açın.

---

### Nasıl Çalışır

```
1. TARA        GamerMarkt ilanlarını rank, fiyat, bölge, skin filtrelerine göre tara
       │
2. ÇIKAR       Her detay sayfasını ziyaret et → skinler, ranklar, envanter, banlar
       │
3. OLUŞTUR     Hesap verilerini Gemini AI'a gönder → optimize başlık & açıklama
       │
4. FİYATLA     (TL fiyat × kâr marjı) ÷ canlı USDT/TRY kuru = USD fiyat
       │
5. YAYINLA     G2G API ile ilan oluştur — özellikler, görseller & fiyatlama
       │
6. SENKRONİZE  Silinen kaynak ilanları tespit et → G2G'den otomatik sil
       │
7. AYARLA      G2G'de "Manual delivery" ve "10 mins" hız ayarını tarayıcı otomasyonu ile uygula
```

---

### Proje Yapısı

```
otomatize/
├── otomatize_scraper.py           # Çekirdek — Flask sunucu, otomasyon döngüsü, 20+ endpoint
├── otomatize.html                 # Panel — gerçek zamanlı kontrol paneli arayüzü
├── g2g_api.py                     # G2G API — HMAC-SHA256 auth, ilan CRUD, özellik önbelleği
├── gamermarkt_scraper.py          # Tarayıcı — ilan keşfetme, filtreler, tekrar önleme
├── ultra_detail_scraper.py        # Çıkartıcı — oyun bazlı hesap verileri (skinler, ranklar vb.)
├── update_delivery_settings.py    # Teslimat ayarı — G2G'de Manual/10mins ayarını uygular
├── botasaurus_bridge.py           # Köprü — Selenium uyumlu Botasaurus wrapper
├── prompts.json                   # YZ — oyun bazlı prompt şablonları (50+ değişken)
├── otomatize_config.json.example  # Config — tüm ayarları içeren şablon
├── llms.txt                       # Dokümantasyon — G2G OpenAPI referansı
└── rdp_disconnect.bat             # VDS — oturumu kilitlemeden güvenli RDP çıkışı
```

> **Uzak Masaüstü Kullanıcıları:** Uzak bir makinede (VDS, VPS, dedicated sunucu vb.) çalıştırıyorsanız RDP oturumunu X butonu ile kapatmayın — oturum kilitlenir ve Chrome arka planda çalışmayı durdurur. Bunun yerine `rdp_disconnect.bat` dosyasını yönetici olarak çalıştırarak bot çalışmaya devam ederken güvenle bağlantıyı kesin.

---

### Teknoloji Yığını

| Katman | Teknoloji |
|:-------|:----------|
| **Backend** | Flask, Python 3.10+, Threading |
| **Tarayıcı** | Botasaurus, Undetected ChromeDriver, Selenium |
| **Yapay Zeka** | Google Gemini (içerik üretimi) |
| **Parsing** | BeautifulSoup4 |
| **API'ler** | G2G REST API (HMAC-SHA256), Binance API |
| **Güvenlik** | python-dotenv, HMAC imzaları, ortam değişkeni tabanlı gizli anahtarlar |

---

### API Endpoint'leri

<details>
<summary><b>Genişletmek için tıklayın — 20+ endpoint</b></summary>

| Metod | Endpoint | Açıklama |
|:------|:---------|:---------|
| GET | `/api/status` | Bot durumu, aktif preset, döngü bilgisi |
| GET | `/api/presets` | Tüm presetleri listele |
| POST | `/api/presets` | Yeni preset oluştur |
| PUT | `/api/presets/<id>` | Preset güncelle |
| DELETE | `/api/presets/<id>` | Preset sil |
| POST | `/api/control` | Botu başlat/durdur |
| GET | `/api/stats` | Genel istatistikler |
| GET | `/api/preset-stats` | Preset bazlı kümülatif istatistikler |
| GET | `/api/preset-session-stats` | Mevcut oturum istatistikleri |
| GET | `/api/retry-queue` | Başarısız ilan kuyruğunu görüntüle |
| GET | `/api/errors` | Hata logu |
| GET | `/api/logs` | Canlı log akışı |
| POST | `/api/prompts` | YZ prompt şablonlarını güncelle |
| GET | `/api/exchange-rate` | Güncel USDT/TRY kuru |

</details>

---

<div align="center">

### License / Lisans

Copyright © 2026 Bee Pixel LLC. All rights reserved.

This repository is provided for portfolio and evaluation purposes only.
No permission is granted to use, copy, modify, distribute, sublicense, or create derivative works from this code without prior written permission from Bee Pixel LLC.

Bu depo yalnızca portfolyo ve değerlendirme amacıyla sunulmaktadır.
Bee Pixel LLC'den önceden yazılı izin alınmadan bu kodun kullanılması, kopyalanması, değiştirilmesi, dağıtılması, alt lisanslanması veya türev çalışmalar oluşturulması için herhangi bir izin verilmemektedir.

**Warning / Uyarı:** Unauthorized commercial use of this code may result in legal action.
Bu kodun izinsiz ticari amaçla kullanılması hukuki işlem başlatılmasına yol açabilir.

---

Built with Python, caffeine, and mass automation.

</div>
