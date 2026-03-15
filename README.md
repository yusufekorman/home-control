# 🏠 Home Control Server

Python tabanlı akıllı ev kontrol sunucusu. Web arayüzü, REST API ve MCP server desteği içerir.

## Özellikler

- 🖥️ **Web Paneli** — Cihaz yönetimi, aksiyon tetikleme, log takibi
- 🔐 **Kullanıcı Girişi** — Session tabanlı kimlik doğrulama
- 🔌 **Cihaz Yönetimi** — IP, Base URL, Auth header, icon desteği
- ⚡ **Aksiyon Sistemi** — GET/POST/PUT/DELETE, custom body & headers
- 📋 **Log Takibi** — Her tetiklemede kayıt
- 🔑 **API Key** — REST API ve MCP erişimi için
- 🤖 **MCP Server** — Claude Desktop entegrasyonu
- 📖 **Swagger UI** — `/api/docs` adresinde otomatik API dokümantasyonu

## Kurulum

```bash
# Bağımlılıkları yükle
pip install -r requirements.txt

# Sunucuyu başlat
python main.py
```

Sunucu `http://localhost:8000` adresinde başlar.

**İlk kurulum girişi:** `admin` / _(başlangıçta terminalde üretilip gösterilen tek seferlik şifre)_  
⚠️ Şifre ilk kurulumda bir kez gösterilir. İlk girişten sonra değiştir!

## Çevre Değişkenleri

| Değişken     | Varsayılan | Açıklama                   |
| ------------ | ---------- | -------------------------- |
| `HOST`       | `0.0.0.0`  | Dinlenecek arayüz          |
| `PORT`       | `8000`     | Port                       |
| `SECRET_KEY` | Rastgele   | Session şifreleme anahtarı |
| `RELOAD`     | `true`     | Hot-reload (geliştirme)    |

## REST API

Tüm endpoint'ler `X-API-Key` header gerektirir.

İstisna: `POST /api/ping` endpoint'i cihaz tarafından çağrılır ve `Authorization: Bearer <device_security_code>` ister.

```bash
# Cihazları listele
curl -H "X-API-Key: hck_..." http://localhost:8000/api/v1/devices

# Aksiyon tetikle
curl -X POST -H "X-API-Key: hck_..." \
  http://localhost:8000/api/v1/devices/1/actions/1/trigger
```

Tam dokümantasyon: `http://localhost:8000/api/docs`

### Endpoint Özeti

| Method | Path                                         | Açıklama                 |
| ------ | -------------------------------------------- | ------------------------ |
| GET    | `/api/v1/devices`                            | Cihaz listesi            |
| POST   | `/api/v1/devices`                            | Cihaz oluştur            |
| GET    | `/api/v1/devices/{id}`                       | Cihaz detayı             |
| PUT    | `/api/v1/devices/{id}`                       | Cihaz güncelle           |
| DELETE | `/api/v1/devices/{id}`                       | Cihaz sil                |
| GET    | `/api/v1/devices/{id}/actions`               | Aksiyonlar               |
| POST   | `/api/v1/devices/{id}/actions`               | Aksiyon ekle             |
| DELETE | `/api/v1/devices/{id}/actions/{aid}`         | Aksiyon sil              |
| POST   | `/api/v1/devices/{id}/actions/{aid}/trigger` | **Tetikle**              |
| GET    | `/api/v1/devices/{id}/logs`                  | Cihaz logları            |
| GET    | `/api/v1/logs`                               | Tüm loglar               |
| GET    | `/api/v1/apikeys`                            | API anahtar listesi      |
| POST   | `/api/v1/apikeys`                            | Anahtar oluştur          |
| DELETE | `/api/v1/apikeys/{id}`                       | Anahtar sil              |
| POST   | `/api/ping`                                  | Cihaz ping + IP güncelle |

### Cihaz Ping Endpoint

ESP8266 gibi cihazlar açılışta kendi IP adresini sunucuya bildirebilir:

```bash
curl -X POST http://localhost:8000/api/ping \
  -H "Authorization: Bearer <device_security_code>" \
  -H "Content-Type: application/json" \
  -d '{"device":"desk_lamp","ip":"192.168.1.44"}'
```

- `device`: cihaz adı (`name`) veya sayısal cihaz id
- `ip`: cihazın güncel IP adresi
- Bearer token: cihazın yeni güvenlik kodu olarak kaydedilir (`auth_header_value` güncellenir)

Doğrulama başarılıysa cihazın `ip_address` ve `base_url` alanları otomatik güncellenir.
Ek olarak gönderilen Bearer token eski güvenlik kodunun yerine yazılır.

## MCP Server

### Claude Desktop Entegrasyonu

`~/Library/Application Support/Claude/claude_desktop_config.json` dosyasına ekle:

```json
{
  "mcpServers": {
    "home-control": {
      "command": "python",
      "args": ["/tam/yol/mcp_server.py"],
      "env": {
        "HOME_CONTROL_URL": "http://localhost:8000",
        "HOME_CONTROL_KEY": "hck_..."
      }
    }
  }
}
```

### MCP Araçları

| Araç             | Açıklama              |
| ---------------- | --------------------- |
| `list_devices`   | Tüm cihazları listele |
| `get_device`     | Cihaz detayı          |
| `create_device`  | Cihaz ekle            |
| `update_device`  | Cihaz güncelle        |
| `delete_device`  | Cihaz sil             |
| `list_actions`   | Aksiyonları listele   |
| `create_action`  | Aksiyon ekle          |
| `delete_action`  | Aksiyon sil           |
| `trigger_action` | **Aksiyonu tetikle**  |
| `get_logs`       | Logları getir         |

## Proje Yapısı

```
home_control/
├── main.py              # FastAPI uygulama giriş noktası
├── database.py          # SQLite veritabanı bağlantısı
├── models.py            # SQLAlchemy modelleri + Pydantic şemaları
├── auth.py              # Kimlik doğrulama yardımcıları
├── mcp_server.py        # MCP stdio server
├── requirements.txt
├── routers/
│   ├── web.py           # Web UI route'ları
│   └── api.py           # REST API route'ları
└── templates/
    ├── base.html        # Ana şablon (sidebar, nav)
    ├── login.html       # Giriş sayfası
    ├── dashboard.html   # Ana panel
    ├── devices.html     # Cihaz listesi
    ├── device_detail.html  # Cihaz detayı + aksiyonlar
    ├── apikeys.html     # API anahtar yönetimi
    └── users.html       # Kullanıcı yönetimi (admin)
```
