# Put Bill Tracker online and install it on your iPhone

> Fly.io charges for this. For a free option, see [DEPLOY-FREE.md](DEPLOY-FREE.md).

Once this is done the app runs on Fly.io at `https://<your-app>.fly.dev`, so you can record
expenses from your phone anywhere, with your laptop switched off. Your data lives in a SQLite file
on a private disk attached to that server.

You only do steps 1–5 once. Everything below runs from the project folder on your Mac
(`flyctl` is already installed).

## 1. Sign in to Fly.io

```bash
fly auth signup
```

(or `fly auth login` if you already have an account). It opens the browser; Fly asks for a card.
The app sleeps when you're not using it, so it costs little, but check
[fly.io/pricing](https://fly.io/pricing) for current prices.

## 2. Pick a name for your app

The name becomes your address, `https://<name>.fly.dev`, and must be unique on Fly, e.g.
`bills-himanshu`. Create it:

```bash
fly apps create bills-himanshu
```

Then put the same name on the `app = ...` line at the top of `fly.toml`.

## 3. Create the disk for your data (1 GB is plenty)

```bash
fly volumes create bill_data --size 1 --region bom
```

`bom` is Mumbai. To use another region, change `primary_region` in `fly.toml` to match
(`fly platform regions` lists them).

## 4. Deploy

```bash
fly deploy --ha=false
```

`--ha=false` keeps it to one server, which a SQLite database needs. Fly builds the app on its own
servers (no Docker needed on your Mac) and prints the address when it's done.

## 5. Create your account straight away

Open `https://<name>.fly.dev` and choose **Create account**. Sign-ups close automatically after
this first account (`FT_REGISTRATION = "0"` in `fly.toml`), so nobody else can register even if they
find the address.

## 6. Install it on your iPhone

1. Open `https://<name>.fly.dev` in **Safari** (not Chrome) and log in.
2. Tap the **Share** button, then **Add to Home Screen**, then **Add**.
3. Open it from the new **Bills** icon. It runs full-screen like an app, and stays logged in for 30 days.

Reminders: inside the home-screen app tap **Enable alerts** in the banner (needs iOS 16.4 or later).
Notifications appear while the app is open or recently used; iPhones don't run web apps in the
background, so a closed app won't ping you.

---

## Updating after changes

Commit or pull the new code, then run `fly deploy` again. Your data is on the volume and is kept.
The installed app picks up the new version the next time it opens.

## Backups

- The server snapshots the database every day into `/data/backups` (newest 14 kept).
- Fly also snapshots the whole volume daily: `fly volumes snapshots list`.
- **Download your data** (the download button in the header) gives you a JSON copy any time.

## Optional: bring over what's already on your laptop

Only if you've recorded real data locally. Do this **before** step 5, so you log in with your
existing account instead of creating one:

```bash
fly ssh sftp shell
```

At the `»` prompt type `put backend/data/finance.db /data/upload.db`, then press Ctrl-D. Then:

```bash
fly ssh console -C "mv /data/upload.db /data/finance.db"
```

```bash
fly apps restart
```

## Useful commands

```bash
fly logs
```

```bash
fly status
```

To let one more person sign up, temporarily set `FT_REGISTRATION = "1"` in `fly.toml`, run
`fly deploy`, have them register, then set it back to `"0"` and deploy again. Each account only
ever sees its own data.
