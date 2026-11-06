# Run Bill Tracker free on Oracle Cloud and use it from your iPhone

This puts the app on a free cloud computer from Oracle Cloud's **Always Free** tier. Once it's set up:

- the app runs at an `https://` address you can open from anywhere;
- your laptop can stay switched off;
- your data is kept on that computer's disk, with a daily backup.

Steps 1–4 are clicks in Oracle's website. Step 5 is one command. It takes about 30–45 minutes the first time.

> Oracle asks for a card to check who you are. Staying inside the Always Free limits costs nothing. Check
> [Oracle's Always Free page](https://www.oracle.com/cloud/free/) for the current limits, because Oracle changes them now and then.

## 1. Create an Oracle Cloud account

Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). When it asks for a **home region**, pick one near you, such as
**India West (Mumbai)** or **India South (Hyderabad)**. You can't change the home region later.

## 2. Create the free computer (a "VM instance")

In the Oracle console: **☰ menu → Compute → Instances → Create instance**.

1. **Name:** `bill-tracker`.
2. **Image:** click *Change image* and choose **Canonical Ubuntu 24.04**.
3. **Shape:** click *Change shape* and pick one marked **Always Free-eligible**:
   - **Ampere (VM.Standard.A1.Flex)** with 1 OCPU and 6 GB memory is faster. If you get "Out of capacity", try again later or use the next one.
   - **AMD (VM.Standard.E2.1.Micro)** is small but enough for this app.
4. **Networking:** leave *Create new virtual cloud network* and *Create new public subnet* selected. Make sure
   **Automatically assign public IPv4 address** is on.
5. **SSH keys:** choose *Generate a key pair for me*, then click **Save private key**. Keep that file. It's the key to your server.
6. Click **Create**. When the status turns **Running**, copy the **Public IP address**.

## 3. Open the web ports

On the instance page, click the **subnet** link, then the **Default Security List**, then **Add Ingress Rules**:

| Source CIDR | IP Protocol | Destination Port Range |
|---|---|---|
| `0.0.0.0/0` | TCP | `80` |
| `0.0.0.0/0` | TCP | `443` |

(Add the first rule, then click **+ Another Ingress Rule** for the second, then **Add Ingress Rules**.)

## 4. Connect from your Mac

In Terminal, with the key file you saved (usually in Downloads):

```bash
chmod 600 ~/Downloads/ssh-key-*.key
```

```bash
ssh -i ~/Downloads/ssh-key-*.key ubuntu@YOUR_PUBLIC_IP
```

Type `yes` if it asks whether to trust the host.

## 5. Install the app (one command, on the server)

```bash
curl -fsSL https://raw.githubusercontent.com/himanshushukla2604/BillTracker/main/deploy/oracle-setup.sh | bash
```

This takes 5–10 minutes. When it's done, it prints your address, which looks like
`https://152-67-1-23.sslip.io` (your IP with dashes). That name is free, comes from sslip.io, and needs no setup.

**Create your account straight away.** Sign-ups close after the first account, so nobody else can register.

## 6. Put it on your iPhone

1. Open the address in **Safari** and log in.
2. Tap **Share → Add to Home Screen → Add**.
3. Open it from the new **Bills** icon. It runs full-screen and stays logged in for 30 days.

---

## Updating after changes

Push the new code to GitHub, connect to the server (step 4), and run the step 5 command again. Your data is kept.

## Your data and backups

- The database is on the server at `/var/lib/bill-tracker/finance.db`.
- The app saves a copy there every day in `/var/lib/bill-tracker/backups` and keeps the newest 14.
- The **download** button in the app gives you a JSON copy at any time. Do this now and then, because a copy on your own
  devices is the backup you can count on.
- Oracle may stop Always Free computers that look idle for a long time. Using the app keeps it active. If it's ever
  stopped, start it again from **Compute → Instances**, and your data will still be there.

## Optional: bring over data from your laptop

Do this **before** creating your account in step 5, so your existing login carries over. On your Mac:

```bash
scp -i ~/Downloads/ssh-key-*.key backend/data/finance.db ubuntu@YOUR_PUBLIC_IP:/tmp/finance.db
```

Then on the server:

```bash
sudo mv /tmp/finance.db /var/lib/bill-tracker/finance.db && sudo docker restart bill-tracker
```

## If something goes wrong

- **The address doesn't load:** check both port rules in step 3, then look at `sudo docker logs caddy`.
- **The app doesn't start:** run `sudo docker logs bill-tracker`.
- **The HTTPS certificate fails:** sslip.io can occasionally hit limits. Get a free name at
  [duckdns.org](https://www.duckdns.org) pointing at your IP, then rerun step 5 as
  `curl -fsSL …/oracle-setup.sh | DOMAIN=yourname.duckdns.org bash`.
