# 📬 Lakeland, TN Custom News Digest

An automated, intelligent email news digest system tailored for the city of **Lakeland, Tennessee** (Shelby County). It monitors municipal notices, hyperlocal reporting, schools, regional media, and community discussions, categorizes stories, and emails a formatted newsletter.

---

## 📡 Monitored Sources

| Source | Type | Focus |
|---|---|---|
| **City of Lakeland (Official)** | CivicEngage RSS | Board of Commissioners, Ordinances, Public Works |
| **City Alert Center** | CivicEngage RSS | Road Closures, Boil Water Advisories, Public Safety |
| **Lakeland Currents** | Hyperlocal RSS | LPS/LES Schools, City Hall, The Lake District, Local Life |
| **Regional Media (Google News)** | Filtered RSS | Daily Memphian, Commercial Appeal, MBJ, FOX13, WREG |
| **Reddit r/memphis** | Community RSS | Local community questions and discussions |

---

## 🚀 Quick Start (Local Preview)

No `pip install` needed — runs on standard **Python 3.8+**.

1. **Run a test preview:**
   ```bash
   python3 main.py --preview
   ```
   This will fetch live feeds, filter out noise, and generate `preview_digest.html`.

2. **Open in browser:**
   ```bash
   open preview_digest.html
   ```

---

## ✉️ Automated Email Setup

### 1. Configure SMTP Credentials
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your email details:
```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=xxxx xxxx xxxx xxxx   # 16-character Google App Password
RECIPIENT_EMAIL=your_email@gmail.com
```

> **How to get a Google App Password:**
> 1. Go to [Google Account Security](https://myaccount.google.com/security).
> 2. Ensure 2-Step Verification is turned ON.
> 3. Search for **"App passwords"** or go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).
> 4. Create a new App Password named "Lakeland Digest" and paste the 16 characters into `SMTP_PASS`.

### 2. Send an Email
```bash
python3 main.py --send
```

---

## ☁️ Free Scheduled Cloud Automation (GitHub Actions)

You can run this completely free in the cloud without keeping your computer on:

1. Push this folder to a private or public GitHub repository.
2. Go to **Settings > Secrets and variables > Actions** in your GitHub repository.
3. Add the following repository secrets:
   - `SMTP_USER`: Your Gmail / SMTP username
   - `SMTP_PASS`: Your 16-character Google App Password
   - `RECIPIENT_EMAIL`: Email where you want the digest sent
4. Enable GitHub Actions in the **Actions** tab.
5. The digest will run **daily at 7:00 AM Central Time**. You can also click **Run workflow** anytime to send a test digest instantly.

---

## ⚙️ Customization (`config.json`)

You can edit `config.json` to:
- Add or remove RSS feeds.
- Adjust `lookback_days` (default: 3 days).
- Add custom category keywords (e.g. tracking specific neighborhood names or school teams).
- Add negative keywords to filter out unwanted noise.
