# Deploy tuKang (Podman Quadlet + Cloudflare Tunnel)

Container `tukang` berjalan di network `global_net` (sama dengan `cloudflared`), tanpa port yang dipublish.
Akses dari internet hanya lewat Cloudflare Tunnel. Node "local" (host server itu sendiri) dikelola lewat SSH
dari dalam container ke `host.containers.internal`.

Contoh di bawah untuk **rootless** Podman. Untuk rootful: jalankan sebagai root, pakai
`/etc/containers/systemd/` dan `systemctl` tanpa `--user`.

## Cara cepat: RHEL rootless (otomatis)

Syarat: RHEL 9.3+ (Podman ≥ 4.6), user non-root yang **sama** dengan pemilik container `cloudflared`
dan network `global_net`, dan user itu punya akses `sudo` (untuk linger & authorized_keys).

```bash
# login langsung sebagai user tersebut (ssh user@server), bukan `sudo su - user`
git clone <repo> ~/tukang && cd ~/tukang
./deploy/dep.sh
```

Skrip ini: cek versi Podman, network, linger → build image → buat secret (password admin ditanya,
kunci enkripsi dibuat + salinan backup di `~/tukang-data-key.backup`, SSH key dibuat) → buat user
`tukang-mgr` + sudoers, daftarkan key dengan `restrict,pty` (+ label SELinux) → pasang Quadlet ke
`~/.config/containers/systemd/` → start → tes HTTP, SSH & sudo container→host → kunci key dengan `from=`.
Pakai user host lain: `LOCAL_SSH_USER=namauser ./deploy/dep.sh` (`root` = tanpa sudo, tidak disarankan). Untuk update cukup
`./deploy/dep.sh`: `git pull` (kalau ada upstream) → build ulang image → restart container dengan image baru →
cek container benar-benar memakai image baru → hapus image lama. Update tidak butuh sudo; setup host (user,
sudoers, authorized_keys) hanya jalan saat instalasi pertama atau dengan `./deploy/dep.sh --setup`.

Langkah 1–4 di bawah adalah versi manual dari skrip tersebut.

## Migrasi dari Cockpit-Py

Server yang masih menjalankan container lama `cockpit-py` dimigrasi otomatis oleh `./deploy/dep.sh` (via
[`deploy/migrate-from-cockpit-py.sh`](../deploy/migrate-from-cockpit-py.sh)), **tanpa kehilangan data**:

| Lama | Baru |
|---|---|
| container / service `cockpit-py` | `tukang` |
| volume `cockpit-py-data` (berisi `cockpit.db`) | `tukang-data` (app mengganti nama ke `tukang.db` saat start) |
| secret `cockpit-py-admin-password`, `-data-key`, `-ssh-key` | `tukang-admin-password`, `-data-key`, `-ssh-key` |
| user host `cockpit-mgr`, `/etc/sudoers.d/cockpit-py` | `tukang-mgr`, `/etc/sudoers.d/tukang` |

Kode terbaru harus sudah ada di server, lalu jalankan `dep.sh`:

```bash
# A) kode dikirim dengan ./sync.sh (rsync): pastikan sync sudah selesai, lalu di server:
cd /path/ke/repo && ./deploy/dep.sh

# B) server berupa git clone: riwayat git ditulis ulang saat rebranding, jadi `git pull` biasa gagal
cd /path/ke/repo && git fetch origin && git reset --hard origin/main && ./deploy/dep.sh
```

`dep.sh` mendeteksi instalasi lama → migrasi → build → setup ulang sudoers/key.

Setelah itu:
1. **Wajib:** ubah tujuan public hostname Cloudflare Tunnel dari `http://cockpit-py:8000` ke
   `http://tukang:8000`. Sebelum diubah, situs tidak bisa diakses.
2. Semua user perlu login ulang sekali (nama cookie sesi berubah). Akun, MFA, server, dan audit log tetap.
3. Data lama tidak dihapus. Setelah tuKang dipastikan berjalan, hapus sisa-sisanya dengan perintah yang
   dicetak di akhir migrasi (`podman volume rm cockpit-py-data`, dst.).
4. Server lain yang ditambahkan dengan username `cockpit-mgr` tidak ikut diubah dan tetap berjalan.

Folder repo di server (`~/cockpit-py`) boleh tetap memakai nama lama; namanya tidak memengaruhi apa pun.

## 1. Build image

```bash
cd /path/to/tukang
podman build -t localhost/tukang:latest -f Containerfile .
```

## 2. User khusus + SSH key untuk mengelola host

tuKang login ke host sebagai user khusus `tukang-mgr` lalu menaikkan hak dengan `sudo -n`, sehingga
login root via SSH tidak diperlukan dan setiap perintah tercatat di log sudo host (`journalctl _COMM=sudo`).

```bash
# user tanpa password (hanya key)
sudo useradd -m -s /bin/bash -c "tuKang management" tukang-mgr
sudo usermod -p '*' tukang-mgr
printf 'Defaults:tukang-mgr !requiretty\ntukang-mgr ALL=(ALL) NOPASSWD: ALL\n' | sudo tee /etc/sudoers.d/tukang
sudo chmod 440 /etc/sudoers.d/tukang && sudo visudo -cf /etc/sudoers.d/tukang

# key khusus: restrict = tanpa port/agent/X11 forwarding, pty untuk web terminal
ssh-keygen -t ed25519 -N '' -C tukang -f ~/tukang-key
sudo install -d -m 700 -o tukang-mgr -g tukang-mgr ~tukang-mgr/.ssh
echo "restrict,pty $(cat ~/tukang-key.pub)" | sudo tee -a ~tukang-mgr/.ssh/authorized_keys
sudo chown tukang-mgr: ~tukang-mgr/.ssh/authorized_keys && sudo chmod 600 ~tukang-mgr/.ssh/authorized_keys
sudo restorecon -R ~tukang-mgr/.ssh
podman secret create tukang-ssh-key ~/tukang-key
rm ~/tukang-key           # private key sekarang hanya ada di podman secret
```

Setelah container jalan, `dep.sh` juga menambahkan `from="<subnet/IP asal container>"` pada baris
key tersebut, sehingga key yang bocor tidak bisa dipakai dari mesin lain. Pastikan `sshd` aktif dan
`AllowUsers`/`AllowGroups` (jika dipakai) mengizinkan `tukang-mgr`.

## 3. Password admin awal & kunci enkripsi

```bash
printf '%s' 'GantiDenganPasswordKuat!' | podman secret create tukang-admin-password -

# Kunci enkripsi kredensial — SIMPAN SALINANNYA di password manager / vault
python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > ~/tukang-data-key
podman secret create tukang-data-key ~/tukang-data-key
# setelah dipindah ke vault: shred -u ~/tukang-data-key
```

Akun `admin` dibuat sekali saat database masih kosong. Saat login pertama Anda diminta memasang
two-factor authentication. Setelah itu ganti password lewat menu akun (ikon user di kanan atas) dan buat
akun bernama untuk setiap orang di *Access Control*, jangan berbagi akun `admin`.

## 4. Pasang Quadlet

```bash
mkdir -p ~/.config/containers/systemd
cp deploy/tukang.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start tukang
systemctl --user status tukang
podman logs -f tukang
```

Agar tetap jalan setelah logout/reboot (rootless): `sudo loginctl enable-linger $USER`.

## 5. Cloudflare Tunnel

Tambahkan ingress yang mengarah ke nama container di `global_net`:

```yaml
# config.yml cloudflared
ingress:
  - hostname: tukang.domainanda.com
    service: http://tukang:8000
  # ...ingress lain...
  - service: http_status:404
```

Jika tunnel dikelola dari dashboard Cloudflare (token): **Zero Trust → Networks → Tunnels → Public Hostname**,
Service `HTTP` → `tukang:8000`. WebSocket (metrics & terminal) didukung otomatis.

Disarankan menambah **Cloudflare Access** di depan hostname ini sebagai lapisan login kedua, karena
aplikasi ini memberi akses root shell ke server.

## Konfigurasi (environment variable)

| Variable | Default (container) | Keterangan |
|---|---|---|
| `ADMIN_USERNAME` | `admin` | Username akun pertama |
| `ADMIN_PASSWORD` | (secret) | Password akun pertama; jika kosong, dibuat acak dan dicetak di log |
| `DATA_ENCRYPTION_KEY` | (secret `tukang-data-key`) | Kunci Fernet untuk enkripsi password/private key server & secret MFA. **Wajib di-backup** |
| `MFA_REQUIRED` | `true` | Semua akun wajib mengaktifkan TOTP sebelum bisa memakai aplikasi |
| `SESSION_HOURS` / `SESSION_IDLE_MINUTES` | `12` / `30` | Umur maksimum sesi / logout otomatis saat tidak aktif |
| `PASSWORD_MIN_LENGTH` | `12` | Panjang minimum password akun |
| `COOKIE_SECURE` | `true` | Cookie hanya via HTTPS (wajib `true` di balik Cloudflare) |
| `TRUST_PROXY_HEADERS` | `true` | Pakai `CF-Connecting-IP` sebagai IP klien (rate limit & audit). Hanya `true` di balik proxy |
| `TRUSTED_PROXIES` | `cloudflared` | Peer yang boleh mengirim header IP klien: IP, CIDR, atau nama host (dipisah koma). Kosong = semua peer dipercaya, sehingga container lain di network yang sama bisa memalsukan IP. `dep.sh` mengisinya dari `CLOUDFLARED_HOST` (default `cloudflared`) |
| `LOGIN_MAX_ATTEMPTS` / `LOGIN_ACCOUNT_MAX_ATTEMPTS` / `LOGIN_LOCKOUT_SECONDS` | `5` / `10` / `900` | Batas gagal login per IP / per akun dalam jendela waktu |
| `LOGIN_KNOWN_IP_DAYS` | `30` | IP yang pernah login sukses ke akun dalam N hari terakhir tidak terkena batas per akun (tetap terkena batas per IP), jadi serangan dari IP lain tidak bisa mengunci pemilik akun |
| `AUDIT_RETENTION_DAYS` | `365` | Lama penyimpanan audit log |
| `FILES_MAX_UPLOAD_MB` | `100` | Batas ukuran upload di menu Files (paket gratis Cloudflare membatasi body request 100 MB) |
| `TRUSTED_ORIGINS` | kosong | Origin tambahan yang diizinkan (mis. `["https://tukang.domain.com"]`) jika proxy mengubah header Host |
| `LOCAL_MODE` | `ssh` | `ssh` = host dikelola via SSH; `direct` = in-process (install tanpa container) |
| `LOCAL_SSH_HOST` / `LOCAL_SSH_PORT` / `LOCAL_SSH_USER` | `host.containers.internal` / `22` / `tukang-mgr` | Target SSH node "local" |
| `LOCAL_SSH_SUDO` | `true` | Naikkan hak dengan `sudo -n` (wajib bila user bukan root) |
| `LOCAL_SSH_KEY_PATH` | `/run/secrets/host_ssh_key` | Private key (dari podman secret) |
| `ENABLE_API_DOCS` | `false` | Tampilkan `/docs` |

Data (SQLite) tersimpan di volume `tukang-data`.

## Keamanan

- **Peran (Access Control)**: `viewer` (lihat saja), `operator` (start/stop service & container, baca log),
  `admin` (semuanya: terminal, Quadlet, user Linux, server, akun & audit). Kebijakan ada di
  `backend/app/core/policy.py`; endpoint baru otomatis butuh `admin` untuk aksi tulis.
- **MFA**: TOTP (Google/Microsoft Authenticator, 1Password, dll.) + 10 recovery code sekali pakai.
  Admin bisa me-reset MFA user yang kehilangan perangkat.
- **Sesi**: disimpan di server (cookie hanya berisi token acak), logout & ganti password langsung mencabut sesi,
  terminal yang terbuka ikut ditutup saat sesi berakhir.
- **Audit log**: semua login, aksi tulis, dan sesi terminal tercatat (menu *Audit Log*) dan juga ditulis
  sebagai JSON ke log container (logger `audit`) → bisa diteruskan ke SIEM via journald.
- **SSH host key**: dipin saat koneksi pertama (TOFU). Jika host key berubah, koneksi ditolak (indikasi MITM).
  Setelah server di-reinstall, reset lewat tombol *Reset* di form edit server.
- **Backup**: simpan backup volume `tukang-data` **dan** kunci `tukang-data-key` di tempat terpisah.
  Tanpa kunci, kredensial server & MFA tidak bisa didekripsi (akun harus reset MFA, kredensial dimasukkan ulang).
- **Akses ke host**: lewat user `tukang-mgr` + sudo (tercatat di log sudo host), key dibatasi
  `restrict,pty,from=...`. Login root via SSH tidak dipakai, jadi bisa dimatikan (`PermitRootLogin no`).
  Untuk server lain di inventaris, aktifkan *Elevate with sudo* di form server dengan pola yang sama.
  Mencabut seluruh akses tuKang ke host cukup dengan menghapus `/etc/sudoers.d/tukang`.
- **Files**: pengelola file (setara Cockpit Files) berjalan sebagai root di node, jadi hanya untuk `admin`.
  Setiap baca/unduh/unggah/ubah file tercatat di audit log; direktori sistem utama (`/`, `/etc`, `/usr`, …)
  tidak bisa dihapus atau dipindah.
- **Peran di UI**: tombol aksi disembunyikan sesuai peran; backend tetap menegakkan kebijakan yang sama.
- **Disarankan**: tetap pasang Cloudflare Access di depan hostname sebagai lapisan pertama.

## Update

```bash
podman build -t localhost/tukang:latest -f Containerfile .
systemctl --user restart tukang
```

## Troubleshooting

- **Node "local" offline / SSH gagal**: cek dari container
  `podman exec tukang python -c "import socket;s=socket.create_connection(('host.containers.internal',22),3);print(s.recv(30))"`.
  Jika `Connection refused`, sshd tidak listen / diblok firewall host. Jika `Permission denied`, cek
  `~tukang-mgr/.ssh/authorized_keys` (opsi `from=` cocok dengan IP asal di `journalctl -u sshd`).
- **Lupa password admin**: hapus akun lalu restart; akun dibuat ulang dari secret
  `podman exec tukang python -c "import sqlite3;c=sqlite3.connect('/data/tukang.db');c.execute('delete from app_users');c.commit()"`
  lalu `systemctl --user restart tukang`.
