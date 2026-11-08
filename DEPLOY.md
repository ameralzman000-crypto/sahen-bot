# نشر البوت على سيرفر مجاني

البوت يحتاج عملية دائمة (polling). أوقف أي نسخة محلية قبل تشغيل السيرفر حتى لا يحدث تعارض `getUpdates`.

الحذف التلقائي للمحادثات مفعّل كل 24 ساعة بعد ربط المجموعة، ويحتاج أن يكون البوت مشرفاً بصلاحية حذف الرسائل.

## أ) Render المجاني

1. ارفع مجلد المشروع إلى GitHub.
2. افتح https://dashboard.render.com وسجّل بحساب GitHub.
3. New + ثم Web Service ثم اختر المستودع.
4. اترك Root Directory فارغاً (ملفات التشغيل في جذر المستودع).
5. الإعدادات:

```text
Runtime: Python 3
Build Command: pip install -r requirements-prod.txt
Start Command: python main.py
Instance Type: Free
```

6. Environment Variables:

```text
BOT_TOKEN=توكن_البوت_من_BotFather
ADMIN_ID=1441524960
WEB_PASSWORD=كلمة_مرور_لوحة_التحكم
WEB_HOST=0.0.0.0
AUTO_PURGE_ENABLED=true
AUTO_PURGE_HOURS=24
DB_PATH=/var/data/alias_group.db
```

لا تضع `WEB_PORT`. Render يضبط `PORT` تلقائياً.

لحفظ الأعضاء بعد إعادة النشر أضف Disk من Render:

```text
Name: shahin-data
Mount Path: /var/data
Size: 1 GB
```

القرص الدائم غير متوفر على الخطة المجانية. إن رفض Render إضافة القرص، حوّل الخدمة إلى Starter ثم أضف القرص قبل أي Deploy جديد.

7. Create Web Service وانتظر حتى تصبح الحالة Live.
8. افتح رابط الخدمة ثم `/health` للتأكد، ولوحة التحكم على الرابط نفسه.
9. أوقف أي تشغيل محلي للبوت، ثم أرسل `/start` من تيليغرام.

ملاحظات Render:
- الخدمة المجانية قد تدخل نوماً بعد خمول حوالي 15 دقيقة، ثم تستيقظ مع أول زيارة للرابط.
- بدون Disk تُمسح قاعدة SQLite عند كل نشر فيُفقد الأعضاء المسجّلون وربط المجموعة.
- بعد تفعيل القرص و`DB_PATH=/var/data/alias_group.db` تبقى التسجيلات بعد إعادة النشر.

## الملفات الجاهزة

- `.env.example` قالب التوكن ومعرّف المدير
- `deploy/install.sh` تثبيت على Ubuntu مع systemd
- `deploy/aliasbot.service` نموذج الخدمة
- `Dockerfile` و `docker-compose.yml` للتشغيل بالحاوية

## أ) Oracle Cloud + Ubuntu (موصى به)

### 1. إنشاء السيرفر

1. سجّل في https://cloud.oracle.com
2. أنشئ Instance بنظام Ubuntu 22.04
3. الشكل المجاني: `VM.Standard.E2.1.Micro` أو Ampere
4. حمّل مفتاح SSH
5. اسمح بمنفذ 22 في Security List

الاتصال من جهازك:

```bash
ssh -i your-key.key ubuntu@SERVER_IP
```

### 2. رفع المشروع

من جهازك، من مجلد المشروع:

```bash
scp -i your-key.key bot.py config.py database.py security.py utils.py requirements.txt requirements-prod.txt .env.example deploy/install.sh ubuntu@SERVER_IP:/tmp/
```

على السيرفر:

```bash
mkdir -p /home/ubuntu/aliasbot
mv /tmp/bot.py /tmp/config.py /tmp/database.py /tmp/security.py /tmp/utils.py /tmp/requirements.txt /tmp/requirements-prod.txt /tmp/.env.example /tmp/install.sh /home/ubuntu/aliasbot/
chmod +x /home/ubuntu/aliasbot/install.sh
```

### 3. وضع التوكن

```bash
cp /home/ubuntu/aliasbot/.env.example /home/ubuntu/aliasbot/.env
nano /home/ubuntu/aliasbot/.env
```

ضع توكن ‎@BotFather في `BOT_TOKEN`. اترك `ADMIN_ID` كما هو إن كنت المدير.

### 4. التثبيت والتشغيل

```bash
cd /home/ubuntu/aliasbot
./install.sh
```

التحقق:

```bash
sudo systemctl status aliasbot
journalctl -u aliasbot -f
```

أوامر لاحقة:

```bash
sudo systemctl restart aliasbot
sudo systemctl stop aliasbot
```

لنقل البيانات الحالية ارفع أيضاً `alias_group.db` إلى `/home/ubuntu/aliasbot/data/` ثم أعد التشغيل.

## ب) Docker على أي VPS

أنشئ `.env` من `.env.example` ثم:

```bash
docker compose up -d --build
```

السجلات:

```bash
docker compose logs -f
```

قاعدة البيانات تُحفظ في مجلد `data/`.

## بعد التشغيل

1. أوقف النسخة القديمة إن كانت تعمل
2. راسل البوت `/start`
3. اربط المجموعة بـ `/setgroup` داخلها
4. اربط القناة من الخاص بـ `/setchannel`

إذا لم يرد البوت: غالباً نسختان تعملان معاً، أو `BOT_TOKEN` فارغ في `.env`.
