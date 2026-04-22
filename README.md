# 🤖 Telegram Subscription Bot — Crypto Payments (USDT TRC-20)

Pilnīgi automatizēts bots, kas pārvalda maksas kanāla/grupas abonēšanu ar crypto maksājumiem.

---

## ✨ Funkcijas

- 📦 **Vairāki tarifi** — 1 mēnesis, 3 mēneši, 6 mēneši, 1 gads (viegli mainīt)
- 💳 **USDT TRC-20 maksājumi** — automātiska pārbaude blockchain
- 🔔 **Atgādinājumi** — 3 un 1 dienu pirms beigām
- 🚪 **Auto kick** — automātiski izmet no kanāla pēc laika beigām
- 🔗 **Unikālas invite links** — katram lietotājam pēc maksājuma
- 🛠 **Admin panel** — statistika, manuāla pievienošana/noņemšana
- 🗄 **SQLite datubāze** — visi abonementi ar vēsturi

---

## 🚀 Uzstādīšana

### 1. Klonē un instalē

```bash
git clone <repo>
cd telegram_sub_bot
pip install -r requirements.txt
```

### 2. Konfigurē `.env`

```bash
cp .env.example .env
nano .env
```

Aizpildi šos laukus:
```
BOT_TOKEN=        # No @BotFather
CHAT_ID=          # Tavs privātais kanāls/grupa (negatīvs skaitlis)
CHAT_LINK=        # Kanāla invite link
CRYPTO_WALLET=    # USDT TRC-20 adrese
TRON_API_KEY=     # (ieteicams) no trongrid.io
```

### 3. Konfigurē tarifi `config.py`

```python
PLANS = {
    "basic_1m": {
        "name": "Basic — 1 mēnesis",
        "price_usd": "10$",
        "price_usdt": 10.0,   # Cena USDT
        "days": 30,
        "popular": False,
    },
    ...
}
```

### 4. Pievieno botu kanālam

1. Ej uz sava kanāla/grupas iestatījumiem
2. **Administrators** → pievienot botu
3. Dod tiesības: **Delete messages** + **Ban users** + **Invite users**

### 5. Palaid

```bash
python bot.py
```

---

## ⚙️ Admin komandas

Lai izmantotu admin komandas, `admin.py` failā pievieno savu `user_id`:
```python
ADMIN_IDS = [123456789]  # Tavs Telegram ID
```

Un pievieno routeri `bot.py`:
```python
from admin import router as admin_router
dp.include_router(admin_router)
```

| Komanda | Apraksts |
|---------|----------|
| `/admin` | Admin izvēlne |
| `/stats` | Statistika |
| `/list_users` | Visi aktīvie |
| `/add_user [id] [days]` | Manuāli pievienot |
| `/remove_user [id]` | Noņemt lietotāju |

---

## 🔍 Kā strādā maksājumu pārbaude

1. Lietotājs izvēlas plānu → bots parāda USDT TRC-20 adresi un summu
2. Lietotājs sūta USDT un nospiež "Esmu samaksājis"
3. Bots pārbauda [TronGrid API](https://api.trongrid.io/) — meklē ienākošu transakciju pēdējo 60 minūšu laikā
4. Ja atrasta transakcija ar pareizu summu (±1% tolerance) — aktivizē abonēšanu
5. Transakcija tiek saglabāta kā "izmantota" — nevar atkārtoti izmantot

---

## 📁 Faili

```
telegram_sub_bot/
├── bot.py           # Galvenais bots
├── config.py        # Konfigurācija un tarifi
├── database.py      # SQLite datubāze
├── crypto_checker.py # Blockchain pārbaude
├── admin.py         # Admin komandas
├── requirements.txt
└── .env.example
```

---

## 🌐 TronGrid API atslēga

Bezmaksas atslēga pieejama: https://www.trongrid.io/

Bez atslēgas arī strādā, bet ir rate limits (~15 req/sek).

---

## 🔧 Problēmas

**Bots nevar noņemt lietotājus:**
→ Pārliecinies ka botam ir Admin tiesības ar "Ban users" grupā/kanālā

**Maksājumi nav atrasti:**
→ Pārliecinies ka sūtāt tieši USDT TRC-20 (nevis ETH vai BEP-20)
→ Pārbaud vai summa ir precīza

**"Chat not found" kļūda:**
→ CHAT_ID ir jābūt precīzam negatīvam skaitlim (izmanto @userinfobot)
